"""The durable citation handles of the chat sessions: `ArtifactBindingStore`.

**One binding, one required artifact.** A new handle is stored before `cite_documents`
returns it, through `agent_common.artifacts.write_required`, as a `chat_artifacts` row of
kind `citation_binding` with its body in the system bucket. The artifact id is a `uuid5` of
the owner, the session and the document, so a retry writes the same row. The row keeps the
handle in `title` and the document in `detail`, so a load reads rows and no object.

**The committed results.** A load also reads the handles of the committed
`cite_documents` results of the session: the `doc_refs` of the transcript rows, and the
typed evidence (`usage_json.evidence`) of the run messages of every depth. A run message
from before the typed evidence shows a handle with no whole document, and its number stays
reserved. `citations.merge_legacy` binds a result handle only when it is unambiguous.

The artifact sweeper removes a binding row after the retention period. The committed
results then keep the handle reserved, and a transcript result keeps it bound.

**One allocator.** The handles of a session are chosen under the lock of `HandleTable` in
one process. The compose service runs one container with one server process. More than one
allocating process needs a shared ordered authority, which this store is not.
"""

from __future__ import annotations

import json
import logging
import uuid

from agent_common import artifacts
from agent_common.result_pages import canonical_json
from collection_search_server.backends import GLOBAL_DB, clickhouse_query
from collection_search_server.citations import BindingStore, LoadedBindings, merge_legacy

log = logging.getLogger(__name__)

#: The `chat_artifacts` kind of a stored citation handle.
KIND_CITATION_BINDING = artifacts.KIND_CITATION_BINDING

#: The namespace of the artifact ids of the bindings. Fixed, because every stored id
#: derives from it.
BINDING_NAMESPACE = uuid.UUID("3c1f7a52-9d4e-5b08-8e61-2a7d4c9f0b15")

#: The session value of a call with no session header. Its handles are not stored.
NO_SESSION = "_no_session"


def binding_id(owner: str, session_id: str, collectionname: str, file_hash: str) -> str:
    """The artifact id of the binding of one document in one session of one owner."""
    return str(uuid.uuid5(BINDING_NAMESPACE,
                          f"{owner}\n{session_id}\n{collectionname}\n{file_hash}"))


def _stored(owner: str, session_id: str) -> dict[tuple[str, str], str]:
    rows = clickhouse_query(
        "SELECT title, detail FROM chat_artifacts FINAL WHERE username = {u:String} "
        "AND session_id = {s:String} AND kind = {k:String} AND is_deleted = 0 "
        "AND status = 'ok'",
        database=GLOBAL_DB,
        params={"u": owner, "s": session_id, "k": KIND_CITATION_BINDING},
    )
    out: dict[tuple[str, str], str] = {}
    for row in rows:
        try:
            detail = json.loads(row.get("detail") or "{}")
        except ValueError:
            continue
        document = (str(detail.get("collectionname") or ""), str(detail.get("file_hash") or ""))
        if all(document) and row.get("title"):
            out[document] = str(row["title"])
    return out


def _transcript_results(owner: str, session_id: str) -> tuple[list, set[int]]:
    """The handles of the transcript rows of `cite_documents`: the pairs whose ref has the
    whole hash, and the numbers of the handles whose ref has a hash start only."""
    from collection_search_server.citations import handle_number

    rows = clickhouse_query(
        "SELECT doc_refs FROM chat_messages FINAL WHERE username = {u:String} "
        "AND session_id = {s:String} AND tool_name = 'cite_documents' AND doc_refs != ''",
        database=GLOBAL_DB,
        params={"u": owner, "s": session_id},
    )
    pairs: list[tuple[str, tuple[str, str]]] = []
    numbers: set[int] = set()
    for row in rows:
        try:
            refs = json.loads(row.get("doc_refs") or "[]")
        except ValueError:
            continue
        for ref in refs if isinstance(refs, list) else []:
            if not (isinstance(ref, dict) and ref.get("handle")):
                continue
            file_hash = str(ref.get("file_hash") or "")
            if len(file_hash) == 64 and ref.get("collectionname"):
                pairs.append((str(ref["handle"]), (str(ref["collectionname"]), file_hash)))
            elif handle_number(str(ref["handle"])):
                numbers.add(handle_number(str(ref["handle"])))
    return pairs, numbers


def _run_results(owner: str, session_id: str) -> tuple[list, set[int]]:
    """The handles of the stored `cite_documents` results of every run depth: the pairs of
    the typed evidence, and the numbers of the handles of results with no evidence."""
    from collection_search_server.citations import handle_number

    rows = clickhouse_query(
        "SELECT content, usage_json FROM agent_run_messages FINAL WHERE username = {u:String} "
        "AND session_id = {s:String} AND role = 'tool' AND tool_name = 'cite_documents'",
        database=GLOBAL_DB,
        params={"u": owner, "s": session_id},
    )
    pairs: list[tuple[str, tuple[str, str]]] = []
    numbers: set[int] = set()
    for row in rows:
        try:
            usage = json.loads(row.get("usage_json") or "{}")
        except ValueError:
            usage = {}
        evidence = usage.get("evidence") if isinstance(usage, dict) else None
        if isinstance(evidence, list):
            for entry in evidence:
                reference = entry.get("reference") if isinstance(entry, dict) else None
                if (entry.get("kind") == "citation" and entry.get("status") == "ok"
                        and isinstance(reference, dict) and reference.get("handle")
                        and reference.get("collectionname")
                        and len(str(reference.get("file_hash") or "")) == 64):
                    pairs.append((str(reference["handle"]),
                                  (str(reference.get("collectionname") or ""),
                                   str(reference["file_hash"]))))
            continue
        try:
            content = json.loads(row.get("content") or "{}")
        except ValueError:
            continue
        items = content.get("citations") if isinstance(content, dict) else None
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and handle_number(str(item.get("handle") or "")):
                numbers.add(handle_number(str(item["handle"])))
    return pairs, numbers


class ArtifactBindingStore(BindingStore):
    """Stores each handle as a required artifact, and loads the stored and committed
    handles of a session."""

    def load(self, owner: str, session_id: str) -> LoadedBindings:
        if not owner or session_id == NO_SESSION:
            return LoadedBindings()
        persisted = _stored(owner, session_id)
        run_pairs, run_numbers = _run_results(owner, session_id)
        row_pairs, row_numbers = _transcript_results(owner, session_id)
        loaded = merge_legacy(persisted, row_pairs + run_pairs, run_numbers | row_numbers)
        if loaded.conflicts:
            log.warning("citation handles of session %s have conflicts: %s", session_id,
                        loaded.conflicts)
        return loaded

    def persist(self, owner: str, session_id: str, collectionname: str, file_hash: str,
                handle: str) -> None:
        if not owner or session_id == NO_SESSION:
            return
        artifact_id = binding_id(owner, session_id, collectionname, file_hash)
        detail = canonical_json({"collectionname": collectionname, "file_hash": file_hash})
        body = canonical_json({"owner": owner, "session_id": session_id,
                               "collectionname": collectionname, "file_hash": file_hash,
                               "handle": handle}).encode("utf-8")
        artifacts.write_required(
            artifacts.ArtifactRequest(session_id=session_id, username=owner,
                                      kind=KIND_CITATION_BINDING, tool_name="cite_documents",
                                      title=handle, detail=detail),
            artifact_id, artifact_id, body, "application/json")


__all__ = ["ArtifactBindingStore", "KIND_CITATION_BINDING", "NO_SESSION", "binding_id"]
