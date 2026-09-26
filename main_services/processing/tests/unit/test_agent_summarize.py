"""Parsing a summariser reply into a conversation title.

The strings here are verbatim from live runs. The prompt asks for two bare lines and the
models label them, wrap them in emphasis, or narrate their thinking first -- and every one
of those lands in the sidebar unless it is stripped here, because prompt wording is not a
reliable parser.
"""

from tasks.P_agent.summarize import parse_reply, strip_label, strip_think_blocks


def test_a_bold_label_is_stripped():
    assert strip_label("**Title:** Water Testing Document Identified") == (
        "Water Testing Document Identified"
    )
    assert strip_label("**Summary:** Search results located a PDF file.") == (
        "Search results located a PDF file."
    )


def test_labels_are_stripped_in_every_spelling_the_model_uses():
    for line in (
        "Title: Water levels",
        "title: Water levels",
        "**Title**: Water levels",
        "## Title: Water levels",
        "Line 1: Water levels",
    ):
        assert strip_label(line) == "Water levels", line


def test_an_unlabelled_line_keeps_its_text():
    assert strip_label("Water levels on the Danube") == "Water levels on the Danube"
    assert strip_label("  spaced out  ") == "spaced out"


def test_emphasis_around_a_whole_line_goes_but_a_prose_colon_stays():
    assert strip_label("**Water levels**") == "Water levels"
    # A colon that is not a label must not truncate the title.
    assert strip_label("Danube: a summary") == "Danube: a summary"


def test_think_blocks_are_removed():
    assert strip_think_blocks("<think>hmm</think>Answer") == "Answer"
    assert strip_think_blocks("no think here") == "no think here"
    # An unterminated block must not leave the whole response in place.
    assert strip_think_blocks("before<think>never closed") == "before"


def test_two_lines_become_a_title_and_a_summary():
    title, summary = parse_reply("Water levels\nWho paid for the testing, and when.")
    assert title == "Water levels"
    assert summary == "Who paid for the testing, and when."


def test_a_title_with_no_summary_is_its_own_summary():
    # The homepage card shows the summary; repeating the title reads better there than a
    # blank line does.
    assert parse_reply("Water levels") == ("Water levels", "Water levels")


def test_a_reply_with_nothing_usable_produces_no_title():
    # An empty title is how the caller knows to keep the provisional one.
    assert parse_reply("")[0] == ""
    assert parse_reply("   \n\n  ")[0] == ""
    assert parse_reply("**Title:**")[0] == ""


def test_a_long_title_is_cut_and_the_summary_with_it():
    title, summary = parse_reply("x" * 200 + "\n" + "y" * 900)
    assert len(title) == 80
    assert len(summary) == 400


# ---------------------------------------------------------------- the request body


class _Reply:
    status_code = 200
    text = ""

    def json(self):
        return {"choices": [{"message": {"content": "A title\nA summary."},
                             "finish_reason": "stop"}]}


def _title_body(monkeypatch, send_temperature):
    from tasks.P_agent import summarize

    bodies = []
    monkeypatch.setattr(summarize, "_model", lambda: "m")
    monkeypatch.setattr(summarize, "_api_key", lambda: "k")
    monkeypatch.setenv("LLM_BASE_URL", "http://model.invalid/v1")
    if send_temperature is None:
        monkeypatch.delenv("LLM_SEND_TEMPERATURE", raising=False)
    else:
        monkeypatch.setenv("LLM_SEND_TEMPERATURE", send_temperature)
    monkeypatch.setattr(summarize, "_post", lambda url, body: bodies.append(body) or _Reply())
    summarize.title_and_summary("question", "answer")
    assert len(bodies) == 1
    return bodies[0]


def test_the_title_body_has_no_temperature_when_the_provider_refuses_it(monkeypatch):
    assert "temperature" not in _title_body(monkeypatch, "false")


def test_the_title_body_keeps_its_temperature_by_default(monkeypatch):
    assert _title_body(monkeypatch, None)["temperature"] == 0.2
    assert _title_body(monkeypatch, "true")["temperature"] == 0.2
