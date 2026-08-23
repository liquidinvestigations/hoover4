"""Two NER providers write to the same segment. P6 must union them, not pick one.

This is the failure mode that produces no error at all: with last-wins, half the
entities never reach Manticore and the only symptom is facet counts that look "a bit
low", on a stage whose output nobody diffs against a previous run.
"""

from tasks.P6_index_data.activities import union_entities_by_segment


def _row(nlp_model, entity_type, values, *, page_id=1, extracted_by="pdftotext"):
    return {
        "file_hash": "h1",
        "extracted_by": extracted_by,
        "page_id": page_id,
        "nlp_model": nlp_model,
        "entity_type": entity_type,
        "entity_values": values,
    }


def test_two_providers_are_unioned_not_overwritten():
    grouped = union_entities_by_segment([
        _row("ner-gpu-xlmr", "PER", ["Alice", "Bob"]),
        _row("ner-spacy-xx", "PER", ["Carol"]),
    ])
    assert grouped[("h1", "pdftotext", 1)]["PER"] == ["Alice", "Bob", "Carol"]


def test_agreement_between_providers_does_not_double_count():
    """The providers agree on most entities. The same term id twice in a Manticore MVA
    inflates every facet count that includes it."""
    grouped = union_entities_by_segment([
        _row("ner-gpu-xlmr", "ORG", ["Acme", "Globex"]),
        _row("ner-spacy-xx", "ORG", ["Globex", "Acme", "Initech"]),
    ])
    assert grouped[("h1", "pdftotext", 1)]["ORG"] == ["Acme", "Globex", "Initech"]


def test_duplicates_within_one_provider_row_are_also_collapsed():
    grouped = union_entities_by_segment([
        _row("ner-gpu-xlmr", "LOC", ["Berlin", "Berlin", "Paris"]),
    ])
    assert grouped[("h1", "pdftotext", 1)]["LOC"] == ["Berlin", "Paris"]


def test_entity_types_stay_separate():
    grouped = union_entities_by_segment([
        _row("ner-gpu-xlmr", "PER", ["Alice"]),
        _row("ner-spacy-xx", "ORG", ["Acme"]),
    ])
    segment = grouped[("h1", "pdftotext", 1)]
    assert segment["PER"] == ["Alice"]
    assert segment["ORG"] == ["Acme"]


def test_text_variants_and_pages_stay_separate():
    """The OCR fan-out means one file has several `extracted_by` variants, each with its
    own pages. Merging across them would attribute an OCR variant's entities to the
    native text and vice versa."""
    grouped = union_entities_by_segment([
        _row("ner-gpu-xlmr", "PER", ["Alice"], extracted_by="pdftotext", page_id=1),
        _row("ner-gpu-xlmr", "PER", ["Bob"], extracted_by="ocr_tesseract_eng", page_id=1),
        _row("ner-gpu-xlmr", "PER", ["Carol"], extracted_by="pdftotext", page_id=2),
    ])
    assert len(grouped) == 3
    assert grouped[("h1", "pdftotext", 1)]["PER"] == ["Alice"]
    assert grouped[("h1", "ocr_tesseract_eng", 1)]["PER"] == ["Bob"]
    assert grouped[("h1", "pdftotext", 2)]["PER"] == ["Carol"]


def test_no_rows_is_no_segments():
    assert union_entities_by_segment([]) == {}
