#!/usr/bin/env python3
"""Turn the is_email test set into conformance cases for the email rule.

``vendored/reference/isemail/test/tests.xml`` is 164 addresses, each with the category and the
diagnosis upstream's validator returns for it. The categories are what make it more than a
valid/invalid split, and they line up with the three things this origin measures:

* ``ISEMAIL_ERR`` — wrong under any reading. These are the precision cases, and they are the largest
  body of email precision evidence available anywhere under a permissive licence.
* ``ISEMAIL_VALID_CATEGORY`` — right under every reading. These are the recall cases.
* everything between — upstream saying "legal under RFC 5322 and a bad idea": quoted local parts,
  comments, folding whitespace, IP-literal domains, obsolete forms. That is one exclusion class, and
  it rests on the email card's own scope.

Two things about the corpus are decided by the file rather than here. XML cannot carry an ASCII
control character, so upstream writes each one as the U+2400-block symbol for it — ``␇`` for BEL —
and says so in its own header comment; decoding those back is what makes the token upstream's own
rather than a picture of it. And an upstream-invalid address is scanned **as the whole fragment**,
because upstream's assertion is about the whole string rather than about a span inside it: the
question that then gets asked is the one upstream asked, "is there an address of this kind in here
at all". A valid address goes into the neutral carrier sentence the other bare-token origins use.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET

TESTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "isemail",
    "test",
    "tests.xml",
)

ORIGIN = "isemail"
SOURCE = "test/tests.xml"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

# The two categories that make a claim a validating rule can be scored against. Everything else is
# upstream grading an address it accepts with a warning.
ERROR = "ISEMAIL_ERR"
VALID = "ISEMAIL_VALID_CATEGORY"

# The constructs whose absence the email rule states as its scope. A row whose diagnosis names one
# of them is upstream rejecting a piece of RFC 5322 syntax this rule never reads.
RFC5322_MACHINERY = (
    "QUOTEDSTR",
    "_QS",
    "QTEXT",
    "QPAIR",
    "COMMENT",
    "CFWS",
    "CTEXT",
    "DOMLIT",
    "DTEXT",
    "BACKSLASHEND",
)

# What separates one token from the next in text rather than belonging to either of them.
TEXT_BOUNDARIES = " \t\r\n"

# --------------------------------------------------------------------------------------------
# The exclusion reasons, each quoting the limit in the tracked tree it rests on
# --------------------------------------------------------------------------------------------

GRADED = (
    "upstream grades this address as legal under RFC 5322 and inadvisable — a quoted local part, a "
    "comment, folding whitespace, an IP-literal domain or an obsolete form. The email.basic card "
    "states the same limit as a decision: full RFC 5322 syntax is deliberately not the target, "
    "because it accepts a great deal nobody has ever typed"
)
MACHINERY = (
    "upstream's diagnosis is about a piece of RFC 5322 syntax the rule does not read — a comment, a "
    "quoted string or a domain literal. The card's scope is the ordinary local-part@domain form "
    "that people actually write, so a malformed comment around a well-formed address is not a "
    "claim the two engines can disagree about"
)
WRAPPED = (
    "an addr-spec with white space or a line break wrapped around it, which upstream reads as part "
    "of the string under test. In text those are the boundary between one token and the next "
    "rather than part of either, so the rule is being asked a different question than the "
    "validator was"
)
TRAILING_DOT = (
    "a domain with a trailing dot. src/rules/email.rs trims one deliberately — a dot at the end of "
    "an address in prose belongs to the sentence — so the rule reports the address and upstream "
    "rejects the string, which is the trim working rather than a disagreement about the address"
)
EMPTY = "upstream's empty input: there is no token to scan and nothing to stay silent about"


def decoded(address: str) -> str:
    """Upstream's U+2400-block symbols turned back into the control characters they stand for.

    The file's own header explains the substitution and the reason for it: XML cannot carry a
    control character, so ``&#x2407;`` is written where a BEL is meant. Reading it back is what
    makes the token upstream's own.
    """
    return "".join(
        chr(ord(character) - 0x2400) if 0x2400 <= ord(character) <= 0x241F else character
        for character in address
    )


def exclusion_for(address: str, diagnosis: str, valid: bool):
    """The documented limit that keeps a case out of the scores, or `None`."""
    if not address:
        return EMPTY
    if valid:
        return None
    if any(marker in diagnosis for marker in RFC5322_MACHINERY):
        return MACHINERY
    if "(" in address or ")" in address:
        # A comment wraps an otherwise well-formed address, and upstream's diagnosis names what is
        # wrong inside the comment rather than the comment itself.
        return MACHINERY
    if address.strip(TEXT_BOUNDARIES) != address:
        return WRAPPED
    if address.endswith("."):
        return TRAILING_DOT
    return None


def main() -> None:
    root = ET.parse(TESTS).getroot()
    cases = []
    counters: dict[str, int] = {}

    for test in root.findall("test"):
        category = test.findtext("category") or ""
        if category not in (ERROR, VALID):
            category_exclusion = GRADED
        else:
            category_exclusion = None
        address = decoded(test.findtext("address") or "")
        diagnosis = test.findtext("diagnosis") or ""
        valid = category == VALID
        exclusion = category_exclusion or exclusion_for(address, diagnosis, valid)

        # A valid address goes into the carrier, so that what is measured is an address inside a
        # sentence. An invalid one is the whole fragment, which is upstream's own assertion: there
        # is no address of this kind anywhere in this string.
        if valid:
            text = f"{CARRIER_PREFIX}{address}{CARRIER_SUFFIX}"
            start = len(CARRIER_PREFIX.encode("utf-8"))
        else:
            text = address
            start = 0

        scheme = "address"
        counters[scheme] = counters.get(scheme, 0) + 1
        cases.append(
            {
                "id": f"{ORIGIN}:{scheme}:{counters[scheme]:04d}",
                "origin": ORIGIN,
                "source": SOURCE,
                "scheme": scheme,
                "token": address,
                "text": text,
                "token_start": start,
                "token_end": start + len(address.encode("utf-8")),
                "cue": None,
                "valid": valid,
                "rule_id": None if exclusion else "email.basic",
                "entity_type": None if exclusion else "email",
                # Upstream answers with a category and a diagnosis, never with a canonical form, so
                # a scored agreement here is about the type over the span and nothing more.
                "expect_value": None,
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
