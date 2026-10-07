"""Store read-page Markdown and bind web citations to a chat and source version."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid

import requests

from agent_common import artifacts
from agent_common.result_pages import canonical_json

KIND_PAGE_TEXT = artifacts.KIND_WEB_PAGE_TEXT
KIND_PAGE_CITATION = artifacts.KIND_WEB_PAGE_CITATION
NAMESPACE = uuid.UUID("cbf403e2-2084-4ced-8432-4458745a459e")
MAX_BODY_BYTES = 64 * 1024 * 1024
MAX_CITATIONS = 200
MAX_PAGES_PER_CALL = 12
_lock = asyncio.Lock()


def _query(sql: str, owner: str, session: str, **params) -> list[dict]:
    response = requests.post(
        os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123").rstrip("/"),
        params={"database": artifacts.GLOBAL_DB,
                "user": os.getenv("CLICKHOUSE_USER", "hoover4"),
                "password": os.getenv("CLICKHOUSE_PASSWORD", "hoover4"),
                "default_format": "JSONEachRow", "param_owner": owner,
                "param_session": session, **{"param_" + k: v for k, v in params.items()}},
        data=sql.encode("utf-8"), timeout=artifacts.CLICKHOUSE_TIMEOUT,
    )
    response.raise_for_status()
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def _rows(owner: str, session: str, kind: str) -> list[dict]:
    return _query(
        "SELECT artifact_id, title, url, detail FROM chat_artifacts FINAL "
        "WHERE username = {owner:String} AND session_id = {session:String} "
        "AND kind = {kind:String} AND is_deleted = 0 AND status = 'ok' "
        "ORDER BY JSONExtractUInt(detail, 'read_ns') DESC, created_at DESC, artifact_id DESC",
        owner, session, kind=kind,
    )


def _id(owner: str, session: str, kind: str, url: str, version: str) -> str:
    return str(uuid.uuid5(NAMESPACE, canonical_json([owner, session, kind, url, version])))


def store_read(owner: str, session: str, page) -> str:
    """Store successful source text before returning its preview identifier."""
    if not owner or not session or page.error or page.blocked or not page.full_text:
        return ""
    body = canonical_json({"url": page.url, "final_url": page.final_url,
                           "title": page.title, "version": page.version,
                           "markdown": page.full_text}).encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("The captured page exceeds the citation storage limit.")
    artifact_id = _id(owner, session, KIND_PAGE_TEXT, page.url, page.version)
    artifacts.write_required(
        artifacts.ArtifactRequest(username=owner, session_id=session, kind=KIND_PAGE_TEXT,
                                  tool_name="read_page", url=page.url, title=page.title,
                                  detail=canonical_json({"version": page.version, "read_ns": time.time_ns()})),
        artifact_id, artifact_id, body, "application/json",
    )
    return artifact_id


def _details(row: dict) -> dict:
    try:
        value = json.loads(row.get("detail") or "{}")
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _references(value):
    if isinstance(value, str):
        try:
            yield from _references(json.loads(value))
        except ValueError:
            return
    elif isinstance(value, list):
        for item in value:
            yield from _references(item)
    elif isinstance(value, dict):
        if re.fullmatch(r"\[W[1-9]\d*\]", str(value.get("handle") or "")):
            yield value
        for name in ("items", "citations", "content", "text", "result", "structuredContent"):
            if name in value:
                yield from _references(value[name])


def _bindings(owner: str, session: str) -> tuple[dict, set[int]]:
    refs = [_details(row) for row in _rows(owner, session, KIND_PAGE_CITATION)]
    committed = _query(
        "SELECT tool_output AS result FROM chat_messages FINAL "
        "WHERE username = {owner:String} AND session_id = {session:String} "
        "AND tool_name = 'cite_pages' "
        "UNION ALL SELECT content AS result FROM agent_run_messages FINAL "
        "WHERE username = {owner:String} AND session_id = {session:String} "
        "AND role = 'tool' AND tool_name = 'cite_pages'", owner, session,
    )
    for row in committed:
        refs.extend(_references(row.get("result") or ""))
    bindings, reserved, handles = {}, set(), {}
    for ref in refs:
        handle = str(ref.get("handle") or "")
        if not re.fullmatch(r"\[W[1-9]\d*\]", handle):
            continue
        reserved.add(int(handle[2:-1]))
        key = (ref.get("url"), ref.get("version"))
        if not all(key):
            continue
        if handle in handles and handles[handle] != key:
            raise ValueError("Stored web citation handles name different source versions.")
        if key in bindings and bindings[key] != handle:
            raise ValueError("A stored page version has conflicting web citation handles.")
        bindings[key], handles[handle] = handle, key
    return bindings, reserved


def passages(text: str, terms: list[str]) -> tuple[list[str], list[dict]]:
    """Return exact case-sensitive source spans and bounded source excerpts."""
    spans, quotes = [], []
    for term in terms:
        start = text.find(term)
        if start < 0:
            raise ValueError(f"The captured page does not contain the exact text {term!r}.")
        end = start + len(term)
        spans.append({"text": term, "start": start, "end": end})
        left, right = max(0, start - 160), min(len(text), end + 240)
        quote = text[left:right]
        if quote not in quotes:
            quotes.append(quote)
    return quotes or [text[:600]], spans


def _cite(owner: str, session: str, pages: list) -> dict:
    if not owner or not session:
        return {"citations": [], "errors": [{"error": "Web citations require an owned chat session."}]}
    bindings, reserved = _bindings(owner, session)
    rows = _rows(owner, session, KIND_PAGE_TEXT)
    citations, errors = [], []
    for item in pages:
        url = item.get("url", "") if isinstance(item, dict) else ""
        try:
            if not isinstance(item, dict) or not isinstance(url, str) or not url:
                raise ValueError("Give each page as an object with a URL string.")
            terms = item.get("terms", [])
            if (not isinstance(terms, list) or not 1 <= len(terms) <= 8
                    or any(not isinstance(t, str) or not t or len(t) > 200 for t in terms)):
                raise ValueError("Give one to eight exact terms of one to 200 characters.")
            version = item.get("version", "")
            row = next((row for row in rows if row["url"] == url
                        and (not version or _details(row).get("version") == version)), None)
            if row is None:
                raise ValueError("Read this page successfully with read_page before citing it.")
            body, size = artifacts.read_range(owner, session, row["artifact_id"], 0, MAX_BODY_BYTES)
            if size > MAX_BODY_BYTES or len(body) != size:
                raise ValueError("The captured page exceeds the citation storage limit.")
            source = json.loads(body)
            try:
                quotes, spans = passages(source["markdown"], terms)
            except ValueError as exc:
                from browser_use_server.read_page import focus
                candidate, _ = focus(source["markdown"], " ".join(terms), 600)
                errors.append({"url": url, "error": str(exc), "candidate": candidate,
                               "version": source["version"]})
                continue
            key = (url, source["version"])
            handle = bindings.get(key)
            if handle is None:
                number = next((n for n in range(1, MAX_CITATIONS + 1) if n not in reserved), None)
                if number is None:
                    raise ValueError("This conversation has reached its web citation limit.")
                handle = f"[W{number}]"
            ref = {"handle": handle, "url": url, "final_url": source["final_url"],
                   "title": source["title"], "version": source["version"],
                   "artifact_id": row["artifact_id"], "terms": terms,
                   "quotes": quotes, "spans": spans, "quote_verified": True}
            artifact_id = _id(owner, session, KIND_PAGE_CITATION, *key)
            artifacts.write_required(
                artifacts.ArtifactRequest(username=owner, session_id=session,
                                          kind=KIND_PAGE_CITATION, tool_name="cite_pages",
                                          title=handle, url=url,
                                          detail=canonical_json({k: ref[k] for k in
                                                                 ("handle", "url", "version")})),
                artifact_id, artifact_id, canonical_json(ref).encode("utf-8"), "application/json",
            )
            bindings[key] = handle
            reserved.add(int(handle[2:-1]))
            citations.append(ref)
        except (ValueError, KeyError, LookupError, PermissionError, artifacts.ArtifactWriteFailed) as exc:
            errors.append({"url": url, "error": str(exc)})
    return {"citations": citations, "errors": errors}


async def cite(owner: str, session: str, pages: object) -> dict:
    """Allocate handles serially and keep storage operations outside the event loop."""
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES_PER_CALL:
        return {"citations": [], "errors": [{"error": "Give one to twelve page citation objects."}]}
    async with _lock:
        task = asyncio.create_task(asyncio.to_thread(_cite, owner, session, pages))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except Exception:
                pass
            raise
