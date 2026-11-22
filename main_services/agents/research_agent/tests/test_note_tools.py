"""The notes tool, and the note in the summary request of a compaction."""

from agent_common.tool_packs import allowed_tools
from research_agent import compaction
from research_agent.tool_catalogue import build_snapshot
from test_thread_index import WINDOW_256K, EST, Thread, chars, ok


def test_a_note_in_the_prefix_reaches_the_summary_request():
    t = Thread()
    t.human("q")
    t.step(ok("write_note", {"text": "the memo is dated 2001-03-12"},
              {"saved": 1, "note": "the memo is dated 2001-03-12"}))
    for n in range(40):
        t.step(ok("doc_metadata", {"n": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=210_000)
    prompts = []
    _out, report = compaction.compact(t.rows, t.rows, window=WINDOW_256K, estimator=EST,
                                      summariser=lambda prompt, cap: prompts.append(prompt)
                                      or "## Findings\nx")
    assert report is not None and len(prompts) == 1
    assert "2001-03-12" in prompts[0]


def test_new_turn_has_no_note_tool():
    for kind in ("chat", "board"):
        allowed = allowed_tools(kind, "all")
        assert "write_note" not in allowed
        snapshot = build_snapshot([], allowed, kind)
        assert "write_note" not in snapshot.callable_names()
