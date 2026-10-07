"""Citation handles, and the quote check behind them.

A citation is the agent's own claim that one document supports one point. It is not the
same object as a search hit: a search returns everything that matched, a citation is what
the agent decided mattered, and rendering the first as if it were the second is what
turns an answer into a pile of links.

Two properties this module exists for.

**The quote is verified.** The server checks that the quoted span actually occurs in the
document's extracted pages before handing back a handle. Verification reads every page
in bounded batches and is independent of the excerpt the model is shown. A quote that
does not verify is returned flagged rather than refused: a model that stops citing is a
worse outcome than a citation carrying a visible "unverified quote" marker, and the
marker is a fact the reader can act on.

**Handles are allocated per SESSION, not per turn.** `[D7]` from the first turn has to
still resolve in the ninth, because the answer that used it is still on screen and the
reader can still click it. Per-turn numbering is cheaper and renumbers the reader's
evidence underneath them.

**Handles survive a restart.** `HandleTable` stores each new handle through its
`BindingStore` before it returns it, and loads the stored handles of a session before its
first new handle. The server's store (`binding_store.py`) also reads the handles of the
committed `cite_documents` results of the session, so a handle from before the store
stays reserved. One process allocates, and its session lock orders the allocations.

**A quote that does not verify gets a candidate.** `candidate_passage` returns an exact
passage of the extracted text near the quote, with its source and span, beside the
unverified citation. The citation keeps the quote it was given.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass, field

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

#: Join between extracted pages. `_read_document_text` concatenates with this, and
#: verification must use the same join so a quote that crosses a page still matches.
PAGE_JOIN = "\n\n"

#: `quote_reason` values on a citation result. Empty means verified, or a stored
#: message that never recorded a reason. These strings are also read by the website.
QUOTE_MATCH_VERIFIED = "verified"
QUOTE_REASON_SHORT = "short"
QUOTE_REASON_ABSENT = "absent"
QUOTE_REASON_LOOKUP_FAILED = "lookup_failed"

# Typographic quotes and dashes, which extractors substitute in both directions.
_PUNCTUATION_FOLDS = (
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2013", "-"),
    ("\u2014", "-"),
    ("\u00a0", " "),
)


def _fold_for_match(text: str) -> str:
    """NFKC, typographic punctuation, and case. Whitespace is left for the caller."""
    text = unicodedata.normalize("NFKC", text)
    for fancy, plain in _PUNCTUATION_FOLDS:
        text = text.replace(fancy, plain)
    return text.lower()


def normalise_for_match(text: str) -> str:
    """Fold the differences that a quote legitimately survives.

    Extracted text is not the document: a PDF wraps lines mid-sentence, a mail parser
    keeps `\\r\\n`, and every extractor has its own opinion about non-breaking spaces and
    typographic quotes. A model quoting a sentence it read will reproduce the words and
    not the whitespace, so an exact-substring test rejects nearly every accurate quote.

    Case is folded too. A quote is evidence about content, and a reader shown `Board`
    where the document says `BOARD` has not been misled.
    """
    return re.sub(r"\s+", " ", _fold_for_match(text)).strip()


def quote_occurs_in(quote: str, document_text: str) -> bool:
    """Whether a quote is present in the document, after whitespace and case folding."""
    return quote_match_in_pages(quote, [document_text]) == QUOTE_MATCH_VERIFIED


def find_in_quote(find: str, quote: str) -> bool:
    """Whether a find phrase is part of its quote, after the quote's folding.

    The quote has a separate verification minimum. A find phrase selects text inside
    that quote and can contain any nonempty substring, including a short table value.
    """
    needle = normalise_for_match(find)
    return bool(needle) and needle in normalise_for_match(quote)


def phrase_query(text: str) -> str:
    """A document find query that matches `text` as one phrase, or "" for empty text.

    Double quotes inside the text become spaces, because the find query uses them to
    mark the phrase.
    """
    words = " ".join(text.replace('"', " ").split())
    return f'"{words}"' if words else ""


def citation_find_query(find: str, quote: str) -> str:
    """The find query of one citation card: the find phrase when it checks, else the quote."""
    if find.strip() and find_in_quote(find, quote):
        return phrase_query(find)
    return phrase_query(quote)


def quote_match_in_pages(quote: str, pages) -> str:
    """Match a quote against extracted pages joined the same way as a full-document read.

    Pages are the `text_content` rows in `extracted_by, page_id` order. They are joined
    with `PAGE_JOIN` and then folded the same way as `normalise_for_match`. The scan
    keeps only a window of folded text as long as the quote, so a document longer than
    the model-facing excerpt still verifies, including a match that crosses a page.
    """
    needle = normalise_for_match(quote)
    if len(needle) < MIN_QUOTE_CHARS:
        return QUOTE_REASON_SHORT
    window = _FoldedWindow(needle)
    first = True
    for page in pages:
        if not first:
            if window.feed(PAGE_JOIN):
                return QUOTE_MATCH_VERIFIED
        first = False
        if window.feed(page or ""):
            return QUOTE_MATCH_VERIFIED
    return QUOTE_REASON_ABSENT


class _FoldedWindow:
    """A streaming fold of extracted text that can match without holding the document."""

    def __init__(self, needle: str) -> None:
        self._needle = needle
        self._keep = max(len(needle) - 1, 0)
        self._tail = ""
        self._started = False
        self._pending_space = False

    def feed(self, raw: str) -> bool:
        folded = _fold_for_match(raw)
        out: list[str] = []
        for char in folded:
            if char.isspace():
                if self._started:
                    self._pending_space = True
                continue
            if self._pending_space:
                out.append(" ")
                self._pending_space = False
            out.append(char)
            self._started = True
        if not out:
            return False
        chunk = "".join(out)
        haystack = self._tail + chunk
        if self._needle in haystack:
            return True
        if self._keep == 0:
            self._tail = ""
            return False
        self._tail = haystack[-self._keep:] if len(haystack) >= self._keep else haystack
        return False


class CitationNotStored(RuntimeError):
    """A new handle was not stored. The caller returns a citation error and no handle."""


@dataclass
class LoadedBindings:
    """The committed handles of one session, as `BindingStore.load` finds them.

    `bindings` maps a document `(collectionname, file_hash)` to its handle. `reserved`
    holds the number of every handle that a committed result used, conflicting ones
    included, so a new handle never takes one. `conflicts` lists each handle that committed
    results give for more than one document, and each document that they give more than
    one handle. No document is bound to a handle of `conflicts` from the legacy results.
    """

    bindings: dict[tuple[str, str], str] = field(default_factory=dict)
    reserved: set[int] = field(default_factory=set)
    conflicts: list[dict] = field(default_factory=list)


class BindingStore:
    """The durable handles of the sessions. The default keeps nothing, so a table with this
    store numbers each session from `[D1]` in each process."""

    def load(self, owner: str, session_id: str) -> LoadedBindings:
        return LoadedBindings()

    def persist(self, owner: str, session_id: str, collectionname: str, file_hash: str,
                handle: str) -> None:
        return None


def handle_number(handle: str) -> int:
    """The number of a `[Dn]` handle, or 0 for another text."""
    match = re.fullmatch(r"\[D(\d+)\]", handle or "")
    return int(match.group(1)) if match else 0


def merge_legacy(persisted: dict[tuple[str, str], str],
                 legacy: list[tuple[str, tuple[str, str]]],
                 reserved_only: set[int] = frozenset()) -> LoadedBindings:
    """The bindings of a session from its stored bindings and the handles of its committed
    `cite_documents` results.

    `persisted` holds the stored bindings, which win. `legacy` holds `(handle, document)`
    pairs from the committed results. A legacy handle that gives one document, for a document
    that has one handle, is bound. Every other legacy handle is reserved and listed in
    `conflicts`. `reserved_only` holds the numbers of handles whose document is not known.
    """
    out = LoadedBindings(bindings=dict(persisted),
                         reserved={handle_number(h) for h in persisted.values()}
                         | set(reserved_only))
    by_handle: dict[str, set[tuple[str, str]]] = {}
    by_document: dict[tuple[str, str], set[str]] = {}
    for handle, document in legacy:
        if not handle_number(handle):
            continue
        by_handle.setdefault(handle, set()).add(document)
        by_document.setdefault(document, set()).add(handle)
        out.reserved.add(handle_number(handle))
    bound = {handle: document for document, handle in persisted.items()}
    for handle, documents in sorted(by_handle.items()):
        if len(documents) > 1:
            out.conflicts.append({"handle": handle, "documents": sorted(documents)})
            continue
        document = next(iter(documents))
        if handle in bound and bound[handle] != document:
            out.conflicts.append({"handle": handle,
                                  "documents": sorted({document, bound[handle]})})
            continue
        if len(by_document[document]) > 1:
            continue
        out.bindings.setdefault(document, handle)
    for document, handles in sorted(by_document.items()):
        if len(handles) > 1:
            out.conflicts.append({"document": list(document), "handles": sorted(handles)})
    return out


@dataclass
class _Session:
    bindings: dict[tuple[str, str], str]
    next_number: int
    conflicts: list[dict]


class HandleTable:
    """Per-session `[Dn]` allocation, stable for the life of the conversation.

    The same document cited twice keeps its first handle. That is why the handle is
    allocated per session rather than per call: two paragraphs of one answer citing the
    same file must point at one card.

    The table is a cache of the `store`. The first use of a session in a process loads its
    committed handles. A new handle takes the number after the highest reserved number, is
    stored, and only then is returned. The session lock covers the load, the choice, the
    store and the cache update. A store that fails drops the session from the cache, so the
    next call loads again and finds a handle that the failed call did store. Handles are
    keyed by owner and session.
    """

    def __init__(self, max_sessions: int = MAX_SESSIONS,
                 store: BindingStore | None = None) -> None:
        self._lock = threading.Lock()
        self._max_sessions = max_sessions
        self._store = store or BindingStore()
        # Insertion-ordered, so the oldest session is the first key.
        self._sessions: dict[tuple[str, str], _Session] = {}
        self._session_locks: dict[tuple[str, str], threading.Lock] = {}

    def _session_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self._lock:
            lock = self._session_locks.get(key)
            if lock is None:
                lock = self._session_locks[key] = threading.Lock()
            return lock

    def _loaded(self, key: tuple[str, str]) -> _Session:
        with self._lock:
            state = self._sessions.get(key)
        if state is not None:
            return state
        loaded = self._store.load(*key)
        state = _Session(dict(loaded.bindings), max(loaded.reserved, default=0) + 1,
                         list(loaded.conflicts))
        with self._lock:
            if len(self._sessions) >= self._max_sessions:
                oldest = next(iter(self._sessions))
                del self._sessions[oldest]
            self._sessions[key] = state
        return state

    def _forget(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._sessions.pop(key, None)

    def handle_for(self, session_id: str, collectionname: str, file_hash: str,
                   owner: str = "") -> str:
        """The handle for one document in one session, allocating if it is new.

        Returns an empty string once the session's budget is spent, which the caller
        reports rather than hiding: a citation with no handle is still a citation, and
        silently reusing `[D200]` for a different document would corrupt the ones already
        on screen. Raises `CitationNotStored` when a new handle was not stored.
        """
        key = (owner, session_id)
        document = (collectionname, file_hash)
        with self._session_lock(key):
            state = self._loaded(key)
            existing = state.bindings.get(document)
            if existing:
                return existing
            if state.next_number > MAX_HANDLES_PER_SESSION:
                return ""
            handle = f"[D{state.next_number}]"
            try:
                self._store.persist(owner, session_id, collectionname, file_hash, handle)
            except Exception as exc:  # noqa: BLE001 - an unstored handle is never returned
                self._forget(key)
                raise CitationNotStored(f"the handle was not stored: {exc}") from exc
            state.bindings[document] = handle
            state.next_number += 1
            return handle

    def conflicts(self, session_id: str, owner: str = "") -> list[dict]:
        """The conflicts that the load of a session found, or empty when it is not loaded."""
        with self._lock:
            state = self._sessions.get((owner, session_id))
        return list(state.conflicts) if state else []

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)


# ------------------------------------------------------------------- candidate passage

#: The longest candidate passage, in characters.
CANDIDATE_CHARS = 400

#: The word counts of the quote parts that the candidate search looks for, longest first.
ANCHOR_WORDS = (8, 5, 3)

#: The most parts of each length that the search tries.
ANCHORS_PER_LENGTH = 6

#: The most extracted pages that the candidate search reads.
CANDIDATE_MAX_PAGES = 400


def _anchors(quote: str) -> list[tuple[int, int, re.Pattern]]:
    """The quote parts to look for: `(words, chars before the part, pattern)`, the longest
    first. A pattern matches the words of the part with any whitespace between them, with
    case and typographic punctuation folded."""
    words = normalise_for_match(quote).split(" ")
    out = []
    for size in ANCHOR_WORDS:
        if len(words) < size:
            continue
        starts = sorted({round(i * (len(words) - size) / max(1, ANCHORS_PER_LENGTH - 1))
                         for i in range(ANCHORS_PER_LENGTH)})
        for start in starts:
            part = words[start:start + size]
            before = len(" ".join(words[:start])) + (1 if start else 0)
            pattern = re.compile(r"\s+".join(re.escape(w) for w in part), re.IGNORECASE)
            out.append((size, before, pattern))
    return out


def _fold_same_length(text: str) -> str:
    """Typographic punctuation folded one character for one character, so an offset in the
    result is an offset in `text`."""
    for fancy, plain in _PUNCTUATION_FOLDS:
        text = text.replace(fancy, plain)
    return text


def candidate_passage(quote: str, pages) -> dict | None:
    """An exact passage of the extracted text near a quote that did not verify, or None.

    `pages` yields `(extracted_by, page_id, text)` in the order of verification. The search
    looks for the longest part of the quote that the text holds, and returns the text of
    that page around it, as long as the quote and at most `CANDIDATE_CHARS`, cut at
    whitespace. The passage is a copy of the stored text, with its source and character
    span. It is not verified: a later citation whose quote passes the check verifies it.
    """
    anchors = _anchors(quote)
    if not anchors:
        return None
    best = None
    for count, (extracted_by, page_id, text) in enumerate(pages):
        if count >= CANDIDATE_MAX_PAGES:
            break
        folded = _fold_same_length(text or "")
        for size, before, pattern in anchors:
            if best is not None and size <= best[0]:
                break
            match = pattern.search(folded)
            if match:
                best = (size, before, match.start(), extracted_by, page_id, text or "")
                break
        if best is not None and best[0] == anchors[0][0]:
            break
    if best is None:
        return None
    _, before, at, extracted_by, page_id, text = best
    length = min(CANDIDATE_CHARS, max(len(quote), 40))
    start = max(0, at - before)
    end = min(len(text), start + length)
    while start > 0 and not text[start - 1].isspace() and at - start < length // 2:
        start -= 1
    while end < len(text) and not text[end].isspace() and end - start < CANDIDATE_CHARS:
        end += 1
    passage = text[start:end].strip()
    if not passage:
        return None
    offset = text.index(passage, start)
    return {"text": passage, "extracted_by": str(extracted_by or ""), "page_id": page_id,
            "start": offset, "end": offset + len(passage)}
