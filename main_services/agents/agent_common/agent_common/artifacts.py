"""Chat artifacts: bytes in S3, one index row in ClickHouse.

An artifact is a blob a tool produced that is too big to put in the model's context but
that the *user* should be able to see: the full before/after ordering of a web search,
the captured HTML and screenshot of a page the agent visited.

The contract, and every part of it decides where the object lands:

* The model receives **only the `artifact_id`**, a UUID of about 36 characters. It is a lookup
  key, never a capability: the website resolves it back to `session_id`/`username` and
  enforces owner-or-admin before serving a single byte.
* Bytes go under `derived/chat-artifacts/…` (see :mod:`.s3_store`), which the ingest
  walker must never see.
* Objects are written **before** the row. A crash between the two leaves an orphan object
  the retention sweeper's prefix scan collects. The reverse order would leave a row
  pointing at nothing, which the UI would render as a broken artifact forever.
* A failure to write an artifact **never fails the tool**. The search still happened; the
  page was still read. `write()` returns `None` and logs, and the caller omits the id.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

from agent_common import s3_store

log = logging.getLogger(__name__)

GLOBAL_DB = "Hoover4_Processing"

#: A ClickHouse insert on the tool's critical path. Short on purpose: an artifact is a
#: nicety, and the tool result is what the user is waiting for.
CLICKHOUSE_TIMEOUT = float(os.getenv("ARTIFACT_CLICKHOUSE_TIMEOUT", "10"))

#: Recognised `kind` values. Not enforced by the schema (LowCardinality(String) takes
#: anything) but enumerated here so the writers and the UI agree. `search_detail` and
#: `page_capture` are best-effort, written through `write()`. `agent_raw_result` and
#: `agent_plan_document` are required, written through `write_required()`: the caller
#: gets a raised error rather than a silently missing artifact id.
KIND_SEARCH_DETAIL = "search_detail"
KIND_PAGE_CAPTURE = "page_capture"
KIND_AGENT_RAW_RESULT = "agent_raw_result"
KIND_AGENT_PLAN_DOCUMENT = "agent_plan_document"

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
    #: Set only by `write_required`. Empty for a best-effort `write` row.
    body_sha256: str = ""
    #: Set only by `write_required`. Empty for a best-effort `write` row.
    idempotency_key: str = ""

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
            "body_sha256": self.body_sha256,
            "idempotency_key": self.idempotency_key,
        }


@dataclass
class ArtifactRequest:
    """What a tool wants stored, before any key is chosen."""

    session_id: str
    username: str
    kind: str
    tool_name: str
    #: `(filename, bytes, content_type)` for the main document, JSON detail or HTML page.
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
    #: so nothing new shares a body key, but the *sweeper* still has to handle
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
    still has to serve its tools; it produces no artifacts.
    """
    return os.getenv("CHAT_ARTIFACTS_ENABLED", "true").lower() in ("1", "true", "yes")


def write(request: ArtifactRequest, artifact_id: str | None = None) -> str | None:
    """Store an artifact and return its id, or `None` if it could not be stored.

    Never raises. See the module docstring: the tool result is worth more to the caller than
    its bookkeeping.
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
        client = s3_store.get_s3_client()
        if request.reuse_body_key:
            row.body_key = request.reuse_body_key
            row.body_bytes = request.reuse_body_bytes
        elif request.body is not None:
            name, data, content_type = request.body
            key = s3_store.artifact_key(request.session_id, artifact_id, name)
            row.body_bytes = s3_store.put_bytes(key, data, content_type, client=client)
            row.body_key = key
        if request.thumb is not None:
            name, data, content_type = request.thumb
            key = s3_store.artifact_key(request.session_id, artifact_id, name)
            row.thumb_bytes = s3_store.put_bytes(key, data, content_type, client=client)
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


class ArtifactWriteFailed(RuntimeError):
    """`write_required` could not complete. The caller returns a typed
    `artifact_write_failed` result and no page, rather than one with a missing link."""


def write_required(
    request: ArtifactRequest,
    artifact_id: str,
    idempotency_key: str,
    body: bytes,
    content_type: str,
) -> str:
    """Store a raw result or plan document the model's page could not carry whole.

    Unlike `write`, this raises instead of returning `None`: the caller (a broker
    building a page, or a plan role storing a document) has already decided the body
    matters enough to need a working link, and a silently missing artifact id would leave
    that link broken with nothing in the transcript saying why.

    The caller creates `artifact_id` and `idempotency_key` before the first attempt, so a
    retry after a partial failure writes the same object key (no attempt number in it)
    and, because every column but `created_at` is fixed by that key, replaces the same row
    rather than adding a second one.

    1. Upload the body to `s3_store.artifact_key(session_id, artifact_id, "detail.json")`,
       as `write_json_detail` does for the best-effort path.
    2. Insert one row with `status='ok'`, the size, the digest and `body_key` set to that
       key. The serving route reads `detail.json` from `body_key`; an empty `body_key`
       would store a body nobody can open.
    3. Read the row back, `FINAL`, by owner and id, and confirm its digest matches.
    4. Any failure raises `ArtifactWriteFailed`.

    The object is written before the row, exactly as in `write`: a crash between the two
    leaves an orphan object, which the sweeper's orphan step collects after its grace
    period. That step already covers this case, because it does not distinguish a
    best-effort write's orphan from a required write's.
    """
    if not enabled():
        raise ArtifactWriteFailed("chat artifacts are disabled for this container")
    if not (request.session_id or "").strip():
        raise ArtifactWriteFailed("no chat session on this call")

    digest = hashlib.sha256(body).hexdigest()

    try:
        client = s3_store.get_s3_client()
        key = s3_store.artifact_key(request.session_id, artifact_id, "detail.json")
        body_bytes = s3_store.put_bytes(key, body, content_type, client=client)
    except Exception as exc:  # noqa: BLE001 - one failure class, raised with context
        raise ArtifactWriteFailed(
            f"could not store required artifact bytes for {artifact_id}: {exc}"
        ) from exc

    row = ArtifactRow(
        artifact_id=artifact_id,
        session_id=request.session_id,
        username=request.username or "",
        kind=request.kind,
        tool_name=request.tool_name,
        url=request.url or "",
        title=(request.title or "")[:500],
        body_key=key,
        body_bytes=body_bytes,
        status=STATUS_OK,
        detail=(request.detail or "")[:2000],
        body_sha256=digest,
        idempotency_key=idempotency_key,
    )

    try:
        insert_row(row)
    except Exception as exc:  # noqa: BLE001 - same
        raise ArtifactWriteFailed(f"could not index required artifact {artifact_id}: {exc}") from exc

    try:
        stored_digest = _read_back_body_sha256(row.username, artifact_id)
    except Exception as exc:  # noqa: BLE001 - same
        raise ArtifactWriteFailed(f"could not confirm required artifact {artifact_id}: {exc}") from exc
    if stored_digest != digest:
        raise ArtifactWriteFailed(
            f"required artifact {artifact_id} digest mismatch after write "
            f"(wrote {digest}, read back {stored_digest!r})"
        )

    log.info(
        "required artifact %s kind=%s tool=%s body=%dB",
        artifact_id, row.kind, row.tool_name, row.body_bytes,
    )
    return artifact_id


def _read_back_body_sha256(username: str, artifact_id: str) -> str | None:
    """`body_sha256` of the newest, non-deleted row for `(username, artifact_id)`, or
    `None` when no such row is visible yet. `FINAL` forces the read past any unmerged
    duplicate part."""
    import requests

    url = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123").rstrip("/")
    response = requests.post(
        url,
        params={
            "database": GLOBAL_DB,
            "user": os.getenv("CLICKHOUSE_USER", "hoover4"),
            "password": os.getenv("CLICKHOUSE_PASSWORD", "hoover4"),
            "default_format": "JSONEachRow",
            "param_username": username,
            "param_artifact_id": artifact_id,
        },
        data=(
            b"SELECT body_sha256 FROM chat_artifacts FINAL "
            b"WHERE username = {username:String} AND artifact_id = {artifact_id:String} "
            b"AND is_deleted = 0 LIMIT 1"
        ),
        timeout=CLICKHOUSE_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"ClickHouse select failed {response.status_code}: {response.text[:400]}")
    lines = [line for line in response.text.splitlines() if line.strip()]
    if not lines:
        return None
    return json.loads(lines[0]).get("body_sha256")


class ArtifactRangeRefused(ValueError):
    """A range read that names an artifact the caller does not own, or a range outside it."""


class ArtifactNotFound(LookupError):
    """No readable artifact row has this id."""


class ArtifactForbidden(PermissionError):
    """The artifact belongs to another caller or another chat."""


def _artifact_row(artifact_id: str) -> dict[str, Any] | None:
    """The owner, session, body key and size of the newest non-deleted row for the id."""
    import requests

    url = os.getenv("CLICKHOUSE_URL", "http://clickhouse:8123").rstrip("/")
    response = requests.post(
        url,
        params={
            "database": GLOBAL_DB,
            "user": os.getenv("CLICKHOUSE_USER", "hoover4"),
            "password": os.getenv("CLICKHOUSE_PASSWORD", "hoover4"),
            "default_format": "JSONEachRow",
            "param_artifact_id": artifact_id,
        },
        data=(
            b"SELECT username, session_id, body_key, body_bytes FROM chat_artifacts FINAL "
            b"WHERE artifact_id = {artifact_id:String} AND is_deleted = 0 AND status = 'ok' LIMIT 1"
        ),
        timeout=CLICKHOUSE_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(f"ClickHouse select failed {response.status_code}: {response.text[:400]}")
    lines = [line for line in response.text.splitlines() if line.strip()]
    return json.loads(lines[0]) if lines else None


def read_range(
    username: str, session_id: str, artifact_id: str, start: int, length: int,
) -> tuple[bytes, int]:
    """Read a byte range of one stored artifact body, and return it with the body size.

    The owner check is the one of the website's artifact route: the caller must be the
    non-empty owner of the row, else `ArtifactForbidden`. The session must also match,
    because a continuation belongs to one chat. An unknown id is `ArtifactNotFound`. The
    caller passes `length` already cut to its page share. This
    function cuts `start + length` to the body size, and refuses a `start` at or past the
    end with `ArtifactRangeRefused`.
    """
    if start < 0 or length < 0:
        raise ArtifactRangeRefused("the artifact range is negative")
    row = _artifact_row(artifact_id)
    if row is None:
        raise ArtifactNotFound(f"artifact {artifact_id} does not exist")
    if not username or row.get("username") != username or row.get("session_id") != session_id:
        raise ArtifactForbidden(f"artifact {artifact_id} belongs to another caller")
    size = int(row.get("body_bytes") or 0)
    if start >= size:
        raise ArtifactRangeRefused(f"start {start} is past the end of artifact {artifact_id} ({size} bytes)")
    length = min(length, size - start)
    return s3_store.get_range(row["body_key"], start, length), size


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
