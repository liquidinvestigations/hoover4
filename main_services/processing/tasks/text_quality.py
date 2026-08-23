"""Is this extracted text *language*, or is it a file's insides spelled out?

Text extraction is deliberately greedy (a parser that skips anything it does not
understand loses real documents), so it also produces text that is not prose in any
language: the base64 body of an email attachment, the pixel rows of an XPM image, an
embedded font table. That text is indistinguishable from a document to every stage after
it. Live, `search_collections("Eiffel Tower height")` returned an `.xpm`'s colour table and
an `.eml`'s base64 as its **top two hits**, because a passage of noise is close to
everything and far from nothing in embedding space.

The cost is three-fold and each part is real: the GPU embeds kilobytes of noise, the
noise then wins vector searches it has no business winning, and the winning snippet is
rendered into a chat transcript a person has to read.

**This is a filter on what gets embedded, not on what gets stored.** `text_content` keeps
every byte the parser produced. That is the evidence, and a heuristic must never be able
to destroy it. What a false positive costs here is that one passage is not semantically
searchable; what a false negative costs is the failure above. The thresholds are set to
make the first much likelier than the second.

Deliberately not statistical: no model, no language ID, no training data. Three cheap
signals that each name a specific corruption, so a chunk that is dropped can be explained
in one sentence rather than attributed to a score.
"""

from __future__ import annotations

import re

#: A run of the base64/hex alphabet with no break in it. Real prose does not produce
#: 60-character unbroken alphanumeric tokens; encoded bytes produce almost nothing else.
#: (Base64 MIME bodies wrap at 76.)
_ENCODED_RUN = re.compile(r"[A-Za-z0-9+/=_-]{60,}")

#: Fraction of a text's non-space characters that may sit inside such runs before the text
#: is called encoded data rather than a document that quotes a hash or a long URL.
MAX_ENCODED_FRACTION = 0.30

#: Fraction of whitespace-separated tokens that may be a single character. Pixel-art rows
#: (`. 5 6 c 0 @ . . X O O #`) and character-per-pixel maps are almost entirely these;
#: prose in every language this pipeline sees is not, even Chinese. CJK arrives without
#: spaces, so it reads as *few, long* tokens, never many one-character ones.
MAX_SINGLE_CHAR_TOKEN_FRACTION = 0.55

#: Below this share of letters among non-space characters, a text is punctuation, digits
#: and symbols. Kept low on purpose: numeric tables, price lists and reference indices are
#: legitimate documents, and this must not reach them.
MIN_LETTER_FRACTION = 0.20

#: A token that is a number in some notation (`0xFB`, `#0C0B01`, `1,234.56`, `42;`) with
#: whatever punctuation the surrounding format wraps it in. Hex digits are letters, so an
#: XBM bitmap (`0xFB, 0xFF, 0xBF, …`) passes the letter test with 67 % "letters" while
#: being a raw byte dump; it is the shape of the tokens that gives it away, not their
#: alphabet.
_NUMERIC_TOKEN = re.compile(
    r"^[^0-9A-Za-z]*(0[xX])?[0-9A-Fa-f]+([^0-9A-Za-z]+[0-9A-Fa-f]+)*[^0-9A-Za-z]*$"
)

#: Fraction of tokens that may be numeric literals. English words built only from hex
#: letters exist ("faced", "beadle"), so this needs to be high enough that prose about
#: cafes cannot reach it, and it only applies once there are enough tokens to have a
#: distribution at all.
MAX_NUMERIC_TOKEN_FRACTION = 0.80
MIN_TOKENS_FOR_NUMERIC_RULE = 30

#: Texts shorter than this are not judged. A short line has no distribution to measure and
#: a heading like "3.1 A" would trip every rule above.
MIN_LENGTH_TO_JUDGE = 120


def non_linguistic_reason(text: str) -> str | None:
    """Why `text` is not language, or `None` if it looks like a document.

    The reason is returned rather than a bare bool so a caller can log *which* rule fired.
    A dropped chunk that cannot be explained is a dropped chunk nobody will trust.
    """
    if not text or len(text) < MIN_LENGTH_TO_JUDGE:
        return None

    non_space = [c for c in text if not c.isspace()]
    if not non_space:
        return None
    total = len(non_space)

    encoded = sum(len(m.group()) for m in _ENCODED_RUN.finditer(text))
    if encoded / total > MAX_ENCODED_FRACTION:
        return f"{encoded / total:.0%} of it is unbroken encoded runs (base64/hex)"

    tokens = text.split()
    if tokens:
        singles = sum(1 for t in tokens if len(t) == 1)
        if singles / len(tokens) > MAX_SINGLE_CHAR_TOKEN_FRACTION:
            return f"{singles / len(tokens):.0%} of its tokens are single characters"

        if len(tokens) >= MIN_TOKENS_FOR_NUMERIC_RULE:
            numeric = sum(1 for t in tokens if _NUMERIC_TOKEN.match(t))
            if numeric / len(tokens) > MAX_NUMERIC_TOKEN_FRACTION:
                return f"{numeric / len(tokens):.0%} of its tokens are numeric literals"

    letters = sum(1 for c in non_space if c.isalpha())
    if letters / total < MIN_LETTER_FRACTION:
        return f"only {letters / total:.0%} of its characters are letters"

    return None


def is_linguistic(text: str) -> bool:
    """`True` when `text` is worth embedding and indexing as language."""
    return non_linguistic_reason(text) is None
