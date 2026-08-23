#!/usr/bin/env python3
"""Turn Presidio's recogniser tests into normalised conformance cases.

``vendored/reference/presidio/tests/`` holds one test module per predefined recogniser, and each is
a ``pytest.mark.parametrize`` list of ``(text, expected_len, expected_positions, ...)`` rows: a
fragment, how many spans upstream asserts are in it, and where. That is the shape of the question
this service is asked (an identifier sitting inside a sentence) rather than a validator called on
a bare token, which is why this origin is the one that measures the rules whose subjects only ever
appear in prose.

Three things follow from the corpus rather than from a choice:

* **Upstream's fragment is what gets scanned** wherever upstream wrote a fragment. Many rows are a
  bare token with nothing around it, and those take the carrier sentence the other bare-token
  origins use, because a token with no sentence around it measures the pattern instead of the rule.
* **A row asserting zero spans is an invalid case** whose token is the whole fragment. Upstream
  names no span to point at, and the scorer's overlap test then asks upstream's own question: did
  anything of this kind fire in a fragment upstream says holds none of it.
* **A row that names no span at all** (the modules parametrised on ``text, expected_len`` alone)
  is recorded with the whole fragment as the token, which asks the same weaker question in the
  valid direction: did the right type fire anywhere in it.

Presidio recognises far more entity types than this rule set implements. Driver's licences,
passports, medical and tax numbers for two dozen countries, US SSNs. Those are excluded for the
plainest reason there is, the absence of a rule, and the exclusion count is printed beside the
score so the coverage figure cannot be mistaken for a recall figure.

The script emits one JSON object per line on stdout, in the shape the Rust runner reads. It runs
inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

TESTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "presidio",
    "tests",
)

ORIGIN = "presidio"

CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

# Scheme -> (rule id, wire entity type). Everything not named here has no rule and is excluded.
SCORED = {
    "aba_routing": ("bank.aba_routing", "bank_account"),
    "credit_card": ("bank.payment_card", "bank_account"),
    "crypto": ("crypto.bitcoin", "crypto_wallet"),
    "date": ("date.iso8601", "date"),
    "de_vat_id": ("company.vat_eu", "company_id"),
    "email": ("email.basic", "email"),
    "es_nie": ("natid.es_nif_nie", "national_id"),
    "es_nif": ("natid.es_nif_nie", "national_id"),
    "iban": ("bank.iban", "bank_account"),
    "in_pan": ("natid.in_pan", "national_id"),
    "ip": ("network.ip", "network"),
    "it_fiscal_code": ("natid.it_codice_fiscale", "national_id"),
    "it_vat_code": ("company.vat_eu", "company_id"),
    "mac": ("device.mac", "device"),
    "ph_mobile_number": ("phone.international", "phone"),
    "phone": ("phone.international", "phone"),
    "pl_pesel": ("natid.pl_pesel", "national_id"),
    "se_organisationsnummer": ("company.se_organisationsnummer", "company_id"),
    "se_personnummer": ("natid.se_personnummer", "national_id"),
    "tr_phone_number": ("phone.international", "phone"),
    "za_mobile_number": ("phone.international", "phone"),
    "za_telephone_number": ("phone.international", "phone"),
}

# The cue a rule requires before it will look at a token at all. Supplied only into a carrier
# sentence, and only for the rule that requires it. Supplying one to a rule that needs none would
# measure a rule that does not run in production.
CUES = {
    "aba_routing": "routing number",
    "credit_card": "card",
    "in_pan": "PAN",
    "pl_pesel": "PESEL",
    "se_organisationsnummer": "orgnr",
    "se_personnummer": "personnummer",
}

# The machine-readable date formats the four date rules claim. Anything else in Presidio's date
# module is a human-written date, which is the documented absence of a rule rather than a miss.
MACHINE_DATE = re.compile(
    r"""
    \d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2})?           # ISO 8601 date, optionally with a clock
  | \d{4}-?W\d{2}(-?\d)?                          # ISO week date
  | \[\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}         # Common Log Format timestamp
  | \w{3},\s\d{1,2}\s\w{3}\s\d{4}                 # mail-header date
    """,
    re.VERBOSE,
)

PHONE_SCHEMES = (
    "ph_mobile_number",
    "phone",
    "tr_phone_number",
    "za_mobile_number",
    "za_telephone_number",
)

RESERVED_MAC = re.compile(r"(?:FF[:-]){5}FF|(?:00[:-]){5}00", re.IGNORECASE)

# A dotted run with a fifth component behind it: `192.168.1.1.1`. The address rule refuses a
# slice of one, so upstream naming the first four as the address is a disagreement about a
# documented guard rather than about the address format.
LONGER_DOTTED_RUN = re.compile(r"^\.\d")

DATE_RULES = (
    (re.compile(r"^\["), "date.clf"),
    (re.compile(r"^\d{4}-?W"), "date.iso_week"),
    (re.compile(r"^\w{3},"), "date.rfc2822"),
    (re.compile(r"."), "date.iso8601"),
)

EXCLUSION_NO_RULE = "no rule for this entity type"
EXCLUSION_NATURAL_DATE = (
    "no rule matches this date format: the date rules ship the machine-readable formats that fix a "
    "whole day — ISO 8601, the ISO week date, the mail-header date and the web-server log "
    "timestamp — while upstream's recogniser also matches human-written and partial dates"
)
EXCLUSION_NATIONAL_PHONE = (
    "a number in national form, which the phone card states is deliberately not matched: the same "
    "digits name a different subscriber in every country and no default region exists"
)
EXCLUSION_COMPACT_ONLY = (
    "the compact upper-case form is the only one these rules match, which their cards state; "
    "upstream's recogniser strips separators and case before it validates"
)
EXCLUSION_VAT_PREFIX = (
    "a VAT number written without its country prefix; company.vat_eu matches the prefixed VATIN, "
    "because the prefix is what says which country's arithmetic to run"
)
EXCLUSION_IT_CF_COMPANY = (
    "the eleven-digit company form; the rule claims the sixteen-character tax code issued to "
    "individuals"
)
EXCLUSION_ES_CIF = (
    "the CIF form issued to companies, which the card lists as not matched: it shares the length "
    "and uses a different check"
)
EXCLUSION_UPSTREAM_HEURISTIC = (
    "upstream's own test name says this row runs its heuristic mode, which asserts the shape and "
    "skips the check digit; every identifier rule here validates before it emits, so the row makes "
    "no claim the two engines can disagree about"
)
EXCLUSION_UPSTREAM_WEAK = (
    "upstream asserts a confidence of %.2f, its grade for a token whose shape matched and whose "
    "content was never verified; that is not an assertion of validity for a validating rule to "
    "agree with"
)
EXCLUSION_PHONE_ONE_COUNTRY = (
    "upstream asserts the token is not a valid number of one country's one kind — its recogniser "
    "is per-country — while phone.international asserts only that an international number is "
    "routable under the numbering plan its calling code names"
)
EXCLUSION_MAC_RESERVED = (
    "the broadcast and all-zero addresses, which upstream drops because they identify no device; "
    "device.mac claims the address format, and both are well-formed in it"
)
EXCLUSION_IP_LONGER_RUN = (
    "a slice of a dotted run longer than four components, which src/rules/network.rs refuses by "
    "name: a five-component run is not an address, and matching its first four is a wrong value "
    "rather than a miss"
)
EXCLUSION_ROUTING_HYPHENATED = (
    "the hyphenated fractional spelling, which the routing card lists as not matched: nine digits "
    "behind a one-in-ten checksum do not buy separator tolerance"
)
EXCLUSION_BITCOIN_ONLY = (
    "an address outside the Bitcoin family; crypto.bitcoin claims P2PKH, P2SH and Bech32 "
    "addresses, and crypto.ethereum the 0x form, and upstream's pattern is broader than either"
)


def byte_offset(text: str, characters: int) -> int:
    return len(text[:characters].encode("utf-8"))


def scheme_of(filename: str) -> str:
    return filename[len("test_") : -len("_recognizer.py")]


def parametrized_rows(path: str):
    """Every `parametrize` row in the module that carries a fragment and a span count.

    Read with `ast`: a row is a literal tuple, and a decorator's own argument names say which
    element is which. Rows that are not literals (the ones built from a helper call) are skipped
    rather than guessed at.
    """
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or len(decorator.args) < 2:
                continue
            if getattr(decorator.func, "attr", None) != "parametrize":
                continue
            try:
                names = ast.literal_eval(decorator.args[0])
                rows = ast.literal_eval(decorator.args[1])
            except (ValueError, SyntaxError, TypeError):
                continue
            if isinstance(names, str):
                names = [name.strip() for name in names.split(",")]
            if "expected_len" not in names:
                continue
            # A handful of modules name the fragment after what is in it: `iban, expected_len,
            # expected_res`, rather than `text`. The first column is the fragment either way.
            if "text" not in names:
                names = ["text"] + list(names[1:])
            for row in rows:
                if not isinstance(row, tuple) or len(row) != len(names):
                    continue
                mapped = dict(zip(names, row))
                mapped["_function"] = node.name
                yield mapped


def spans_of(row):
    """The (start, end) character spans upstream asserts, or `None` when it names none."""
    for key in ("expected_positions", "expected_res", "expected_position"):
        value = row.get(key)
        if not value:
            continue
        if isinstance(value, tuple) and len(value) == 2 and all(
            isinstance(item, int) for item in value
        ):
            return [value]
        spans = [item for item in value if isinstance(item, tuple) and len(item) == 2]
        return spans or None
    if isinstance(row.get("expected_start"), int) and isinstance(row.get("expected_end"), int):
        return [(row["expected_start"], row["expected_end"])]
    return None


def asserted_score(row):
    """The confidence upstream asserts for the row, or `None` where it asserts none.

    Presidio's pattern recognisers grade themselves: 0.5 is a shape its own comments call medium,
    and 0.1 or 0.01 is a shape it will surface for a human to look at. A row asserting one of the
    low grades is not upstream saying the token is a valid identifier, so it is not a case a
    validating rule can be scored against.
    """
    value = row.get("expected_score")
    if isinstance(value, (int, float)):
        return float(value)
    ranges = row.get("expected_score_ranges")
    if isinstance(ranges, tuple) and ranges and isinstance(ranges[0], tuple):
        low = ranges[0][0]
        if isinstance(low, (int, float)):
            return float(low)
    return None


def documented_exclusion(scheme: str, token: str, tail: str, valid: bool, function: str, score):
    """The limit written in the tracked tree that keeps a case out of the scores, or `None`.

    Out-of-scope is a category, not a failure, but only when the limit is written down, either in
    this rule set's cards and docs or in upstream's own assertion. Every branch names one.
    """
    if scheme not in SCORED:
        return EXCLUSION_NO_RULE
    if valid and "heuristic" in function:
        return EXCLUSION_UPSTREAM_HEURISTIC
    if valid and score is not None and score < 0.4:
        return EXCLUSION_UPSTREAM_WEAK % score
    if scheme == "date":
        return None if MACHINE_DATE.search(token) else EXCLUSION_NATURAL_DATE
    if scheme in PHONE_SCHEMES:
        if scheme != "phone" and not valid:
            return EXCLUSION_PHONE_ONE_COUNTRY
        if not token.lstrip("_: ").startswith(("+", "00")):
            return EXCLUSION_NATIONAL_PHONE
        return None
    if scheme == "aba_routing" and not token.isdigit():
        return EXCLUSION_ROUTING_HYPHENATED
    if scheme == "mac" and not valid and RESERVED_MAC.search(token):
        return EXCLUSION_MAC_RESERVED
    if scheme == "ip" and LONGER_DOTTED_RUN.match(tail):
        return EXCLUSION_IP_LONGER_RUN
    if scheme == "it_vat_code":
        return EXCLUSION_VAT_PREFIX
    if scheme in ("es_nif", "es_nie"):
        if token[:1].isalpha() and token[0].upper() not in "XYZKLM":
            return EXCLUSION_ES_CIF
        if token != token.upper() or not token.isalnum():
            return EXCLUSION_COMPACT_ONLY
        return None
    if scheme == "it_fiscal_code":
        compact = "".join(character for character in token if character.isalnum())
        if len(compact) != 16:
            return EXCLUSION_IT_CF_COMPANY
        if token != token.upper() or not token.isalnum():
            return EXCLUSION_COMPACT_ONLY
        return None
    if scheme == "de_vat_id" and (token != token.upper() or not token.isalnum()):
        return EXCLUSION_COMPACT_ONLY
    if scheme == "crypto" and not token.startswith(("1", "3", "bc1", "0x")):
        return EXCLUSION_BITCOIN_ONLY
    return None


def rule_for(scheme: str, token: str) -> str:
    if scheme == "date":
        return next(name for pattern, name in DATE_RULES if pattern.search(token))
    if scheme == "crypto" and token.startswith("0x"):
        return "crypto.ethereum"
    return SCORED[scheme][0]


def case(index, scheme, text, token, start, end, valid, cue, exclusion):
    rule = rule_for(scheme, token) if exclusion is None else None
    entity_type = SCORED[scheme][1] if exclusion is None else None
    return {
        "id": "presidio:%s:%04d" % (scheme, index),
        "origin": ORIGIN,
        "source": "tests/test_%s_recognizer.py" % scheme,
        "scheme": scheme,
        "token": token,
        "text": text,
        "token_start": start,
        "token_end": end,
        "cue": cue,
        "valid": valid,
        "rule_id": rule,
        "entity_type": entity_type,
        # Presidio asserts a span, never a canonical value (it redacts rather than normalises), so
        # there is no upstream value to compare against and every scored case is type-only.
        "expect_value": None,
        "exclusion": exclusion,
    }


def housed(text: str, token: str, start: int, end: int, scheme: str):
    """Where the case is scanned: upstream's own fragment, or the carrier around a bare token.

    A row whose fragment is one unbroken token has no sentence in it, and scanning a bare token measures
    the pattern rather than the rule, the guards that make a rule trustworthy are all about what
    stands next to a match. Those rows go into the same neutral carrier the bare-token origins use,
    and it is the only place a cue word is ever supplied.
    """
    if text != token or text.split() != [text]:
        return text, byte_offset(text, start), byte_offset(text, end), None
    cue = CUES.get(scheme)
    prefix = CARRIER_PREFIX + (cue + " " if cue else "")
    fragment = prefix + token + CARRIER_SUFFIX
    offset = len(prefix.encode("utf-8"))
    return fragment, offset, offset + len(token.encode("utf-8")), cue


def module_cases(path: str, scheme: str):
    index = 0
    seen = set()
    for row in parametrized_rows(path):
        text = row.get("text")
        expected = row.get("expected_len")
        if not isinstance(text, str) or not text.strip() or not isinstance(expected, int):
            continue
        spans = spans_of(row) if expected else None
        if spans and len(spans) != expected:
            spans = None
        if spans:
            pairs = [(text[start:end], start, end) for start, end in spans]
        else:
            # Upstream names no span: the whole fragment is the token, which asks "did anything of
            # this kind fire in here". Exactly the assertion upstream makes in that form.
            pairs = [(text, 0, len(text))]
        for token, start, end in pairs:
            if not token.strip():
                continue
            key = (text, token, start, end, bool(expected))
            if key in seen:
                continue
            seen.add(key)
            fragment, token_start, token_end, cue = housed(text, token, start, end, scheme)
            index += 1
            yield case(
                index,
                scheme,
                fragment,
                token,
                token_start,
                token_end,
                bool(expected),
                cue,
                documented_exclusion(
                    scheme,
                    token,
                    text[end:],
                    bool(expected),
                    row.get("_function", ""),
                    asserted_score(row),
                ),
            )


def main() -> int:
    cases = []
    for filename in sorted(os.listdir(TESTS)):
        if not filename.startswith("test_") or not filename.endswith("_recognizer.py"):
            continue
        cases.extend(module_cases(os.path.join(TESTS, filename), scheme_of(filename)))
    cases.sort(key=lambda item: item["id"])
    for item in cases:
        json.dump(item, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    scored = sum(1 for item in cases if item["exclusion"] is None)
    print("%d cases, %d scored" % (len(cases), scored), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
