"""The corpus-wide precision of the delimited-text sniff.

The sniff decides from a heuristic, so the only thing that can hold it accurate is a
measurement over real corpora, kept as a test rather than as a script. The failure it
guards against is a future edit that widens the match and turns a strict sniff into an
eager one.

The consequence of that edit is specific and expensive. An RFC 822 message is hundreds of
consistent `Name: value` lines, which any sniff that accepts `:` as a delimiter reads as a
perfectly rectangular two-column CSV. On this box that is 21 291 messages turning into
21 291 tables, filling the cell store with the "columns" of mail headers, moving every one
of them out of the `email` bucket of the file-type facet, and requiring a full reprocess
to undo.

Both corpora are gitignored and bind-mounted into the worker at `/testdata`. The test
skips when they are absent, so a checkout that has not fetched them still has a green
suite.
"""

from pathlib import Path

import pytest

from tasks.P3_parse_files.sniff_email import sniff_email_path
from tasks.P3_parse_files.sniff_table import should_check_table, sniff_table_path
from tasks.P3_parse_files.table_formats import table_reader_for

pytestmark = pytest.mark.integration

EMAIL_CORPUS = Path("/testdata/enron-kaminski-v")
MIXED_CORPUS = Path("/testdata/hoover-testdata/data")
EXCELS = MIXED_CORPUS / "www.learningcontainer.com/excels"


def _regular_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())


@pytest.mark.skipif(not EMAIL_CORPUS.is_dir(), reason="enron corpus not fetched")
def test_no_email_is_ever_a_table():
    """Zero acceptances. Not a rate, not a threshold: zero."""
    files = _regular_files(EMAIL_CORPUS)
    assert files, f"{EMAIL_CORPUS} is empty"
    hits = [str(p.relative_to(EMAIL_CORPUS)) for p in files if sniff_table_path(str(p))]
    assert not hits, (
        f"the table sniff accepted {len(hits)} of {len(files)} RFC 822 messages, "
        f"first: {hits[:10]}"
    )


@pytest.mark.skipif(not EMAIL_CORPUS.is_dir(), reason="enron corpus not fetched")
def test_the_gate_would_have_stopped_them_anyway():
    """Belt and braces: the sniff refuses these on its own rules, and the gate in
    `detect_mime_by_content` never offers it a file the email sniff accepted."""
    files = _regular_files(EMAIL_CORPUS)[:2000]
    offered = [p for p in files
               if should_check_table(["text/plain"],
                                     is_email=sniff_email_path(str(p)) is not None)]
    assert not offered, f"{len(offered)} messages reached the table sniff"


#: The one file outside the excels folder that genuinely is delimited text: the second
#: copy of the CSV fixture, which is also the dedup case (one content hash, two paths).
#: An exact set rather than a count, so a swap of one false positive for one false
#: negative cannot pass.
EXPECTED_MIXED_HITS = {
    "www.learningcontainer.com/wp-content/uploads/2020/05/sample-csv-file-for-testing.csv",
}


@pytest.mark.skipif(not MIXED_CORPUS.is_dir(), reason="mixed corpus not fetched")
def test_only_the_known_delimited_files_in_the_mixed_corpus():
    """PDFs, zips, images, office documents, HTML, GPG keys and shell scripts, plus one
    real CSV outside the fixture folder."""
    files = [p for p in _regular_files(MIXED_CORPUS) if EXCELS not in p.parents]
    assert files, f"{MIXED_CORPUS} is empty"
    hits = {str(p.relative_to(MIXED_CORPUS)) for p in files if sniff_table_path(str(p))}
    false_positives = sorted(hits - EXPECTED_MIXED_HITS)
    false_negatives = sorted(EXPECTED_MIXED_HITS - hits)
    assert not false_positives, f"the table sniff became eager: {false_positives}"
    assert not false_negatives, f"the table sniff lost known CSVs: {false_negatives}"


@pytest.mark.skipif(not EXCELS.is_dir(), reason="excel fixtures not fetched")
def test_every_table_fixture_is_named_by_its_extension_or_by_the_sniff():
    """Recall, from the other side: the routing condition has to fire on all of them."""
    files = _regular_files(EXCELS)
    assert files, f"{EXCELS} is empty"
    unrouted = [
        str(p.relative_to(EXCELS)) for p in files
        if not table_reader_for([], str(p)) and not sniff_table_path(str(p))
    ]
    assert not unrouted, f"no reader would be chosen for {unrouted}"
