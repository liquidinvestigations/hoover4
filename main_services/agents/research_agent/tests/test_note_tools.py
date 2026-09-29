"""The notes tool, and the note in the summary request of a compaction."""

import json

from agent_common.tool_packs import allowed_tools
from research_agent import compaction
from research_agent.note_tools import DESCRIPTION, REFUSAL, WRITE_NOTE, make_note_tools
from research_agent.tool_catalogue import build_snapshot
from test_thread_index import DGEMMA, EST, Thread, chars, ok


async def test_a_note_is_saved_and_counted():
    tool = make_note_tools()[0]
    first = json.loads(await tool.ainvoke({"text": "the memo is dated 2001-03-12"}))
    assert first == {"saved": 1, "note": "the memo is dated 2001-03-12"}
    second = json.loads(await tool.ainvoke({"text": "a second fact"}))
    assert second["saved"] == 2


async def test_a_note_of_2001_characters_is_refused():
    tool = make_note_tools()[0]
    assert await tool.ainvoke({"text": "x" * 2_001}) == REFUSAL
    assert await tool.ainvoke({"text": ""}) == REFUSAL
    assert json.loads(await tool.ainvoke({"text": "x" * 2_000}))["saved"] == 1


def test_a_note_in_the_prefix_reaches_the_summary_request():
    t = Thread()
    t.human("q")
    t.step(ok(WRITE_NOTE, {"text": "the memo is dated 2001-03-12"},
              {"saved": 1, "note": "the memo is dated 2001-03-12"}))
    for n in range(40):
        t.step(ok("doc_metadata", {"n": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=210_000)
    prompts = []
    _out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                      summariser=lambda prompt, cap: prompts.append(prompt)
                                      or "## Findings\nx")
    assert report is not None and len(prompts) == 1
    assert "2001-03-12" in prompts[0] and "`write_note`" in prompts[0]


def test_the_note_description_states_what_the_summary_does():
    assert "summary request asks for each note" in DESCRIPTION


def test_write_note_is_in_every_run():
    assert WRITE_NOTE in allowed_tools("planner", "collections")
    snapshot = build_snapshot([], allowed_tools("chat", "all"), "chat")
    assert WRITE_NOTE in snapshot.callable_names()


def test_write_note_is_callable_without_a_read_tool_call():
    snapshot = build_snapshot([], allowed_tools("chat", "all"), "chat")
    assert WRITE_NOTE in snapshot.callable_names()
