"""Content sniff that recognises delimited text no other detector can name.

A `.csv` on disk is named by the filename detector and never reaches this code. What
reaches it is the extension-less or `.txt`-named export: a database dump, a mail-merge
source, a bank statement someone saved without a suffix. To `file`, to Tika and to Magika
all of those are `text/plain`, so without a sniff they index as prose and no grid is ever
built for them.

Why this sniff is so much stricter than it could be
---------------------------------------------------
The cost of a false negative is one file that stays text. The cost of a false positive is
a corpus of mail turning into a corpus of two-column tables: every RFC 822 message is
hundreds of consistent `Name: value` lines, which a colon-accepting delimiter sniff reads
as a perfectly rectangular CSV. Measured on `enron-kaminski-v` (21 291 messages) with
`:` among the candidates, essentially every message is accepted. `:` is therefore
excluded permanently — it is not a tuning parameter — and a space is excluded with it,
because prose is full of spaces and nothing exports space-delimited data.

Measured over the corpora on this box with the rules below:

* `enron-kaminski-v` -- 21 291 RFC 822 messages, 0 accepted.
* `hoover-testdata/data` minus the known table fixtures -- 0 accepted.

`tests/integration/test_table_sniff_corpus.py` reruns exactly that and fails if either
number moves, which is what stops a future "more robust" rewrite from becoming an eager
one.

The rules, and what each one is for
-----------------------------------
Every relaxation of these is a false positive against prose, so each carries its reason:

* the email sniff runs first and this one is never offered a message it accepted;
* `MIN_SNIFF_LINES` complete lines, because four lines of anything can be rectangular by
  accident;
* the field count **exactly constant** across every sampled line -- not modal, not within
  one. A real export is rectangular; prose that happens to average three commas a line is
  not;
* the delimiter present in **every** sampled line, which is the same requirement stated
  from the other side and catches the case where `csv.reader` merges quoted lines;
* at least `MIN_DELIMITED_COLUMNS` fields, so a single-column list stays text.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from tasks.P3_parse_files.table_formats import MIN_DELIMITED_COLUMNS

#: The only delimiters ever considered.
#:
#: `:` is absent permanently and deliberately: with it in the candidate set, an RFC 822
#: header block is a rectangular two-column table and all 21 291 messages of
#: `enron-kaminski-v` are accepted as CSV. A space is absent for the same reason applied
#: to prose. Nothing exports data delimited by either.
CANDIDATE_DELIMITERS = (",", "\t", ";", "|")

#: Complete lines the sample must contain before acceptance is even considered. A short
#: file that happens to be rectangular is the commonest accidental table there is.
MIN_SNIFF_LINES = 5

#: How much of the file the sniff reads. A file whose first quarter-megabyte is not
#: rectangular is not one this sniff can help with.
SNIFF_READ_SIZE = 256 * 1024

#: Lines the rectangularity test looks at. Bounded so a 256 KB sample of very short lines
#: does not cost a `csv.reader` pass over tens of thousands of rows.
MAX_SNIFF_LINES = 200

MIME_CSV = "text/csv"
MIME_TSV = "text/tab-separated-values"

_DELIMITER_MIMES = {
    ",": MIME_CSV,
    ";": MIME_CSV,
    "|": MIME_CSV,
    "\t": MIME_TSV,
}


@dataclass
class TableSniff:
    """What the sniff concluded about one file."""

    mime_type: str
    #: The delimiter that produced the rectangle, so the reader does not sniff twice.
    delimiter: str
    #: Fields per line, constant by construction.
    field_count: int
    #: Complete lines examined.
    line_count: int


def _sample_lines(text: str) -> list[str]:
    """Complete lines of the sample, with the trailing partial line dropped.

    The last line of a truncated read is almost always cut mid-field, and a cut line is
    the one thing guaranteed to have the wrong field count.
    """
    lines = text.split("\n")
    if lines:
        lines = lines[:-1]
    return [line.rstrip("\r") for line in lines[:MAX_SNIFF_LINES]]


def _rectangular(lines: list[str], delimiter: str) -> int:
    """Fields per line if every line has the same count and contains the delimiter, else 0.

    Parsed with `csv.reader` rather than `str.split` so a quoted field containing the
    delimiter counts as one field, which is the difference between accepting a real
    export and rejecting it.
    """
    if not all(delimiter in line for line in lines):
        return 0
    try:
        rows = list(csv.reader(io.StringIO("\n".join(lines)), delimiter=delimiter))
    except csv.Error:
        return 0
    # A quoted field spanning a newline makes `csv.reader` emit fewer rows than there
    # were lines. That is legal CSV, but it is also what a stray quote in prose looks
    # like, and this sniff refuses to guess between the two.
    if len(rows) != len(lines):
        return 0
    counts = {len(row) for row in rows}
    if len(counts) != 1:
        return 0
    count = counts.pop()
    return count if count >= MIN_DELIMITED_COLUMNS else 0


def sniff_table(data: bytes) -> TableSniff | None:
    """Whether `data` is delimited text, and which kind. `None` means it is not.

    Ties between two qualifying delimiters go to the one that yields the most fields: a
    semicolon-delimited European CSV whose decimal commas also parse as a two-field
    comma table is a semicolon table.
    """
    text = data[:SNIFF_READ_SIZE].decode("latin-1")
    lines = _sample_lines(text)
    if len(lines) < MIN_SNIFF_LINES:
        return None
    if any(not line.strip() for line in lines):
        # A blank line inside the sample is a paragraph break, not an empty record.
        return None

    best: tuple[int, str] | None = None
    for delimiter in CANDIDATE_DELIMITERS:
        fields = _rectangular(lines, delimiter)
        if fields and (best is None or fields > best[0]):
            best = (fields, delimiter)
    if best is None:
        return None

    fields, delimiter = best
    return TableSniff(
        mime_type=_DELIMITER_MIMES[delimiter],
        delimiter=delimiter,
        field_count=fields,
        line_count=len(lines),
    )


def sniff_table_path(file_path: str) -> TableSniff | None:
    """`sniff_table` over the first `SNIFF_READ_SIZE` bytes of a file on disk."""
    try:
        with open(file_path, "rb") as handle:
            data = handle.read(SNIFF_READ_SIZE)
    except OSError:
        return None
    if b"\x00" in data[:4096]:
        # A NUL in the first pages means binary. Decoding it as latin-1 would succeed and
        # a compressed stream is rectangular often enough to matter.
        return None
    return sniff_table(data)


def should_check_table(mime_types, is_email: bool = False) -> bool:
    """The cheap gate: only text or unknown bytes, and never something already email.

    An RFC 822 message is never offered to the table sniff. That is the single most
    important line in this module: the email sniff runs first in `detect_mime_by_content`
    and its answer suppresses this one.
    """
    if is_email:
        return False
    types = [t for t in (mime_types or []) if t]
    if not types:
        return True
    return any(t.startswith("text/") or t == "application/octet-stream" for t in types)
