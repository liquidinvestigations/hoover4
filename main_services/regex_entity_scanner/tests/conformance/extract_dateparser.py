#!/usr/bin/env python3
"""Turn the dateparser parser tests into normalised conformance cases for the date rules.

``vendored/reference/dateparser/tests/test_date_parser.py`` is one long parametrised list of date
strings with the datetime each is expected to parse to, across every locale and format that project
supports. It is the widest labelled date corpus available under a permissive license, and it is
where the machine formats our four rules claim (ISO 8601, RFC 3339 with an offset, the mail-header
date, the week date) sit beside the several hundred human-written forms we deliberately do not
match. Both halves are the measurement: one gives recall, the other gives the size of the limit.

The file is read with ``ast``, not with a regular expression: every ``param(...)`` call inside a
``@parameterized.expand`` decorator is a case, and the decorated function's name is what says
whether upstream considers the string parseable. ``test_dates_not_parsed`` and the too-large-day
test are upstream declaring a string invalid, and those become the invalid half of the corpus.
The only place in this origin where precision is measured.

Tokens here are bare date strings rather than sentences, so the carrier sentence the identifier
extractors build is used, exactly as for python-stdnum: the fragment scanned is
``The record shows <token> on the form.``

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from extract_grok import (  # noqa: E402  (the shared shape table lives with the other date origin)
    COMPACT_DIGITS,
    NAMED_MONTH,
    NUMERIC_ORDER,
    SHAPES,
    WHOLE_DAY,
    classify,
)

TESTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "dateparser",
    "tests",
    "test_date_parser.py",
)

ORIGIN = "dateparser"
SOURCE = "tests/test_date_parser.py"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

# The four shapes a date rule claims, tried against the whole token. A token that is one of them is
# scored; a token that merely contains one is not, because upstream's expectation is about the whole
# string and a partial match answers a different question.
MACHINE_SHAPES = [
    (kind, pattern) for kind, pattern in SHAPES if kind in {"clf", "iso8601", "rfc2822", "iso_week"}
]

# --------------------------------------------------------------------------------------------
# The exclusion reasons, each quoting the limit in the tracked tree it rests on
# --------------------------------------------------------------------------------------------

RELATIVE = (
    "a relative expression — an hour ago, next Tuesday, yesterday. Resolving one needs a reference "
    "instant the scanner does not have: it is stateless and sees a fragment, not a document date. "
    "No rule matches this shape"
)
EPOCH = (
    "a Unix epoch timestamp. There is no rule for one, and a bare ten-digit run carries no date "
    "syntax at all to separate it from an identifier — the same objection docs/Rules_And_Patterns.md "
    "makes to bare YYYYMMDD, only stronger"
)
TIME_ONLY = (
    "a time of day with no date. The standing date policy in docs/Rules_And_Patterns.md matches a "
    "date only when the match itself determines year, month and day"
)
NATURAL = (
    "a human-written date string. src/rules/date_iso.rs states the limit: human-written dates need "
    "a month-name lexicon and an order-disambiguation policy, and are a separate rule, which we do "
    "not ship — the four date rules are machine formats only"
)

RELATIVE_WORDS = re.compile(
    r"\b(ago|hence|later|yesterday|today|tomorrow|tonight|now|last|next|this|"
    r"in \d|\d+ (sec|min|hour|day|week|month|year))",
    re.IGNORECASE,
)
FOUR_DIGIT_YEAR = re.compile(r"(?<!\d)\d{4}(?!\d)")
TIME_OF_DAY = re.compile(r"^\d{1,2}[:.]\d{2}(?::\d{2})?\s*(?:[ap]\.?m\.?)?$", re.IGNORECASE)
EPOCH_DIGITS = re.compile(r"^-?\d{9,17}$")
COMPACT = re.compile(r"^\d{8}$")
HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def cases_in(tree: ast.Module):
    """Every ``param(...)`` in a ``@parameterized.expand`` decorator, with its test's name."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            for call in ast.walk(decorator):
                if not isinstance(call, ast.Call):
                    continue
                if not (isinstance(call.func, ast.Name) and call.func.id == "param"):
                    continue
                if not call.args:
                    continue
                first = call.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    yield node.name, first.value


# Upstream declares a string unparseable in exactly these two tests. Everything else in the file is
# a string it parses, which is what makes the split a fact about upstream rather than a guess.
def is_invalid(test_name: str) -> bool:
    return "not_parsed" in test_name or "error_should_be_raised" in test_name


def machine_format(token: str):
    """The scored classification of a token that is entirely one machine format, or None."""
    for kind, pattern in MACHINE_SHAPES:
        match = pattern.fullmatch(token)
        if match is not None:
            return classify(kind, match, prefix="parser")
    return None


def excluded(token: str) -> tuple[str, str]:
    """(scheme, reason) for a token no date rule claims."""
    if RELATIVE_WORDS.search(token):
        return ("parser.relative", RELATIVE)
    if EPOCH_DIGITS.match(token):
        return ("parser.epoch", EPOCH)
    if COMPACT.match(token):
        return ("parser.compact", COMPACT_DIGITS)
    if TIME_OF_DAY.match(token):
        return ("parser.time_only", TIME_ONLY)
    if not FOUR_DIGIT_YEAR.search(token):
        return ("parser.yearless", WHOLE_DAY)
    if not HAS_LETTER.search(token):
        return ("parser.numeric", NUMERIC_ORDER)
    if re.match(r"^[\x00-\x7f]+$", token):
        return ("parser.named_month", NAMED_MONTH)
    return ("parser.locale", NATURAL)


def main() -> None:
    with open(TESTS, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    cases = []
    seen = set()
    counters: dict[str, int] = {}
    for test_name, token in cases_in(tree):
        if not token.strip() or token in seen:
            continue
        seen.add(token)
        valid = not is_invalid(test_name)

        classified = machine_format(token) if valid else None
        if classified is not None:
            scheme, rule_id, expect_value, exclusion, _ = classified
        elif valid:
            scheme, exclusion = excluded(token)
            rule_id, expect_value = None, None
        else:
            # An upstream-invalid string is never excluded: what it measures is whether we stay
            # silent on it, and that is the precision half this origin exists to supply.
            scheme, rule_id, expect_value, exclusion = "parser.unparseable", None, None, None

        text = f"{CARRIER_PREFIX}{token}{CARRIER_SUFFIX}"
        counters[scheme] = counters.get(scheme, 0) + 1
        cases.append(
            {
                "id": f"{ORIGIN}:{scheme}:{counters[scheme]:04d}",
                "origin": ORIGIN,
                "source": SOURCE,
                "scheme": scheme,
                "token": token,
                "text": text,
                "token_start": len(CARRIER_PREFIX.encode("utf-8")),
                "token_end": len(CARRIER_PREFIX.encode("utf-8")) + len(token.encode("utf-8")),
                "cue": None,
                "valid": valid,
                "rule_id": rule_id,
                "entity_type": None if exclusion else "date",
                "expect_value": expect_value,
                "exclusion": exclusion,
            }
        )

    cases.sort(key=lambda case: case["id"])
    for case in cases:
        print(json.dumps(case, sort_keys=True, ensure_ascii=False))

    scored = sum(1 for case in cases if case["exclusion"] is None)
    print(
        f"{len(cases)} cases, {scored} scored, {len(cases) - scored} excluded",
        file=sys.stderr,
    )
    for scheme, count in sorted(counters.items()):
        print(f"  {scheme}: {count}", file=sys.stderr)


if __name__ == "__main__":
    main()
