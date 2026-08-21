#!/usr/bin/env bash
# dateparser (Zyte) — BSD-3.
# Its CLDR-derived translation tables cover 200+ locales with month and weekday names, separators
# and skip-words, plus a hand-curated supplementary layer for what CLDR misses. It is data rather
# than code, so it ports to Rust as a transform rather than a rewrite.
#
# The parser test module is taken alongside the tables. It is one long parametrised list of date
# strings with the datetime each is expected to parse to, across every locale and format the
# project supports, which makes it a labelled corpus for the date rules rather than only a lexicon.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/scrapinghub/dateparser.git dateparser)"
target="${REFERENCE}/dateparser"
replace_dir "$target"
cp -r "${src}/dateparser_data" "${target}/dateparser_data"
mkdir -p "${target}/tests"
cp "${src}/tests/test_date_parser.py" "${target}/tests/test_date_parser.py"
cp "${src}/LICENSE" "${LICENSES}/dateparser.LICENSE"
stamp "$target" "https://github.com/scrapinghub/dateparser" "$(git_head "$src")"
note "$(find "${target}" -name '*.yaml' -o -name '*.json' | wc -l) locale files"
