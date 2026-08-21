#!/usr/bin/env bash
# GLEIF Level 1 concatenated file — CC0.
#
# Not part of the default fetch: it is a multi-gigabyte download, and `vendored/gleif/data` is
# gitignored for that reason. Run it when LEI resolution is wanted. It is what takes an LEI from a
# validated string to a resolved company — legal name, jurisdiction, registered address, status and
# parent relationships — which is the best enrichment-per-effort available anywhere in this space.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

target="${VENDOR_ROOT}/gleif/data"
mkdir -p "$target"

note "resolving the current Level 1 golden copy"
url="$(curl --fail --silent --show-error --location \
    'https://leidata.gleif.org/api/v1/concatenated-files/lei2/latest' \
    | jq -r '.data[0].file.url // .[0].data.file.url')"

if [[ -z "$url" || "$url" == "null" ]]; then
    echo "GLEIF did not return a download URL; the API shape may have changed" >&2
    exit 1
fi

download "$url" "${target}/lei2-golden-copy.zip"
stamp "${VENDOR_ROOT}/gleif" "https://www.gleif.org/en/about/open-data" "$(date -u +%Y-%m-%d)"
note "downloaded $(du -h "${target}/lei2-golden-copy.zip" | cut -f1)"
