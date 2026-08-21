#!/usr/bin/env bash
# Unicode CLDR, via the official JSON distribution — Unicode-3.0, which the FSF lists as
# GPL-compatible.
#
# CLDR is the only source that scales past a handful of languages without linear human effort:
# month and era names, per-locale number separators and currency placement, and unit display names,
# all versioned and authoritative. We take the `modern` variant — the locales in active use — and
# only the three files per locale we generate from.
#
# CLDR describes formatting. Turning a format pattern into a parser is our work, and an inverted
# pattern is always laxer than the formatter that produced it.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

target="${REFERENCE}/cldr"
replace_dir "$target"

take() {
    local package="$1" filename="$2"
    local src dest
    src="$(npm_tarball "$package")"
    dest="${target}/${package}"
    mkdir -p "$dest"
    ( cd "${src}/main" && find . -name "$filename" -exec cp --parents {} "${dest}/" \; )
    note "${package}: $(find "$dest" -name "$filename" | wc -l) locales"
}

take cldr-dates-modern ca-gregorian.json
take cldr-numbers-modern numbers.json
take cldr-units-modern units.json

# Territory names are runtime data rather than reference material: the explainer resolves a
# country-code top-level domain to the country it belongs to, and a card that says "GB" where it
# could say "United Kingdom" is a card nobody needed. Flattened to one map, because the release
# image should not carry CLDR's bundle structure for the sake of 300 strings.
names="$(npm_tarball cldr-localenames-modern)"
mkdir -p "${DATA}/cldr"
jq '.main.en.localeDisplayNames.territories
    | with_entries(select(.key | test("^[A-Z]{2}$")))' \
    "${names}/main/en/territories.json" > "${DATA}/cldr/territories-en.json"
note "territories: $(jq 'length' "${DATA}/cldr/territories-en.json") names"

# Currency data is runtime data for the same reason territory names are: a sum of money is only a
# typed value once it carries an ISO 4217 code and the number of minor units that code divides into,
# and the symbol somebody actually wrote has to resolve to a code before either is known.
#
# `iso4217.json` is code -> {exponent, name}, restricted to the codes in current use: a region entry
# with no end date and tender status. Dead codes and the non-tender funds and metals (XAU, CLF) are
# left out, because a scanner that accepts them turns every three-letter token into money.
#
# `currency-symbols.json` is symbol -> [codes], ordered by how many regions currently use each code,
# ties broken alphabetically. A one-entry list is an unambiguous symbol; a longer one is the reason
# the ambiguous-currency flag exists. Both the standard and the narrow CLDR symbols are indexed,
# because "A$" and "$" are both written for the same currency and "$" is written for thirty.
numbers="$(npm_tarball cldr-numbers-modern)"
core="$(npm_tarball cldr-core)"
currency_data="${core}/supplemental/currencyData.json"
currency_names="${numbers}/main/en/currencies.json"

jq -n --slurpfile core "$currency_data" --slurpfile names "$currency_names" '
    ($core[0].supplemental.currencyData) as $cd
    | ($names[0].main.en.numbers.currencies) as $display
    | ($cd.fractions.DEFAULT._digits | tonumber) as $default
    | [ $cd.region | to_entries[] | .value[] | to_entries[]
        | select((.value | has("_to")) | not)
        | select(.value._tender != "false")
        | .key ]
      | unique
      | map({ key: .,
              value: { exponent: (($cd.fractions[.]._digits // ($default | tostring)) | tonumber),
                       name: ($display[.].displayName // .) } })
      | from_entries' > "${DATA}/cldr/iso4217.json"
note "currencies: $(jq 'length' "${DATA}/cldr/iso4217.json") codes in current use"

jq -n --slurpfile core "$currency_data" --slurpfile names "$currency_names" '
    ($core[0].supplemental.currencyData) as $cd
    | ($names[0].main.en.numbers.currencies) as $display
    | [ $cd.region | to_entries[] | .value[] | to_entries[]
        | select((.value | has("_to")) | not)
        | select(.value._tender != "false")
        | .key ] as $current
    | ($current | group_by(.) | map({ key: .[0], value: length }) | from_entries) as $regions
    | [ $current[] | . as $code
        | [ $display[$code].symbol, $display[$code]["symbol-alt-narrow"] ]
        | map(select(. != null and . != "\u00a4" and . != $code))
        | unique[]
        | { symbol: ., code: $code, regions: $regions[$code] } ]
      | unique
      | group_by(.symbol)
      | map({ key: .[0].symbol,
              value: (sort_by([-.regions, .code]) | map(.code)) })
      | from_entries' > "${DATA}/cldr/currency-symbols.json"
note "currency symbols: $(jq 'length' "${DATA}/cldr/currency-symbols.json") symbols, $(jq '[.[] | select(length == 1)] | length' "${DATA}/cldr/currency-symbols.json") of them unambiguous"

stamp "${DATA}/cldr" \
    "https://github.com/unicode-org/cldr-json (npm cldr-localenames-modern, cldr-numbers-modern, cldr-core)" \
    "cldr-localenames-modern $(jq -r .version "${names}/package.json"), cldr-numbers-modern $(jq -r .version "${numbers}/package.json"), cldr-core $(jq -r .version "${core}/package.json")"

# Supplemental data is locale-independent: currency minor units, week rules, likely subtags.
mkdir -p "${target}/cldr-core"
cp "${core}/supplemental/currencyData.json" "${target}/cldr-core/"
cp "${core}/supplemental/weekData.json" "${target}/cldr-core/"
cp "${core}/supplemental/likelySubtags.json" "${target}/cldr-core/"
cp "${core}/LICENSE" "${LICENSES}/cldr.LICENSE"

stamp "$target" "https://github.com/unicode-org/cldr-json (npm cldr-*-modern, cldr-core)" \
    "$(jq -r .version "${core}/package.json")"
