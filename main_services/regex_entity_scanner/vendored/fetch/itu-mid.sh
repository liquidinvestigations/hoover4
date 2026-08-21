#!/usr/bin/env bash
# ITU Maritime Identification Digits — MIT mapping of the ITU allocation table.
# The first three digits of an MMSI are the flag state. An MMSI has no check digit, so a valid MID
# plus a cue word is the entire precision story for that rule; without the table it is nine digits
# that match every invoice number in the corpus.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/michaeljfazio/MIDs.git itu-mids)"
target="${DATA}/itu"
mkdir -p "$target"
cp "${src}/mids.json" "${target}/mids.json"
cp "${src}/LICENSE" "${LICENSES}/itu-mids.LICENSE" 2>/dev/null || true
stamp "$target" "https://github.com/michaeljfazio/MIDs" "$(git_head "$src")"
note "$(jq 'length' "${target}/mids.json") maritime identification digits"
