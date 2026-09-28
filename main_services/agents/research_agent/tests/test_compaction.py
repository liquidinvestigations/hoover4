"""Context compaction: the trigger, the record, its summary parts, and the version 2 row.

The tests pass their own summariser. A test that reached a real model would test the model.
The threads come from `Thread` of `test_thread_index`, with a fixed estimator of 0.25 tokens
a character, so each size in tokens is known by hand.
"""

import json
import threading

import pytest

from research_agent import compaction, steps
from research_agent.compaction import (
    DEFAULT_COMPACTION_FRACTION, EVICTION_PLACEHOLDER, PART_FAILED, PREVIOUS_RECORD_LINE,
    RECORD_HEADER, compaction_fraction, last_billed, threshold_tokens,
)
from research_agent.run_messages import RunMessage, ToolCallRecord, apply_compactions
from test_thread_index import DGEMMA, EST, THREAD, TODAY_EMPTY, Thread, chars, ok


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("AGENT_COMPACTION_FRACTION", "LLM_BASE_URL", "LLM_MODEL_COMPACTION",
                 "CLICKHOUSE_URL"):
        monkeypatch.delenv(name, raising=False)


class Recorder:
    """A summariser that records each prompt and its cap. `fail` names a part that raises."""

    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
        self.lock = threading.Lock()

    def __call__(self, prompt, cap):
        with self.lock:
            self.calls.append((prompt, cap))
        if self.fail and f"part {self.fail} of" in prompt:
            raise RuntimeError("the model server closed the stream")
        return "## Goal\nthe summary"


# --------------------------------------------------------------- the trigger


def test_the_shipped_fraction_is_eighty_percent():
    assert compaction_fraction() == DEFAULT_COMPACTION_FRACTION == 0.80
    assert threshold_tokens(DGEMMA) == 209_715
    assert compaction.target_tokens(209_715) == 69_905


def test_the_fraction_is_configuration(monkeypatch):
    monkeypatch.setenv("AGENT_COMPACTION_FRACTION", "0.30")
    assert threshold_tokens(DGEMMA) == 78_643


@pytest.mark.parametrize("bad", ["0", "-1", "1.5", "sixty percent"])
def test_a_fraction_out_of_range_turns_compaction_off(monkeypatch, bad):
    monkeypatch.setenv("AGENT_COMPACTION_FRACTION", bad)
    assert compaction_fraction() == 0.0
    assert threshold_tokens(DGEMMA) == 0


def test_an_unknown_window_never_produces_a_threshold():
    assert threshold_tokens(0) == 0
    assert threshold_tokens(-1) == 0


def test_the_trigger_reads_prompt_plus_completion_of_the_newest_billed_call():
    t = Thread()
    t.human("q")
    t.step(billed=170_000)
    t.step()
    assert last_billed(t.rows) == 170_010


# --------------------------------------------------------------- the record


def _thread(results, size, *, before=()):
    """A human message, the steps of `before`, then `results` results of `size` tokens,
    then a small newest step over the trigger."""
    t = Thread()
    t.human("Who approved the lease?")
    for call in before:
        t.step(call)
    for n in range(results):
        t.step(ok("doc_metadata", {"n": n}, chars(size)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=210_000)
    return t


def test_a_compacted_part_over_30000_tokens_sends_3_requests_of_666_tokens():
    t = _thread(14, 4_000, before=[ok("search_collections", {"queries": ["Raptor"]},
                                      TODAY_EMPTY)])
    stub = Recorder()
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    assert len(stub.calls) == 3
    assert [cap for _p, cap in stub.calls] == [666, 666, 666]
    record = report.row["handoff"]
    assert record.startswith(RECORD_HEADER + "## Searches that found nothing\n")
    assert record.index("## Searches that found nothing") < record.index("Part 1 of 3:")
    assert report.row["parts"] == ["ok", "ok", "ok"]
    assert out[1].content == record
    assert report.row["version"] == 2 and report.row["layer"] == "record"


def test_a_compacted_part_of_29000_tokens_sends_1_request():
    t = _thread(15, 2_900)
    stub = Recorder()
    plan = compaction.plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST)
    assert 25_000 < sum(b[1] for b in plan.blocks) <= compaction.PARTS_ABOVE_TOKENS
    _out, report = compaction.finish_compaction(plan, stub)
    assert len(stub.calls) == 1 and report.row["parts"] == ["ok"]
    assert "part 1 of" not in stub.calls[0][0]


def test_a_second_compaction_summarises_the_first_record_again():
    t = _thread(14, 4_000)
    _out, first = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=Recorder())
    ai = t.rows[-2]
    t.rows.insert(ai.idx + 1, RunMessage(role="compaction", content=json.dumps(first.row),
                                         thread_id=THREAD, idx=ai.idx + 1))
    for m in t.rows[ai.idx + 2:]:
        m.idx += 1
    for n in range(14):
        t.step(ok("doc_metadata", {"m": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"m": "last"}, chars(10)), billed=210_000)
    rows, applied = steps.model_input_rows([], t.rows)
    stub = Recorder()
    _out, second = compaction.compact(applied, rows, window=DGEMMA, estimator=EST,
                                      summariser=stub)
    assert second is not None
    prompts = "\n".join(p for p, _c in stub.calls)
    assert PREVIOUS_RECORD_LINE in prompts
    assert "[earlier record]\n" + RECORD_HEADER in prompts


def test_a_failed_part_gives_its_failure_line_and_the_planned_size_holds():
    t = _thread(14, 4_000)
    plan = compaction.plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST)
    out, report = compaction.finish_compaction(plan, Recorder(fail=2))
    assert report.row["parts"] == ["ok", "failed", "ok"]
    assert PART_FAILED.format(n=2, k=3) in report.row["handoff"]
    assert report.est_after <= report.target
    assert EST.list_size(out) <= plan.sizer.rest(plan.layout) + plan.layout.budget


# ------------------------------------------------------- skill and tool texts


def test_skill_and_tool_texts_never_reach_the_summariser():
    t = _thread(12, 4_000, before=[
        ok("read_skill", {"name": "search"}, "Skill `search`.\nSEARCH TEXT"),
        ok("read_skill", {"name": "thorough"}, "Skill `thorough`.\nOLD THOROUGH"),
        ok("read_skill", {"name": "thorough"}, "Skill `thorough`.\nNEW THOROUGH"),
        ok("read_tool", {"name": "search_histogram"}, '{"tool": "search_histogram"}'),
    ])
    stub = Recorder()
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    prompts = "\n".join(p for p, _c in stub.calls)
    for text in ("SEARCH TEXT", "OLD THOROUGH", "NEW THOROUGH", "search_histogram",
                 "read_skill(", "read_tool("):
        assert text not in prompts
    assert report.row["dropped"] == [[THREAD, 4], [THREAD, 8]]
    contents = [m.content for m in out]
    assert "Skill `search`.\nSEARCH TEXT" in contents
    assert "Skill `thorough`.\nNEW THOROUGH" in contents
    assert "Texts removed whole: tool `search_histogram`." in report.row["handoff"]


def test_the_skill_cap_of_25000_moves_the_oldest_skill_out_of_the_list():
    skills = [ok("read_skill", {"name": f"s{n}"}, f"Skill `s{n}`.\n" + chars(5_000))
              for n in range(6)]
    t = _thread(12, 4_000, before=skills)
    stub = Recorder()
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    assert [THREAD, 2] in report.row["dropped"]
    assert not any(m.content.startswith("Skill `s0`.") for m in out)
    assert sum(m.content.startswith("Skill `s") for m in out) == 5
    assert not any("Skill `s" in p for p, _c in stub.calls)
    assert "Texts removed whole: skill `s0`." in report.row["handoff"]


# ------------------------------------------------------------------ the replay


def test_a_version_1_eviction_row_and_a_later_version_2_row_replay():
    def m(role, idx, content="", **kw):
        return RunMessage(role=role, content=content, thread_id=THREAD, idx=idx, **kw)

    def call(i):
        return [ToolCallRecord(id=f"c{i}", name="doc_metadata", args={})]

    thread = [
        m("human", 0, "q"),
        m("ai", 1, tool_calls=call(1)), m("tool", 2, "A" * 500, tool_call_id="c1", name="doc_metadata"),
        m("ai", 3, tool_calls=call(3)), m("tool", 4, "B" * 500, tool_call_id="c3", name="doc_metadata"),
        m("ai", 5, tool_calls=call(5)),
        m("compaction", 6, json.dumps({"layer": "eviction", "evicted": [[THREAD, 2]],
                                       "summarised": [], "handoff": ""})),
        m("tool", 7, "C" * 500, tool_call_id="c5", name="doc_metadata"),
        m("ai", 8, "keep me", tool_calls=call(8)),
        m("compaction", 9, json.dumps({"version": 2, "layer": "record",
                                       "summarised": [[THREAD, 3], [THREAD, 4]],
                                       "text_removed": [], "dropped": [],
                                       "cuts": [[THREAD, 7, 10]], "handoff": "RECORD"})),
        m("tool", 10, "D", tool_call_id="c8", name="doc_metadata"),
    ]
    applied = apply_compactions(thread)
    assert [(x.role, x.content) for x in applied] == [
        ("human", "q"), ("ai", ""), ("tool", EVICTION_PLACEHOLDER), ("human", "RECORD"),
        ("ai", ""), ("tool", "C" * 10 + compaction.CUT_MARK), ("ai", "keep me"), ("tool", "D")]
    asked = [c.id for x in applied if x.role == "ai" for c in x.tool_calls]
    answered = [x.tool_call_id for x in applied if x.role == "tool"]
    assert sorted(asked) == sorted(answered)


def test_a_dropped_result_takes_its_call_and_an_empty_ai_message_with_it():
    thread = [
        RunMessage(role="human", content="q", thread_id=THREAD, idx=0),
        RunMessage(role="ai", content="", thread_id=THREAD, idx=1, tool_calls=[
            ToolCallRecord(id="a", name="read_skill", args={"name": "x"})]),
        RunMessage(role="tool", content="Skill `x`.", tool_call_id="a", name="read_skill",
                   thread_id=THREAD, idx=2),
        RunMessage(role="compaction", thread_id=THREAD, idx=3, content=json.dumps({
            "version": 2, "summarised": [], "text_removed": [], "dropped": [[THREAD, 2]],
            "cuts": [], "handoff": "R"})),
    ]
    assert [(x.role, x.content) for x in apply_compactions(thread)] == [("human", "q")]


# ---------------------------------------------------------------- the summariser request


class _RecordingClient:
    """A stand-in for `httpx.Client` that records the timeout and the request body."""

    seen: dict = {}

    def __init__(self, *, timeout):
        _RecordingClient.seen = {"timeout": timeout}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers, json):
        _RecordingClient.seen["body"] = json

        class _Response:
            status_code = 200
            text = ""

            @staticmethod
            def json():
                return {"choices": [{"message": {"content": "summary"}}]}

        return _Response()


def _summariser_request(monkeypatch, **env):
    for name in ("LLM_SEND_TEMPERATURE", "LLM_REQUEST_TIMEOUT_SECONDS",
                 "AGENT_MAX_OUTPUT_TOKENS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("LLM_BASE_URL", "http://model.invalid/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(compaction.httpx, "Client", _RecordingClient)
    assert compaction.summarise_with_model("prompt", model_id="m", max_tokens=666) == "summary"
    return _RecordingClient.seen


def test_the_summariser_sends_thinking_off_and_the_cap_of_its_caller(monkeypatch):
    seen = _summariser_request(monkeypatch, AGENT_MAX_OUTPUT_TOKENS="32768")
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["max_tokens"] == 666
    assert seen["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen["timeout"] == (5.0, 3600.0)


def test_the_summariser_leaves_temperature_out_when_the_provider_refuses_it(monkeypatch):
    seen = _summariser_request(monkeypatch, LLM_SEND_TEMPERATURE="false")
    assert "temperature" not in seen["body"]


def test_the_summariser_timeout_follows_the_request_timeout(monkeypatch):
    seen = _summariser_request(monkeypatch, LLM_REQUEST_TIMEOUT_SECONDS="3600")
    assert seen["timeout"] == (10.0, 3600.0)
