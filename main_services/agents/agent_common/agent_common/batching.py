"""The three mechanics every batched tool needs, written once.

A batched tool (one that takes a *list* of queries, urls, documents or domains instead
of one) repeats the same three problems in every server, and three copies of each is
three chances to fix a bug in two of them.

**List coercion.** XML-style tool-call parsers hand every parameter across as a string,
so a `list[str]` argument arrives as the literal `'["a","b"]'`. Pydantic rejects it, the
tool returns a validation error, and a small model retries the identical call until the
recursion budget is gone. Models also send a bare string for a one-element list, and a
comma-separated string when they have been told the parameter is a list. All three are
accepted, because all three are things models actually produce. A tool whose items are
records rather than strings meets the same parser, so `as_objects` is the same coercion
one level up.

**The divided budget.** A batched tool has one character budget for the whole call, not
one per item. Splitting it evenly and telling the model what was cut beats returning
twenty stubs that each say nothing: an item the model can read is worth more than five it
cannot. The budget never divides below `MIN_ITEM_CHARS`. Past that the items are dropped
and reported as dropped, rather than all of them being made useless together.

**The corrective note.** The tool compares what it was asked for with what was sensible to
do, and says so in words the model can act on. A tool that silently de-duplicates has
taught the model nothing and will be handed the same duplicate list next turn; one that
says "two of your five queries were repeats, they were run once" changes the next call.
This is the mechanism that makes batching improve over turns rather than only within one.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Sequence

#: Below this an item's slice of the budget is too small to carry meaning, so items are
#: dropped instead of every one of them being truncated into uselessness.
MIN_ITEM_CHARS = int(os.getenv("BATCH_MIN_ITEM_CHARS", "400"))


def as_list(value: Any, *, separator: str = ",") -> list[str]:
    """Whatever the model sent, as a list of non-empty strings.

    Accepts a real list, a JSON-encoded list, and a bare or separated string. Returns an
    empty list for `None` and for anything with no content, never `None`: a caller that
    has to distinguish "absent" from "empty" has two error paths where one will do.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    if not isinstance(value, str):
        return [str(value).strip()] if str(value).strip() else []

    text = value.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            return [str(v).strip() for v in parsed if str(v).strip()]
        # A truncated or malformed JSON list still has the items in it, and splitting the
        # raw string leaves `["a"` and `"b"`. Junk that reaches a URL fetcher or a search
        # backend as a query. Strip the syntax rather than passing it on.
        return [part for part in (_debracket(p) for p in text.split(separator)) if part]
    if separator and separator in text:
        return [part.strip() for part in text.split(separator) if part.strip()]
    return [text]


def _debracket(part: str) -> str:
    return part.strip().strip("[]").strip().strip("'\"").strip()


def as_objects(value: Any) -> list[dict]:
    """The same coercion as [`as_list`], for a list of *objects* rather than strings.

    A batched tool whose items are records (`{id, text, status}` rather than a bare
    query) meets the same stringifying parser, so `'[{"id": "a"}]'` arrives where a
    list was declared. A single object is accepted as a one-element list for the same
    reason a bare string is: models send it.

    Anything that is not an object once unwrapped is left in place rather than dropped,
    because the caller validates the items and a silently discarded row is a record the
    model treats as written. `None` and unparseable text give an empty list.
    """
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except ValueError:
            return []
        return as_objects(value)
    if isinstance(value, (list, tuple)):
        return [v for v in value if v is not None]
    return []


def dedupe(items: Sequence[str], *, casefold: bool = True) -> tuple[list[str], list[str]]:
    """`(kept, repeats)`, order preserved.

    The repeats are returned rather than discarded because they are what the corrective
    note is built from. De-duplicating silently is the failure this pair exists to avoid.
    """
    seen: set[str] = set()
    kept: list[str] = []
    repeats: list[str] = []
    for item in items:
        key = item.casefold() if casefold else item
        if key in seen:
            repeats.append(item)
            continue
        seen.add(key)
        kept.append(item)
    return kept, repeats


def divide_budget(total_chars: int, count: int) -> tuple[int, int]:
    """`(per_item_chars, items_that_fit)` for `count` items sharing `total_chars`.

    When the even split falls under `MIN_ITEM_CHARS` the number of items is reduced until
    it does not. The caller keeps the first `items_that_fit` and reports the rest as
    dropped. See the module docstring for why that beats truncating everything.
    """
    if count <= 0 or total_chars <= 0:
        return (0, 0)
    fits = min(count, max(1, total_chars // MIN_ITEM_CHARS))
    return (max(MIN_ITEM_CHARS, total_chars // fits), fits)


#: How far back `truncate` will look for a word boundary. An absolute distance, not a
#: fraction of the limit: a fraction is meaningless at a 400-character floor and wasteful
#: at a 10000-character budget, and either way the question is "is there a space close by".
WORD_BOUNDARY_SLACK = 60


def truncate(text: str, limit: int) -> tuple[str, bool]:
    """`(text, was_truncated)`, cut on a word boundary where there is one nearby."""
    if limit <= 0 or len(text) <= limit:
        return (text, False)
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > 0 and limit - space <= WORD_BOUNDARY_SLACK:
        cut = cut[:space]
    return (cut.rstrip(), True)


def corrective_note(*parts: str) -> str:
    """One note out of the observations a tool made about its own call.

    Empty parts are dropped, so a caller can pass conditions unguarded. Returns `""` when
    there is nothing to say, which is the common case and must stay free of charge.
    """
    said = [part.strip() for part in parts if part and part.strip()]
    return " ".join(said)


def repeats_note(repeats: Iterable[str], noun: str = "query") -> str:
    """The corrective note for de-duplication: what was repeated, and what to do instead."""
    repeated = list(repeats)
    if not repeated:
        return ""
    shown = ", ".join(sorted({f'"{r}"' for r in repeated}))
    one = len(repeated) == 1
    return (
        f"{len(repeated)} repeated {noun if one else noun + 's'} ({shown}) "
        f"{'was' if one else 'were'} run once. "
        f"Send each distinct {noun} once; use the extra slots for different angles."
    )


def dropped_note(dropped: Sequence[str], noun: str = "item") -> str:
    """The corrective note for items the budget could not fit."""
    if not dropped:
        return ""
    plural = noun if len(dropped) == 1 else f"{noun}s"
    return (
        f"{len(dropped)} {plural} were not fetched because the shared character budget "
        f"does not divide that far: {', '.join(dropped)}. Ask for fewer at a time."
    )


__all__ = [
    "MIN_ITEM_CHARS",
    "as_list",
    "as_objects",
    "corrective_note",
    "dedupe",
    "divide_budget",
    "dropped_note",
    "repeats_note",
    "truncate",
]
