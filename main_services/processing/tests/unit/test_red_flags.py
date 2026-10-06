"""Verify calibrated concepts, windows, Unicode offsets, and stored byte identity."""

import copy
import pytest
from tasks.red_flags import compute_clusters, load_calibration, score_concepts, text_digest
from tasks.signal_storage import page_clusters


def hit(text, term, concept=None, tier="H", flags=(), category="bribery"):
    start = text.encode().index(term.encode())
    return dict(category=category, start=start, end=start + len(term.encode()),
                text=term, term=term, concept=concept or term, tier=tier, flags=list(flags))


def test_calibration_has_every_category_and_selected_noisy_list():
    value = load_calibration()
    assert len(value["categories"]) == 26
    assert len(value["noisy_terms"]) == 654
    assert value["window_words"] == 400 and value["stride_words"] == 200
    assert all(rule["threshold"] == 8 for rule in value["categories"].values())
    assert {name for name, rule in value["categories"].items() if rule["low_recall"]} == {
        "concealment", "accounting", "rationalisation", "litigation", "legal_letter"}


def test_concepts_score_once_and_quoted_or_boilerplate_hits_do_not_score():
    rule = load_calibration()["categories"]["bribery"]
    text = "alpha beta gamma"
    hits = [hit(text, "alpha"), hit(text, "alpha"), hit(text, "beta", flags=["negated"])]
    assert score_concepts(hits, "bribery", rule, set()) == (9, True)
    hits[2]["concept"] = "alpha"
    assert score_concepts(hits, "bribery", rule, set()) == (6, False)
    for flags in [["quoted"], ["boilerplate"]]:
        hits[2].update(concept="beta", flags=flags)
        assert score_concepts(hits, "bribery", rule, set()) == (6, False)


def test_low_tier_cap_and_noisy_override():
    rule = load_calibration()["categories"]["bribery"]
    text = "alpha beta gamma delta"
    hits = [hit(text, term, tier="L") for term in text.split()]
    assert score_concepts(hits, "bribery", rule, set()) == (2, False)
    hits[0]["tier"] = "H"
    assert score_concepts(hits, "bribery", rule, set()) == (8, True)
    assert score_concepts(hits, "bribery", rule, {("bribery", "alpha")}) == (2, False)


def test_unicode_excerpt_and_overlapping_qualifying_windows_merge():
    words = ["á"] * 900
    words[210], words[390], words[610], words[790] = "alpha", "beta", "gamma", "delta"
    text = " ".join(words)
    hits = [hit(text, term) for term in ["alpha", "beta", "gamma", "delta"]]
    clusters = compute_clusters(text, hits)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["points"] == 12
    for start, end in zip(cluster["hit_starts"], cluster["hit_ends"]):
        assert cluster["excerpt"].encode()[start:end].decode() in {"alpha", "beta", "gamma", "delta"}


def test_one_concept_and_wrong_bytes_cannot_raise_a_flag():
    text = "alpha beta"
    assert compute_clusters(text, [hit(text, "alpha")]) == []
    broken = hit(text, "alpha")
    broken["end"] += 1
    with pytest.raises(ValueError, match="source bytes"):
        compute_clusters(text, [broken])


def test_page_digest_and_version_must_match_the_completed_scan():
    text = "alpha beta"
    row = dict(collection_dataset="dataset", file_hash="file", extracted_by="raw_text", page_id=1, text_version=2)
    key = ("file", "raw_text", 1)
    hits = {key: [hit(text, "alpha"), hit(text, "beta")]}
    marks = {key: ("lexicon", text_digest(text), 2)}
    assert page_clusters(row, text, marks, hits, 3)[0]["write_version"] == 3
    for bad in [("lexicon", "wrong", 2), ("lexicon", text_digest(text), 1)]:
        with pytest.raises(ValueError, match="current signal scan"):
            page_clusters(row, text, {key: bad}, hits, 3)


def test_phrase_that_crosses_a_window_end_remains_in_the_excerpt():
    words = ["á"] * 800
    words[10], words[399], words[400] = "alpha", "beta", "gamma"
    text = " ".join(words)
    clusters = compute_clusters(text, [hit(text, "alpha"), hit(text, "beta gamma")])
    assert len(clusters) == 1
    assert "beta gamma" in clusters[0]["excerpt"]
    assert all(end <= len(clusters[0]["excerpt"].encode()) for end in clusters[0]["hit_ends"])


def test_invalid_scanner_offsets_and_classes_are_refused_before_storage():
    from tasks.P4_extract_entities.scan_regex_entities import validate_signal_hit
    text = "á alpha"
    value = hit(text, "alpha")
    validate_signal_hit(text.encode(), value)
    for updates in [dict(start=0), dict(end=100), dict(category="unknown"), dict(tier="unknown")]:
        with pytest.raises(ValueError):
            validate_signal_hit(text.encode(), dict(value, **updates))
