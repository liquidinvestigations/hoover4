#!/usr/bin/env bash
# Credential and token rule corpora: Kingfisher (Apache-2.0), Gitleaks (MIT).
#
# These are the largest maintained bodies of structured-identifier patterns in existence, and
# Kingfisher's rule schema is also the best available model for ours: match, then confirm. In a
# document corpus a live credential is both an investigative signal and a duty-of-care one.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

target="${REFERENCE}/secret-rules"
replace_dir "$target"

kingfisher="$(clone https://github.com/mongodb/kingfisher.git kingfisher)"
cp -r "${kingfisher}/crates/kingfisher-rules/data/rules" "${target}/kingfisher-rules"
cp "${kingfisher}/LICENSE" "${LICENSES}/kingfisher.LICENSE"
note "kingfisher: $(find "${target}/kingfisher-rules" -name '*.yml' -o -name '*.yaml' | wc -l) rule files"

gitleaks="$(clone https://github.com/gitleaks/gitleaks.git gitleaks)"
mkdir -p "${target}/gitleaks"
cp "${gitleaks}/config/gitleaks.toml" "${target}/gitleaks/"
cp "${gitleaks}/LICENSE" "${LICENSES}/gitleaks.LICENSE"

stamp "$target" "https://github.com/mongodb/kingfisher + https://github.com/gitleaks/gitleaks" \
    "$(git_head "$kingfisher") / $(git_head "$gitleaks")"
