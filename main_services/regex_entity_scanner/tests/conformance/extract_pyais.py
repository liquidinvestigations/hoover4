#!/usr/bin/env python3
"""Turn pyais' decoded expectations into conformance cases for the MMSI rule.

``vendored/reference/pyais/tests/`` holds two decode modules. Every place they assert what an AIS
message decodes to — a dict entry, a comparison against ``msg["mmsi"]`` or ``msg.mmsi``, a keyword
argument to an encoder — is upstream stating an identity, and those statements are the cases. The
modules are read with ``ast`` rather than by pattern, because the same value is written four
different ways across them.

Two caveats belong with the cases rather than in a report somewhere else.

**An AIS sentence contains no MMSI as text.** ``!AIVDM,1,1,,A,15M67FC000G?ufbE`FepT@3n00Sa,0*5C``
carries the identity in a six-bit payload, so scanning a raw NMEA sentence produces nothing at all
and the sentences are not a corpus for this rule. Only the decoded expectations are, and they are
bare integers, so they go into the standard carrier with the rule's own documented cue. That
measures the rule against a list of numbers rather than against text somebody wrote, which is
weaker evidence than a prose origin gives and is the best this rule can have.

**The origin measures recall and nothing else.** pyais decodes the identity field to an integer, so
a coast station or a group call — identities that begin with one or two zeros — arrives with its
leading zeros gone. A value of fewer than nine digits is therefore not upstream declaring an invalid
MMSI; it is a valid identity that lost its shape on the way out, and padding it back would
manufacture a token nobody wrote. Those rows are an exclusion, and with them goes any precision
evidence this origin might have looked like it had.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import ast
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
TESTS = os.path.join(ROOT, "vendored", "reference", "pyais", "tests")
MIDS = os.path.join(ROOT, "vendored", "data", "itu", "mids.json")

ORIGIN = "pyais"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

# The rule refuses a bare nine-digit run without one of its own documented cue words, and calling a
# field `mmsi` is upstream's statement that this is one.
CUE = "MMSI"

# --------------------------------------------------------------------------------------------
# The exclusion reasons, each quoting the limit in the tracked tree it rests on
# --------------------------------------------------------------------------------------------

NOT_NINE_DIGITS = (
    "a decoded value that is not nine digits. The identity field decodes to an integer, so a coast "
    "station or group call — the identities that begin with a zero — arrives with its leading zeros "
    "stripped, and the vessel.mmsi card requires a run of exactly nine digits. Padding the value "
    "back to nine would manufacture a token upstream never wrote"
)
SPECIAL_IDENTITY = (
    "an identity whose Maritime Identification Digits are not the first three characters — a coast "
    "station, group call, SAR aircraft, handheld or craft-associated identity. The card lists those "
    "forms under what is not matched: reading the wrong three digits as a flag state is worse than "
    "not reading them"
)
UNALLOCATED_MID = (
    "the leading three digits are not a Maritime Identification Digit triple the ITU has allocated, "
    "which is the card's first check. A test fixture is free to invent an identity that decodes "
    "correctly and belongs to no administration, and the rule refuses one by design"
)


def mids() -> set[str]:
    """The allocated triples, read from the same file the rule validates against."""
    with open(MIDS, encoding="utf-8") as handle:
        return set(json.load(handle))


def stated_identities(path: str):
    """Every MMSI value the module states, in the four shapes it states them in."""
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    def named(node) -> str | None:
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            return node.slice.value if isinstance(node.slice.value, str) else None
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and "mmsi" in key.value
                    and isinstance(value, ast.Constant)
                ):
                    yield value.value
        elif isinstance(node, ast.Compare) and len(node.comparators) == 1:
            name = named(node.left)
            if name and "mmsi" in name and isinstance(node.comparators[0], ast.Constant):
                yield node.comparators[0].value
        elif isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "assertEqual":
            if len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
                name = named(node.args[0])
                if name and "mmsi" in name:
                    yield node.args[1].value
        elif isinstance(node, ast.keyword) and node.arg and "mmsi" in node.arg:
            if isinstance(node.value, ast.Constant):
                yield node.value.value


def exclusion_for(token: str, allocated: set[str]):
    """The documented limit that keeps an identity out of the scores, or `None`."""
    if len(token) != 9:
        return NOT_NINE_DIGITS
    if token[0] in "0189":
        return SPECIAL_IDENTITY
    if token[:3] not in allocated:
        return UNALLOCATED_MID
    return None


def main() -> None:
    allocated = mids()
    cases = []
    index = 0
    seen = set()

    for name in sorted(os.listdir(TESTS)):
        if not name.endswith(".py"):
            continue
        for value in stated_identities(os.path.join(TESTS, name)):
            if isinstance(value, bool) or not isinstance(value, (int, str)):
                continue
            token = str(value)
            if not token.isdigit() or token in seen:
                continue
            seen.add(token)
            exclusion = exclusion_for(token, allocated)
            cue = None if exclusion else CUE
            prefix = CARRIER_PREFIX + (cue + " " if cue else "")
            start = len(prefix.encode("utf-8"))
            index += 1
            cases.append(
                {
                    "id": f"{ORIGIN}:mmsi:{index:04d}",
                    "origin": ORIGIN,
                    "source": f"tests/{name}",
                    "scheme": "mmsi",
                    "token": token,
                    "text": f"{prefix}{token}{CARRIER_SUFFIX}",
                    "token_start": start,
                    "token_end": start + len(token.encode("utf-8")),
                    "cue": cue,
                    "valid": True,
                    "rule_id": None if exclusion else "vessel.mmsi",
                    "entity_type": None if exclusion else "vessel",
                    "expect_value": None if exclusion else token,
                    "exclusion": exclusion,
                }
            )

    cases.sort(key=lambda item: item["id"])
    for item in cases:
        print(json.dumps(item, sort_keys=True, ensure_ascii=False))

    scored = sum(1 for item in cases if item["exclusion"] is None)
    print(
        f"{len(cases)} cases, {scored} scored, {len(cases) - scored} excluded",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
