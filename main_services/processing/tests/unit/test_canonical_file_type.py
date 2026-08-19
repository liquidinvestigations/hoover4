"""The rank table that turns five disagreeing detectors into one definitive type.

One case per row of the design's own list, plus the archive demotion. Table-driven,
because the failure this guards is a new rule quietly reordering the existing ones.
"""

import pytest

from tasks.P6_index_data.canonical_file_type import resolve_canonical

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

#: (name, detections, parsed, archive_member_count, expected file_type, expected decided_by)
CASES = [
    (
        "docx detected as zip is a doc",
        {"file": ["application/zip", "application/octet-stream"],
         "extension": [DOCX],
         "magika": ["application/zip"]},
        set(),
        3,
        "doc",
        "zip_based_document",
    ),
    (
        "docx whose office extractor produced text is a doc on the strongest rule",
        {"file": ["application/zip"], "extension": [DOCX]},
        {"doc"},
        3,
        "doc",
        "parse_succeeded",
    ),
    (
        "an image encoded as text is an image",
        {"file": ["text/plain"], "magika": ["image/x-xpixmap"]},
        {"image"},
        0,
        "image",
        "parse_succeeded",
    ),
    (
        "an image nobody parsed still beats text on the ladder",
        {"file": ["text/plain"], "magika": ["image/x-xpixmap"]},
        set(),
        0,
        "image",
        "specificity_ladder",
    ),
    (
        "an email detected as text is an email",
        {"file": ["text/plain"], "tika": ["text/plain"],
         "content_sniff": ["message/rfc822"]},
        set(),
        0,
        "email",
        "content_sniff_email",
    ),
    (
        "an empty archive falls back to its other detected type",
        {"file": ["application/zip", "text/plain"]},
        {"archive"},
        0,
        "text",
        "empty_archive_demoted",
    ),
    (
        "an archive with members stays an archive",
        {"file": ["application/zip"]},
        {"archive"},
        7,
        "archive",
        "parse_succeeded",
    ),
    (
        "the filename agreeing with a content detector breaks a tie",
        {"file": ["text/plain", "text/html"], "extension": ["text/html"]},
        set(),
        0,
        "html",
        "extension_agrees",
    ),
]


@pytest.mark.parametrize(
    "detections,parsed,members,file_type,decided_by",
    [c[1:] for c in CASES],
    ids=[c[0] for c in CASES],
)
def test_rank_table(detections, parsed, members, file_type, decided_by):
    result = resolve_canonical(detections, parsed, members)
    assert result.file_type == file_type
    assert result.decided_by == decided_by


def test_losers_keep_every_other_detection():
    """Nothing is lost by canonicalising: the metadata tab shows the whole set."""
    result = resolve_canonical(
        {"file": ["text/plain"], "tika": ["text/plain"],
         "content_sniff": ["message/rfc822"]},
        set(),
        0,
    )
    assert result.mime_type == "message/rfc822"
    assert result.losers == ["text/plain"]


def test_a_document_with_no_detections_at_all_is_other():
    result = resolve_canonical({}, set(), 0)
    assert result.file_type == "other"
    assert result.mime_type == ""
    assert result.losers == []
