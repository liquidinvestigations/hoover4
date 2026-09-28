"""The compaction line and the note warning of `tasks/P_agent/steps.py`."""

from types import SimpleNamespace

from tasks.P_agent import steps

#: The note warning at 90 percent, as the research agent's `compaction.NOTE_WARNING_TEXT`
#: renders it. Its test holds the same literal, so a change of one copy fails one test.
NOTE_WARNING_AT_90 = (
    "Your context is at 90 percent of its limit. The older steps of this run will soon be "
    "replaced by a record. Save each fact that you need later with `write_note` now. When "
    "`write_note` is not ready, call `read_tool` with the name `write_note` first. Then call "
    "`write_note` in your next reply."
)


def test_the_worker_copy_of_the_note_warning_matches_the_agent_text():
    assert steps.NOTE_WARNING_TEXT.format(pct=90) == NOTE_WARNING_AT_90


def test_the_note_warning_percent_is_of_the_stated_window(monkeypatch):
    from tasks.P_agent import stream_writer

    monkeypatch.setattr(stream_writer, "context_window_for",
                        lambda model: 200_000 if model == "m" else 0)
    ai = SimpleNamespace(usage={"input_tokens": 150_000, "output_tokens": 1_000, "model": "m"})
    assert steps.note_warning_text(ai).startswith("Your context is at 76 percent")


def test_the_done_line_holds_every_key_and_the_part_states():
    record = {"handoff": "rec", "tokens_before": 212004, "target": 69905,
              "parts": ["ok", "failed", "ok"], "steps_summarised": 31, "target_reached": False}
    assert steps.compaction_line(record, 61020, 3) == {
        "state": "done", "tokens_before": 212004, "target": 69905, "parts": 3,
        "tokens_after": 61020, "steps_summarised": 31, "target_reached": False,
        "record": "rec", "part_states": ["ok", "failed", "ok"]}
    assert steps.compaction_line({}, 0)["part_states"] == []
