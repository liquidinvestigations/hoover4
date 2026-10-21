"""Reject the historical false-accept mechanisms and stale reference identities."""

from copy import deepcopy
import pytest
from scripts.chat_review.grade import grade, inventory_delivery
from scripts.chat_review.schema import Invalid, digest, text_digest
from .conftest import make_packet, reference_for, labels_for, approve, seal


def run(packet, reference=None):
    reference = reference or reference_for(packet)
    return grade(packet, packet["delivery"], reference, labels_for(reference))


def test_correct_control_passes(packet):
    assert run(packet)["verdict"] == "delivery_pass"


def test_compound_claim_does_not_inherit_supported_label():
    packet = make_packet("The source lists Rome, and every city committed fraud.")
    ref = reference_for(packet)
    text = packet["delivery"]["files"][0]["content"]
    f = ref["files"][0]
    first, second = "The source lists Rome", "every city committed fraud"
    f["claims"] = [{"id": cid, "span": [text.index(quote), text.index(quote) + len(quote)],
                    "quote": quote, "label": label, "source_ids": ["cities"], "reason": reason}
                   for cid, quote, label, reason in (
                       ("city", first, "supported", "Ada's row names Rome."),
                       ("allegation", second, "unsupported", "The source records cities and names only."))]
    f["regions"][0]["claim_ids"] = ["city", "allegation"]
    approve(ref)
    result = run(packet, ref)
    assert result["verdict"] == "delivery_fail"
    assert [c["id"] for c in result["defects"]] == ["allegation"]


def test_plain_factual_sentence_enters_coverage():
    packet = make_packet("every city committed fraud")
    ref = reference_for(packet)
    ref["files"][0]["regions"] = []
    ref["files"][0]["claims"] = []
    approve(ref)
    assert inventory_delivery(packet["delivery"], ref)["uncovered"][0]["quote"] == "every city committed fraud"
    assert run(packet, ref)["verdict"] == "review_incomplete"


def test_uncertain_assertion_prevents_acceptance(packet):
    ref = reference_for(packet, labels={"cities.md": "uncertain"})
    assert run(packet, ref)["verdict"] == "review_incomplete"


def test_qualified_uncertainty_preserves_scope():
    packet = make_packet("The supplied rows do not establish misconduct.")
    ref = reference_for(packet)
    ref["files"][0]["regions"][0]["kind"] = "qualified_uncertainty"
    approve(ref)
    assert run(packet, ref)["verdict"] == "delivery_pass"


def test_closing_answer_madrid_omission_fails_delivery():
    packet = make_packet(closing="The complete city list is Rome.")
    ref = reference_for(packet, labels={"<closing>": "contradicted"})
    result = run(packet, ref)
    assert result["verdict"] == "delivery_fail"
    assert result["defects"][0]["file"] == "<closing>"


def test_agent_reference_needs_independent_source_review(packet):
    ref = reference_for(packet)
    ref["independent_review"] = None
    assert run(packet, ref)["verdict"] == "review_incomplete"


@pytest.mark.parametrize("change", ["source", "delivery", "reference", "label", "unknown"])
def test_stale_or_malformed_reference_rejected(packet, change):
    ref = reference_for(packet)
    labels = labels_for(ref)
    if change == "source":
        packet["evidence"][0]["content"] += "new data"
        packet["evidence"][0]["digest"] = text_digest(packet["evidence"][0]["content"])
        seal(packet)
    elif change == "delivery":
        packet["delivery"]["closing_answer"]["content"] += "!"
        packet["delivery"]["closing_answer"]["digest"] = text_digest(packet["delivery"]["closing_answer"]["content"])
        seal(packet)
    elif change == "reference":
        ref["reference_revision"] += 1
    elif change == "label":
        labels["labels"][0]["label"] = "probably"
    else:
        ref["extra"] = True
    with pytest.raises(Invalid):
        grade(packet, packet["delivery"], ref, labels)


def test_unsupported_label_cannot_be_overridden_by_adjudicator(packet):
    ref = reference_for(packet, labels={"cities.md": "unsupported"})
    labels = labels_for(ref)
    labels["labels"][0]["label"] = "supported"
    assert grade(packet, packet["delivery"], ref, labels)["verdict"] == "delivery_fail"


def test_wrong_report_subject_heading_prevents_acceptance():
    packet = make_packet("# Rome\nThe city is Madrid.")
    ref = reference_for(packet, labels={"cities.md": "contradicted"})
    claim = ref["files"][0]["claims"][0]
    claim["context_spans"] = [{"file": "cities.md", "span": [0, 6], "quote": "# Rome"}]
    approve(ref)
    assert run(packet, ref)["verdict"] == "delivery_fail"


def test_missing_output_is_a_defect(packet):
    packet["delivery"]["files"] = []
    packet["coverage"]["available"] = ["<closing>"]
    seal(packet)
    assert run(packet)["defects"][0]["kind"] == "missing_output"


def test_exact_quote_cannot_be_classified_without_source_match(packet):
    ref = reference_for(packet)
    ref["files"][0]["regions"][0]["kind"] = "quoted_source"
    approve(ref)
    with pytest.raises(Invalid):
        run(packet, ref)


def test_missing_reference_region_cannot_be_hidden_by_whitespace(packet):
    ref = reference_for(packet)
    ref["files"] = ref["files"][1:]
    approve(ref)
    assert run(packet, ref)["unresolved"]


def test_wrong_reviewer_cannot_change_expected_facts():
    packet = make_packet("The table has 220 distinct offices.")
    ref = reference_for(packet, labels={"cities.md": "contradicted"})
    assert run(packet, ref)["verdict"] == "delivery_fail"


@pytest.mark.parametrize('damaged,reason', [
    ('The table has 214 distinct offices, 9 empty cases, and 29 two-case offices.', 'The complete table establishes 27 two-case offices.'),
    ('54 + 196 + 9 = 250', 'The terms sum to 259. The complete table has 187 single-office cases.'),
    ('Office 025 has cases C-025 and C-225.', 'Both named rows have empty office cells. Office 025 occurs at C-245.'),
    ('Case C-250 names Harbury Annex.', 'The source row names Harbour Annex.'),
    ('There are 214 empty cases.', 'The distinct-office count cannot support the empty-case count.'),
])
def test_source_valid_values_cannot_support_wrong_claims(damaged, reason):
    from website.tools.prepare_table_fixtures import office_rows, _csv
    packet = make_packet(damaged)
    source = _csv(office_rows(), ['case_id', 'office', 'amount']).decode()
    packet['evidence'][0].update(content=source, digest=text_digest(source))
    seal(packet)
    ref = reference_for(packet, labels={'cities.md': 'contradicted'})
    ref['files'][0]['claims'][0]['reason'] = reason
    approve(ref)
    assert run(packet, ref)['verdict'] == 'delivery_fail'
