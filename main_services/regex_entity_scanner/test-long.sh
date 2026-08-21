#!/usr/bin/env bash
#
# The upstream conformance run, in the dev container. It scans the checked-in conformance cases —
# valid and invalid numbers taken from the reference projects our rules were ported from — and
# reports recall, precision and coverage per scheme and in aggregate.
#
# This is not the fast battery and does not run it. `./test.sh` stays inside two to three minutes
# and never triggers this; this one has a budget of fifteen to twenty minutes and samples each
# scheme deterministically rather than exceeding it.
#
#   ./test-long.sh              # every origin
#   ./test-long.sh stdnum       # one origin, named by its case file's stem
#
# A human-readable table goes to stdout; the machine-readable JSON lands in
# target/conformance/report.json.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

origin=""
case "${1:-}" in
    -h|--help) sed -n '2,17p' "${BASH_SOURCE[0]}" | cut -c3-; exit 0 ;;
    "") ;;
    -*) echo "usage: $0 [origin]" >&2; exit 2 ;;
    *) origin="$1" ;;
esac

ensure_dev_image

exec docker run --rm \
    "${DEV_RUN_ARGS[@]}" \
    --env "RES_VENDORED_DIR=/work/vendored" \
    --env "RES_CONFORMANCE_ORIGIN=${origin}" \
    --env "RES_CONFORMANCE_REPORT=/work/target/conformance/report.json" \
    "$DEV_IMAGE" \
    bash -c '
        set -euo pipefail
        if [[ -z "${RES_CONFORMANCE_ORIGIN}" ]]; then unset RES_CONFORMANCE_ORIGIN; fi
        cargo test --all-features --test conformance -- --ignored --nocapture
    '
