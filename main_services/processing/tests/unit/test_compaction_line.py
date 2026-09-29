"""The compaction line of `tasks/P_agent/steps.py`, from a version 3 record and from a
version 2 record that a stored thread can still hold."""

from tasks.P_agent import steps


def test_a_version_3_record_gives_its_summary_and_its_state():
    record = {"version": 3, "status": "ok", "summary": "rec", "tokens_before": 212004,
              "target": 69905, "steps_summarised": 31, "target_reached": True,
              "source": [["t", 1]], "retained_from": ["t", 9]}
    assert steps.compaction_line(record, 61020, 1) == {
        "state": "done", "tokens_before": 212004, "target": 69905, "parts": 1,
        "tokens_after": 61020, "steps_summarised": 31, "target_reached": True,
        "record": "rec", "part_states": [], "summary_state": "ok"}


def test_a_failed_version_3_record_gives_no_record_and_the_failed_state():
    record = {"version": 3, "status": "failed", "summary": "", "tokens_before": 212004,
              "target": 69905, "steps_summarised": 0, "target_reached": False}
    line = steps.compaction_line(record, 190000, 1)
    assert (line["summary_state"], line["record"], line["steps_summarised"]) == (
        "failed", "", 0)


def test_a_version_2_record_gives_its_handoff_and_its_part_states():
    record = {"handoff": "rec", "tokens_before": 212004, "target": 69905,
              "parts": ["ok", "failed", "ok"], "steps_summarised": 31, "target_reached": False}
    assert steps.compaction_line(record, 61020, 3) == {
        "state": "done", "tokens_before": 212004, "target": 69905, "parts": 3,
        "tokens_after": 61020, "steps_summarised": 31, "target_reached": False,
        "record": "rec", "part_states": ["ok", "failed", "ok"], "summary_state": ""}
    assert steps.compaction_line({}, 0)["part_states"] == []


def test_the_worker_writes_no_note_warning():
    assert not hasattr(steps, "NOTE_WARNING_TEXT")
    assert not hasattr(steps, "note_warning_text")
