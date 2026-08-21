#!/usr/bin/env bash
# quantulum3 — MIT.
# `units.json` and the entity taxonomy are a curated unit lexicon; `common-words` is the list that
# keeps bare `m`, `in` and `t` from matching ordinary prose, which is the real problem with units.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

src="$(clone https://github.com/nielstron/quantulum3.git quantulum3)"
target="${REFERENCE}/quantulum3"
replace_dir "$target"
mkdir -p "${target}/data"
find "${src}/quantulum3/_lang" "${src}/quantulum3" -maxdepth 3 -name '*.json' \
    -exec cp {} "${target}/data/" \; 2>/dev/null || true
cp "${src}/LICENSE" "${LICENSES}/quantulum3.LICENSE"
stamp "$target" "https://github.com/nielstron/quantulum3" "$(git_head "$src")"
note "$(find "${target}/data" -name '*.json' | wc -l) lexicon files"
