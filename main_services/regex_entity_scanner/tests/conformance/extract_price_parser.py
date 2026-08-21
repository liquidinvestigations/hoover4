#!/usr/bin/env python3
"""Turn price-parser's parametrised test data into normalised conformance cases.

``vendored/reference/price-parser/tests/test_price_parsing.py`` is a few hundred
``Example(currency_raw, price_raw, currency, amount_text, amount)`` rows collected from a random
sample of real pages: the string a page showed, the currency upstream expects to read out of it and
the amount it expects to scale it to. Our separator inference is ported from this project, so this
is the corpus that tests whether the port kept its meaning.

Two differences between the two questions decide what is scored:

* Upstream is asked "what is the price in this string" and may be *handed* the currency out of band
  as a page-level hint. We are asked "is there a sum of money in this text, and what is it", and
  both money rules require the currency beside the amount. A row whose currency does not appear in
  the text is therefore out of scope, not a miss.
* Upstream extracts a bare amount with no currency at all. That is not a sum of money by our
  definition and there is nothing for us to report, so those rows are excluded too.

Where the currency *is* in the text, the expected value is computed the way the rule computes it:
the ISO 4217 code the sign resolves to in ``vendored/data/cldr/currency-symbols.json`` — most
widely used first, exactly as the symbol rule picks it — scaled by the minor units
``vendored/data/cldr/iso4217.json`` gives for that code. That makes the comparison a real test of
the amount, not of the entity type alone.

The script emits one JSON object per line on stdout, in the shape the Rust runner reads. It runs
inside the dev container and needs no network; the case file it writes is checked in.
"""

from __future__ import annotations

import ast
import decimal
import json
import os
import sys
import unicodedata

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SOURCE = os.path.join(
    REPO, "vendored", "reference", "price-parser", "tests", "test_price_parsing.py"
)
CLDR = os.path.join(REPO, "vendored", "data", "cldr")

ORIGIN = "price-parser"
SOURCE_NAME = "tests/test_price_parsing.py"

EXCLUSION_NO_CURRENCY = (
    "upstream extracts a bare amount with no currency anywhere in the text; both money rules match "
    "an amount beside a sign or an ISO 4217 code, so there is no sum of money here to report"
)
EXCLUSION_HINTED_CURRENCY = (
    "upstream is handed the currency out of band as a page-level hint and the text carries the "
    "amount alone; a scanner has only the text, and both money cards require the currency beside "
    "the amount"
)
EXCLUSION_XFAIL = (
    "upstream marks this row as an expected failure of its own parser, so it asserts nothing that "
    "another implementation could be measured against"
)
EXCLUSION_LETTER_SYMBOL = (
    "the currency is written as a letter-only symbol — Kč, zł, Ft, руб., Rs — which the symbol "
    "card lists as not matched: the rule matches the Unicode currency signs and an ISO 4217 code, "
    "and a two-letter abbreviation beside a number is an ordinary word far more often"
)
EXCLUSION_FRACTION = (
    "the fraction is longer than the currency's own minor units, which both money cards state is "
    "read as a rate or a measurement rather than as a price"
)
EXCLUSION_WITHDRAWN_SIGN = (
    "the sign names no currency in current use in CLDR — a withdrawn currency, or something that "
    "is not a currency at all — and the symbol card requires a sign CLDR publishes for a currency "
    "in current use"
)
EXCLUSION_WORD_LIKE_CODE = (
    "the code is one of the eleven that are also ordinary English capitalised words, for which the "
    "iso_code card requires a word about money nearby, and this text carries none"
)

# The codes the ISO-code rule refuses without a nearby money word, and the words that satisfy it.
# Both lists are the rule's own, quoted here so the exclusion can be checked against the card.
WORD_LIKE_CODES = frozenset(
    "ALL BOB COP CUP GEL MAD MOP PEN SOS TOP TRY".split()
)
MONEY_CUES = frozenset(
    "price cost costs amount total paid pay invoice fee fees salary budget balance sum worth "
    "value revenue turnover currency".split()
)


def is_currency_sign(currency: str) -> bool:
    r"""Whether the string carries a character in the Unicode currency-sign category.

    That property, `\p{Sc}`, is what the symbol rule's pattern is written against, so it is also
    the boundary of what can be scored: `€` and `R$` are signs, `Kč` and `zł` are abbreviations
    spelled with letters and the card says they are not matched.
    """
    return any(unicodedata.category(character) == "Sc" for character in currency)


def load_tables():
    with open(os.path.join(CLDR, "iso4217.json"), encoding="utf-8") as handle:
        codes = json.load(handle)
    with open(os.path.join(CLDR, "currency-symbols.json"), encoding="utf-8") as handle:
        symbols = json.load(handle)
    return codes, symbols


def literal(node):
    """The value of a constant argument, including the `Decimal("…")` the test data uses."""
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Decimal":
        return decimal.Decimal(node.args[0].value)
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def rows():
    """Every `Example(...)` in the test module, as (list name, positional arguments)."""
    with open(SOURCE, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        name = node.targets[0].id
        if not name.startswith("PRICE_PARSING_EXAMPLES"):
            continue
        for element in node.value.elts:
            if isinstance(element, ast.Call) and getattr(element.func, "id", None) == "Example":
                yield name, [literal(argument) for argument in element.args]


def expected(codes, symbols, currency, amount):
    """The canonical `CODE minor-units` string, or `None` where the sign names no code we carry."""
    if currency is None or amount is None:
        return None
    code = currency if currency in codes else None
    if code is None:
        # The symbol table is ordered most widely used first, which is the order the symbol rule
        # picks from, so taking the head reproduces the rule rather than guessing.
        candidates = symbols.get(currency)
        code = candidates[0] if candidates else None
    if code is None or code not in codes:
        return None
    exponent = codes[code]["exponent"]
    scaled = decimal.Decimal(str(amount)).scaleb(exponent)
    if scaled != scaled.to_integral_value():
        return None
    return "%s %d" % (code, int(scaled))


def fraction_too_long(codes, symbols, currency, amount_text) -> bool:
    if currency is None or not amount_text:
        return False
    code = currency if currency in codes else (symbols.get(currency) or [None])[0]
    if code is None or code not in codes:
        return False
    for separator in (".", ","):
        head, found, tail = amount_text.rpartition(separator)
        if found and tail.isdigit() and len(tail) != 3:
            return len(tail) > codes[code]["exponent"]
    return False


def main() -> int:
    codes, symbols = load_tables()
    cases: list[dict] = []
    counters: dict[str, int] = {}

    for name, arguments in rows():
        currency_raw, price_raw, currency, amount_text = arguments[:4]
        amount = arguments[4] if len(arguments) > 4 else None
        text = price_raw if price_raw else currency_raw
        if not isinstance(text, str) or not text:
            continue

        scheme = "price." + name[len("PRICE_PARSING_EXAMPLES") :].strip("_").lower()
        if scheme == "price.":
            scheme = "price.examples"

        if "xfail" in scheme:
            exclusion = EXCLUSION_XFAIL
        elif amount is not None and currency is None:
            exclusion = EXCLUSION_NO_CURRENCY
        elif currency is not None and currency not in text:
            exclusion = EXCLUSION_HINTED_CURRENCY
        elif currency is not None and not is_currency_sign(currency) and currency not in codes:
            exclusion = EXCLUSION_LETTER_SYMBOL
        elif currency is not None and currency not in codes and not symbols.get(currency):
            exclusion = EXCLUSION_WITHDRAWN_SIGN
        elif currency in WORD_LIKE_CODES and not (
            MONEY_CUES & {word.strip(".,:;()").lower() for word in text.split()}
        ):
            exclusion = EXCLUSION_WORD_LIKE_CODE
        elif fraction_too_long(codes, symbols, currency, amount_text):
            exclusion = EXCLUSION_FRACTION
        else:
            exclusion = None

        valid = amount is not None and currency is not None
        counters[scheme] = counters.get(scheme, 0) + 1
        cases.append(
            {
                "id": "price-parser:%s:%04d" % (scheme, counters[scheme]),
                "origin": ORIGIN,
                "source": SOURCE_NAME,
                "scheme": scheme,
                # Upstream is handed the whole string and names no offsets inside it, so the token
                # is the string. For an invalid row that is exactly the right question: did
                # anything of this type fire anywhere in a string upstream reads no price from.
                "token": text,
                "text": text,
                "token_start": 0,
                "token_end": len(text.encode("utf-8")),
                "cue": None,
                "valid": valid,
                "rule_id": (
                    None
                    if exclusion
                    else ("money.iso_code" if currency in codes else "money.symbol")
                ),
                "entity_type": None if exclusion else "money",
                "expect_value": (
                    None if exclusion or not valid else expected(codes, symbols, currency, amount)
                ),
                "exclusion": exclusion,
            }
        )

    cases.sort(key=lambda item: item["id"])
    for item in cases:
        json.dump(item, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    print("%d cases" % len(cases), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
