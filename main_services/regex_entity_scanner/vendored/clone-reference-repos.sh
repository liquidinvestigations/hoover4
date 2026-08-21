#!/usr/bin/env bash
#
# Shallow-clones the upstreams worth reading in full into `tmp/reference/`, which is gitignored
# scratch. Nothing here is vendored — these are the projects to consult when designing a rule, an
# engine binding or a service shape, including the ones we deliberately did not adopt.
#
# Runs inside the dev container:  ./shell.sh vendored/clone-reference-repos.sh

source "$(dirname -- "${BASH_SOURCE[0]}")/fetch/common.sh"

TARGET="${REPO_ROOT}/tmp/reference"
mkdir -p "$TARGET"

# name|url|why
REPOS=(
    "kingfisher|https://github.com/mongodb/kingfisher.git|Rust, Apache-2.0, 1000+ rules, vendored vectorscan-rs; the closest existing engineering to this service and the best rule-schema model"
    "titus|https://github.com/praetorian-inc/titus.git|Go, Apache-2.0; successor to Nosey Parker, another large rule corpus"
    "duckling|https://github.com/facebook/duckling.git|Haskell, BSD-3; the same dimensions we want, built as an utterance parser rather than a document scanner. Rule design reference and a cross-check oracle"
    "presidio|https://github.com/microsoft/presidio.git|Python, MIT; the PII entity checklist and per-country recognisers"
    "recognizers-text|https://github.com/microsoft/Recognizers-Text.git|MIT; the full tree behind the vendored Patterns/, including the test corpora that document what each pattern is meant to catch"
    "libphonenumber|https://github.com/google/libphonenumber.git|Apache-2.0; PhoneNumberMatcher and the metadata that decides whether a candidate is a real number"
    "python-stdnum|https://github.com/arthurdejong/python-stdnum.git|LGPL-2.1+; 200+ checksummed formats, with the tests that pin each algorithm"
    "dateparser|https://github.com/scrapinghub/dateparser.git|BSD-3; the date lexicon and the search-in-free-text heuristics"
    "followthemoney|https://github.com/alephdata/followthemoney.git|MIT; the investigative data model our output should speak"
    "vectorscan|https://github.com/VectorCamp/vectorscan.git|BSD-3; the multi-gigabyte-per-second prefilter engine, if measurement ever calls for one"
)

for entry in "${REPOS[@]}"; do
    IFS='|' read -r name url why <<< "$entry"
    dir="${TARGET}/${name}"
    if [[ -d "${dir}/.git" ]]; then
        note "have ${name}"
    else
        note "cloning ${name}"
        git clone --depth 1 --quiet "$url" "$dir" || { note "FAILED ${name}"; continue; }
    fi
    printf '%s\n' "$why" > "${dir}/.why"
done

printf '\n%s\n' "$(du -sh "$TARGET" | cut -f1) in ${TARGET}"
