"""Chat artifacts: bytes in MinIO, one index row in ClickHouse.

An artifact is a blob a tool produced that is too big to put in the model's context but
that the *user* should be able to see: the full before/after ordering of a web search,
the captured HTML and screenshot of a page the agent visited.

The contract, and every part of it is load-bearing:

* The model receives **only the `artifact_id`** — a UUID, ~36 characters. It is a lookup
  key, never a capability: the website resolves it back to `session_id`/`username` and
  enforces owner-or-admin before serving a single byte.
* Bytes go under `derived/chat-artifacts/…` (see :mod:`.minio_store`), which the ingest
  walker must never see.
* Objects are written **before** the row. A crash between the two leaves an orphan object
  the retention sweeper's prefix scan collects. The reverse order would leave a row
  pointing at nothing, which the UI would render as a broken artifact forever.
* A failure to write an artifact **never fails the tool**. The search still happened; the
  page was still read. `write()` returns `None` and logs, and the caller omits the id.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_common import minio_store

log = logging.getLogger(__name__)

GLOBAL_DB = "Hoover4_Processing"

#: A ClickHouse insert on the tool's critical path. Short on purpose: an artifact is a
#: nicety, and the tool result is what the user is waiting for.
CLICKHOUSE_TIMEOUT = float(os.getenv("ARTIFACT_CLICKHOUSE_TIMEOUT", "10"))

#: Recognised `kind` values. Not enforced by the schema (LowCardinality(String) takes
#: anything) but enumerated here so the two writers and the UI agree.
KIND_SEARCH_DETAIL = "search_detail"
KIND_PAGE_CAPTURE = "page_capture"

STATUS_OK = "ok"
STATUS_TOO_LARGE = "too_large"
STATUS_FAILED = "failed"


@dataclass
class ArtifactRow:
    """One `chat_artifacts` row, before it is written."""

    artifact_id: str
    session_id: str
    username: str
    kind: str
    tool_name: str
    url: str = ""
    title: str = ""
    thumb_key: str = ""
    body_key: str = ""
    body_bytes: int = 0
    thumb_bytes: int = 0
    status: str = STATUS_OK
    detail: str = ""

    def as_json_row(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "session_id": self.session_id,
            "username": self.username,
            "kind": self.kind,
            "tool_name": self.tool_name,
            "url": self.url,
            "title": self.title,
            "thumb_key": self.thumb_key,
            "body_key": self.body_key,
            "body_bytes": int(self.body_bytes),
            "thumb_bytes": int(self.thumb_bytes),
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class ArtifactRequest:
    """What a tool wants stored, before any key is chosen."""

    session_id: str
    username: str
    kind: str
    tool_name: str
    #: `(filename, bytes, content_type)` for the main document — JSON detail or HTML page.
    body: tuple[str, bytes, str] | None = None
    #: Same shape, for the WebP thumbnail.
    thumb: tuple[str, bytes, str] | None = None
    url: str = ""
    title: str = ""
    status: str = STATUS_OK
    detail: str = ""
    #: Point this artifact at an already-stored body instead of writing one.
    #:
    #: **No caller sets this any more.** It existed for the implicit-capture path, which
    #: re-captured after every browser action and skipped the second MHTML serialisation
    #: when `(url, document.lastModified)` had not moved. Implicit captures are gone
    #: (Q4/Q5), so nothing shares a body key now — but the *sweeper* still has to handle
    #: rows written while it did, which is why the field and its handling stay rather than
    #: being deleted. Do not reach for it: two artifacts pointing at one object means
    #: deleting either one can strand the other.
    reuse_body_key: str = ""
    reuse_body_bytes: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def new_id() -> str:
    return str(uuid.uuid4())


def enabled() -> bool:
    """Whether this container is configured to write artifacts at all.

    A server with no ClickHouse reachable (a developer running it bare, the unit tests)
    still has to serve its tools; it simply produces no artifacts.
    """
    return os.getenv("CHAT_ARTIFACTS_ENABLED", "true").lower() in ("1", "true", "yes")


def write(request: ArtifactRequest, artifact_id: str | None = None) -> str | None:
    """Store an artifact and return its id, or `None` if it could not be stored.

    Never raises. See the module docstring: the tool result matters more than its
    bookkeeping.
    """
    if not enabled():
        return None
    if not (request.session_id or "").strip():
        # No session means no ACL to resolve on read, so the artifact would be
        # unreachable by design. Better to skip it than to write bytes nobody can fetch.
        log.debug("artifact skipped: no chat session on this call")
        return None

    artifact_id = artifact_id or new_id()
    row = ArtifactRow(
        artifact_id=artifact_id,
        session_id=request.session_id,
        username=request.username or "",
        kind=request.kind,
        tool_name=request.tool_name,
        url=request.url or "",
        title=(request.title or "")[:500],
        status=request.status,
        detail=(request.detail or "")[:2000],
    )

    try:
        client = minio_store.get_minio_client()
        if request.reuse_body_key:
            row.body_key = request.reuse_body_key
            row.body_bytes = request.reuse_body_bytes
        elif request.body is not None:
            name, data, content_type = request.body
            key = minio_store.artifact_key(request.session_id, artifact_id, name)
            row.body_bytes = minio_store.put_bytes(key, data, content_type, client=client)
            row.body_key = key
        if request.thumb is not None:
            name, data, content_type = request.thumb
            key = minio_store.artifact_key(request.session_id, artifact_id, name)
            row.thumb_bytes = minio_store.put_bytes(key, data, content_type, client=client)
            row.thumb_key = key
    except Exception:  # noqa: BLE001 - an artifact is never worth failing a tool for
        log.exception("could not store artifact bytes for %s", artifact_id)
        return None

    try:
        insert_row(row)
    except Exception:  # noqa: BLE001 - same
        log.exception("could not index artifact %s", artifact_id)
        return None

    log.info(
        "artifact %s kind=%s tool=%s body=%dB thumb=%dB status=%s",
        artifact_id, row.kind, row.tool_name, row.body_bytes, row.thumb_bytes, row.status,
    )
    return artifact_id


def write_json_detail(
    session_id: str,
    username: str,
    tool_name: str,
    detail: dict[str, Any],
    title: str = "",
) -> str | None:
    """Store a `search_detail` JSON document. Convenience over :func:`write`."""
    body = json.dumps(detail, ensure_ascii=False, default=str).encode("utf-8")
    return write(
        ArtifactRequest(
            session_id=session_id,
            username=username,
            kind=KIND_SEARCH_DETAIL,
            tool_name=tool_name,
            title=title,
            body=("detail.json", body, "application/json"),
        )
    )


def insert_row(row: ArtifactRow) -> None:
    """Insert one row into `Hoover4_Processing.chat_artifacts` over the HTTP interface.

    Same approach as `collection_search_server/backends.py`: plain HTTP rather than a
    driver, because this is one INSERT and the image should not carry a ClickHouse client
    whose major version has to be tracked.
    """
    import requests

    url = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123").rstrip("/")
    payload = json.dumps(row.as_json_row(), ensure_ascii=False)
    response = requests.post(
        url,
        params={
            "database": GLOBAL_DB,
            "user": os.getenv("CLICKHOUSE_USER", "hoover4"),
            "password": os.getenv("CLICKHOUSE_PASSWORD", "hoover4"),
            "query": "INSERT INTO chat_artifacts FORMAT JSONEachRow",
        },
        data=payload.encode("utf-8"),
        timeout=CLICKHOUSE_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"ClickHouse insert failed {response.status_code}: {response.text[:400]}"
        )


#: Reserved key under which a tool result carries the artifacts it produced. The website
#: reads it off the tool payload; the model is told nothing about it beyond the id.
ARTIFACTS_KEY = "_hoover4_artifacts"


def artifacts_field(*entries: dict[str, Any]) -> dict[str, Any]:
    """Build the `_hoover4_artifacts` field for a tool result."""
    kept = [e for e in entries if e and e.get("artifact_id")]
    return {ARTIFACTS_KEY: kept} if kept else {}
