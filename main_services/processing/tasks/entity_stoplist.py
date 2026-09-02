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

Two rules are positional rather than whole-value, and they are the exception that proves
the rule: a value made entirely of single characters is letter-spaced text (`U I`), and a
value whose LAST token is a reply-block header keyword is the name above that header
(`Eric Cc`). Both are anchored to a position precisely so they cannot fire on a keyword
sitting in the middle of a real name, and the second one asks for the header's colon as
well whenever the keyword is also an ordinary English word (`Blind Date` stays, `Sara
Shackleton To:` goes).

Applied by the NLP stage before `entity_hit` is written, so every consumer of that table
agrees without doing anything. The website applies the same rules again when it renders
entities (`website/common/src/entity_stoplist.rs`) because rows written before a rule
existed keep their junk until the stage is re-run; the duplication is deliberate and is
the same arrangement as `text_sources.py` / `document_sources.rs`. The two lists are kept
accurate by the canonical cases in `tests/unit/test_entity_stoplist.py`, which the Rust
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
#:
#: Lowering the threshold breaks on `J F Kennedy`, which carries two and is a name. What
#: separates the two is that letter-spacing leaves NOTHING but single characters, so a
#: value whose every token is one character long is stopped whatever the count -- which
#: takes `U I` and `∆ Y` without touching a value that has a real word in it.
_MAX_SINGLE_CHAR_TOKENS = 3

#: The header keywords a mail reply block prints, as they appear glued to the end of the
#: name above them: `Peter Aldhous Subject`, `Eric Cc`, `Larry Sent`. Matched only in
#: a NON-INITIAL position, and only as the last token or with the header's colon still
#: attached, because that is what distinguishes debris from prose: `Subject Matter
#: Experts` starts with one, `Mission To Mars` has one in the middle, and both are kept.
_REPLY_BLOCK_HEADERS = frozenset({"bcc", "cc", "from", "sent", "subject"})

#: `Date` and `To` are reply-block headers too, but unlike the five above they are also
#: ordinary English words that end real names: `Blind Date`, `Save The Date`, `Tokyo To`.
#: A bare trailing one is therefore not evidence of anything, and they count only with the
#: header's colon still attached (`Sara Shackleton To:`). The colon is what makes the
#: value a header line rather than a phrase, so nothing a user would search for is lost --
#: the whole-value header rule still takes `To: Vince J Kaminski` and `Date: Mon`, and the
#: `X-` rule still takes `X-To`.
_COLON_ONLY_REPLY_BLOCK_HEADERS = frozenset({"date", "to"})

#: The separator Outlook puts above a quoted message. Never part of a name.
_ORIGINAL_MESSAGE_MARKER = "-----original message-----"

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


def _ends_in_a_header_keyword(tokens: List[str]) -> bool:
    """True for `<name> Subject`, `<name> Cc`, `<name> Sent: Monday`, `<name> To:`.

    A mail body's reply block puts the header keyword on the line under the name, and the
    model returns the pair as one entity. The whole-value rules never see it because the
    value is not the keyword, it merely ends with it.

    Deliberately narrow, on two axes. By POSITION: matching a header keyword anywhere in a
    value would take `Mission To Mars` with it, so the first token is exempt entirely
    (`Subject Matter Experts` survives) and only the last token or a colon-carrying one
    counts. By KEYWORD: a bare trailing `Date` or `To` is ordinary English and is left
    alone, so those two count only with the colon attached.
    """
    if len(tokens) < 2:
        return False
    for index, token in enumerate(tokens[1:], start=1):
        keyword = token.rstrip(":").lower()
        carries_colon = token.endswith(":")
        if carries_colon and (
            keyword in _REPLY_BLOCK_HEADERS or keyword in _COLON_ONLY_REPLY_BLOCK_HEADERS
        ):
            return True
        if index == len(tokens) - 1 and keyword in _REPLY_BLOCK_HEADERS:
            return True
    return False


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

    if _ORIGINAL_MESSAGE_MARKER in lowered:
        return True

    tokens = text.split()
    if len(tokens) > _MAX_TOKENS:
        return True
    if sum(1 for token in tokens if len(token) == 1 and token.isalnum()) > _MAX_SINGLE_CHAR_TOKENS:
        return True
    # Letter-spaced text with too few tokens to trip the count above: `U I`, `∆ Y`.
    if len(tokens) > 1 and all(len(token) == 1 for token in tokens):
        return True
    if _ends_in_a_header_keyword(tokens):
        return True

    # A quoted-printable soft line break: the `=` is the line continuation, and the model
    # takes the fragment before it (`of=`, `th=`) for a name.
    if not any(char.isspace() for char in text) and text.endswith("="):
        return True

    return _looks_like_encoded_blob(text)


def filter_entity_values(values: Iterable[str]) -> List[str]:
    """Drop stopped values, keeping order and duplicates (a hit count is a count)."""
    return [value for value in values if not is_stopped_entity(value)]
