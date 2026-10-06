"""Verify language thresholds and bounded source sampling."""

import pytest
from tasks import document_language as language


@pytest.mark.parametrize("score,expected", [(0.49, "und"), (0.5, "hu"), (0.9, "hu")])
def test_language_score_threshold(monkeypatch, score, expected):
    class Model:
        def predict(self, text, k):
            assert len(text) <= 4000 and "\n" not in text
            return ["__label__hu"], [score]
    monkeypatch.setattr(language, "language_model", lambda: Model())
    assert language.detect_language("á\n" * 3000) == expected


def test_short_source_avoids_model_and_detector_failure_returns_und(monkeypatch):
    def fail():
        raise RuntimeError("The detector failed.")
    monkeypatch.setattr(language, "language_model", fail)
    assert language.detect_language("a" * 199) == "und"
    assert language.detect_language("a" * 200) == "und"


def test_source_sampling_stops_before_later_pages(monkeypatch):
    def pages():
        yield 1, "a" * 3000
        yield 2, "b" * 3000
        pytest.fail("An unnecessary page was read.")
    monkeypatch.setattr(language, "detect_language", lambda text: text)
    assert language.source_language(pages()) == "a" * 3000 + "b" * 1000
