"""Context compaction: the trigger, the prefix and the recent steps, the one summary, the
version 3 record, and the explicit failures.

The tests pass their own summariser. A test that reached a real model would test the model.
The threads come from `Thread` of `test_thread_index`, with a fixed estimator of 0.25 tokens
a character, so each size in tokens is known by hand.
"""

import json

import pytest

from research_agent import compaction, steps
from research_agent.compaction import (
    CONTEXT_SIZE, DEFAULT_COMPACTION_FRACTION, EXTRACT_MARK, PREVIOUS_SUMMARY_LINE,
    RECORD_HEADER, SUMMARY_TOKENS, ContextError, compaction_fraction, last_billed,
    threshold_tokens,
)
from research_agent.run_messages import RunMessage, apply_compactions
from test_thread_index import DGEMMA, EST, THREAD, TODAY_EMPTY, Thread, chars, ok


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("AGENT_COMPACTION_FRACTION", "LLM_BASE_URL", "LLM_MODEL_COMPACTION",
                 "CLICKHOUSE_URL"):
        monkeypatch.delenv(name, raising=False)


class Recorder:
    """A summariser that records each prompt and its cap. `fail` makes it raise, and
    `empty` makes it give no text."""

    def __init__(self, fail=False, empty=False, text="## Findings\nthe summary"):
        self.calls = []
        self.fail = fail
        self.empty = empty
        self.text = text

    def __call__(self, prompt, cap):
        self.calls.append((prompt, cap))
        if self.fail:
            raise RuntimeError("the model server closed the stream")
        return "" if self.empty else self.text


def _plan(t, **kw):
    kw.setdefault("window", DGEMMA)
    kw.setdefault("estimator", EST)
    return compaction.plan_compaction(t.rows, t.rows, **kw)


def _thread(results, size, *, before=(), billed=210_000):
    """A human message, the steps of `before`, then `results` results of `size` tokens,
    then a small newest step over the trigger."""
    t = Thread()
    t.human("Who approved the lease?")
    for call in before:
        t.step(call)
    for n in range(results):
        t.step(ok("doc_metadata", {"n": n}, chars(size)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=billed)
    return t


def _store(t, report):
    """Store the report's record after the newest `ai` message, as the worker does."""
    ai = max(m.idx for m in t.rows if m.role == "ai")
    t.rows.insert(ai + 1, RunMessage(role="compaction", content=json.dumps(report.row),
                                     thread_id=THREAD, idx=ai + 1))
    for m in t.rows[ai + 2:]:
        m.idx += 1


def _pairs_complete(messages):
    asked = sorted(c.id for m in messages if m.role == "ai" for c in m.tool_calls)
    answered = sorted(m.tool_call_id for m in messages if m.role == "tool")
    return asked == answered


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


def test_no_billed_usage_and_no_window_give_no_compaction():
    t = _thread(40, 4_000, billed=0)
    assert _plan(t) is None
    t = _thread(40, 4_000)
    assert _plan(t, window=0) is None
    assert _plan(t) is not None


def test_a_thread_that_fits_the_target_gives_no_compaction():
    assert _plan(_thread(4, 1_000)) is None


def test_the_measured_size_of_new_results_fires_the_trigger():
    # The billed call is small. The results stored after it are the size of the request.
    t = _thread(20, 4_000, billed=1_000)
    assert _plan(t) is None
    assert _plan(t, measured=210_000) is not None


def test_the_trigger_is_never_above_the_safe_input():
    t = _thread(20, 4_000, billed=1_000)
    plan = _plan(t, measured=150_000, safe_input=140_000)
    assert plan.trigger == 140_000 and plan.target == 46_666


# --------------------------------------------------------------- the projection


def test_one_older_prefix_is_summarised_once_and_the_newest_groups_stay():
    t = _thread(40, 4_000)
    stub = Recorder()
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    assert len(stub.calls) == 1 and stub.calls[0][1] == SUMMARY_TOKENS
    row = report.row
    assert (row["version"], row["layer"], row["status"]) == (3, "prefix", "ok")
    assert report.est_after <= report.target and row["target_reached"]
    # The record replaces the prefix at its first key. The user message keeps its place.
    assert out[0].content == "Who approved the lease?"
    assert out[1].content.startswith(RECORD_HEADER) and out[1].content == row["summary"]
    assert (out[1].thread_id, out[1].idx) == tuple(row["source"][0])
    # The recent steps are the suffix after the retained boundary, whole.
    start = next(i for i, m in enumerate(t.rows) if (m.thread_id, m.idx) ==
                 tuple(row["retained_from"]))
    assert [m.content for m in out[2:]] == [m.content for m in t.rows[start:]]
    assert _pairs_complete(out)
    # The largest suffix: one more group would pass the target with the summary reserve.
    group = EST.list_size(t.rows[start - 2:start])
    reserve = SUMMARY_TOKENS + EST.tokens_text(RECORD_HEADER)
    sizes = row["sizes"]
    assert sizes["user"] + sizes["retained"] + reserve <= report.target
    assert sizes["user"] + sizes["retained"] + reserve + group > report.target
    assert row["sizes"]["retained"] > 0 and row["sizes"]["summary_input"] > 0


def test_the_stored_row_replays_the_list_that_the_compacting_call_sent():
    t = _thread(40, 4_000)
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=Recorder())
    _store(t, report)
    assert [(m.role, m.content) for m in apply_compactions(t.rows)] == [
        (m.role, m.content) for m in out]


def test_a_multi_call_batch_leaves_or_stays_whole():
    t = Thread()
    t.human("Compare the two leases.")
    for n in range(12):
        t.step(ok("read_documents", {"n": n}, chars(3_000)),
               ok("search_passages", {"q": n}, chars(3_000)),
               ok("doc_metadata", {"h": n}, chars(2_000)))
    t.step(ok("read_documents", {"n": "a"}, chars(10)), ok("read_documents", {"n": "b"},
                                                           chars(10)), billed=210_000)
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=Recorder())
    assert report.row["status"] == "ok"
    assert _pairs_complete(out)
    source = {tuple(k) for k in report.row["source"]}
    for m in t.rows:
        if m.role == "ai":
            members = {(THREAD, m.idx)} | {(THREAD, r.idx) for r in t.rows
                                           if r.tool_call_id in {c.id for c in m.tool_calls}}
            assert members <= source or not members & source
    assert [c.id for c in out[-3].tool_calls] == [c.id for c in t.rows[-3].tool_calls]


def test_every_user_message_stays_in_its_place():
    t = Thread()
    t.human("Find the lease approvals.")
    for n in range(10):
        t.step(ok("doc_metadata", {"n": n}, chars(4_000)))
    t.human("Only the 2001 approvals, and name the signer.")
    for n in range(10):
        t.step(ok("doc_metadata", {"m": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=210_000)
    out, _report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                      summariser=Recorder())
    humans = [m.content for m in out if m.role == "human"]
    assert humans[0] == "Find the lease approvals."
    assert humans[1].startswith(RECORD_HEADER)
    assert "Only the 2001 approvals, and name the signer." in humans


def test_the_summary_contract_asks_for_findings_contradictions_work_and_sources():
    t = _thread(40, 4_000, before=[ok("search_collections", {"queries": ["Raptor"]},
                                      TODAY_EMPTY)])
    stub = Recorder()
    _out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                      summariser=stub)
    prompt = stub.calls[0][0]
    for section in ("## Findings", "## Contradictions", "## Outstanding work",
                    "## Sources to read again"):
        assert section in prompt
    assert "`write_note`" in prompt and "Who approved the lease?" in prompt
    record = report.row["summary"]
    assert record.startswith(RECORD_HEADER + "## Searches that found nothing\n")
    assert record.index("## Searches that found nothing") < record.index("## Findings")
    assert "Read a source again before you quote it." in RECORD_HEADER


def test_a_second_compaction_extends_the_previous_summary():
    t = _thread(40, 4_000)
    _out, first = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=Recorder(text="## Findings\nFIRST FACT"))
    _store(t, first)
    for n in range(40):
        t.step(ok("doc_metadata", {"m": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"m": "last"}, chars(10)), billed=210_000)
    rows, applied = steps.model_input_rows([], t.rows)
    stub = Recorder(text="## Findings\nSECOND FACT")
    out, second = compaction.compact(applied, rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    prompt = stub.calls[0][0]
    assert PREVIOUS_SUMMARY_LINE in prompt and "[previous summary]\n" in prompt
    assert "FIRST FACT" in prompt
    # The previous record is in the new source, so one record stays after the replay.
    assert first.row["source"][0] in second.row["source"]
    _store(t, second)
    replayed = apply_compactions(t.rows)
    records = [m for m in replayed if compaction.is_record(m)]
    assert len(records) == 1 and "SECOND FACT" in records[0].content
    assert [m.content for m in replayed] == [m.content for m in out]


def test_skill_and_tool_texts_never_reach_the_summariser():
    t = _thread(40, 4_000, before=[
        ok("read_skill", {"name": "search"}, "Skill `search`.\nSEARCH TEXT"),
        ok("read_tool", {"name": "search_histogram"}, '{"tool": "search_histogram"}'),
    ])
    stub = Recorder()
    _out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                      summariser=stub)
    prompt = stub.calls[0][0]
    for text in ("SEARCH TEXT", "search_histogram", "read_skill(", "read_tool("):
        assert text not in prompt
    assert ("Texts removed: skill `search`, tool `search_histogram`."
            in report.row["summary"])


def test_citation_labels_of_the_prefix_are_in_the_index():
    t = _thread(40, 4_000, before=[
        ok("cite_documents", {"citations": []},
           {"citations": [{"file_hash": "5e8bb0ff3822761c", "handle": "[D4]"}]}),
    ])
    _out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                      summariser=Recorder())
    assert "## Citation labels\n- [D4] 5e8bb0ff3822761c" in report.row["summary"]


# --------------------------------------------------------------- summary input size


def test_a_larger_legacy_result_goes_to_the_summary_as_a_bounded_extract():
    big = "HEAD " + "y" * len(chars(60_000)) + " TAIL-continuation=c7f3a91b0d2e"
    t = Thread()
    t.human("Who approved the lease?")
    for n in range(20):
        t.step(ok("doc_metadata", {"n": n}, chars(500)))
    t.step(ok("read_page", {"url": "u"}, big))
    for n in range(6):
        t.step(ok("doc_metadata", {"m": n}, chars(11_000)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=210_000)
    stub = Recorder()
    plan = _plan(t, summary_window=32_000)
    assert plan.extracts == 1
    _out, report = compaction.finish_compaction(plan, stub)
    prompt = stub.calls[0][0]
    assert EST.tokens_text(prompt) + SUMMARY_TOKENS <= 32_000
    assert "[result of read_page(" in prompt and "HEAD " in prompt
    assert "TAIL-continuation=c7f3a91b0d2e" in prompt
    assert EXTRACT_MARK.format(chars=len(big)) in prompt
    # Every small result stays whole in the summary request.
    assert prompt.count(chars(500)) == 20
    assert report.row["sizes"]["extracts"] == 1


def test_a_prefix_that_fits_the_summary_model_goes_whole():
    t = _thread(40, 4_000)
    plan = _plan(t)
    assert plan.extracts == 0
    assert plan.prompt.count(chars(4_000)) == len(plan.source) // 2


# --------------------------------------------------------------- the failures


def test_fixed_input_past_the_safe_input_fails_without_a_summary():
    t = Thread()
    t.human(chars(240_000))
    t.step(ok("doc_metadata", {"n": 1}, chars(1_000)))
    t.step(ok("doc_metadata", {"n": 2}, chars(1_000)), billed=250_000)
    with pytest.raises(ContextError) as err:
        _plan(t, safe_input=229_376)
    assert err.value.error_class == CONTEXT_SIZE
    assert "The fixed input alone is about" in str(err.value)
    assert "229,376 tokens of input" in str(err.value)


def test_a_newest_batch_past_the_safe_input_fails_and_names_the_results():
    t = Thread()
    t.human("q")
    t.step(ok("doc_metadata", {"n": 1}, chars(1_000)))
    t.step(ok("read_page", {"url": "u"}, chars(230_000)), billed=210_000)
    with pytest.raises(ContextError) as err:
        _plan(t, safe_input=229_376)
    assert "The newest tool results are about" in str(err.value)


def test_user_messages_past_the_target_keep_the_run_and_report_the_target_missed():
    t = Thread()
    t.human(chars(80_000))
    for n in range(10):
        t.step(ok("doc_metadata", {"n": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(1_000)), billed=210_000)
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=Recorder())
    assert report.row["status"] == "ok" and report.target_reached is False
    assert report.row["sizes"]["user"] > report.target
    assert out[0].content == t.rows[0].content


def test_a_failed_summary_changes_no_message_and_is_not_asked_again():
    t = _thread(40, 4_000)
    stub = Recorder(fail=True)
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    row = report.row
    assert (row["status"], row["summary"], row["steps_summarised"]) == ("failed", "", 0)
    assert "the model server closed the stream" in row["error"]
    assert [m.content for m in out] == [m.content for m in t.rows]
    _store(t, report)
    assert [m.content for m in apply_compactions(t.rows)] == [
        m.content for m in t.rows if m.role != "compaction"]
    # The same prefix: no second request over unchanged input.
    rows, applied = steps.model_input_rows([], t.rows)
    plan = compaction.plan_compaction(applied, rows, window=DGEMMA, estimator=EST)
    assert plan.unchanged_failure and plan.parts == 0
    again = Recorder()
    _out, second = compaction.finish_compaction(plan, again)
    assert again.calls == [] and second.row["status"] == "failed"


def test_an_empty_summary_is_a_failure():
    t = _thread(40, 4_000)
    _out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                      summariser=Recorder(empty=True))
    assert report.row["status"] == "failed"
    assert report.row["error"] == "the summary request gave no text"


# --------------------------------------------------------------- provider refusals


@pytest.mark.parametrize("status, text, stated", [
    (400, "This model's maximum context length is 131072 tokens. However, you requested "
          "140000 tokens", 131072),
    (400, "prompt is too long", 0),
    (413, "Request too large: input is too long for the context window", 0),
    (400, "invalid tool schema", None),
    (500, "maximum context length is 1", None),
    (None, "maximum context length is 1", None),
])
def test_a_size_refusal_is_recognised_with_its_stated_limit(status, text, stated):
    assert compaction.size_refusal(status, text) == stated


def test_forget_window_makes_the_next_read_ask_the_catalog(monkeypatch):
    compaction._window_cache["m"] = (10 ** 12, 1_000)
    assert compaction.context_window("m") == 1_000
    compaction.forget_window("m")
    monkeypatch.delenv("CLICKHOUSE_URL", raising=False)
    assert compaction.context_window("m") == 0


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
    assert seen["body"]["model"] == "m"


def test_the_summariser_uses_the_compaction_model(monkeypatch):
    seen = _summariser_request(monkeypatch, LLM_MODEL_COMPACTION="small")
    assert seen["body"]["model"] == "small"


def test_the_summariser_leaves_temperature_out_when_the_provider_refuses_it(monkeypatch):
    seen = _summariser_request(monkeypatch, LLM_SEND_TEMPERATURE="false")
    assert "temperature" not in seen["body"]


def test_the_summariser_timeout_follows_the_request_timeout(monkeypatch):
    seen = _summariser_request(monkeypatch, LLM_REQUEST_TIMEOUT_SECONDS="3600")
    assert seen["timeout"] == (10.0, 3600.0)
