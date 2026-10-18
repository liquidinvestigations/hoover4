"""Read one JSON value out of a model reply.

A model often wraps the JSON that a prompt asks for in a Markdown fence, adds a sentence
before it, or leaves out the opening brace of a fenced object. `extract_json` accepts these
forms for an object and for an array, so the board assessment, the board labels and the
follow-up suggestions read a reply with one set of rules.

The rules, in order:

1. `<think>` blocks are removed.
2. The last fenced body of the requested kind is used. For an object, a fenced body that
   starts with a quoted key gets the opening brace that the model left out.
3. Otherwise the text from the first opening bracket to the last closing bracket of the
   kind is used.
4. A comma before a closing bracket, which JSON does not allow, is removed when the first
   parse fails.
"""

from __future__ import annotations

import json
import re
from typing import Any

THINK_PATTERN = re.compile(r"<think>.*?</think>", re.S)
_FENCES = {
    "object": re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S),
    "array": re.compile(r"```(?:json)?\s*(\[.*?\])\s*```", re.S),
}
#: A fenced body that starts with a quoted key: an object without its opening brace.
OPEN_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(\"[^`]*?)\s*```", re.S)
#: A comma before a closing bracket.
TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_BRACKETS = {"object": ("{", "}", dict), "array": ("[", "]", list)}


def extract_json(text: str, kind: str = "object") -> Any:
    """The JSON object (`kind` "object") or array (`kind` "array") of a reply.

    Raises `ValueError` when the reply holds no value of that kind.
    """
    if kind not in _BRACKETS:
        raise ValueError(f"unknown JSON kind {kind!r}")
    opening, closing, expected = _BRACKETS[kind]
    text = THINK_PATTERN.sub("", text or "").strip()
    fenced = _FENCES[kind].findall(text)
    keyed = OPEN_FENCE_PATTERN.findall(text) if kind == "object" else []
    if fenced:
        text = fenced[-1]
    elif keyed:
        body = keyed[-1].strip()
        text = "{" + body + ("" if body.endswith("}") else "}")
    start, end = text.find(opening), text.rfind(closing)
    if start < 0 or end < start:
        raise ValueError(f"the reply holds no JSON {kind}")
    candidate = text[start:end + 1]
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        value = json.loads(TRAILING_COMMA.sub(r"\1", candidate))
    if not isinstance(value, expected):
        raise ValueError(f"the reply is not a JSON {kind}")
    return value


__all__ = ["THINK_PATTERN", "TRAILING_COMMA", "extract_json"]
