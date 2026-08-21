#!/usr/bin/env bash
# GitHub Advisory Database — CC-BY-4.0, verified from `LICENSE.md` at the repository root.
#
# One month of reviewed advisories in the OSV schema. The month directory is the slice, which is
# what makes it deterministic: the name says exactly what is here and a re-fetch changes nothing
# unless upstream edits those advisories.
#
# Two fields are what this is for. `aliases` carries the CVE identifier the advisory is known by,
# and `references[].url` carries it again inside an NVD or vendor URL — the identifier in the
# surface context a document actually writes, with a slash on its left rather than a space.
#
# The clone is sparse and blobless: the repository is hundreds of megabytes of advisories and the
# month wanted here is under half of one.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

repo="https://github.com/github/advisory-database"
month="advisories/github-reviewed/2021/12"
src="${STAGE}/advisory-database"

if [[ -d "${src}/.git" ]]; then
    note "updating advisory-database"
    git -C "$src" fetch --depth 1 origin HEAD >/dev/null 2>&1
    git -C "$src" reset --hard FETCH_HEAD >/dev/null 2>&1
else
    note "cloning advisory-database (sparse, ${month})"
    git clone --depth 1 --filter=blob:none --sparse --quiet --no-progress "${repo}.git" "$src" 2>/dev/null
    git -C "$src" sparse-checkout set "$month" >/dev/null 2>&1
fi

target="${REFERENCE}/advisory-database"
replace_dir "${target}/advisories"

# Flattened: upstream gives every advisory a directory of its own holding one file, and the
# directory name is the file name without its extension.
find "${src}/${month}" -name 'GHSA-*.json' -exec cp {} "${target}/advisories/" \;

cp "${src}/LICENSE.md" "${LICENSES}/advisory-database.LICENSE"
stamp "$target" "${repo} (${month})" "$(git_head "$src")"
note "$(find "${target}/advisories" -name '*.json' | wc -l) advisories"
