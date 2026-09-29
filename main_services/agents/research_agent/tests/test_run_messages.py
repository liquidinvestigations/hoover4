"""The compaction records of a stored thread: the version 3 prefix record, and the readers
of the version 1 and version 2 rows that stored threads still hold."""

import json

from research_agent.compaction import CUT_MARK, EVICTION_PLACEHOLDER
from research_agent.run_messages import (
    RunMessage, ToolCallRecord, apply_compactions, apply_record, to_langchain,
)

THREAD = "t1"


def m(role, idx, content="", **kw):
    return RunMessage(role=role, content=content, thread_id=THREAD, idx=idx, **kw)


def call(i, name="doc_metadata"):
    return [ToolCallRecord(id=f"c{i}", name=name, args={})]


def row(idx, record):
    return m("compaction", idx, json.dumps(record))


def v3(source, summary="SUMMARY", status="ok", retained_from=None):
    return {"version": 3, "layer": "prefix", "status": status,
            "source": [[THREAD, i] for i in source],
            "retained_from": [THREAD, retained_from] if retained_from is not None else None,
            "summary": summary, "error": "", "tokens_before": 1, "threshold": 1,
            "target": 1, "est_after": 1, "target_reached": True, "steps_summarised": 1,
            "sizes": {}}


def _thread():
    return [
        m("human", 0, "q"),
        m("ai", 1, tool_calls=call(1)), m("tool", 2, "A", tool_call_id="c1", name="doc_metadata"),
        m("ai", 3, tool_calls=call(3)), m("tool", 4, "B", tool_call_id="c3", name="doc_metadata"),
        m("human", 5, "only 2001"),
        m("ai", 6, tool_calls=call(6)), m("tool", 7, "C", tool_call_id="c6", name="doc_metadata"),
    ]


def _roles(messages):
    return [(x.role, x.content) for x in messages]


# ------------------------------------------------------------------ version 3


def test_a_version_3_row_replaces_its_source_with_one_summary_at_the_first_key():
    out = apply_record(_thread(), v3([1, 2, 3, 4], retained_from=6))
    assert _roles(out) == [("human", "q"), ("human", "SUMMARY"), ("human", "only 2001"),
                           ("ai", ""), ("tool", "C")]
    assert (out[1].thread_id, out[1].idx) == (THREAD, 1)


def test_a_failed_version_3_row_changes_no_message():
    thread = _thread()
    assert _roles(apply_record(thread, v3([1, 2], summary="", status="failed"))) == \
        _roles(thread)
    assert _roles(apply_record(thread, v3([1, 2], summary=""))) == _roles(thread)


def test_a_version_3_row_that_names_half_a_group_leaves_no_orphan():
    # A row written by this module names whole groups. A damaged row must still give a
    # request with one result for each call.
    out = apply_record(_thread(), v3([1]))
    asked = [c.id for x in out if x.role == "ai" for c in x.tool_calls]
    answered = [x.tool_call_id for x in out if x.role == "tool"]
    assert sorted(asked) == sorted(answered) and "c1" not in asked


def test_a_second_version_3_row_replaces_the_first_summary():
    thread = _thread() + [row(8, v3([1, 2, 3, 4])),
                          m("ai", 9, tool_calls=call(9)),
                          m("tool", 10, "D", tool_call_id="c9", name="doc_metadata"),
                          row(11, v3([1, 6, 7], summary="SECOND"))]
    assert _roles(apply_compactions(thread)) == [
        ("human", "q"), ("human", "SECOND"), ("human", "only 2001"), ("ai", ""), ("tool", "D")]


# ------------------------------------------------------------------ legacy rows


def test_a_version_1_eviction_and_summarisation_row_is_read():
    thread = _thread() + [row(8, {"layer": "eviction", "evicted": [[THREAD, 2]],
                                  "summarised": [[THREAD, 3], [THREAD, 4]],
                                  "handoff": "HANDOFF", "tokens_before": 1, "threshold": 1})]
    assert _roles(apply_compactions(thread)) == [
        ("human", "q"), ("ai", ""), ("tool", EVICTION_PLACEHOLDER), ("human", "HANDOFF"),
        ("human", "only 2001"), ("ai", ""), ("tool", "C")]


def test_a_version_2_row_is_read_with_its_cuts_drops_and_removed_text():
    thread = [
        m("human", 0, "q"),
        m("ai", 1, "old text", tool_calls=call(1)),
        m("tool", 2, "A" * 50, tool_call_id="c1", name="doc_metadata"),
        m("ai", 3, tool_calls=call(3, "read_skill")),
        m("tool", 4, "Skill", tool_call_id="c3", name="read_skill"),
        m("ai", 5, tool_calls=call(5)), m("tool", 6, "C", tool_call_id="c5", name="doc_metadata"),
        row(7, {"version": 2, "layer": "record", "summarised": [[THREAD, 5], [THREAD, 6]],
                "text_removed": [[THREAD, 1]], "dropped": [[THREAD, 4]],
                "cuts": [[THREAD, 2, 10]], "handoff": "RECORD"}),
    ]
    assert _roles(apply_compactions(thread)) == [
        ("human", "q"), ("ai", ""), ("tool", "A" * 10 + CUT_MARK), ("human", "RECORD")]


def test_rows_of_all_three_versions_replay_in_order():
    thread = [
        m("human", 0, "q"),
        m("ai", 1, tool_calls=call(1)), m("tool", 2, "A", tool_call_id="c1", name="doc_metadata"),
        m("ai", 3, tool_calls=call(3)), m("tool", 4, "B", tool_call_id="c3", name="doc_metadata"),
        row(5, {"layer": "eviction", "evicted": [[THREAD, 2]], "summarised": [],
                "handoff": ""}),
        m("ai", 6, tool_calls=call(6)), m("tool", 7, "C", tool_call_id="c6", name="doc_metadata"),
        row(8, {"version": 2, "summarised": [[THREAD, 1], [THREAD, 2]], "text_removed": [],
                "dropped": [], "cuts": [], "handoff": "RECORD2"}),
        m("ai", 9, tool_calls=call(9)), m("tool", 10, "D", tool_call_id="c9", name="doc_metadata"),
        row(11, v3([1, 3, 4], summary="RECORD3", retained_from=6)),
    ]
    assert _roles(apply_compactions(thread)) == [
        ("human", "q"), ("human", "RECORD3"), ("ai", ""), ("tool", "C"), ("ai", ""),
        ("tool", "D")]


def test_a_row_that_is_not_a_json_object_is_skipped():
    thread = _thread() + [m("compaction", 8, "not json"), m("compaction", 9, "[1, 2]")]
    assert _roles(apply_compactions(thread)) == _roles(_thread())


def test_malformed_keys_in_a_row_are_skipped():
    record = v3([1, 2])
    record["source"] += [["x"], [THREAD, "not a number"], "text"]
    out = apply_record(_thread(), record)
    assert _roles(out)[:2] == [("human", "q"), ("human", "SUMMARY")]


def test_a_compaction_row_never_reaches_the_model():
    thread = _thread() + [row(8, v3([1, 2]))]
    assert all(type(x).__name__ != "compaction" for x in to_langchain(thread))
    assert len(to_langchain(thread)) == len(_thread())
