#!/usr/bin/env bash
# price-parser (Zyte) — BSD-3.
# Small, and the separator-inference logic is the best available answer to `1.234` meaning either a
# thousand or one-and-a-bit depending on the locale that wrote it.
#
# The test module comes with it: a parametrised list of (text, currency, amount) triples collected
# from a random sample of real pages, which is the labelled corpus the upstream conformance run
# scores the money rules against.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/scrapinghub/price-parser.git price-parser)"
target="${REFERENCE}/price-parser"
replace_dir "$target"
cp -r "${src}/price_parser" "${target}/price_parser"
mkdir -p "${target}/tests"
cp "${src}/tests/test_price_parsing.py" "${target}/tests/"
cp "${src}/LICENSE" "${LICENSES}/price-parser.LICENSE"
stamp "$target" "https://github.com/scrapinghub/price-parser" "$(git_head "$src")"
