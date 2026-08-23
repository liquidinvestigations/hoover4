#!/usr/bin/env python3
"""Turn the Open Location Code test data into conformance cases for the two coordinate rules.

``vendored/reference/open-location-code/test_data/`` is the specification's own conformance
material, and three of its four files answer three different questions:

* ``validityTests.csv`` is a code with the validity upstream asserts for it, and its invalid half is
  the adversarial set nobody could write for themselves: a plus sign in the wrong place, padding
  after data, a non-alphabet Unicode character in the middle, a bare separator.
* ``decoding.csv`` is a code with the cell its decode produces, as ``latLo,lngLo,latHi,lngHi``. The
  point a code names is the centre of that cell, which is what the rule reports, so the expected
  value is computed from the four corners rather than asserted here.
* ``encoding.csv`` and ``shortCodeTests.csv`` carry the latitude and longitude a code encodes as
  two adjacent comma-separated cells, which is the decimal rule's surface form exactly: the byte run
  ``20.3700625,2.7821875`` is in the file, so the token is upstream's and not something joined out
  of two columns.

Two implementations of the same code reach a coordinate by different arithmetic and disagree in the
last bits of the double. The runner compares a geographic point componentwise within a billionth of
a degree for that reason, so these cases carry the value upstream computed rather than a rounded
one.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import json
import os
import re
import sys

DATA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "open-location-code",
    "test_data",
)

ORIGIN = "open-location-code"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

# The decimal rule's own shape: a signed number with four to ten fractional digits on both sides of
# the comma. Reproduced here so the extractor's arithmetic and the rule's pattern agree about which
# rows are recall cases and which are an exclusion.
DECIMAL_PAIR = re.compile(r"([-+]?\d{1,3}[.]\d{4,10},[-+]?\d{1,3}[.]\d{4,10})")

# --------------------------------------------------------------------------------------------
# The exclusion reasons, each quoting the limit in the tracked tree it rests on
# --------------------------------------------------------------------------------------------

SHORT_CODE = (
    "a short code. The coord.plus_code card lists them under what is not checked: they omit the "
    "leading characters and are meaningless without a reference location this service does not "
    "hold, and the rule requires the full eight characters in front of the separator"
)
PADDED = (
    "a padded code. The card's first check is that every character is in the twenty-character "
    "alphabet, and the padding character `0` is not in it — a padded code names a cell whole "
    "degrees across rather than a place"
)
ENDS_AT_SEPARATOR = (
    "a code that stops at the separator. The rule claims the ten-character form the card names — "
    "eight characters, the plus sign and at least two more — and a code truncated in front of the "
    "separator names a cell a quarter of a kilometre across"
)
BEYOND_ELEVEN = (
    "a code longer than eleven characters. The card states that the grid refinement an eleventh "
    "character carries is not read, and the rule refuses a code with further characters outright "
    "rather than reporting a coarser point for it"
)
GRID_REFINEMENT = (
    "an eleven-character code, whose expected value is the centre of the refined cell. The card "
    "states that the refinement character is not read and that the point reported is the centre of "
    "the ten-character cell, so the difference is the documented resolution rather than a "
    "disagreement about the place"
)
LOWER_CASE = (
    "a code written in lower case; the alphabet in the card and in the rule is the upper-case one, "
    "and the compact upper-case form is the only one these rules match"
)
COARSE_PAIR = (
    "a coordinate pair with fewer than four fractional digits. src/rules/coordinates.rs states the "
    "limit and the reason: at three digits a pair of numbers is a pair of measurements as often as "
    "it is a place, and there is no arithmetic that tells the two apart"
)
OUT_OF_RANGE = (
    "a pair outside the range of latitudes and longitudes, which upstream's encoder clips before it "
    "encodes — the row exercises the clip. src/rules/coordinates.rs refuses a pair outside \u00b190 "
    "and \u00b1180 instead of clipping it, because a number out of range is a measurement that is "
    "not a place"
)
LONG_FRACTION = (
    "a coordinate pair with more than ten fractional digits, which the rule's pattern bounds; the "
    "guard against a slice of a longer number then refuses the truncated match, so the pair is not "
    "matched at all rather than matched short"
)


def rows(name: str):
    """The comment-free lines of one test-data file, split on commas."""
    path = os.path.join(DATA, name)
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line and not line.startswith("#"):
                yield line.split(",")


def code_exclusion(code: str):
    """The documented limit that keeps a plus code out of the scores, or `None`."""
    body, _, tail = code.partition("+")
    if len(body) != 8:
        return SHORT_CODE
    if "0" in code:
        return PADDED
    if not tail:
        return ENDS_AT_SEPARATOR
    if len(tail) > 3:
        return BEYOND_ELEVEN
    if code != code.upper():
        return LOWER_CASE
    return None


def in_range(latitude: str, longitude: str) -> bool:
    """Whether the pair names a point on the earth at all."""
    return abs(float(latitude)) <= 90 and abs(float(longitude)) <= 180


def case(scheme, index, source, token, valid, rule_id, expect_value, exclusion):
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
        "rule_id": None if exclusion else rule_id,
        "entity_type": None if exclusion else "coordinates",
        "expect_value": None if exclusion else expect_value,
        "exclusion": exclusion,
    }


def validity_cases():
    """`code,isValid,isShort,isFull`, the valid half measures recall, the invalid half precision.

    An upstream-invalid code is never excluded: what it measures is whether the rule stays silent
    on it, which is the whole of the precision evidence this origin supplies for plus codes.
    """
    for index, row in enumerate(rows("validityTests.csv"), start=1):
        code, is_valid = row[0], row[1] == "true"
        exclusion = code_exclusion(code) if is_valid else None
        yield case(
            "plus_code",
            index,
            "test_data/validityTests.csv",
            code,
            is_valid,
            "coord.plus_code",
            None,
            exclusion,
        )


def decoding_cases(start_index: int):
    """`code,length,latLo,lngLo,latHi,lngHi`, the cell, whose centre is the point the code names."""
    index = start_index
    for row in rows("decoding.csv"):
        code = row[0]
        latitude = (float(row[2]) + float(row[4])) / 2
        longitude = (float(row[3]) + float(row[5])) / 2
        exclusion = code_exclusion(code)
        if exclusion is None and len(code.partition("+")[2]) == 3:
            exclusion = GRID_REFINEMENT
        index += 1
        yield case(
            "plus_code",
            index,
            "test_data/decoding.csv",
            code,
            True,
            "coord.plus_code",
            f"{latitude!r},{longitude!r}",
            exclusion,
        )


def pair_cases():
    """The latitude and longitude cells, which sit side by side in the file as one byte run."""
    index = 0
    seen = set()
    for name, columns in (("encoding.csv", (0, 1)), ("shortCodeTests.csv", (1, 2))):
        for row in rows(name):
            latitude, longitude = row[columns[0]], row[columns[1]]
            token = f"{latitude},{longitude}"
            if token in seen:
                continue
            seen.add(token)
            if not in_range(latitude, longitude):
                exclusion = OUT_OF_RANGE
            elif DECIMAL_PAIR.fullmatch(token):
                exclusion = None
            elif any(len(half.partition(".")[2]) > 10 for half in (latitude, longitude)):
                exclusion = LONG_FRACTION
            else:
                exclusion = COARSE_PAIR
            index += 1
            yield case(
                "decimal",
                index,
                f"test_data/{name}",
                token,
                True,
                "coord.decimal",
                token,
                exclusion,
            )


def main() -> None:
    cases = list(validity_cases())
    cases.extend(decoding_cases(len(cases)))
    cases.extend(pair_cases())
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
