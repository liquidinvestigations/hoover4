#!/usr/bin/env python3
"""Turn libphonenumber's own test material into normalised conformance cases.

Two corpora come out of ``vendored/reference/libphonenumber/``:

``PhoneNumberMetadata.xml``
    Every region carries an ``<exampleNumber>`` for every line type it issues — fixed line,
    mobile, toll free, premium rate, shared cost, personal number, VoIP, UAN, voicemail, pager.
    That is a labelled corpus of over a thousand numbers written by the people who maintain the
    numbering plans, each already tagged with the region and the line type our ``Value::Phone``
    reports.

``PhoneNumberMatcherTest.java``
    The matcher's free-text corpus: strings that are number-like, each labelled with the leniency
    level at which libphonenumber's own text matcher accepts it.

**The example numbers are national significant numbers, and are rendered here in international
form.** ``phone.international`` matches international form only and says so on its card; upstream's
own test calls ``parse(exampleNumber, region)``, which supplies the region out of band. Prefixing
the country calling code is the faithful way to supply the same information inside the text, which
is the only channel a scanner has. Leaving them national and scoring them as misses would be
measuring the documented absence of a national-format rule a thousand times over.

The matcher's leniency corpus is scored against libphonenumber's *fabricated* test metadata
(``PhoneNumberMetadataForTesting.xml``, which we do not vendor: "US numbers cannot start with 7 in
the test metadata to be valid"), so the ranges it asserts are not the ranges our rule validates
against. Only the two parts that survive that gap are scored — see ``main``.

The script emits one JSON object per line on stdout, in the shape the Rust runner reads. It runs
inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import json
import os
import re
import sys
import xml.etree.ElementTree as ElementTree

ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "libphonenumber",
)

ORIGIN = "libphonenumber"
RULE = "phone.international"
ENTITY_TYPE = "phone"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

# The line types that carry an example number, in the metadata's own element names, mapped to the
# snake-case names `Value::Phone::number_type` reports. `fixedLine` and `mobile` are also the two
# that a region may merge into `fixed_line_or_mobile`, which is why the scheme is the metadata's
# element rather than our reported type — the scheme has to name what upstream asserted.
LINE_TYPES = {
    "fixedLine": "fixed_line",
    "mobile": "mobile",
    "pager": "pager",
    "tollFree": "toll_free",
    "premiumRate": "premium_rate",
    "sharedCost": "shared_cost",
    "personalNumber": "personal_number",
    "voip": "voip",
    "uan": "uan",
    "voicemail": "voicemail",
}

EXCLUSION_TEST_METADATA = (
    "the matcher's leniency corpus is scored against libphonenumber's fabricated test metadata, "
    "not the production numbering ranges the phone rule validates against, so upstream's verdict "
    "is not a claim about these digits"
)
EXCLUSION_IS_A_DATE = (
    "upstream asserts only that the string is not a telephone number; it is a machine-readable "
    "date, which the date rules match by design, and any overlapping entity fails an invalid case"
)


def case(
    identifier,
    source,
    scheme,
    token,
    valid,
    expect,
    exclusion,
    rule=RULE,
    entity_type=ENTITY_TYPE,
):
    """One line of the case file. The phone rule is not cue-gated, so no cue is ever supplied."""
    text = CARRIER_PREFIX + token + CARRIER_SUFFIX
    return {
        "id": identifier,
        "origin": ORIGIN,
        "source": source,
        "scheme": scheme,
        "token": token,
        "text": text,
        "token_start": len(CARRIER_PREFIX.encode("utf-8")),
        "token_end": len(CARRIER_PREFIX.encode("utf-8")) + len(token.encode("utf-8")),
        "cue": None,
        "valid": valid,
        "rule_id": rule if exclusion is None else None,
        "entity_type": entity_type if exclusion is None else None,
        "expect_value": expect,
        "exclusion": exclusion,
    }


def example_numbers(cases):
    """Every ``<exampleNumber>`` in the metadata, rendered in international form."""
    tree = ElementTree.parse(os.path.join(ROOT, "PhoneNumberMetadata.xml"))
    counters: dict[str, int] = {}
    for territory in tree.getroot().iter("territory"):
        region = territory.get("id")
        country_code = territory.get("countryCode")
        if not country_code:
            continue
        for element, number_type in LINE_TYPES.items():
            child = territory.find(element)
            if child is None:
                continue
            example = child.find("exampleNumber")
            if example is None or not example.text:
                continue
            national = example.text.strip()
            # E.164 is the country calling code followed by the national significant number, with
            # nothing between them: the same string the rule normalises to.
            token = "+" + country_code + national
            scheme = "example." + number_type
            counters[scheme] = counters.get(scheme, 0) + 1
            cases.append(
                case(
                    "libphonenumber:%s:%s:%04d"
                    % (scheme, region, counters[scheme]),
                    "resources/PhoneNumberMetadata.xml",
                    scheme,
                    token,
                    True,
                    token,
                    None,
                )
            )


JAVA_ESCAPES = re.compile(r"\\u([0-9a-fA-F]{4})")
NUMBER_TEST = re.compile(r'new NumberTest\("((?:[^"\\]|\\.)*)"')
ARRAY_HEAD = re.compile(r"private static final NumberTest\[\] (\w+) = \{")
FIND_IN_CONTEXT = re.compile(r"doTestFindInContext\(\s*(.*?),\s*(?:RegionCode\.\w+|null)\)", re.S)
STRING_LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')

# A machine-readable date the date rules claim: an ISO 8601 calendar date, alone or followed by a
# clock. Nothing else in the impossible corpus is a format any rule in the tree matches.
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def unescape(raw: str) -> str:
    return JAVA_ESCAPES.sub(lambda m: chr(int(m.group(1), 16)), raw).replace('\\"', '"')


def matcher_source() -> str:
    with open(
        os.path.join(ROOT, "PhoneNumberMatcherTest.java"), encoding="utf-8"
    ) as handle:
        return handle.read()


def number_test_arrays(source: str):
    """Each ``NumberTest[]`` array in the matcher test, as (name, [raw string, ...])."""
    for head in ARRAY_HEAD.finditer(source):
        end = source.index("};", head.end())
        body = source[head.end() : end]
        yield head.group(1), [unescape(m.group(1)) for m in NUMBER_TEST.finditer(body)]


def leniency_cases(cases):
    """The matcher's labelled number-like strings.

    ``IMPOSSIBLE_CASES`` is the one array whose verdict survives the change of metadata: dates,
    five-digit runs and digit groups split by plus signs are not telephone numbers under any
    numbering plan. The rest assert that a *specific fabricated range* is matched, and are counted
    and excluded rather than scored.
    """
    for name, tokens in number_test_arrays(matcher_source()):
        scheme = "matcher." + name.lower().replace("_cases", "")
        for index, token in enumerate(tokens, start=1):
            if name == "IMPOSSIBLE_CASES":
                exclusion = (
                    EXCLUSION_IS_A_DATE if ISO_DATE.search(token) else None
                )
            else:
                exclusion = EXCLUSION_TEST_METADATA
            cases.append(
                case(
                    "libphonenumber:%s:%04d" % (scheme, index),
                    "java/libphonenumber/test/com/google/i18n/phonenumbers/"
                    "PhoneNumberMatcherTest.java",
                    scheme,
                    token,
                    False,
                    None,
                    exclusion,
                )
            )


def context_cases(cases):
    """The international-form numbers the matcher test embeds in prose.

    ``doTestFindInContext`` asserts that a match is found for the number in fifty surrounding
    contexts. Where the number is written with a leading plus, the assertion needs no region and
    survives into real metadata: these are the punctuation spellings — brackets, dots, slashes,
    extension suffixes, full-width digits — that a scanner meets in prose. Upstream documents no
    canonical form for them, so they are scored on entity type alone.
    """
    seen = set()
    index = 0
    for match in FIND_IN_CONTEXT.finditer(matcher_source()):
        # The argument is sometimes several literals joined with `+` across two source lines, and
        # half of a full-width number is not a case.
        token = unescape("".join(STRING_LITERAL.findall(match.group(1))))
        if not token.startswith("+") and not token.startswith("＋"):
            continue
        if token in seen:
            continue
        seen.add(token)
        index += 1
        cases.append(
            case(
                "libphonenumber:matcher.context:%04d" % index,
                "java/libphonenumber/test/com/google/i18n/phonenumbers/"
                "PhoneNumberMatcherTest.java",
                "matcher.context",
                token,
                True,
                None,
                None,
            )
        )


def main() -> int:
    cases: list[dict] = []
    example_numbers(cases)
    leniency_cases(cases)
    context_cases(cases)
    cases.sort(key=lambda item: item["id"])
    for item in cases:
        json.dump(item, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    print("%d cases" % len(cases), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
