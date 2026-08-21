#!/usr/bin/env bash
# pyais (Leon Morten Richter) — MIT.
#
# The two decode test modules, which are the only labelled MMSI corpus that is both public and
# redistributable. What they carry is a decoded expectation — `msg["mmsi"] == 366053209` — beside
# the AIS sentence it came from.
#
# The sentences themselves are not an MMSI corpus and are deliberately not taken: an AIS sentence
# carries the identity inside a six-bit payload, so `!AIVDM,1,1,,A,15M67FC000G?ufbE`FepT@3n00Sa,0*5C`
# contains no MMSI as text and scanning one produces nothing. That is also why `nmea-sample` and
# `nmea_data_sample.txt` are left behind, along with four megabytes they would cost.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

repo="https://github.com/M0r13n/pyais"
raw="https://raw.githubusercontent.com/M0r13n/pyais/main"
target="${REFERENCE}/pyais"
replace_dir "${target}/tests"

for module in test_decode test_decode_8; do
    download "${raw}/tests/${module}.py" "${target}/tests/${module}.py"
done
download "${raw}/LICENSE" "${LICENSES}/pyais.LICENSE"
stamp "$target" "$repo" "$(remote_head "$repo")"
note "$(cat "${target}"/tests/*.py | grep -c mmsi) lines mentioning an MMSI"
