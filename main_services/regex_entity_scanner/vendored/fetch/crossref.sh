#!/usr/bin/env bash
# Crossref REST API — open metadata, and the one upstream here with no SPDX identifier to name.
#
# Crossref states the terms on the API's own documentation page: no sign-up is required, almost
# none of the metadata is subject to copyright, and it may be used for any purpose — with the single
# carve-out that some abstracts may be copyright of publishers or authors. What is taken here is
# DOIs and ORCID identifiers and nothing else, so that carve-out does not reach this slice. See the
# manifest row for the wording and the URL.
#
# Two queries against one publication day, reduced to the identifiers before anything is written:
# the day alone for DOIs, and the same day filtered to works that carry an ORCID, because an
# arbitrary day's author records carry one only a few times in a hundred. `?sample=` is not used —
# it is not deterministic — and determinism comes from the checked-in case file, with the fetch date
# in the stamp.
#
# Set CROSSREF_MAILTO to a contact address to join the polite pool, which is Crossref's convention
# for a client that wants to be told when it misbehaves rather than throttled.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

api="https://api.crossref.org/works"
day="from-pub-date:2020-01-01,until-pub-date:2020-01-01"
agent="regex-entity-scanner conformance fetch${CROSSREF_MAILTO:+ (mailto:${CROSSREF_MAILTO})}"

target="${REFERENCE}/crossref"
replace_dir "$target"

fetch_slice() {
    local name="$1" query="$2"
    local staged="${STAGE}/crossref-${name}.json"
    note "querying ${name}"
    curl --fail --silent --show-error --location \
        --user-agent "$agent" --output "$staged" "$query"
    jq --arg query "$query" '{
        query: $query,
        items: [.message.items[] | {
            doi: .DOI,
            orcid: [(.author // [])[] | select(.ORCID) | .ORCID]
        }]
    }' "$staged" > "${target}/${name}.json"
}

# A thousand works of one day, sorted by publication date so the slice is a prefix rather than a
# draw. `sort=DOI` is rejected by the API; `published` is the field it offers that orders a day.
fetch_slice works "${api}?filter=${day}&rows=1000&sort=published&order=asc&select=DOI,author"
sleep 1
# The same day, restricted to works that carry an ORCID. Two hundred and fifty works are more
# identifiers than the run's per-scheme sample takes, and carrying a corpus nothing scores is
# hoarding.
fetch_slice works-with-orcid "${api}?filter=${day},has-orcid:true&rows=250&sort=published&order=asc&select=DOI,author"

stamp "$target" "https://api.crossref.org/works" "fetched $(date -u +%Y-%m-%d)"
note "$(jq '[.items[].doi] | length' "${target}/works.json") DOIs"
note "$(jq '[.items[].orcid[]] | length' "${target}/works-with-orcid.json") ORCID identifiers"
