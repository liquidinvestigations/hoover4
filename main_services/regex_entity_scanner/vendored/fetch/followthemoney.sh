#!/usr/bin/env bash
# FollowTheMoney (OCCRP) — MIT.
# The de-facto data model for investigative reporting. We take the schema rather than the code:
# naming our output properties the way FtM names them is what makes an extraction usable in the
# tooling investigative users already run, instead of a private vocabulary they have to map.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/alephdata/followthemoney.git followthemoney)"
target="${REFERENCE}/followthemoney"
replace_dir "$target"
cp -r "${src}/followthemoney/schema" "${target}/schema"
cp "${src}/LICENSE" "${LICENSES}/followthemoney.LICENSE"
stamp "$target" "https://github.com/alephdata/followthemoney" "$(git_head "$src")"
note "$(find "${target}/schema" -name '*.yaml' | wc -l) schema files"
