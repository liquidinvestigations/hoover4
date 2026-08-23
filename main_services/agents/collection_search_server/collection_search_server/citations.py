"""Citation handles, and the quote check behind them.

A citation is the agent's own claim that one document supports one point. It is not the
same object as a search hit: a search returns everything that matched, a citation is what
the agent decided mattered, and rendering the first as if it were the second is what
turns an answer into a pile of links.

Two properties this module exists for.

**The quote is verified.** The server checks that the quoted span actually occurs in the
document's extracted text before handing back a handle. A quote that does not verify is
returned flagged rather than refused: a model that stops citing is a worse outcome than a
citation carrying a visible "unverified quote" marker, and the marker is a fact the
reader can act on.

**Handles are allocated per SESSION, not per turn.** `[D7]` from the first turn has to
still resolve in the ninth, because the answer that used it is still on screen and the
reader can still click it. Per-turn numbering is cheaper and renumbers the reader's
evidence underneath them.
"""

from __future__ import annotations

import re
import threading
import unicodedata

#: Chat sessions whose handle tables are kept in memory at once.
#:
#: Bounded because this is a process that serves every conversation on the site. Eviction
#: is oldest-first and whole-session: a session that falls out gets fresh numbering rather
#: than a table with holes in it, which is the failure mode worth avoiding: `[D3]`
#: meaning two different documents inside one conversation is worse than `[D1]` starting
#: over.
MAX_SESSIONS = 512

#: Handles one session may allocate. Past this the tool still verifies and still returns
#: the document, without a handle, and says so.
MAX_HANDLES_PER_SESSION = 200

#: A quote shorter than this cannot be checked usefully ("the" occurs in everything), so
#: it is treated as unverifiable rather than as verified.
MIN_QUOTE_CHARS = 12


def normalise_for_match(text: str) -> str:
    """Fold the differences that a quote legitimately survives.

    Extracted text is not the document: a PDF wraps lines mid-sentence, a mail parser
    keeps `\\r\\n`, and every extractor has its own opinion about non-breaking spaces and
    typographic quotes. A model quoting a sentence it read will reproduce the words and
    not the whitespace, so an exact-substring test rejects nearly every honest quote.

    Case is folded too. A quote is evidence about content, and a reader shown `Board`
    where the document says `BOARD` has not been misled.
    """
    text = unicodedata.normalize("NFKC", text)
    # Typographic quotes and dashes, which extractors substitute in both directions.
    for fancy, plain in (
        ("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'),
        ("–", "-"), ("—", "-"), (" ", " "),
    ):
        text = text.replace(fancy, plain)
    return re.sub(r"\s+", " ", text).strip().lower()


def quote_occurs_in(quote: str, document_text: str) -> bool:
    """Whether a quote is present in the document, after whitespace and case folding."""
    needle = normalise_for_match(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return False
    return needle in normalise_for_match(document_text)


class HandleTable:
    """Per-session `[Dn]` allocation, stable for the life of the conversation.

    The same document cited twice keeps its first handle. That is why the handle is
    allocated per session rather than per call: two paragraphs of one answer citing the
    same file must point at one card.
    """

    def __init__(self, max_sessions: int = MAX_SESSIONS) -> None:
        self._lock = threading.Lock()
        self._max_sessions = max_sessions
        # Insertion-ordered, so the oldest session is the first key.
        self._sessions: dict[str, dict[tuple[str, str], str]] = {}

    def handle_for(self, session_id: str, collectionname: str, file_hash: str) -> str:
        """The handle for one document in one session, allocating if it is new.

        Returns an empty string once the session's budget is spent, which the caller
        reports rather than hiding: a citation with no handle is still a citation, and
        silently reusing `[D200]` for a different document would corrupt the ones already
        on screen.
        """
        key = (collectionname, file_hash)
        with self._lock:
            table = self._sessions.get(session_id)
            if table is None:
                if len(self._sessions) >= self._max_sessions:
                    oldest = next(iter(self._sessions))
                    del self._sessions[oldest]
                table = {}
                self._sessions[session_id] = table
            existing = table.get(key)
            if existing:
                return existing
            if len(table) >= MAX_HANDLES_PER_SESSION:
                return ""
            handle = f"[D{len(table) + 1}]"
            table[key] = handle
            return handle

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)
