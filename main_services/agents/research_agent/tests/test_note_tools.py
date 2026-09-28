"""The notes tool, the note warning, the note keep class and the reread class."""

import json

from agent_common.tool_packs import allowed_tools
from research_agent import compaction
from research_agent.compaction import (
    NOTE_WARNING_HEAD, NOTE_WARNING_TEXT, Sizer, add_rereads, initial_layout, note_warning_due,
    shrink,
)
from research_agent.note_tools import REFUSAL, WRITE_NOTE, make_note_tools
from research_agent.run_messages import RunMessage
from research_agent.tool_catalogue import ALWAYS_BOUND, bound_names_from_thread, build_snapshot
from test_thread_index import DGEMMA, EST, THREAD, Thread, chars, ok


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


def test_the_note_stays_through_a_compaction():
    t = Thread()
    t.human("q")
    t.step(ok(WRITE_NOTE, {"text": "the memo is dated 2001-03-12"},
              {"saved": 1, "note": "the memo is dated 2001-03-12"}))
    for n in range(12):
        t.step(ok("doc_metadata", {"n": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=210_000)
    out, report = compaction.compact(t.rows, t.rows, window=DGEMMA, estimator=EST,
                                     summariser=lambda prompt, cap: "summary")
    assert report is not None
    assert any("2001-03-12" in m.content and m.role == "tool" for m in out)


def test_six_notes_of_1000_tokens_keep_the_newest_4():
    t = Thread()
    t.human("q")
    for n in range(6):
        # 1,000 tokens with the frame of the message.
        t.step(ok(WRITE_NOTE, {"text": str(n)}, chars(990)))
    for n in range(6):
        t.step(ok("doc_metadata", {"n": n}, chars(4_000)))
    layout = initial_layout(t.rows, EST, 69_905)
    notes = sorted(i for i in layout.fixed_keep if layout.names.get(i) == WRITE_NOTE)
    assert notes == [6, 8, 10, 12]


def _reread_thread(size):
    t = Thread()
    t.human("q")
    for n in range(4):
        t.step(ok("read_documents", {"file_hash": [str(n)]}, chars(size)))
    for n in range(8):
        t.step(ok("doc_metadata", {"n": n}, chars(4_000)))
    t.step(ok("doc_metadata", {"n": "last"}, chars(10)), billed=210_000)
    return t


def test_the_newest_3_documents_come_back_after_a_summary():
    t = _reread_thread(2_000)
    sizer = Sizer(t.rows, EST)
    layout = add_rereads(shrink(initial_layout(t.rows, EST, 69_905), sizer, 69_905),
                         sizer, 69_905)
    assert layout.rereads == [8, 6, 4]
    assert sizer.rest(layout) + layout.budget <= 69_905


def test_a_reread_that_would_pass_the_target_is_not_added():
    t = _reread_thread(2_000)
    sizer = Sizer(t.rows, EST)
    layout = shrink(initial_layout(t.rows, EST, 69_905), sizer, 69_905)
    target = sizer.rest(layout) + layout.budget + 1_000       # room for none of 2,000 tokens
    layout = add_rereads(layout, sizer, target)
    assert layout.rereads == []


def test_the_warning_is_due_once_at_90_percent_of_the_trigger():
    trigger = compaction.threshold_tokens(DGEMMA)
    near = {"input_tokens": int(0.9 * trigger) + 1, "output_tokens": 0}
    rows = [RunMessage(role="human", content="q", thread_id=THREAD, idx=0)]
    assert note_warning_due(rows, near, True, DGEMMA)
    assert not note_warning_due(rows, {"input_tokens": int(0.8 * trigger)}, True, DGEMMA)
    assert not note_warning_due(rows, near, False, DGEMMA)
    assert not note_warning_due(rows, near, True, 0)
    warned = rows + [RunMessage(role="human", content=NOTE_WARNING_TEXT.format(pct=90))]
    assert not note_warning_due(warned, near, True, DGEMMA)
    compacted = warned + [RunMessage(role="compaction", content="{}")]
    assert note_warning_due(compacted, near, True, DGEMMA)


def test_the_warning_text_names_read_tool():
    text = NOTE_WARNING_TEXT.format(pct=90)
    assert text.startswith(NOTE_WARNING_HEAD + " 90 percent")
    assert "`read_tool`" in text and "`write_note`" in text


def test_write_note_is_in_every_run_and_deferred():
    assert WRITE_NOTE in allowed_tools("planner", "collections")
    assert WRITE_NOTE not in ALWAYS_BOUND
    snapshot = build_snapshot([], allowed_tools("chat", "all"), "chat")
    assert WRITE_NOTE in snapshot.deferred_names


def test_a_successful_read_tool_of_write_note_binds_it_for_the_next_call():
    snapshot = build_snapshot([], allowed_tools("chat", "all"), "chat")
    t = Thread()
    t.human("q")
    t.step(ok("read_tool", {"name": WRITE_NOTE}, {"tool": WRITE_NOTE, "ready": "next call"}))
    assert WRITE_NOTE in bound_names_from_thread(snapshot, t.rows)
