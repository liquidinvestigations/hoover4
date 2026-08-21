#!/usr/bin/env python3
"""Turn one month of GitHub advisories into conformance cases for the CVE rule.

``vendored/reference/advisory-database/advisories/`` is a month of reviewed advisories in the OSV
schema. Two of their fields carry a CVE identifier, and they carry it differently, which is the
whole reason both are taken:

* ``aliases`` is the identifier on its own — the bare token, which goes into the neutral carrier
  sentence the other bare-token origins use.
* ``references[].url`` is the identifier inside an NVD or vendor URL. That is the surface context a
  document actually writes, with a slash on its left rather than a space, and the URL is kept as the
  fragment rather than re-housed because re-housing it would delete the thing being measured.

What this origin cannot do is worth stating beside what it can. `vulnerability.cve` is a literal
prefix, a year window and a digit count, so well-formed identifiers all pass and the score is 100%
by construction. **An origin that can only agree with us is a ratchet on nothing**: it holds the
rule against accidental narrowing and it measures nothing about precision, because the advisories
contain no malformed identifier to stay silent about.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import json
import os
import re
import sys

ADVISORIES = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "advisory-database",
    "advisories",
)

ORIGIN = "advisory-database"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

CVE = re.compile(r"CVE-\d{4}-\d{4,}")


def case(scheme, index, source, token, text, start):
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
        "valid": True,
        "rule_id": "vulnerability.cve",
        "entity_type": "vulnerability",
        "expect_value": token,
        "exclusion": None,
    }


def main() -> None:
    cases = []
    counters: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    for name in sorted(os.listdir(ADVISORIES)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(ADVISORIES, name), encoding="utf-8") as handle:
            advisory = json.load(handle)
        source = f"advisories/{name}"

        for alias in advisory.get("aliases", []):
            match = CVE.fullmatch(alias)
            if match is None or ("alias", alias) in seen:
                continue
            seen.add(("alias", alias))
            counters["alias"] = counters.get("alias", 0) + 1
            text = f"{CARRIER_PREFIX}{alias}{CARRIER_SUFFIX}"
            cases.append(
                case(
                    "alias",
                    counters["alias"],
                    source,
                    alias,
                    text,
                    len(CARRIER_PREFIX.encode("utf-8")),
                )
            )

        for reference in advisory.get("references", []):
            url = reference.get("url", "")
            match = CVE.search(url)
            if match is None or ("reference", url) in seen:
                continue
            seen.add(("reference", url))
            counters["reference"] = counters.get("reference", 0) + 1
            cases.append(
                case(
                    "reference",
                    counters["reference"],
                    source,
                    match.group(),
                    url,
                    len(url[: match.start()].encode("utf-8")),
                )
            )

    cases.sort(key=lambda item: item["id"])
    for item in cases:
        print(json.dumps(item, sort_keys=True, ensure_ascii=False))

    print(f"{len(cases)} cases, {len(cases)} scored, 0 excluded", file=sys.stderr)


if __name__ == "__main__":
    main()
