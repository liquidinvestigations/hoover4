"""The notes that the worker writes into a run, in the agent language of the run.

The texts are Fluent messages in `i18n/<language>/notes.ftl`. English is the source, and
`scripts/i18n/translate_catalogs.py` writes the other languages. The website reads its
catalogs with the same format.

The worker image has no Fluent runtime, so this module reads the subset that the notes
use: a message is plain text with `{ $name }` variables and `{"…"}` string literals, on one
line or on indented continuation lines. A message with another construct, such as a
selector, is not read, and the English message is used. `test_agent_notes` checks that
every message of every catalog is in the subset and has the variables of English.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from tasks.P_agent.language import DEFAULT_LANGUAGE, turn_language

log = logging.getLogger(__name__)

CATALOG_DIR = Path(__file__).parent / "i18n"

_MESSAGE = re.compile(r"^([a-z][a-z0-9-]*)\s*=\s?(.*)$")
_PLACEABLE = re.compile(r"\{\s*(?:\$([a-zA-Z][\w-]*)|\"((?:[^\"\\]|\\.)*)\")\s*\}")


def parse(text: str) -> dict[str, list]:
    """The messages of a catalog in the subset, by id. Each message is a list of parts: a
    string is literal text, and a one-item tuple names a variable. A message outside the
    subset is left out."""
    raw: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in text.split("\n"):
        match = _MESSAGE.match(line)
        if match:
            current = match.group(1)
            raw[current] = [match.group(2)]
        elif current and line.startswith(" ") and line.strip():
            raw[current].append(line.strip())
        elif not line.strip() or line.startswith("#"):
            current = None if line.startswith("#") else current
        else:
            current = None
    out: dict[str, list] = {}
    for message_id, lines in raw.items():
        value = "\n".join(lines).strip()
        parts: list = []
        texts: list[str] = []
        position = 0
        for placeable in _PLACEABLE.finditer(value):
            texts.append(value[position:placeable.start()])
            parts.append(texts[-1])
            if placeable.group(1):
                parts.append((placeable.group(1),))
            else:
                parts.append(placeable.group(2).replace('\\"', '"').replace("\\\\", "\\"))
            position = placeable.end()
        texts.append(value[position:])
        parts.append(texts[-1])
        # A brace outside a variable or a string literal is another Fluent construct.
        if not any("{" in text or "}" in text for text in texts):
            out[message_id] = [p for p in parts if p != ""]
    return out


@lru_cache(maxsize=None)
def catalog(language: str) -> dict[str, list]:
    """The notes of one language. A language without a catalog has none."""
    path = CATALOG_DIR / language / "notes.ftl"
    return parse(path.read_text(encoding="utf-8")) if path.is_file() else {}


def variables(parts: list) -> set[str]:
    return {p[0] for p in parts if isinstance(p, tuple)}


def note(language: Optional[str], message_id: str, **args) -> str:
    """The text of note `message_id` in `language`, with `args`. A message that the
    language lacks, or whose variables differ from English, gives the English text."""
    english = catalog(DEFAULT_LANGUAGE)[message_id]
    parts = catalog(turn_language(language)).get(message_id)
    if parts is None or variables(parts) != variables(english):
        parts = english
    return "".join(str(args[p[0]]) if isinstance(p, tuple) else p for p in parts)


__all__ = ["CATALOG_DIR", "catalog", "note", "parse", "variables"]
