"""The chat and board citation handles of a chat session: `[Cn]` for a chat, `[Bn]` for a board.

`cite_chats_and_boards` gives one handle for each chat or board that an answer uses. The
handles of a session are numbered once for the session, each kind from 1, like the document
handles `[Dn]`. The same item cited again keeps its first handle.

**One binding, one required artifact.** A new handle is stored before the tool returns it,
through `agent_common.artifacts.write_required`, as a `chat_artifacts` row of kind
`item_citation`. The artifact id is a `uuid5` of the owner, the session, the kind and the
item id, so a retry writes the same row. The row keeps the handle in `title` and the item in
`detail`. The artifact sweeper removes the rows when a person deletes the chat.

**One allocator.** The allocation runs under one process lock and reads the stored rows of
the session each time. The compose service runs one server process. More than one allocating
process needs a shared ordered authority, which this store is not.
"""

from __future__ import annotations

import json
import threading
import uuid

from agent_common import artifacts
from agent_common.result_pages import canonical_json

#: The `chat_artifacts` kind of a stored chat or board handle.
KIND_ITEM_CITATION = artifacts.KIND_ITEM_CITATION

#: The namespace of the artifact ids of the bindings. Fixed, because every stored id derives
#: from it.
NAMESPACE = uuid.UUID("7d2c5b14-3f8e-4a61-9c07-5e1b2a6f8d43")

#: The highest handle number of each kind in one session. Mirrors
#: `common::chat_items::MAX_ITEM_HANDLE` in the website.
MAX_HANDLES = 200

#: The kinds and the letter of their handles.
PREFIXES = {"chat": "C", "board": "B"}

_lock = threading.Lock()


def binding_id(owner: str, session_id: str, kind: str, item_id: str) -> str:
    """The artifact id of the binding of one item in one session of one owner."""
    return str(uuid.uuid5(NAMESPACE, canonical_json([owner, session_id, kind, item_id])))


class ItemHandleStore:
    """Reads and writes the bindings of a session as `chat_artifacts` rows."""

    def load(self, owner: str, session_id: str) -> dict[tuple[str, str], str]:
        from collection_search_server.backends import GLOBAL_DB, clickhouse_query

        rows = clickhouse_query(
            "SELECT title, detail FROM chat_artifacts FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} AND kind = {k:String} AND is_deleted = 0 "
            "AND status = 'ok'",
            database=GLOBAL_DB,
            params={"u": owner, "s": session_id, "k": KIND_ITEM_CITATION},
        )
        out: dict[tuple[str, str], str] = {}
        for row in rows:
            try:
                detail = json.loads(row.get("detail") or "{}")
            except ValueError:
                continue
            key = (str(detail.get("kind") or ""), str(detail.get("id") or ""))
            if key[0] in PREFIXES and key[1] and row.get("title"):
                out[key] = str(row["title"])
        return out

    def persist(self, owner: str, session_id: str, kind: str, item_id: str, handle: str) -> None:
        artifact_id = binding_id(owner, session_id, kind, item_id)
        detail = canonical_json({"kind": kind, "id": item_id})
        body = canonical_json({"owner": owner, "session_id": session_id, "kind": kind,
                               "id": item_id, "handle": handle}).encode("utf-8")
        artifacts.write_required(
            artifacts.ArtifactRequest(session_id=session_id, username=owner,
                                      kind=KIND_ITEM_CITATION, tool_name="cite_chats_and_boards",
                                      title=handle, detail=detail),
            artifact_id, artifact_id, body, "application/json")


def handle_number(handle: str, kind: str) -> int:
    """The number of a handle of `kind`, or 0 for another text."""
    prefix = PREFIXES.get(kind, "")
    if prefix and handle.startswith(f"[{prefix}") and handle.endswith("]") and handle[2:-1].isdigit():
        return int(handle[2:-1])
    return 0


def allocate(store: ItemHandleStore, owner: str, session_id: str, kind: str, item_id: str) -> str:
    """The handle of one item in one session, allocated and stored when it is new. An empty
    string once the session used every handle of the kind. Raises
    `artifacts.ArtifactWriteFailed` when a new handle was not stored, and returns nothing then."""
    with _lock:
        bound = store.load(owner, session_id)
        existing = bound.get((kind, item_id))
        if existing:
            return existing
        used = {handle_number(handle, kind) for (k, _), handle in bound.items() if k == kind}
        number = max(used, default=0) + 1
        if number > MAX_HANDLES:
            return ""
        handle = f"[{PREFIXES[kind]}{number}]"
        store.persist(owner, session_id, kind, item_id, handle)
        return handle


__all__ = ["ItemHandleStore", "KIND_ITEM_CITATION", "MAX_HANDLES", "allocate", "binding_id"]
