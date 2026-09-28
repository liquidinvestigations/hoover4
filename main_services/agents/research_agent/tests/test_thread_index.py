"""The index of a compaction record, the token estimate, and the plan of a compaction.

Every function here is pure. The tests build stored threads with `Thread` and plan them with a
fixed estimator of 0.25 tokens a character, so a size in tokens is known by hand.
"""

import json

from research_agent import compaction, thread_index
from research_agent.compaction import (
    CUT_MARK, Estimator, RECORD_HEADER, Sizer, initial_layout, plan_compaction, shrink,
)
from research_agent.run_messages import RunMessage, ToolCallRecord

THREAD = "t1"
EST = Estimator(ratio=0.25, fixed=0)
#: dgemma: a window of 262,144 tokens at 0.80 gives a trigger of 209,715 and a target of 69,905.
DGEMMA = 262_144


def chars(tokens: int) -> str:
    """Content of about `tokens` tokens by `EST`."""
    return "x" * max(1, int(tokens / (EST.ratio * compaction.MARGIN)))


class Thread:
    """A stored run thread, one row at a time, with keys (THREAD, idx)."""

    def __init__(self):
        self.rows = []

    def _add(self, **fields):
        m = RunMessage(thread_id=THREAD, idx=len(self.rows), **fields)
        self.rows.append(m)
        return m

    def human(self, text):
        return self._add(role="human", content=text)

    def step(self, *calls, text="", billed=0):
        """One `ai` message with `calls`, each (name, args, result, status), then the results."""
        n = len(self.rows)
        records = [ToolCallRecord(id=f"c{n}_{k}", name=name, args=args)
                   for k, (name, args, _r, _s) in enumerate(calls)]
        usage = {"input_tokens": billed, "output_tokens": 10} if billed else None
        ai = self._add(role="ai", content=text, tool_calls=records, usage=usage)
        for record, (name, _a, result, status) in zip(records, calls):
            self._add(role="tool", content=result, tool_call_id=record.id, name=name,
                      status=status)
        return ai


def ok(name, args, result):
    return (name, args, result if isinstance(result, str) else json.dumps(result), "ok")


def stub(prompt, cap):
    return "## Goal\nshort"


# ------------------------------------------------------------------------ index

TODAY_EMPTY = json.dumps({"success": True, "items": [], "fields": {"total_count": 0}})
TODAY_FULL = json.dumps({"success": True, "items": [{"file_hash": "a" * 64}],
                         "fields": {"total_count": 1}})
SLIM_EMPTY = json.dumps({"items": [], "notes": ["'Raptor approval': 0 found"]})
SLIM_FULL = json.dumps({"items": [{"file_hash": "a5ee8d51b5bc1579"}, {"file_hash": "b" * 16}],
                        "more": "c7f3a91b0d2e"})
REFUSAL = json.dumps({"success": False, "error": "invalid_arguments", "message": "no"})


def test_found_nothing_reads_both_result_formats_and_refuses_a_refusal():
    assert thread_index.found_nothing("search_collections", TODAY_EMPTY)
    assert thread_index.found_nothing("search_passages", SLIM_EMPTY)
    assert thread_index.found_nothing("web_search", json.dumps({"results": []}))
    assert not thread_index.found_nothing("search_collections", TODAY_FULL)
    assert not thread_index.found_nothing("search_collections", SLIM_FULL)
    assert not thread_index.found_nothing("search_collections", REFUSAL)
    assert not thread_index.found_nothing("read_documents", TODAY_EMPTY)


def _index_thread():
    t = Thread()
    t.human("Find the lease approvals.")
    t.step(ok("search_collections", {"queries": ["Raptor approval"], "collections": ["enron"]},
              TODAY_EMPTY))
    t.step(ok("search_passages", {"query": "LJM2 board"}, SLIM_EMPTY))
    t.step(ok("search_passages", {"queries": ["Fastow memo"]}, SLIM_FULL))
    t.step(ok("read_documents", {"collectionname": "enron", "file_hash": ["5e8b"]},
              {"items": [{"collectionname": "enron", "file_hash": "5e8bb0ff3822761c",
                          "path": "/maildir/kean-s/sent/12", "page": 1},
                         {"collectionname": "enron", "file_hash": "5e8bb0ff3822761c",
                          "path": "/maildir/kean-s/sent/12", "page": 2}]}))
    t.step(ok("read_skill", {"name": "thorough"}, "Skill `thorough`.\ntext"))
    t.step(ok("read_tool", {"name": "search_histogram"}, {"tool": "search_histogram"}))
    return t


def test_the_index_lists_the_searches_the_documents_and_the_removed_texts():
    t = _index_thread()
    text = thread_index.render(t.rows, visible_after=set())
    assert "## Searches that found nothing" in text
    assert '- search_collections ["Raptor approval"] filters {"collections": ["enron"]}' in text
    assert '- search_passages "LJM2 board" filters {}' in text
    assert '## Searches that found documents\n- search_passages ["Fastow memo"]: 2 documents' in text
    assert "- enron/5e8bb0ff3822761c /maildir/kean-s/sent/12. pages 1, 2" in text
    assert text.endswith("Texts removed whole: skill `thorough`, tool `search_histogram`. Read "
                         "one again with `read_skill` or `read_tool` when you need it.")


def test_every_hash_of_documents_read_occurs_in_the_thread():
    t = _index_thread()
    text = thread_index.render(t.rows, visible_after=set())
    lines = text.split("## Documents read\n")[1].split("\n\n")[0].splitlines()
    whole = " ".join(m.content for m in t.rows)
    assert lines
    for line in lines:
        assert line.split()[1].split("/", 1)[1] in whole


def test_a_result_visible_whole_is_not_in_the_index():
    t = _index_thread()
    keys = {(THREAD, m.idx) for m in t.rows if m.role == "tool"}
    assert thread_index.render(t.rows, visible_after=keys) == ""


# ------------------------------------------------------------------------ estimate


def test_the_estimate_calibrates_on_the_last_billed_call_and_clamps():
    t = Thread()
    t.human("h" * 976)                                 # 1,000 chars with the frame
    t.step(billed=250)
    est = Estimator.calibrate(t.rows)
    assert abs(est.ratio - 0.25) < 1e-9
    assert est.tokens(t.rows[0]) == 263                # 1,000 x 0.25 x 1.05, rounded up
    t.rows[-1] = t.rows[-1].model_copy(update={"usage": {"input_tokens": 10_000}})
    assert Estimator.calibrate(t.rows).ratio == 1 / 1.5
    est = Estimator.calibrate(t.rows[:1] + [t.rows[1].model_copy(
        update={"usage": {"input_tokens": 1}})], system_text="s" * 100)
    assert est.ratio == 1 / 6 and est.fixed == 18


# ------------------------------------------------------------------------ the plan


def test_no_billed_usage_and_no_window_give_no_compaction():
    t = Thread()
    t.human("q")
    t.step(ok("doc_metadata", {"h": 1}, chars(30_000)))
    assert plan_compaction(t.rows, t.rows, window=DGEMMA, estimator=EST) is None
    t.step(billed=250_000)
    assert plan_compaction(t.rows, t.rows, window=0, estimator=EST) is None
    assert plan_compaction(t.rows, t.rows, window=DGEMMA, fraction=0.8, estimator=EST)


def test_a_thread_of_40_groups_fits_a_target_of_333_and_keeps_its_state():
    t = Thread()
    t.human("Find the memo.")
    t.step(ok("write_todo", {"steps": ["a"]}, {"version": 1}))
    t.step(ok("write_todo", {"steps": ["b"]}, {"version": 2}))
    t.step(ok("append_node", {"text": "s"}, {"version": 5}))
    t.step(ok("cite_documents", {"file_hash": ["a"]}, {"citations": [{"handle": "[D1]"}]}))
    t.step(text="The memo [D1] says so.")
    for n in range(35):
        t.step(ok("doc_metadata", {"n": n}, chars(40)))
    t.human("And the date?")
    t.step(ok("doc_metadata", {"n": 99}, chars(20)), billed=1_200)
    out, report = compaction.compact(t.rows, t.rows, window=3_000, fraction=1 / 3,
                                     estimator=EST, summariser=stub)
    assert report is not None and report.target == 333
    assert report.est_after <= 333 and report.target_reached
    contents = [m.content for m in out]
    assert "Find the memo." in contents and "And the date?" in contents
    assert json.dumps({"version": 2}) in contents                     # the newest todo
    assert json.dumps({"version": 1}) not in contents
    assert json.dumps({"version": 5}) in contents                     # the plan result
    assert any("[D1]" in c and "citations" in c for c in contents)
    assert "The memo [D1] says so." in contents
    assert out[1].content.startswith(RECORD_HEADER)


def _report_thread(reports=8, other=6_000):
    t = Thread()
    t.human(chars(other))
    for n in range(reports):
        t.step(ok("run_subagent", {"tasks": [{"objective": str(n)}]}, chars(5_000)))
    for n in range(5):
        t.step(ok("doc_metadata", {"n": n}, chars(3_000)))
    t.step(ok("doc_metadata", {"n": 9}, chars(100)), billed=210_000)
    return t


def test_a_keep_set_over_its_cap_moves_the_oldest_report_out():
    t = _report_thread()
    sizer = Sizer(t.rows, EST)
    layout = initial_layout(t.rows, EST, 69_905)
    assert 37_000 < sizer.keep_outside_window(layout) < 39_000
    layout = shrink(layout, sizer, 69_905)
    assert layout.steps == ["report"]
    assert sizer.keep_outside_window(layout) <= compaction.KEEP_CAP_TOKENS
    first_report = t.rows[2].idx
    kept, _blank, gone, _drop = layout.classify()
    assert first_report in gone and t.rows[4].idx in kept


def test_a_newest_group_larger_than_the_target_is_cut_to_fit():
    t = Thread()
    t.human("q")
    for n in range(3):
        t.step(ok("doc_metadata", {"n": n}, chars(1_000)))
    t.step(ok("read_page", {"url": "u"}, chars(100_000)), billed=210_000)
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    newest = out[-1]
    assert newest.content.endswith(CUT_MARK)
    assert EST.tokens(newest) >= compaction.NEWEST_MIN_TOKENS
    assert "newest" in report.steps and report.est_after <= report.target


def test_user_messages_past_the_target_give_target_reached_false():
    t = Thread()
    t.human(chars(80_000))
    t.step(ok("doc_metadata", {"n": 1}, chars(1_000)))
    t.human(chars(1_000))
    t.step(ok("doc_metadata", {"n": 2}, chars(1_000)), billed=210_000)
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=stub)
    assert report.target_reached is False and report.row["target_reached"] is False
    assert report.row["sizes"]["user"] > report.target
    humans = [m.content for m in out if m.role == "human"]
    assert t.rows[0].content in humans and t.rows[3].content in humans


def test_a_skill_read_twice_keeps_the_newer_read():
    t = Thread()
    t.human("q")
    t.step(ok("read_skill", {"name": "thorough"}, "Skill `thorough`.\nold"))
    t.step(ok("doc_metadata", {"n": 1}, chars(1_000)))
    t.step(ok("read_skill", {"name": "thorough"}, "Skill `thorough`.\nnew"))
    for n in range(4):
        t.step(ok("doc_metadata", {"n": n}, chars(20_000)))
    t.step(ok("doc_metadata", {"n": 9}, chars(10)), billed=210_000)
    layout = initial_layout(t.rows, EST, 69_905)
    kept, _blank, _gone, drop = layout.classify()
    assert 2 in drop and 6 in kept
