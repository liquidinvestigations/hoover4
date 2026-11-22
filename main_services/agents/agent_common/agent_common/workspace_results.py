"""Store and read immutable results in the conversation workspace."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass

from agent_common import artifacts
from agent_common.tool_packs import pack_of

KIND = "workspace_result"
WEB_KIND = artifacts.KIND_WEB_PAGE_TEXT
MAX_BODY_BYTES = 64 * 1024 * 1024
DISPLAY_EDGE = 2000
DISPLAY_LIMIT = max(4001, min(30000, int(os.getenv("AGENT_RESULT_CHARACTER_LIMIT", "15000"))))
COLLECTION_READS = {"read_documents", "doc_search_text", "doc_metadata", "doc_email",
                    "doc_diff_sources", "pdf_search", "list_document_entities"}
COLLECTION_RESULTS = {"search_collections", "search_passages", "search_facet_values",
                      "search_histogram", "search_entity_explainer", "read_more", "folder_list",
                      "folder_search", "table_overview", "table_page", "table_cell",
                      "table_column_values", "table_search_cells"}


def prefix(tool: str) -> str | None:
    if tool in COLLECTION_READS:
        return "sources/collections"
    if pack_of(tool) == "browser":
        return "sources/browser"
    if tool in COLLECTION_RESULTS or tool in {"read_page", "web_search", "whois_lookup", "execute", "read_chat", "read_board", "list_chats_and_boards"}:
        return "results"
    return None


def save(owner: str, session: str, operation: str, tool: str, content: str, collections: list[str],
         source: dict | None = None) -> dict:
    """Publish a path only after its body and index row are readable."""
    group = prefix(tool)
    if group is None:
        raise ValueError("This tool does not produce a saved result.")
    body = content.encode("utf-8")
    if len(body) > MAX_BODY_BYTES:
        raise ValueError("The result exceeds the workspace storage limit.")
    version = hashlib.sha256(body).hexdigest()
    artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([owner, session, operation, tool, version, source], sort_keys=True)))
    detail = json.dumps({
        "collections": sorted({name for name in collections if name})
        if pack_of(tool) == "collections" or tool == "execute" else [],
        "version": version, "chars": len(content), "source": source or {},
    }, ensure_ascii=False)
    if artifacts._artifact_row(artifact_id) is None:
        artifacts.write_required(
            artifacts.ArtifactRequest(session, owner, KIND, tool, title=(source or {}).get("title") or tool, detail=detail),
            artifact_id, operation, body, "text/plain; charset=utf-8",
        )
    return {"path": f"{group}/{artifact_id}", "version": version, "kind": tool,
            "extent": {"characters": len(content)}, **({"source": source} if source else {})}


def public_reference(reference):
    if not isinstance(reference, dict):
        return None
    return {key: value for key, value in reference.items()
            if key in {"path", "version", "kind"} and isinstance(value, str) and len(value) <= 300}


def display(content: str, reference: dict | None, limit: int) -> str | None:
    if len(content) <= limit:
        return None
    controls = {}
    try:
        value = json.loads(content)
    except ValueError:
        value = None
    if isinstance(value, dict):
        for key in ("success", "status", "error", "next_offset", "more", "continuation", "version"):
            field = value.get(key)
            if isinstance(field, (bool, int)) or isinstance(field, str) and len(field) <= 160:
                controls[key] = field
    recovery = (json.dumps({"result_ref": public_reference(reference)}, ensure_ascii=False) if reference else
                "The omitted content could not be saved.")
    controls_text = json.dumps(controls, ensure_ascii=False)
    room = max(0, limit - len(recovery) - len(controls_text) - 64)
    edge = min(DISPLAY_EDGE, room // 2)
    boundary = f"{len(content) - 2 * edge} characters omitted."
    return (f"{content[:edge]}\n\n{boundary}\n{recovery}\n{controls_text}\n\n"
            + (content[-edge:] if edge else ""))


@dataclass(frozen=True)
class Entry:
    artifact_id: str
    tool: str
    version: str
    chars: int
    path: str
    title: str
    url: str
    source: dict

    def as_dict(self) -> dict:
        return {"path": self.path, "version": self.version, "kind": self.tool,
                "extent": {"characters": self.chars}, "title": self.title, "url": self.url,
                **({"source": self.source} if self.source else {})}


def entries(owner: str, session: str, collections: list[str], *, after: str = "",
            artifact_id: str = "", limit: int = 100) -> list[Entry]:
    rows = artifacts.query_rows(
        "SELECT artifact_id, tool_name, title, url, kind, detail FROM chat_artifacts FINAL "
        "WHERE username = {owner:String} AND session_id = {session:String} "
        "AND kind IN ('workspace_result', 'web_page_text') AND is_deleted = 0 AND status = 'ok' "
        "AND isValidJSON(detail) AND (kind != 'workspace_result' OR JSONHas(detail, 'collections')) "
        "AND (username, session_id) NOT IN (SELECT username, session_id FROM chat_sessions WHERE is_deleted = 1) "
        "AND artifact_id > {after:String} AND ({id:String} = '' OR artifact_id = {id:String}) "
        "AND hasAll(JSONExtract({collections:String}, 'Array(String)'), "
        "JSONExtract(detail, 'collections', 'Array(String)')) "
        "ORDER BY artifact_id LIMIT {limit:UInt32}",
        owner=owner, session=session, after=after, id=artifact_id, limit=str(limit),
        collections=json.dumps(collections),
    )
    result = []
    for row in rows:
        detail = json.loads(row["detail"])
        group = "sources/web" if row["kind"] == WEB_KIND else prefix(row["tool_name"])
        if group:
            result.append(Entry(row["artifact_id"], row["tool_name"], detail["version"],
                                detail.get("chars", 0), f"{group}/{row['artifact_id']}",
                                row["title"], row["url"], detail.get("source") or {}))
    return result


def read(owner: str, session: str, collections: list[str], path: str, version: str | None = None) -> tuple[Entry, str]:
    try:
        artifact_id = str(uuid.UUID(path.rsplit("/", 1)[-1]))
    except ValueError as exc:
        raise LookupError("The saved result path is invalid.") from exc
    rows = entries(owner, session, collections, artifact_id=artifact_id)
    if not rows or path != rows[0].path or (version is not None and str(version) != rows[0].version):
        raise LookupError("The saved result or version is unavailable.")
    entry = rows[0]
    body, size = artifacts.read_range(owner, session, artifact_id, 0, MAX_BODY_BYTES)
    if len(body) != size:
        raise LookupError("The stored result is incomplete.")
    if path.startswith("sources/web/"):
        return entry, json.loads(body)["markdown"]
    return entry, body.decode("utf-8")


def record_citations(owner: str, session: str, operation: str, tool: str, payload: dict) -> None:
    """Keep verified nested citations available to the report writer before it commits."""
    if tool not in {"cite_documents", "cite_pages"}:
        raise ValueError("This operation does not verify citations.")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps([
        owner, session, operation, tool, hashlib.sha256(body).hexdigest(),
    ])))
    if artifacts._artifact_row(artifact_id) is None:
        artifacts.write_required(
            artifacts.ArtifactRequest(session, owner, "workspace_code_citation", tool),
            artifact_id, operation, body, "application/json",
        )
