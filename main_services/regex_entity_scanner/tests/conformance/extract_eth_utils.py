#!/usr/bin/env python3
"""Turn the eth-utils address tests and the ERC-55 vectors into conformance cases.

Two upstreams, one subject. ``vendored/reference/eth-utils/tests/test_address_utils.py`` is a set of
parametrised tables, each asking a different question about the same forty hexadecimal characters,
and the questions are exactly the ones a scanner has to keep apart:

* ``test_is_address`` — is this the shape of an address at all? Upstream answers yes for a
  mixed-case address whose checksum is wrong, because that function does not read the checksum.
* ``test_is_checksum_address`` — does the capitalisation carry a correct EIP-55 checksum?
* ``test_to_normalized_address`` and ``test_to_checksum_address`` — what is the canonical spelling?
  These are the only rows in the origin that document a value.

ERC-55's own Test Cases section carries the eight vectors the standard is defined by, in three
labelled groups: all caps, all lower and mixed. They are read with the file, not transcribed.

The blind spot this origin has, stated here because it decides how the cases are written: an address
in a single case carries no checksum, and the rule reports it with the no-checksum flag and a
markedly lower confidence. The case schema has no field for a flag, so such an address scores as a
plain agreement on the type, and upstream's ``is_checksum_address`` answering False about it is a
statement about the capitalisation rather than about the address. Those rows are an exclusion for
that reason and not because they disagree.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

REFERENCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "vendored", "reference"
)
TESTS = os.path.join(REFERENCE, "eth-utils", "tests", "test_address_utils.py")
ERC55 = os.path.join(REFERENCE, "erc-55", "erc-55.md")

ORIGIN = "eth-utils"
UTILS_SOURCE = "tests/test_address_utils.py"
ERC_SOURCE = "erc-55.md"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

PREFIXED = re.compile(r"^0x[0-9a-fA-F]{40}$")
BARE_FORTY = re.compile(r"^[0-9a-fA-F]{40}$")
VECTOR = re.compile(r"^0x[0-9a-fA-F]{40}$", re.MULTILINE)

# --------------------------------------------------------------------------------------------
# The exclusion reasons, each quoting the limit in the tracked tree it rests on
# --------------------------------------------------------------------------------------------

UNPREFIXED = (
    "an address written without its 0x prefix. The crypto.ethereum card's first check is 0x "
    "followed by exactly forty hexadecimal characters: without the prefix a forty-character hex "
    "run is a hash, a key or a commit as often as it is an account"
)
PREFIX_CASE = (
    "an address written with an upper-case 0X prefix, which the card's first check does not admit; "
    "the prefix is a literal marker rather than part of the hexadecimal"
)
UNREAD_CHECKSUM = (
    "upstream's is_address asserts the hexadecimal shape and does not read the EIP-55 checksum, "
    "while the rule verifies the capitalisation before it emits. The checksummed readings are "
    "measured by the is_checksum_address table instead, which is where upstream makes that claim"
)
ONE_CASE_UNCHECKED = (
    "an address written in a single case, which carries no checksum at all. Upstream answering "
    "False here is a statement about the capitalisation, not about the address: the rule reports "
    "such an address with the no-checksum flag and a markedly lower confidence, and the case schema "
    "has no field for a flag, so the row cannot be scored as a disagreement"
)
RECHECKSUMMED = (
    "upstream recomputes the capitalisation from the address. src/rules/crypto.rs reports an "
    "address written in a single case in the lower-case spelling, which is the one spelling that "
    "carries no claim, and rewriting it into checksummed form would assert a check that was never "
    "made"
)
NOT_TEXT = (
    "a binary address: twenty raw bytes rather than a written token. A scanner is given text, and "
    "there is nothing here for a pattern to match"
)


def mixed_case(token: str) -> bool:
    """Whether the capitalisation carries an EIP-55 checksum at all."""
    body = token[2:]
    return any(c.isupper() for c in body) and any(c.islower() for c in body)


def normalised(token: str) -> str:
    """The value the rule reports: a mixed-case address as written, any other in lower case."""
    return token if mixed_case(token) else "0x" + token[2:].lower()


def literal(node):
    """The Python value of a literal element, or `None` for anything built by a call."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        return None


def tables(path: str):
    """Every `parametrize` table in the module, as (test name, column names, rows of nodes).

    The rows are yielded as syntax nodes rather than values: upstream's first table holds a lambda
    and a dict beside its strings, and evaluating the table whole would lose every row in it.
    """
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or len(decorator.args) < 2:
                continue
            if getattr(decorator.func, "attr", None) != "parametrize":
                continue
            names = literal(decorator.args[0])
            if isinstance(names, str):
                names = [name.strip() for name in names.split(",")]
            rows = decorator.args[1]
            if not isinstance(rows, (ast.Tuple, ast.List)) or not names:
                continue
            for row in rows.elts:
                if isinstance(row, (ast.Tuple, ast.List)) and len(row.elts) == len(names):
                    yield node.name, dict(zip(names, (literal(e) for e in row.elts)))


def case(scheme, index, source, token, valid, expect_value, exclusion):
    text = f"{CARRIER_PREFIX}{token}{CARRIER_SUFFIX}"
    start = len(CARRIER_PREFIX.encode("utf-8"))
    return {
        "id": f"{ORIGIN}:{scheme}:{index:04d}",
        "origin": ORIGIN,
        "source": source,
        "scheme": scheme,
        "token": token,
        "text": text,
        "token_start": start,
        "token_end": start + len(token.encode("utf-8")),
        "cue": None,
        "valid": valid,
        "rule_id": None if exclusion else "crypto.ethereum",
        "entity_type": None if exclusion else "crypto_wallet",
        "expect_value": None if exclusion else expect_value,
        "exclusion": exclusion,
    }


def shape_exclusion(token: str):
    """The documented limit a token's own shape rests on, or `None`."""
    if any(ord(character) < 0x20 or ord(character) > 0x7E for character in token):
        return NOT_TEXT
    if token[:2] == "0X":
        return PREFIX_CASE
    if BARE_FORTY.match(token):
        return UNPREFIXED
    return None


def utils_cases():
    """The four tables that make a claim about a written address."""
    counters: dict[str, int] = {}
    seen = set()
    for test_name, row in tables(TESTS):
        if test_name == "test_is_address":
            token, valid = row.get("args"), bool(row.get("is_hexstr"))
            scheme, expect_value = "address", None
            exclusion = None
            if isinstance(token, str) and PREFIXED.match(token) and mixed_case(token):
                exclusion = UNREAD_CHECKSUM
        elif test_name == "test_is_checksum_address":
            token, valid = row.get("value"), bool(row.get("expected"))
            scheme, exclusion = "checksum", None
            expect_value = normalised(token) if isinstance(token, str) else None
            if isinstance(token, str) and not valid and PREFIXED.match(token):
                exclusion = ONE_CASE_UNCHECKED if not mixed_case(token) else None
        elif test_name in ("test_to_normalized_address", "test_to_checksum_address"):
            token, expect_value = row.get("value"), row.get("expected")
            valid, scheme, exclusion = True, "normalise", None
            if isinstance(token, str) and isinstance(expect_value, str):
                if normalised(token) != expect_value:
                    exclusion = RECHECKSUMMED
        else:
            continue

        if not isinstance(token, str) or not token:
            continue
        exclusion = exclusion or shape_exclusion(token)
        key = (scheme, token, valid)
        if key in seen:
            continue
        seen.add(key)
        counters[scheme] = counters.get(scheme, 0) + 1
        yield case(
            scheme,
            counters[scheme],
            UTILS_SOURCE,
            token,
            valid,
            expect_value if exclusion is None else None,
            exclusion,
        )


def erc55_cases():
    """The vectors in ERC-55's own Test Cases section, in the three groups the standard writes."""
    with open(ERC55, encoding="utf-8") as handle:
        body = handle.read()
    section = body.split("# Test Cases", 1)[-1]
    for index, token in enumerate(VECTOR.findall(section), start=1):
        yield case("erc55", index, ERC_SOURCE, token, True, normalised(token), None)


def main() -> None:
    cases = list(utils_cases()) + list(erc55_cases())
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
