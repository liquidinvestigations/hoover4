#!/usr/bin/env bash
# Open Location Code (Google) — Apache-2.0, over the reference implementations and the test data
# alike.
#
# The four CSVs under `test_data/` are the specification's own conformance material and the only
# labelled Plus Code corpus there is: codes with the validity upstream asserts for each, codes with
# the cell their decode produces, and coordinate pairs with the code that encodes them. The
# encoding file is also the only licensed corpus anywhere that writes a decimal coordinate pair in
# the surface form a document uses — `latitude,longitude` on one line — rather than as two columns
# a reader would have to join.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

repo="https://github.com/google/open-location-code"
raw="https://raw.githubusercontent.com/google/open-location-code/main"
target="${REFERENCE}/open-location-code"
replace_dir "${target}/test_data"

for file in validityTests encoding decoding shortCodeTests; do
    download "${raw}/test_data/${file}.csv" "${target}/test_data/${file}.csv"
done
download "${raw}/LICENSE" "${LICENSES}/open-location-code.LICENSE"
stamp "$target" "$repo" "$(remote_head "$repo")"
note "$(cat "${target}"/test_data/*.csv | grep -cv '^#') test rows"
