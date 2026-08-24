"""The corpus-wide precision and recall of the email content sniff.

The sniff is the one detector in the fan-out with no ground truth in the bytes it reads:
it decides from a heuristic, so the only thing that can hold it honest is a measurement
over real corpora. This is that measurement, kept as a test rather than as a script,
because the failure it guards against is a future edit that widens the match, quietly turns
a strict sniff into an eager one, and reclassifies a corpus of plain text as mail.

Both corpora are gitignored and are bind-mounted into the worker at `/testdata`. The test
skips when they are absent, so a checkout that has not fetched them still has a green
suite.
"""

from pathlib import Path

import pytest

from tasks.P3_parse_files.sniff_email import sniff_email_path

pytestmark = pytest.mark.integration

EMAIL_CORPUS = Path("/testdata/enron-kaminski-v")
MIXED_CORPUS = Path("/testdata/hoover-testdata/data")

#: Every file in the enron maildir is a complete RFC 822 message, so recall is the whole
#: story there. 99.9% of 21 291 leaves room for 21 files.
MIN_EMAIL_RECALL = 0.999

#: The mixed corpus holds PDFs, zips, images, office documents, HTML, GPG keys and shell
#: scripts alongside its mail fixtures. Exactly 22 of its 991 files are email, and the
#: sniff must find those 22 and nothing else. An exact set, not a count, so a swap of
#: one false positive for one false negative cannot pass.
EXPECTED_MIXED_HITS = {
    "eml-1-promotional/Introducing Mapbox Android Services - Mapbox Team <newsletter@mapbox.com> - 2016-04-20 1603.eml",
    "eml-1-promotional/Machine Learning comes to CodinGame! - CodinGame Team <contact@codingame.com> - 2016-04-22 1731.eml",
    "eml-1-promotional/New on CodinGame: Check it out! - CodinGame <coders@codingame.com> - 2016-04-21 1034.eml",
    "eml-10-broken-header/broken-subject.eml",
    "eml-2-attachment/FW: Invitation Fontys Open Day 2nd of February 2014 - Campus Venlo <campusvenlo@fontys.nl> - 2013-12-16 1700.eml",
    "eml-2-attachment/Fwd: The American College of Thessaloniki - Greece - Tarek Kouatly <tarek@act.edu> - 2013-11-11 1622.eml",
    "eml-2-attachment/Urăsc canicula, e nașpa.eml",
    "eml-2-attachment/attachments-have-octet-stream-content-type.eml",
    "eml-2-attachment/message-without-subject.eml",
    "eml-3-uppercaseheaders/Fwd: The American College of Thessaloniki - Greece - Tarek Kouatly <tarek@act.edu> - 2013-11-11 1622.eml",
    "eml-5-long-names/Attachments have long file names..eml",
    "eml-8-double-encoded/double-encoding.eml",
    "eml-8-double-encoded/simple-encoding.eml",
    "eml-9-pgp/encrypted-hushmail-knockoff.eml",
    "eml-9-pgp/encrypted-hushmail-smashed-bytes.eml",
    "eml-9-pgp/encrypted-machine-learning-comes.eml",
    "eml-bom/with-bom.eml",
    "emlx-4-missing-part/1498.partial.emlx",
    "lists.mbox/F2D0D67E-7B19-4C30-B2E9-B58FE4789D51/Data/1/Messages/1498.partial.emlx",
    "mbox/2018-March.txt",
    "mbox/shapelib.mbox",
    "no-extension/file_eml",
}


def _regular_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink())


@pytest.mark.skipif(not EMAIL_CORPUS.is_dir(), reason="enron corpus not fetched")
def test_recall_on_an_all_email_corpus():
    files = _regular_files(EMAIL_CORPUS)
    assert files, f"{EMAIL_CORPUS} is empty"
    hits = [p for p in files if sniff_email_path(str(p))]
    recall = len(hits) / len(files)
    misses = [str(p.relative_to(EMAIL_CORPUS)) for p in files if p not in set(hits)]
    assert recall >= MIN_EMAIL_RECALL, (
        f"recall {recall:.4%} over {len(files)} files, first misses: {misses[:10]}"
    )


@pytest.mark.skipif(not MIXED_CORPUS.is_dir(), reason="mixed corpus not fetched")
def test_exactly_the_known_emails_in_the_mixed_corpus():
    files = _regular_files(MIXED_CORPUS)
    assert files, f"{MIXED_CORPUS} is empty"
    hits = {
        str(p.relative_to(MIXED_CORPUS))
        for p in files
        if sniff_email_path(str(p))
    }
    false_positives = sorted(hits - EXPECTED_MIXED_HITS)
    false_negatives = sorted(EXPECTED_MIXED_HITS - hits)
    assert not false_positives, f"sniff became eager: {false_positives}"
    assert not false_negatives, f"sniff lost known emails: {false_negatives}"
