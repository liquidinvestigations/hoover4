"""The words of board node ids in the board language, and the comparison of node ids.

A new intent, finding or correction id is `<prefix>-<words>`. The prefix is the type word of
the board language (`PREFIXES`), and the words name the content in that language. The
storage kind of a finding is `fact`, so `prefix(language, "fact")` gives the finding word.
The kind of a node comes from its row, never from its prefix. Old ids keep `fact-` and the
English words.

The fixed ids `background` and `goal-NN` are the same in every language, because code
parses them (`model.goal_slot`).

Every generated slug is canonical: Unicode NFC, then lowercase. The writers compare
canonical strings exactly. A node id that a model writes in a reply is made canonical
before the lookup. When that lookup fails, `match_node_id` compares the ids without their
marks (NFKD, then the characters of general category `M*` removed), and accepts the match
only when exactly one known id matches.

A chat session id and an explore workflow id hold the node id when it is ASCII, else `x`
and the first 16 hex digits of its SHA-256 (`node_key`). Every id before this rule is ASCII,
so its session and its workflow keep their ids. **Mirrored in
`website/common/src/board_types.rs`** (`node_key`).

The prefix words use the interface words of the board pages (`ai-chat-board-intent`,
`ai-chat-board-finding` and the correction texts of `website/frontend/i18n/<code>/chat.ftl`),
lowercase and as one word. Native speakers have not reviewed them.
"""

from __future__ import annotations

import hashlib
import unicodedata

from tasks.P_agent.language import DEFAULT_LANGUAGE, supported_code

#: The prefix words of an intent, a finding and a correction, for each supported code.
PREFIXES: dict[str, tuple[str, str, str]] = {
    "en": ("intent", "finding", "correction"),
    "de": ("absicht", "erkenntnis", "korrektur"),
    "es": ("intención", "hallazgo", "corrección"),
    "fr": ("intention", "constat", "correction"),
    "pl": ("zamiar", "ustalenie", "poprawka"),
    "pt": ("intenção", "conclusão", "correção"),
    "ar": ("مقصد", "استنتاج", "تصحيح"),
    "he": ("כוונה", "ממצא", "תיקון"),
    "hi": ("आशय", "निष्कर्ष", "सुधार"),
    "zh": ("意图", "发现", "更正"),
    "it": ("intento", "riscontro", "correzione"),
    "nl": ("intentie", "bevinding", "correctie"),
    "da": ("hensigt", "fund", "rettelse"),
    "nb": ("hensikt", "funn", "korreksjon"),
    "sv": ("avsikt", "fynd", "korrigering"),
    "el": ("πρόθεση", "εύρημα", "διόρθωση"),
    "hr": ("namjera", "nalaz", "ispravak"),
    "ro": ("intenție", "constatare", "corecție"),
    "ru": ("намерение", "находка", "поправка"),
    "ja": ("意図", "調査結果", "訂正"),
    "ko": ("의도", "발견", "수정"),
    "tr": ("niyet", "bulgu", "düzeltme"),
}

#: The node kinds that take a prefix, in the order of the `PREFIXES` entries.
KINDS = ("intent", "fact", "correction")

#: Words that name a node type in every language: the legacy English words and the fixed
#: ids. A slug loses them, and also the prefix words of its board language
#: (`type_words`).
LEGACY_TYPE_WORDS = frozenset({"intent", "fact", "finding", "correction", "origin", "goal", "background"})


def canonical(text: str) -> str:
    """`text` in Unicode NFC, lowercase."""
    return unicodedata.normalize("NFC", str(text or "")).lower()


def mark_free(text: str) -> str:
    """The canonical `text` without its marks: NFKD, then every `M*` character removed."""
    decomposed = unicodedata.normalize("NFKD", canonical(text))
    return "".join(c for c in decomposed if not unicodedata.category(c).startswith("M"))


def language_code(language: str | None) -> str:
    """The supported code of `language`, else English."""
    return supported_code(language) or DEFAULT_LANGUAGE


def prefix(language: str | None, kind: str) -> str:
    """The prefix word of a new node of `kind` (`intent`, `fact` or `correction`) in the
    board language. Another kind is its own prefix."""
    if kind not in KINDS:
        return kind
    return PREFIXES[language_code(language)][KINDS.index(kind)]


def type_words(language: str | None) -> frozenset:
    """The words that a slug of a board in `language` loses: the legacy words and the prefix
    words of the language and of English."""
    return LEGACY_TYPE_WORDS | set(PREFIXES[language_code(language)]) | set(PREFIXES[DEFAULT_LANGUAGE])


def node_key(node_id: str) -> str:
    """The form of a node id inside a system identifier: the id when it is ASCII, else `x`
    and the first 16 hex digits of the SHA-256 of its UTF-8 bytes."""
    if node_id.isascii():
        return node_id
    return "x" + hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:16]


def match_node_id(raw: str, known) -> tuple[str | None, bool]:
    """The known id that a model wrote as `raw`, and whether the match ignored marks.

    An exact match, then a unique canonical match, then a unique match without marks. The
    second value is true only for the match without marks, which the caller records as a
    problem of the reply. `(None, False)` when no rule finds exactly one id."""
    raw = str(raw or "").strip()
    known = list(known)
    if raw in known:
        return raw, False
    wanted = canonical(raw)
    same = [k for k in known if canonical(k) == wanted]
    if len(same) == 1:
        return same[0], False
    plain = mark_free(raw)
    close = [k for k in known if mark_free(k) == plain]
    if len(close) == 1:
        return close[0], True
    return None, False


__all__ = ["KINDS", "LEGACY_TYPE_WORDS", "PREFIXES", "canonical", "language_code", "mark_free",
           "match_node_id", "node_key", "prefix", "type_words"]
