"""The worker notes: the catalogs are in the subset that the worker reads, every language
keeps the variables of English, and a run reads its own language with an English fallback."""

from types import SimpleNamespace

import pytest

from tasks.P_agent import notes
from tasks.P_agent.language import LANGUAGES
from tasks.P_agent.steps import StepRef, _step_run


def _ids(text: str) -> set[str]:
    return {line.split("=", 1)[0].strip() for line in text.splitlines()
            if line and line[0].isalpha() and "=" in line}


@pytest.mark.parametrize("code", sorted(LANGUAGES))
def test_every_catalog_message_is_in_the_subset_with_the_english_variables(code):
    path = notes.CATALOG_DIR / code / "notes.ftl"
    if not path.is_file():
        pytest.skip(f"no {code} catalog")
    english = notes.catalog("en")
    parsed = notes.parse(path.read_text(encoding="utf-8"))
    assert _ids(path.read_text(encoding="utf-8")) <= set(parsed), "a message is outside the subset"
    for message_id, parts in parsed.items():
        assert message_id in english, message_id
        assert notes.variables(parts) == notes.variables(english[message_id]), message_id


def test_a_note_takes_its_variables():
    assert notes.note("en", "note-capture-empty", urls="https://a.example") == (
        "The capture of https://a.example holds no article text. Read another source. "
        "Do not cite this page.")


def test_a_missing_or_unknown_language_reads_english(monkeypatch):
    monkeypatch.setattr(notes, "catalog", lambda code: {
        "en": notes.parse("note-x = Read { $tool } now.\n"),
        "de": notes.parse("note-x = Lies jetzt { $werkzeug }.\n"),
        "fr": notes.parse("note-x = Lisez { $tool } maintenant.\n"),
    }.get(code, {}))
    assert notes.note("fr", "note-x", tool="t") == "Lisez t maintenant."
    # The German message names another variable, so English is used.
    assert notes.note("de", "note-x", tool="t") == "Read t now."
    assert notes.note("xx", "note-x", tool="t") == "Read t now."
    assert notes.note("it", "note-x", tool="t") == "Read t now."


def test_a_selector_is_outside_the_subset():
    parsed = notes.parse('note-a = { $n ->\n    [one] one\n   *[other] many\n}\nnote-b = A {"{"} b\n')
    assert "note-a" not in parsed
    assert parsed["note-b"] == ["A ", "{", " b"]


def test_a_step_request_carries_the_run_language():
    row = SimpleNamespace(run_id="r", username="u", session_id="s")
    assert _step_run(row, StepRef("r", "u", "s", language="de", llm_model="m"))["language"] == "de"
    assert _step_run(row, StepRef("r", "u", "s", language="", llm_model="m"))["language"] == "en"
    assert _step_run(row, StepRef("r", "u", "s", language="xx", llm_model="m"))["language"] == "en"
