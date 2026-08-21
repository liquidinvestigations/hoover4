#!/usr/bin/env bash
# Microsoft Recognizers-Text — MIT.
# The language-neutral YAML under Patterns/ is the whole reason to vendor this: curated, already
# false-positive-tuned pattern and lexicon files for dates, currency, units, phones, email and more,
# in fifteen languages, kept separate from the C#/JS/Python implementations.
#
# The patterns are .NET flavour and lean on lookaround, which no linear-time engine accepts. They
# are input to our rule authoring, not something we compile as-is.
#
# From Specs/ we take the English spec files for the four recognisers we ship rules for — dates,
# currency, IP addresses and phone numbers — plus email, and nothing else. Each is free text with
# the expected extractions and resolutions beside it, which is what the upstream conformance run
# scores against. The tree holds fifteen languages and a dozen recognisers we have no rule for;
# taking it whole would be hoarding, not vendoring.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/microsoft/Recognizers-Text.git recognizers-text)"
target="${REFERENCE}/recognizers-text"
replace_dir "$target"
cp -r "${src}/Patterns" "${target}/Patterns"

specs=(
    DateTime/English/DateExtractor.json
    DateTime/English/DateParser.json
    DateTime/English/DateTimeExtractor.json
    DateTime/English/DateTimeParser.json
    NumberWithUnit/English/CurrencyModel.json
    Sequence/English/EmailModel.json
    Sequence/English/IpAddressModel.json
    Sequence/English/PhoneNumberModel.json
)
for spec in "${specs[@]}"; do
    mkdir -p "${target}/Specs/$(dirname "$spec")"
    cp "${src}/Specs/${spec}" "${target}/Specs/${spec}"
done
cp "${src}/LICENSE" "${LICENSES}/recognizers-text.LICENSE"
stamp "$target" "https://github.com/microsoft/Recognizers-Text" "$(git_head "$src")"
note "$(find "${target}/Patterns" -name '*.yaml' | wc -l) pattern files"
note "${#specs[@]} spec files"
