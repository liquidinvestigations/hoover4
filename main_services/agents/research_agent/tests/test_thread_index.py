"""The index of a compaction record and the token estimate.

Every function here is pure. The tests build stored threads with `Thread`, and the
compaction tests import it, with a fixed estimator of 0.25 tokens a character, so a size in
tokens is known by hand.
"""

import json

from research_agent import compaction, thread_index
from research_agent.compaction import Estimator
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
    t.step(ok("cite_documents", {"citations": [{"file_hash": "5e8b"}]},
              {"citations": [{"file_hash": "5e8bb0ff3822761c", "handle": "[D1]"},
                             {"file_hash": "a5ee8d51b5bc1579", "error": "not_found"}]}))
    t.step(ok("read_page", {"urls": ["https://a.example/lease"]},
              "## Lease\nhttps://a.example/lease\n\ntext\n\n[cut: this call read 9,000 of the "
              "page's 61,020 characters. Call read_page with offset 9000 for the next part]"
              "\n\n---\n\n## Notice\nhttps://b.example/notice\n\nwhole text"))
    t.step(ok("search_passages", {"query": "lease clause"},
              {"items": [{"file_hash": "c" * 16}], "more": "c7f3a91b0d2e"}))
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
    assert "## Citation labels\n- [D1] 5e8bb0ff3822761c\n\n" in text
    assert "a5ee8d51b5bc1579" not in text.split("## Citation labels")[1].split("##")[0]
    assert ("## Pages read\n- https://a.example/lease. next offset 9000\n"
            "- https://b.example/notice\n\n") in text
    assert ('## Results that continue\n- search_passages {"queries": ["Fastow memo"]}: more '
            'c7f3a91b0d2e\n- search_passages {"query": "lease clause"}: more c7f3a91b0d2e'
            ) in text
    assert text.endswith("Texts removed: skill `thorough`, tool `search_histogram`. Read "
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
