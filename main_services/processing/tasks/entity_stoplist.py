"""Entity values that are never entities, in one place.

A named-entity model labels whatever it is handed. Some of what the pipeline extracts is
not prose: a mail file's own MIME envelope, an Outlook reply block quoted into a body,
quoted-printable soft breaks, base64 payloads, letter-spaced PDF headings. The model
labels those tokens as confidently as it labels a person, and because a header name
appears in every message of a mail corpus, `Content-Transfer-Encoding` arrives as a MISC
entity on hundreds of thousands of documents and outranks every real entity in the facet.

The rules reject a value on its **shape** wherever a shape exists -- an `X-`-prefixed
header name, a token ending in the quoted-printable soft break `=`, a long case-shuffled
run of base64 characters, four or more single-character tokens (letter-spaced PDF text) --
and fall back to a named set only for things with no shape: the standard mail headers,
the day and month names, a handful of SMTP/MIME protocol words.

**The rules match the whole value, never a substring.** `May` goes; `May Chen` stays.
`Sun` goes; `Sun Microsystems` stays. That is the entire safety argument for dropping
tokens that are also names: as a standalone facet value a bare day or month name filters
nothing a user wants filtered, while every multi-word entity containing one survives.

Applied by the NLP stage before `entity_hit` is written, so every consumer of that table
agrees without doing anything. The website applies the same rules again when it renders
entities (`website/common/src/entity_stoplist.rs`) because rows written before a rule
existed keep their junk until the stage is re-run; the duplication is deliberate and is
the same arrangement as `text_sources.py` / `document_sources.rs`. The two lists are kept
honest by the canonical cases in `tests/unit/test_entity_stoplist.py`, which the Rust
module's own tests mirror value for value.
"""

import re
from typing import Iterable, List

#: Standard mail and MIME header names, plus the four Outlook writes into a quoted reply
#: block (`From:/Sent:/To:/Subject:`), which is why bodies carry them too. Matched against
#: the text before the value's first colon, so `Date: Mon` and `Subject:` go with `Date`.
#: `Organization` is deliberately absent: it is a real word far more often than a header.
MAIL_HEADER_NAMES = frozenset({
    "accept-language",
    "authentication-results",
    "bcc",
    "cc",
    "content-description",
    "content-disposition",
    "content-id",
    "content-language",
    "content-length",
    "content-transfer-encoding",
    "content-type",
    "date",
    "delivered-to",
    "disposition-notification-to",
    "dkim-signature",
    "errors-to",
    "from",
    "importance",
    "in-reply-to",
    "list-id",
    "list-unsubscribe",
    "mail-followup-to",
    "message-id",
    "mime-version",
    "precedence",
    "priority",
    "received",
    "references",
    "reply-to",
    "return-path",
    "sender",
    "sent",
    "subject",
    "thread-index",
    "thread-topic",
    "to",
    "user-agent",
})

#: Protocol words that appear in every `Received:` chain and MIME preamble. Unambiguous:
#: none of them is a plausible search term for a person, place or organisation.
PROTOCOL_TOKENS = frozenset({
    "7bit",
    "8bit",
    "application/octet-stream",
    "base64",
    "boundary",
    "charset",
    "ehlo",
    "esmtp",
    "helo",
    "multipart/alternative",
    "multipart/mixed",
    "quoted-printable",
    "smtp",
    "text/html",
    "text/plain",
})

#: Day and month names with their usual abbreviations. A whole-value match only.
DAY_AND_MONTH_TOKENS = frozenset({
    "mon", "monday", "tue", "tues", "tuesday", "wed", "weds", "wednesday",
    "thu", "thur", "thurs", "thursday", "fri", "friday", "sat", "saturday",
    "sun", "sunday",
    "jan", "january", "feb", "february", "mar", "march", "apr", "april",
    "may", "jun", "june", "jul", "july", "aug", "august",
    "sep", "sept", "september", "oct", "october", "nov", "november",
    "dec", "december",
})

#: Any `X-` extension header, so Enron's private ones (`X-Folder`, `X-Origin`,
#: `X-FileName`, `X-To`, `X-cc`) need no enumeration and neither does the next corpus's.
_X_HEADER_RE = re.compile(r"^x-[a-z0-9]+(?:-[a-z0-9]+)*$")

#: A header key is a single hyphenated word. Anything else before a colon is prose.
_HEADER_KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")

#: base64 and base64url, plus the `.`/`_` that appear in mail-tracking tokens
#: (`X-YMailISG`, DKIM). `@` and `:` are absent on purpose: they keep addresses and URLs
#: out of this rule.
_BLOB_CHARSET_RE = re.compile(r"^[A-Za-z0-9+/._-]+={0,2}$")

#: Below this a case-shuffled run is a plausible identifier a user might paste.
_BLOB_MIN_CHARS = 24

#: An encoded blob shuffles case at random; a run-together name does it once per word.
_BLOB_MIN_CASE_SWITCHES = 4

#: Letter-spaced PDF headings (`F O N T Y S`) arrive as one entity per heading. Real
#: entities do not carry four bare initials with no punctuation.
_MAX_SINGLE_CHAR_TOKENS = 3

#: Beyond this the model has captured a paragraph, not a name.
_MAX_TOKENS = 12
_MAX_CHARS = 200


def _case_switches(value: str) -> int:
    """Adjacent letter pairs whose case differs -- ~1 per word in a name, many in base64."""
    switches = 0
    previous = ""
    for char in value:
        if not char.isalpha():
            previous = ""
            continue
        if previous and previous.isupper() != char.isupper():
            switches += 1
        previous = char
    return switches


def _looks_like_encoded_blob(value: str) -> bool:
    """True for a base64/quoted-printable payload fragment.

    Four conditions together, because each alone has a false positive: no whitespace (a
    name has some), long (short tokens are identifiers people search for), a digit or
    `+`/`/` (a run-together CamelCase company name has neither), and shuffled case (a
    hexadecimal hash or an uppercase acronym does not).
    """
    if any(char.isspace() for char in value):
        return False
    if len(value) < _BLOB_MIN_CHARS:
        return False
    if not _BLOB_CHARSET_RE.match(value):
        return False
    if not any(char.isdigit() or char in "+/" for char in value):
        return False
    return _case_switches(value) >= _BLOB_MIN_CASE_SWITCHES


def is_stopped_entity(value: str) -> bool:
    """True if `value` is extraction debris rather than a named entity."""
    text = (value or "").strip()
    if not text:
        return True
    if len(text) > _MAX_CHARS:
        return True
    if not any(char.isalnum() for char in text):
        return True
    # Markup that survived a text extractor: `<td align`, `FONT SIZE=1>Updated`.
    if "<" in text or ">" in text:
        return True

    # One latin character. A model handed a base64 payload returns its fragments as
    # entities, and most of them are one letter long. Non-ASCII is exempt: a single CJK
    # character is a word, and can be a surname.
    if len(text) == 1 and text.isascii():
        return True

    lowered = text.lower()
    if lowered in DAY_AND_MONTH_TOKENS or lowered in PROTOCOL_TOKENS:
        return True

    header_key = lowered.split(":", 1)[0].strip()
    if _HEADER_KEY_RE.match(header_key) and (
        header_key in MAIL_HEADER_NAMES or _X_HEADER_RE.match(header_key)
    ):
        return True

    tokens = text.split()
    if len(tokens) > _MAX_TOKENS:
        return True
    if sum(1 for token in tokens if len(token) == 1 and token.isalnum()) > _MAX_SINGLE_CHAR_TOKENS:
        return True

    # A quoted-printable soft line break: the `=` is the line continuation, and the model
    # takes the fragment before it (`of=`, `th=`) for a name.
    if not any(char.isspace() for char in text) and text.endswith("="):
        return True

    return _looks_like_encoded_blob(text)


def filter_entity_values(values: Iterable[str]) -> List[str]:
    """Drop stopped values, keeping order and duplicates (a hit count is a count)."""
    return [value for value in values if not is_stopped_entity(value)]
