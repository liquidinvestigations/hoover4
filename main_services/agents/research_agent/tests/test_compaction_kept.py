"""The kept compaction: a stored `compaction` row makes every later call send the compacted
list, so the calls above the threshold do not alternate between a short and a full list.

The replay uses a synthetic thread. Each reply makes two tool calls, each result has 30,000
characters, the window is 262,144 tokens, and the prompt tokens of a call are the fit
`4,466 + characters / 2.91` over the list that the call sends.
"""

import json

import pytest

from research_agent import compaction, steps
from research_agent.run_messages import (
    NOT_RUN_RESULT, RunMessage, ToolCallRecord, apply_compactions, close_unanswered,
)

WINDOW = 262_144
THRESHOLD = int(WINDOW * 0.65)
THREAD = "11111111-2222-4333-8444-555555555555"
RESULT_CHARS = 30_000


@pytest.fixture(autouse=True)
def _window(monkeypatch):
    for name in ("AGENT_COMPACTION_FRACTION", "AGENT_COMPACTION_KEEP_RECENT",
                 "AGENT_COMPACTION_KEEP_RECENT_MESSAGES", "CLICKHOUSE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(compaction, "context_window", lambda model_id: WINDOW)


def _tokens(messages) -> int:
    chars = sum(len(compaction._content_text(m)) for m in messages)
    return int(4466 + chars / 2.91)


def _replay(calls: int, failed_at: int = -1):
    """Run `calls` model calls over a growing thread. Returns the measured size of each
    call, the full-list size of each call, and the thread with its compaction rows."""
    thread = [RunMessage(role="human", content="question", thread_id=THREAD, idx=0)]
    sent, full, reports = [], [], []
    for call in range(1, calls + 1):
        applied, compacted, report = steps.build_model_input([], thread, "m")
        sent.append(_tokens(compacted))
        full.append(_tokens(steps.to_langchain([m for m in thread if m.role != "compaction"])))
        reports.append(report)
        ids = [f"c{call}a", f"c{call}b"]
        thread.append(RunMessage(
            role="ai", content="", thread_id=THREAD, idx=len(thread),
            tool_calls=[ToolCallRecord(id=i, name="read_documents", args={"n": i}) for i in ids],
            usage={"input_tokens": sent[-1], "output_tokens": 100,
                   "total_tokens": sent[-1] + 100}))
        if report is not None:
            thread.append(RunMessage(
                role="compaction", content=json.dumps(steps.compaction_record(report, applied)),
                thread_id=THREAD, idx=len(thread)))
        for i in ids:
            failed = call == failed_at
            thread.append(RunMessage(
                role="tool", content=("E" if failed else "x") * RESULT_CHARS, tool_call_id=i,
                name="read_documents", thread_id=THREAD, idx=len(thread),
                status="error" if failed else "ok"))
    return sent, full, reports, thread


def test_the_first_call_over_the_threshold_compacts_and_writes_a_row():
    sent, _, reports, thread = _replay(16)
    first = next(i for i, r in enumerate(reports) if r is not None)
    # The trigger reads the usage of the call before, which passed the threshold.
    assert sent[first - 1] + 100 >= THRESHOLD
    assert all(s + 100 < THRESHOLD for s in sent[:first - 1])
    rows = [m for m in thread if m.role == "compaction"]
    assert len(rows) == 1
    record = json.loads(rows[0].content)
    assert record["layer"] == "eviction"
    assert record["evicted"] and all(k[0] == THREAD for k in record["evicted"])
    assert record["threshold"] == THRESHOLD


def test_no_call_after_a_compaction_sends_the_full_list_again():
    sent, full, reports, _ = _replay(16)
    first = next(i for i, r in enumerate(reports) if r is not None)
    assert reports[first + 1:] == [None] * (len(reports) - first - 1)
    for i in range(first + 1, len(sent)):
        assert sent[i] >= sent[first], i
        assert sent[i] < full[i], i
        assert sent[i] < THRESHOLD, i


def test_a_failed_tool_result_in_the_evicted_range_is_kept_whole():
    _, _, reports, thread = _replay(16, failed_at=2)
    assert any(r is not None for r in reports)
    applied = apply_compactions(thread)
    failed = [m for m in applied if m.role == "tool" and m.status == "error"]
    assert len(failed) == 2
    assert all(m.content == "E" * RESULT_CHARS for m in failed)
    ok = [m for m in applied if m.role == "tool" and m.status != "error"]
    assert any(m.content == compaction.EVICTION_PLACEHOLDER for m in ok)


def test_a_thread_under_the_threshold_is_sent_as_it_is():
    sent, full, reports, thread = _replay(4)
    assert reports == [None] * 4
    assert sent == full
    applied, compacted, report = steps.build_model_input([], thread, "m")
    assert report is None
    assert applied == thread
    assert [m.content for m in compacted] == [m.content for m in steps.to_langchain(thread)]


def test_a_stopped_earlier_turn_gets_a_not_run_result_in_the_request_only():
    earlier = [
        RunMessage(role="human", content="first", thread_id=THREAD, idx=0),
        RunMessage(role="ai", content="", thread_id=THREAD, idx=1, tool_calls=[
            ToolCallRecord(id="a", name="search_passages"),
            ToolCallRecord(id="b", name="read_documents")]),
        RunMessage(role="tool", content="hits", tool_call_id="a", name="search_passages",
                   thread_id=THREAD, idx=2),
    ]
    closed = close_unanswered(earlier)
    assert [m.role for m in closed] == ["human", "ai", "tool", "tool"]
    assert closed[3].tool_call_id == "b"
    assert closed[3].content == NOT_RUN_RESULT
    assert closed[3].status == "error"
    assert len(earlier) == 3
    messages = [RunMessage(role="human", content="second", thread_id="t2", idx=0)]
    applied, _, _ = steps.build_model_input(earlier, messages, "m")
    assert [m.role for m in applied] == ["human", "ai", "tool", "tool", "human"]


def test_a_summarisation_row_puts_the_handoff_in_place_of_the_first_replaced_message():
    thread = [
        RunMessage(role="human", content="q", thread_id=THREAD, idx=0),
        RunMessage(role="ai", content="", thread_id=THREAD, idx=1,
                   tool_calls=[ToolCallRecord(id="a", name="search_passages")]),
        RunMessage(role="tool", content="old", tool_call_id="a", name="search_passages",
                   thread_id=THREAD, idx=2),
        RunMessage(role="ai", content="", thread_id=THREAD, idx=3,
                   tool_calls=[ToolCallRecord(id="b", name="read_documents")]),
        RunMessage(role="compaction", thread_id=THREAD, idx=4, content=json.dumps({
            "layer": "summarisation", "evicted": [],
            "summarised": [[THREAD, 1], [THREAD, 2]], "handoff": "HANDOFF",
            "tokens_before": 1, "threshold": 1})),
        RunMessage(role="tool", content="new", tool_call_id="b", name="read_documents",
                   thread_id=THREAD, idx=5),
    ]
    applied = apply_compactions(thread)
    assert [(m.role, m.content) for m in applied] == [
        ("human", "q"), ("human", "HANDOFF"), ("ai", ""), ("tool", "new")]
    assert (applied[1].thread_id, applied[1].idx) == (THREAD, 1)
