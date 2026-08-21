#!/usr/bin/env python3
"""Turn the reduced Crossref slice into conformance cases for the DOI and ORCID rules.

``vendored/reference/crossref/`` holds two queries against one publication day, already reduced to
the identifiers: a thousand works for their DOIs, and the same day filtered to works that carry an
ORCID, because an arbitrary day's author records carry one only a few times in a hundred.

Both schemes measure **recall only, and that is a property of the source rather than a choice**:
Crossref publishes registered identifiers, so there are no malformed ones in it to stay silent
about. `publication.orcid` has an ISO 7064 check digit, which makes the invalid examples the
interesting ones, and mutating a digit here would manufacture a token that nobody wrote — so those
negatives live in the rule's unit tests and this origin does not pretend to supply them.

An ORCID is published as a resolver URL, and the URL is the token: it is what upstream wrote, and
the identifier inside it is what the rule reports, which is exactly the arrangement a real document
presents. A DOI is published bare and goes into the neutral carrier sentence with the other
bare-token origins.

The script emits one JSON object per line on stdout, sorted by id, in the shape the Rust runner
reads. It runs inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import json
import os
import sys

DATA = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "vendored", "reference", "crossref"
)

ORIGIN = "crossref"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."


def slices():
    """Each reduced query file, with the file name that identifies it in a case."""
    for name in sorted(os.listdir(DATA)):
        if name.endswith(".json"):
            with open(os.path.join(DATA, name), encoding="utf-8") as handle:
                yield name, json.load(handle)["items"]


def case(scheme, index, source, token, rule_id, expect_value):
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
        "valid": True,
        "rule_id": rule_id,
        "entity_type": "publication",
        "expect_value": expect_value,
        "exclusion": None,
    }


def main() -> None:
    cases = []
    counters: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()

    for source, items in slices():
        for item in items:
            for scheme, token in [("doi", item["doi"])] + [
                ("orcid", value) for value in item["orcid"]
            ]:
                if (scheme, token) in seen:
                    continue
                seen.add((scheme, token))
                counters[scheme] = counters.get(scheme, 0) + 1
                # A DOI is case-insensitive, so the rule reports one spelling; an ORCID's value is
                # the identifier the resolver URL carries.
                expect_value = token.lower() if scheme == "doi" else token.rsplit("/", 1)[-1]
                rule_id = "publication.doi" if scheme == "doi" else "publication.orcid"
                cases.append(case(scheme, counters[scheme], source, token, rule_id, expect_value))

    cases.sort(key=lambda item: item["id"])
    for item in cases:
        print(json.dumps(item, sort_keys=True, ensure_ascii=False))

    print(f"{len(cases)} cases, {len(cases)} scored, 0 excluded", file=sys.stderr)


if __name__ == "__main__":
    main()
