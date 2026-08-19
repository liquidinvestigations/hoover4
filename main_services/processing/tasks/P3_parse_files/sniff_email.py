"""Content sniff that recognises an RFC 822 message no other detector can name.

Every detector in the fan-out answers from bytes or from a name. Neither is enough for a
mail spool: an extension-less file whose content is `Message-ID:` followed by prose is
`text/plain` to libmagic, to Tika and to Magika alike, so a whole maildir indexes as text
and never produces an `emails` row.

The sniff reads the header block at the top of the file and decides. It is strict on
purpose -- an eager version costs precision across every plain-text corpus, and the
measurement below is the thing that keeps it honest.

Measured over the two corpora on this box:

* `enron-kaminski-v` -- 21 291 extension-less RFC 822 messages, 21 291 accepted (100.0%)
* `hoover-testdata/data` -- 991 mixed files (PDF, zip, image, office, HTML, GPG, shell),
  22 accepted, and all 22 are genuinely email: the `eml-*`, `emlx-*`, `mbox` and
  `no-extension/file_eml` fixtures. Zero false positives.

`tests/integration/test_email_sniff_corpus.py` reruns exactly that and fails if either
number moves, which is what stops a future "more robust" rewrite from becoming an eager
one. Three real files forced the corrections a naive port does not have, and each is
named on the constant it justifies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Headers that count towards acceptance, title-cased for comparison.
KNOWN_HEADERS = frozenset({
    "Relay-Version", "Return-Path", "From", "To",
    "Received", "Message-Id", "Date", "In-Reply-To", "Subject",
})

#: A single one of these is enough on its own: nothing but a mail transport writes them.
STRONG_HEADERS = frozenset({"Message-Id", "Received", "Return-Path"})

#: How many known headers the block must carry before the acceptance rule is consulted.
MIN_HEADER_HITS = 2

#: Lines inside the block that are neither a header nor a folded continuation.
#:
#: `enron-kaminski-v/calendar/3.` has a `Subject:` value containing a bare LF, so the
#: next line (`Room`) is unparseable while the message around it is perfectly good mail.
#: Two enron files fail without this tolerance, and it is exactly the "slightly
#: nonstandard or malformed" mail the sniff exists for. Bounded, so a text file that
#: happens to open with one colon does not walk its whole length looking for a second.
MAX_JUNK_LINES = 3

#: Ceiling on the header block. Real `Received:` chains reach a few dozen lines.
MAX_HEADER_LINES = 400

#: How much of the file the sniff reads. Inherited from snoop2.
HEADER_READ_SIZE = 64 * 1024

#: Longest first line still considered an Apple `.emlx` byte count.
EMLX_MAX_PREFIX_BYTES = 24

#: Repetitions of the `From `/`From:`/`Date:`/`Subject:`/blank cycle that make a spool an
#: mbox rather than one message. Inherited from snoop2, which documents that it cannot
#: recognise an mbox holding fewer than three messages.
MBOX_MINIMUM_EMAILS = 3

MIME_RFC822 = "message/rfc822"
MIME_EMLX = "message/x-emlx"
MIME_MBOX = "application/mbox"

#: `DomainKey-Signature:a=rsa-sha1;` -- no whitespace after the colon. RFC 5322 permits
#: zero WSP there, and a `^Name:[ \t]` regex rejects it, taking the four
#: `eml-8-double-encoded` and `eml-2-attachment` fixtures with it.
_HEADER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]{0,60}):")
_CONTINUATION_RE = re.compile(r"^[ \t]")
_MBOX_SEPARATOR_RE = re.compile(r"^From ")

_MBOX_PATTERNS = (r"^From ", r"^From: ", r"^Date: ", r"^Subject: ", r"^$")

#: `eml-bom/with-bom.eml` opens with a UTF-8 BOM before `Delivered-To:`.
_BOMS = (
    b"\xef\xbb\xbf",
    b"\xff\xfe",
    b"\xfe\xff",
)


@dataclass
class EmailSniff:
    """What the sniff concluded about one file."""

    mime_type: str
    #: Bytes to skip before the RFC 822 message starts: BOM plus Apple `.emlx` prefix.
    emlx_prefix_bytes: int = 0
    #: Header names seen in the block, for the metadata tab and for tests.
    headers: list[str] = field(default_factory=list)


def bom_length(data: bytes) -> int:
    """Length of a leading byte-order mark, or 0."""
    for bom in _BOMS:
        if data.startswith(bom):
            return len(bom)
    return 0


def emlx_prefix_length(data: bytes) -> int:
    """Length of an Apple `.emlx` byte-count prefix line, including its newline, or 0.

    Apple Mail writes the message length as a decimal number on its own first line. The
    `email` parser has never heard of it and reads the number as the start of a body, so
    the prefix is stripped before parsing rather than tolerated afterwards.
    """
    head = data[:EMLX_MAX_PREFIX_BYTES + 2]
    newline = head.find(b"\n")
    if newline < 0:
        return 0
    first = head[:newline].strip()
    if not first or len(first) > EMLX_MAX_PREFIX_BYTES:
        return 0
    if not first.isdigit():
        return 0
    return newline + 1


def message_offset(data: bytes) -> int:
    """Where the RFC 822 message actually begins: past the BOM and the emlx prefix."""
    offset = bom_length(data)
    return offset + emlx_prefix_length(data[offset:])


def strip_email_envelope(data: bytes) -> bytes:
    """`data` with the BOM and any Apple `.emlx` byte count removed."""
    return data[message_offset(data):]


def _header_block(text: str) -> tuple[set[str], bool]:
    """Header names found in the block at the top of `text`, and whether it parsed.

    Returns `(names, ok)`. `ok` is False when the junk tolerance was exceeded, which
    means the top of the file is not a header block at all.
    """
    names: set[str] = set()
    junk = 0
    for index, raw_line in enumerate(text.split("\n")):
        if index >= MAX_HEADER_LINES:
            break
        line = raw_line.rstrip("\r")
        if not line:
            break
        if index == 0 and _MBOX_SEPARATOR_RE.match(line):
            continue
        if _CONTINUATION_RE.match(line):
            continue
        match = _HEADER_RE.match(line)
        if match:
            names.add(match.group(1).title())
            continue
        junk += 1
        if junk > MAX_JUNK_LINES:
            return names, False
    return names, True


def looks_like_mbox(text: str) -> bool:
    """snoop2's cycle counter: three complete message cycles make it a spool."""
    emails = 0
    pending = set(_MBOX_PATTERNS)
    for line in text.split("\n"):
        line = line.rstrip("\r")
        for pattern in list(pending):
            if re.match(pattern, line):
                pending.discard(pattern)
                break
        if not pending:
            pending = set(_MBOX_PATTERNS)
            emails += 1
            if emails >= MBOX_MINIMUM_EMAILS:
                return True
    return False


def sniff_email(data: bytes) -> EmailSniff | None:
    """Whether `data` is an email, and which kind. `None` means it is not.

    Acceptance needs at least `MIN_HEADER_HITS` known headers in a real block at the top
    of the file, *and* either one strong header or `From` and `Date` together. The second
    clause is what keeps a Debian control file, an HTTP capture and a YAML front matter
    block out: they all carry two colon-separated names from the known set and none of
    them carries a `Message-Id`.
    """
    offset = message_offset(data)
    body = data[offset:offset + HEADER_READ_SIZE]
    text = body.decode("latin-1")

    names, ok = _header_block(text)
    if not ok:
        return None
    hits = names & KNOWN_HEADERS
    if len(hits) < MIN_HEADER_HITS:
        return None
    if not (hits & STRONG_HEADERS) and not {"From", "Date"} <= hits:
        return None

    if offset and emlx_prefix_length(data[bom_length(data):]):
        mime_type = MIME_EMLX
    elif looks_like_mbox(text):
        mime_type = MIME_MBOX
    else:
        mime_type = MIME_RFC822

    return EmailSniff(
        mime_type=mime_type,
        emlx_prefix_bytes=offset,
        headers=sorted(hits),
    )


def sniff_email_path(file_path: str) -> EmailSniff | None:
    """`sniff_email` over the first `HEADER_READ_SIZE` bytes of a file on disk.

    The mbox test wants the whole file in snoop2, but a spool that needs more than 64 KB
    to show three message cycles is not one this sniff can help with anyway, and reading
    a multi-gigabyte spool to find out is not worth the I/O.
    """
    try:
        with open(file_path, "rb") as handle:
            data = handle.read(HEADER_READ_SIZE + EMLX_MAX_PREFIX_BYTES + 4)
    except OSError:
        return None
    return sniff_email(data)


def should_check_email(mime_types, magic_output: str = "") -> bool:
    """snoop2's cheap gate: only text, only unknown, or only a bare multipart boundary.

    Keeps the sniff off the ~98% of a mixed corpus that no amount of header reading will
    turn into mail.
    """
    types = [t for t in (mime_types or []) if t]
    if not types:
        return True
    if (magic_output or "").startswith("multipart/"):
        return True
    return any(t.startswith("text/") or t == "application/octet-stream" for t in types)
