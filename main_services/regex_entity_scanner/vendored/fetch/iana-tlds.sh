#!/usr/bin/env bash
# IANA top-level domain list — public domain.
# Runtime data: the membership test that stops an email pattern matching `sprite@2x.png`.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

target="${DATA}/iana"
mkdir -p "$target"
download "https://data.iana.org/TLD/tlds-alpha-by-domain.txt" "${target}/tlds-alpha-by-domain.txt"
stamp "$target" "https://data.iana.org/TLD/tlds-alpha-by-domain.txt" \
    "$(head -1 "${target}/tlds-alpha-by-domain.txt")"
note "$(grep -cv '^#' "${target}/tlds-alpha-by-domain.txt") top-level domains"
