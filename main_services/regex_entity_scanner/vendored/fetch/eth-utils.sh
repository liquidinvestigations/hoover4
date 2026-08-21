#!/usr/bin/env bash
# eth-utils (Ethereum Foundation) — MIT — and ERC-55 — CC0-1.0.
#
# Two upstreams, one subject. `tests/core/address-utils/test_address_utils.py` is a parametrised
# table that separates the three readings of an Ethereum address a scanner has to tell apart:
# checksummed and correct, checksummed and wrong, and written in a single case so that EIP-55
# carries no information at all. ERC-55 itself carries the eight vectors the standard is defined
# by, in its own Test Cases section.
#
# The two licences stay separate because the data does: the address utilities are the Foundation's
# MIT-licensed code, and the ERC text is contributed under CC0.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

utils_repo="https://github.com/ethereum/eth-utils"
utils_raw="https://raw.githubusercontent.com/ethereum/eth-utils/main"
utils="${REFERENCE}/eth-utils"
replace_dir "${utils}/tests"
download "${utils_raw}/tests/core/address-utils/test_address_utils.py" \
    "${utils}/tests/test_address_utils.py"
download "${utils_raw}/LICENSE" "${LICENSES}/eth-utils.LICENSE"
stamp "$utils" "$utils_repo" "$(remote_head "$utils_repo")"

ercs_repo="https://github.com/ethereum/ERCs"
ercs_raw="https://raw.githubusercontent.com/ethereum/ERCs/master"
ercs="${REFERENCE}/erc-55"
replace_dir "$ercs"
download "${ercs_raw}/ERCS/erc-55.md" "${ercs}/erc-55.md"
download "${ercs_raw}/LICENSE.md" "${LICENSES}/ercs.LICENSE"
stamp "$ercs" "$ercs_repo" "$(remote_head "$ercs_repo")"
