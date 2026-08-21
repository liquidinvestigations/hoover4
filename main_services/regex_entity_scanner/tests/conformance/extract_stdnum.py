#!/usr/bin/env python3
"""Turn the python-stdnum doctests into normalised conformance cases.

Every module under ``vendored/reference/python-stdnum/stdnum/`` documents its scheme with
``>>> validate(...)`` lines whose expected output is either the canonical form of the number or a
traceback naming one of the library's own exceptions. That is a labelled valid/invalid corpus
written by the people who implement the scheme, which is exactly what an upstream conformance run
needs.

The script emits one JSON object per line on stdout, in the shape the Rust runner reads. It is run
inside the dev container; the case file it writes is checked in, so a conformance run never depends
on re-extraction.
"""

from __future__ import annotations

import ast
import doctest
import json
import os
import sys

STDNUM_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..",
    "..",
    "vendored",
    "reference",
    "python-stdnum",
)

ORIGIN = "python-stdnum"

# The carrier. An upstream test calls an API on a bare token; we scan free text, so every token is
# placed in the same neutral sentence. The words carry no digits, no currency symbol and no cue
# word of their own, so the only thing the scanner can find in a case is the token itself.
CARRIER_PREFIX = "The record shows "
CARRIER_SUFFIX = " on the form."

# Rules that require a cue word near the candidate get that scheme's own documented cue, because
# calling `stdnum.cusip.validate` is itself the statement "this is a CUSIP". A cue is never
# supplied to a rule that does not require one.
DIRECT = {
    # module               scheme            rule                       entity type       cue
    "iban": ("iban", "bank.iban", "bank_account", None),
    "bic": ("bic", "bank.bic", "bank_account", "BIC"),
    "us.rtn": ("us_rtn", "bank.aba_routing", "bank_account", "routing number"),
    "iso9362": ("bic", "bank.bic", "bank_account", "BIC"),
    "lei": ("lei", "company.lei", "company_id", None),
    "isin": ("isin", "security.isin", "security", None),
    "cusip": ("cusip", "security.cusip", "security", "CUSIP"),
    "gb.sedol": ("sedol", "security.sedol", "security", "SEDOL"),
    "imo": ("imo", "vessel.imo", "vessel", "IMO"),
    "iso6346": ("iso6346", "container.iso6346", "cargo_container", None),
    "imei": ("imei", "device.imei", "device", "IMEI"),
    "it.codicefiscale": (
        "it_codice_fiscale",
        "natid.it_codice_fiscale",
        "national_id",
        None,
    ),
    "es.nif": ("es_nif_nie", "natid.es_nif_nie", "national_id", None),
    "es.nie": ("es_nif_nie", "natid.es_nif_nie", "national_id", None),
    "mx.curp": ("mx_curp", "natid.mx_curp", "national_id", None),
    "in_.pan": ("in_pan", "natid.in_pan", "national_id", "PAN"),
    "pl.pesel": ("pl_pesel", "natid.pl_pesel", "national_id", "PESEL"),
    "se.personnummer": (
        "se_personnummer",
        "natid.se_personnummer",
        "national_id",
        "personnummer",
    ),
    "se.orgnr": (
        "se_orgnr",
        "company.se_organisationsnummer",
        "company_id",
        "orgnr",
    ),
    "eu.vat": ("vat.eu", "company.vat_eu", "company_id", None),
    "vatin": ("vat.vatin", "company.vat_eu", "company_id", None),
}

# The VAT families. `stdnum.<cc>.vat` is frequently an alias for the state's company-register or
# personal-number module, so the module names come from the library's own resolution table
# (`stdnum.eu.vat._get_cc_module`) rather than from a guess. A national module's `validate` asserts
# the same arithmetic our VATIN rule applies behind the country prefix, so the prefix is prepended
# to both the token and the expected value when the upstream form does not already carry it.
VAT_EU = {
    "at.uid": "AT",
    "be.vat": "BE",
    "bg.vat": "BG",
    "cy.vat": "CY",
    "cz.dic": "CZ",
    "de.vat": "DE",
    "dk.cvr": "DK",
    "ee.kmkr": "EE",
    "es.nif": "ES",
    "fi.alv": "FI",
    "fr.tva": "FR",
    "gr.vat": "EL",
    "hr.oib": "HR",
    "hu.anum": "HU",
    "ie.vat": "IE",
    "it.iva": "IT",
    "lt.pvm": "LT",
    "lu.tva": "LU",
    "lv.pvn": "LV",
    "mt.vat": "MT",
    "nl.btw": "NL",
    "pl.nip": "PL",
    "pt.nif": "PT",
    "ro.cf": "RO",
    "se.vat": "SE",
    "si.ddv": "SI",
    "sk.dph": "SK",
}

VAT_NON_EU = {
    "ch.vat": "CH",
    "gb.vat": "GB",
    "me.pib": "ME",
    "mk.edb": "MK",
    "no.mva": "NO",
    "rs.pib": "RS",
    "ru.inn": "RU",
    "tr.vkn": "TR",
}

# The country prefixes the VATIN rules carry arithmetic for. A `vatin` doctest for any other
# country is an unimplemented scheme, not a miss.
VAT_PREFIXES = set(VAT_EU.values()) | set(VAT_NON_EU.values())

EXCLUSION_NO_RULE = "no rule for this scheme"
EXCLUSION_EXTRA_ARGS = "upstream call takes arguments our API does not offer"
EXCLUSION_PREFIX = "VATIN country prefix not implemented"

# Whole modules whose assertion is not the one our rule makes. Each names the rule's own card,
# because an exclusion that is not traceable to a documented limit is a thumb on the scale.
EXCLUDED_MODULES = {
    key: (
        "country-specific IBAN module: it asserts the national check digits inside the account "
        "number and that the number belongs to that one country, and bank.iban claims neither"
    )
    for key in ("be.iban", "es.iban", "me.iban", "no.iban")
}


def alphanumeric(value: str) -> str:
    return "".join(character for character in value if character.isalnum())


def documented_exclusion(scheme: str, token: str):
    """Formats a rule's explainer card states it does not match.

    Out-of-scope is a category, not a failure — but only when the limit is written down in the
    tracked tree. Every branch here quotes one, so the exclusion can be checked without trusting
    this script.
    """
    if scheme.startswith("vat.") and any(not c.isalnum() for c in token):
        return (
            "the VAT rules match the compact form only, prefix immediately followed by the body; "
            "their cards list numbers written with invoice separators as not matched"
        )
    if scheme == "imei" and len([c for c in token if c.isdigit()]) == 16:
        return (
            "the sixteen-digit IMEISV form, which the card states carries a software version "
            "instead of a check digit and is not matched"
        )
    if scheme == "it_codice_fiscale" and len(alphanumeric(token)) != 16:
        return (
            "the eleven-digit company form; the rule claims the sixteen-character tax code "
            "issued to individuals"
        )
    if scheme == "es_nif_nie" and token[:1].isalpha() and token[0].upper() not in "XYZKLM":
        return (
            "the CIF form issued to companies, which the card lists as not matched: it shares the "
            "length and uses a different check"
        )
    return None


def module_key(path: str) -> str:
    """`stdnum/be/vat.py` -> `be.vat`, `stdnum/iban.py` -> `iban`."""
    relative = os.path.relpath(path, os.path.join(STDNUM_ROOT, "stdnum"))
    return relative[: -len(".py")].replace(os.sep, ".")


def docstring_examples(path: str):
    """Every doctest example in the module docstring, as (source, want, exc_msg)."""
    with open(path, encoding="utf-8") as handle:
        source = handle.read()
    try:
        text = ast.get_docstring(ast.parse(source))
    except SyntaxError:
        return []
    if not text:
        return []
    return doctest.DocTestParser().get_examples(text)


def parse_call(source: str):
    """`validate('X')` -> ("validate", "X", False); anything else -> None."""
    try:
        tree = ast.parse(source.strip())
    except SyntaxError:
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.Expr):
        return None
    call = tree.body[0].value
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
        return None
    if call.func.id not in ("validate", "is_valid"):
        return None
    if not call.args or not isinstance(call.args[0], ast.Constant):
        return None
    argument = call.args[0].value
    if not isinstance(argument, str):
        return None
    extra = len(call.args) > 1 or bool(call.keywords)
    return call.func.id, argument, extra


def outcome(want: str, exc_msg):
    """The label: (valid, expected upstream form or None)."""
    if exc_msg is not None:
        return False, None
    want = want.strip()
    if want in ("True", "False"):
        return want == "True", None
    try:
        literal = ast.literal_eval(want)
    except (SyntaxError, ValueError):
        return None, None
    if isinstance(literal, str):
        return True, literal
    return None, None


def prefixed(value: str, prefix: str) -> str:
    return value if value[:2].upper() == prefix[:2].upper() else prefix + value


def case(index, key, scheme, rule, entity_type, cue, token, valid, expect, exclusion):
    """One line of the case file."""
    carrier = CARRIER_PREFIX + (cue + " " if cue else "")
    text = carrier + token + CARRIER_SUFFIX
    # Sorted ids group a scheme's cases together, which is what makes the sampling rule — take the
    # first N of a scheme — keep whole modules rather than slicing across them.
    name = key if scheme == key else "%s:%s" % (scheme, key)
    return {
        "id": "stdnum:%s:%03d" % (name, index),
        "origin": ORIGIN,
        "source": "stdnum/%s.py" % key.replace(".", "/"),
        "scheme": scheme if scheme else key,
        "token": token,
        "text": text,
        "token_start": len(carrier.encode("utf-8")),
        "token_end": len(carrier.encode("utf-8")) + len(token.encode("utf-8")),
        "cue": cue,
        "valid": valid,
        "rule_id": rule,
        "entity_type": entity_type,
        "expect_value": expect,
        "exclusion": exclusion,
    }


def emit(cases, key, scheme, rule, entity_type, cue, kind, prefix=None):
    """Every usable doctest of one module, as cases under one scheme."""
    path = os.path.join(STDNUM_ROOT, "stdnum", key.replace(".", os.sep) + ".py")
    index = 0
    for example in docstring_examples(path):
        parsed = parse_call(example.source)
        if parsed is None:
            continue
        _, argument, extra = parsed
        valid, upstream = outcome(example.want, example.exc_msg)
        if valid is None:
            continue
        index += 1
        token, expect = argument, upstream
        if kind == "vat":
            token = prefixed(argument, prefix)
            expect = prefixed(upstream, prefix) if upstream else None

        exclusion = None
        if extra:
            exclusion = EXCLUSION_EXTRA_ARGS
        elif key in EXCLUDED_MODULES:
            exclusion = EXCLUDED_MODULES[key]
        elif kind == "unmapped":
            exclusion = EXCLUSION_NO_RULE
        else:
            exclusion = documented_exclusion(scheme, token)
        if (
            exclusion is None
            and scheme == "vat.vatin"
            and upstream
            and upstream[:2].upper() not in VAT_PREFIXES
        ):
            exclusion = EXCLUSION_PREFIX
        if not valid:
            expect = None

        cases.append(
            case(
                index,
                key,
                scheme,
                rule,
                entity_type,
                cue if exclusion is None else None,
                token,
                valid,
                expect,
                exclusion,
            )
        )


def main() -> int:
    cases: list[dict] = []
    mapped = set()

    for key, (scheme, rule, entity_type, cue) in sorted(DIRECT.items()):
        emit(cases, key, scheme, rule, entity_type, cue, "direct")
        mapped.add(key)

    for table, rule in ((VAT_EU, "company.vat_eu"), (VAT_NON_EU, "company.vat_non_eu")):
        for key, prefix in sorted(table.items()):
            scheme = "vat.%s" % prefix.lower()
            emit(cases, key, scheme, rule, "company_id", None, "vat", prefix)
            mapped.add(key)

    root = os.path.join(STDNUM_ROOT, "stdnum")
    for directory, _, files in os.walk(root):
        for name in sorted(files):
            if not name.endswith(".py") or name == "__init__.py":
                continue
            key = module_key(os.path.join(directory, name))
            if key in mapped:
                continue
            emit(cases, key, key, None, None, None, "unmapped")

    cases.sort(key=lambda item: item["id"])
    for item in cases:
        json.dump(item, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    print("%d cases" % len(cases), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
