#!/usr/bin/env python3
"""Turn the Recognizers-Text English specs into normalised conformance cases.

``vendored/reference/recognizers-text/Specs/`` holds, per recogniser, a JSON list of free-text
inputs with the extractions Microsoft's recognisers are expected to produce and the values those
extractions resolve to. Unlike a doctest corpus it is *already* free text, so the carrier sentence
the other extractors build is not used here: upstream's own sentence is what we scan, and the
offsets come from upstream's own ``Start``/``End``/``Length`` where it gives them.

An input with an empty ``Results`` list is upstream saying "there is nothing of this kind in this
sentence", which is the invalid half of the corpus. The whole input is recorded as the token for
those, because upstream names no span to point at, and the scorer's overlap test then asks the
right question: did anything at all fire in a sentence upstream says is empty.

The exclusions are large and they are the finding, not a way around it. Upstream's date recognisers
resolve natural language and relative expressions; our four date rules ship the machine-readable
formats that fix a whole day, and nothing else. Upstream's phone recogniser matches national form;
``phone.international`` matches international form only, and its card says why. Both limits are
written in the tracked tree, which is the test an exclusion has to pass.

The script emits one JSON object per line on stdout, in the shape the Rust runner reads. It runs
inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import json
import os
import re
import sys

SPECS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "recognizers-text",
    "Specs",
)

ORIGIN = "recognizers-text"

# The machine-readable date formats the four date rules claim, as they appear inside a sentence:
# ISO 8601 calendar dates and timestamps, the ISO week date, the mail-header date and the bracketed
# Common Log Format timestamp. A date token outside this set has no rule, which is the exclusion.
MACHINE_DATE = re.compile(
    r"""
    ^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?          # ISO 8601 date, optionally with a clock
  | ^\d{4}-?W\d{2}(-?\d)?$                        # ISO week date
  | ^\[\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}        # Common Log Format timestamp
  | ^\w{3},\s\d{1,2}\s\w{3}\s\d{4}                # mail-header date
    """,
    re.VERBOSE | re.IGNORECASE,
)

# A currency sign or an ISO 4217 code somewhere in the token. Amounts written with the currency's
# name in words ("420 million finnish markka") are what both money cards list as not matched.
CURRENCY_MARK = re.compile(r"[$€£¥₩₽₹¢₺₫₪]|\b[A-Z]{3}\b")

EXCLUSION_NATURAL_DATE = (
    "no rule matches this date format: the date rules ship the machine-readable formats that fix a "
    "whole day — ISO 8601, the ISO week date, the mail-header date and the web-server log "
    "timestamp — while upstream's recognisers resolve natural-language and relative expressions"
)
EXCLUSION_NATIONAL_PHONE = (
    "a number in national form, which the phone card states is deliberately not matched: the same "
    "digits name a different subscriber in every country and no default region exists"
)
EXCLUSION_CURRENCY_WORDS = (
    "an amount written with its currency spelled out in words, which both money cards list as not "
    "matched — they match a sign or an ISO 4217 code beside the amount"
)

# One entry per spec file: the path under Specs/, the scheme it reports as, the rule and entity
# type it is scored against, and whether upstream's resolved value is comparable with ours.
SOURCES = [
    ("DateTime/English/DateExtractor.json", "date.extractor", "date", "date"),
    ("DateTime/English/DateParser.json", "date.parser", "date", "date"),
    ("DateTime/English/DateTimeExtractor.json", "datetime.extractor", "date", "date"),
    ("DateTime/English/DateTimeParser.json", "datetime.parser", "date", "date"),
    ("NumberWithUnit/English/CurrencyModel.json", "currency", "money", "money"),
    ("Sequence/English/EmailModel.json", "email", "email.basic", "email"),
    ("Sequence/English/IpAddressModel.json", "ip", "network.ip", "network"),
    ("Sequence/English/PhoneNumberModel.json", "phone", "phone.international", "phone"),
]

# Which rule a date token belongs to, so the report names the rule that should have fired.
DATE_RULES = (
    (re.compile(r"^\["), "date.clf"),
    (re.compile(r"^\d{4}-?W", re.IGNORECASE), "date.iso_week"),
    (re.compile(r"^\w{3},"), "date.rfc2822"),
    (re.compile(r"."), "date.iso8601"),
)


def byte_offset(text: str, characters: int) -> int:
    return len(text[:characters].encode("utf-8"))


def locate(text: str, token: str, start):
    """Where the extraction sits in the sentence, in characters.

    Upstream gives `Start` on some recognisers and not others, and the `Text` it reports is its own
    normalised spelling (the email recogniser case-folds it), so a literal search has to fall back
    to a case-insensitive one before the case is dropped.
    """
    if isinstance(start, int) and text[start : start + len(token)].lower() == token.lower():
        return start
    found = text.find(token)
    if found >= 0:
        return found
    found = text.lower().find(token.lower())
    return found if found >= 0 else None


def value_of(resolution, scheme: str):
    """Upstream's normalised value, where it is the same kind of string ours is.

    Only the IPv4 half of the IP recogniser and the email recogniser resolve to something directly
    comparable. Upstream's phone resolution is the raw text rather than E.164, its currency
    resolution names the currency in English words rather than by ISO code, and its IPv6
    resolution echoes the spelling in the sentence instead of the RFC 5952 canonical form, so
    those are scored on entity type alone and the value column is left empty rather than filled
    with a string that was never meant to be compared.
    """
    if scheme not in ("ip", "email") or not isinstance(resolution, dict):
        return None
    if resolution.get("type") == "ipv6":
        return None
    value = resolution.get("value")
    return value if isinstance(value, str) else None


def rule_for(scheme: str, rule: str, token: str) -> str:
    if scheme.startswith("date") or scheme.startswith("datetime"):
        return next(name for pattern, name in DATE_RULES if pattern.search(token))
    if scheme == "currency":
        return "money.iso_code" if re.search(r"\b[A-Z]{3}\b", token) else "money.symbol"
    return rule


def exclusion_for(scheme: str, token: str):
    """The documented limit that keeps a case out of the scores, or `None`."""
    if scheme.startswith("date") or scheme.startswith("datetime"):
        return None if MACHINE_DATE.search(token) else EXCLUSION_NATURAL_DATE
    if scheme == "phone" and not token.startswith("+") and not token.startswith("00"):
        return EXCLUSION_NATIONAL_PHONE
    if scheme == "currency" and not CURRENCY_MARK.search(token):
        return EXCLUSION_CURRENCY_WORDS
    return None


def spec_cases(cases, path, scheme, rule, entity_type):
    with open(os.path.join(SPECS, path), encoding="utf-8") as handle:
        specs = json.load(handle)

    index = 0
    for spec in specs:
        text = spec["Input"]
        results = spec.get("Results") or []
        if not results:
            # Upstream names no span, so the token is the whole sentence: the question the scorer
            # then asks (did anything fire anywhere in it) is exactly upstream's assertion.
            index += 1
            cases.append(
                make(
                    index,
                    path,
                    scheme,
                    text,
                    text,
                    0,
                    len(text.encode("utf-8")),
                    False,
                    None,
                    rule,
                    entity_type,
                    None,
                )
            )
            continue

        for result in results:
            token = result.get("Text")
            if not token:
                continue
            start = locate(text, token, result.get("Start"))
            if start is None:
                continue
            # Upstream's `Text` is its own normalised form, which for email is case-folded; the
            # token has to be what the sentence actually says, or the offsets name nothing.
            token = text[start : start + len(token)]
            index += 1
            exclusion = exclusion_for(scheme, token)
            cases.append(
                make(
                    index,
                    path,
                    scheme,
                    text,
                    token,
                    byte_offset(text, start),
                    byte_offset(text, start + len(token)),
                    True,
                    value_of(result.get("Resolution"), scheme),
                    rule_for(scheme, rule, token),
                    entity_type,
                    exclusion,
                )
            )


def make(
    index,
    path,
    scheme,
    text,
    token,
    token_start,
    token_end,
    valid,
    expect,
    rule,
    entity_type,
    exclusion,
):
    return {
        "id": "recognizers:%s:%04d" % (scheme, index),
        "origin": ORIGIN,
        "source": "Specs/" + path,
        "scheme": scheme,
        "token": token,
        "text": text,
        "token_start": token_start,
        "token_end": token_end,
        # The text is upstream's own sentence, so no cue is ever synthesised: whatever cue words a
        # rule needs are either in the sentence upstream wrote or the rule does not fire.
        "cue": None,
        "valid": valid,
        "rule_id": rule if exclusion is None else None,
        "entity_type": entity_type if exclusion is None else None,
        "expect_value": expect if valid and exclusion is None else None,
        "exclusion": exclusion,
    }


def main() -> int:
    cases: list[dict] = []
    for path, scheme, rule, entity_type in SOURCES:
        spec_cases(cases, path, scheme, rule, entity_type)
    cases.sort(key=lambda item: item["id"])
    for item in cases:
        json.dump(item, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    print("%d cases" % len(cases), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
