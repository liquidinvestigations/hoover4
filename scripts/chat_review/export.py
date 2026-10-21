"""Export a completed turn through owner-scoped, read-only storage calls."""

from dataclasses import asdict
import json
import subprocess

from .client import implementation_identity
from .packets import assemble_packet
from .schema import Incomplete, digest, require, text_digest


class Store:
    """Use existing storage readers and parameterized transcript queries."""

    def __init__(self):
        from database import agent_runs, chat_workspace
        self.runs = agent_runs
        self.workspace = chat_workspace

    def deleted(self, owner, session):
        return self.workspace.session_deleted(owner, session)

    def turn_runs(self, owner, session, turn):
        return self.runs.read_turn_runs(owner, session, turn)

    def earlier_threads(self, owner, session, turn):
        return self.runs.read_earlier_threads(owner, session, turn)

    def messages(self, owner, session, thread):
        return self.runs.read_messages(owner, session, thread)

    def version(self, owner, session, name, version):
        return self.workspace.read_version(owner, session, name, version)

    def answer(self, run):
        from database.clickhouse import get_global_client
        with get_global_client() as client:
            result = client.query(
                "SELECT content, usage_json, seq FROM chat_messages FINAL "
                "WHERE username = {owner:String} AND session_id = {session:String} "
                "AND seq >= {start:UInt32} AND seq < {end:UInt32} AND role = 'assistant' "
                "ORDER BY seq DESC LIMIT 1",
                parameters={"owner": run.username, "session": run.session_id,
                            "start": run.start_seq, "end": run.next_seq})
        return dict(zip(result.column_names, result.result_rows[0])) if result.result_rows else None


def stored_message(thread, row):
    return {"thread_id": thread, "idx": row.idx, "run_id": row.run_id,
            "role": {"human": "user", "ai": "assistant"}.get(row.role, row.role),
            "content": row.content if row.is_final else "", "is_final": bool(row.is_final),
            "metadata": {"tool_name": row.tool_name, "tool_call_id": row.tool_call_id,
                         "tool_calls": row.tool_calls,
                         "usage": {k: v for k, v in row.usage.items()
                                   if k in ("status", "model_content", "evidence", "image_refs", "capture_refs")}}}


def source_records(messages):
    evidence, citations, missing = [], [], []
    for m in messages:
        if m["role"] != "tool" or not m["is_final"]:
            continue
        sid = f'{m["thread_id"]}:{m["idx"]}'
        usage = m["metadata"]["usage"]
        typed = usage.get("evidence", [])
        # A complete stored response can still describe only part of a document.
        evidence.append({"id": sid, "kind": "stored_tool_result", "content": m["content"],
                         "digest": text_digest(m["content"]), "complete": False,
                         "metadata": {"message_identity": [m["thread_id"], m["idx"]],
                                      "tool_name": m["metadata"]["tool_name"], "typed_evidence": typed,
                                      "source_extent": "Only the captured response is available.",
                                      "stored_response_complete": True}})
        for i, entry in enumerate(typed):
            if entry.get("kind") == "citation":
                citations.append({"id": f"{sid}:citation:{i}", "source_id": sid,
                                  "kind": "citation", "status": entry.get("status", "error"),
                                  "reference": entry.get("reference", {}),
                                  "metadata": {k: v for k, v in entry.items()
                                               if k not in ("kind", "status", "reference")}})
            if entry.get("status") == "error":
                missing.append({"target": sid, "reason": "A stored source operation failed."})
        if usage.get("image_refs") or usage.get("capture_refs"):
            missing.append({"target": sid, "reason": "Stored image references have no exported image bytes."})
    # Citation tool receipts establish quote identity, but do not replace full source reads.
    reads = [e for e in evidence if any(x.get("kind") == "document_read"
                                      for x in e["metadata"]["typed_evidence"])]
    for c in citations:
        ref = c["reference"]
        matched = any(any((ref.get("file_hash") and x.get("reference", {}).get("file_hash") == ref["file_hash"])
                          or (ref.get("url") and x.get("reference", {}).get("url") == ref["url"]
                              and x.get("reference", {}).get("version") == ref.get("version"))
                          for x in e["metadata"]["typed_evidence"]) for e in reads)
        if not matched:
            missing.append({"target": c["source_id"], "reason": "Citation body has no matching captured source read."})
    return evidence, citations, missing


def export_turn(owner, session_id, turn_seq, store=None, requirements=None):
    """Read one stable completed answer and its pinned report versions."""
    store = store or Store()
    if store.deleted(owner, session_id):
        raise Incomplete("The requested session is deleted or unavailable.")
    runs = store.turn_runs(owner, session_id, turn_seq)
    for r in runs:
        require((r.username, r.session_id, r.turn_seq) == (owner, session_id, turn_seq), "Run scope differs from the requested identity.")
    from database.agent_runs import TERMINAL_STATES
    if not runs or any(r.state not in TERMINAL_STATES for r in runs):
        raise Incomplete("The turn has no stable completed run.")
    answers = [(r, store.answer(r)) for r in runs if r.result and not r.end_reason]
    answers = [(r, a) for r, a in answers if a is not None]
    if len(answers) != 1:
        raise Incomplete("The published answer does not identify one run.")
    run, answer = answers[0]
    from tasks.P_workspace.selection import delivered_reports, manifest
    threads = list(dict.fromkeys(store.earlier_threads(owner, session_id, turn_seq) + [r.thread_id for r in runs]))
    raw = {thread: store.messages(owner, session_id, thread) for thread in threads}
    answer_messages = [m for m in raw[run.thread_id] if m.is_final]
    selected = delivered_reports(answer_messages)
    published = json.loads(answer["usage_json"] or "{}")
    require(isinstance(published, dict), "Invalid published metadata.")
    if selected != published.get("reports", []) or manifest(answer_messages).get("report") != published.get("report"):
        raise Incomplete("The published manifest differs from the answer thread receipts.")
    versions = {}
    for item in selected:
        key = (item["name"], item["version"])
        version = store.version(owner, session_id, *key)
        if version is None:
            raise Incomplete("A delivered file version is unavailable.")
        versions[key] = asdict(version)
    messages = [stored_message(thread, m) for thread in threads for m in raw[thread]]
    evidence, citations, missing = source_records(messages)
    opening = next((m for m in raw[run.thread_id] if m.role == "human" and m.is_final), None)
    if opening is None:
        raise Incomplete("The turn request is unavailable.")
    control = opening.usage.get("control", {})
    prior_requests = [{"source_turn": "thread:" + thread, "text": m.content}
                      for thread in threads if thread != run.thread_id
                      for m in [next((row for row in raw[thread] if row.role == "human" and row.is_final), None)]
                      if m is not None]
    if requirements is None:
        missing.append({"target": "task_requirements", "reason": "Explicit output requirements need independent annotation."})
    omissions = []
    if answer["content"] != run.result:
        omissions.append("Published closing text differs from the run result. The published text is exported.")
    if any(m.role == "compaction" for rows in raw.values() for m in rows):
        omissions.append("Compaction records are metadata. Their summaries are not original source evidence.")
    run_data = {"owner": owner, "session_id": session_id, "thread_id": run.thread_id,
                "request": opening.content, "task_state": control.get("task_state", {}),
                "amendments": control.get("task_state", {}).get("amendments", []),
                "prior_requests": prior_requests, "requirements": requirements or [],
                "closing_answer": answer["content"], "answer_seq": int(answer["seq"]),
                "published_reports": published.get("reports", []), "citations": citations,
                "missing": missing, "history_omissions": omissions}
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        revision = "unavailable"
    identity = {"owner": owner, "session_id": session_id, "turn_id": str(turn_seq),
                "source_revision": revision, "loaded_source_digest": digest(implementation_identity())}
    packet = assemble_packet(run_data, messages, versions, evidence, identity)
    # Re-read all mutable selection inputs. Exact file versions remain immutable.
    if store.deleted(owner, session_id) or store.turn_runs(owner, session_id, turn_seq) != runs:
        raise Incomplete("The session changed during export.")
    if store.answer(run) != answer or any(store.messages(owner, session_id, t) != raw[t] for t in threads):
        raise Incomplete("The answer or its stored messages changed during export.")
    return packet, {"serializer": "control.canonical_json.v1", "run_id": run.run_id,
                    "thread_ids": threads, "selected_versions": selected,
                    "partial_messages": [[m["thread_id"], m["idx"]] for m in messages if not m["is_final"]],
                    "published_result_differs": answer["content"] != run.result,
                    "published_answer_digest": text_digest(answer["content"]),
                    "run_result_digest": text_digest(run.result),
                    "source_retrieval": False, "writes": False}
