#!/usr/bin/env bash
#
# The full test battery, in the dev container. Builds the dev image first if it is missing.
# Any arguments are passed through to `cargo test`:  ./test.sh email
#
# The whole battery is meant to stay inside two to three minutes. If it starts to drift past that,
# the fix is a smaller reference subset in the offending test, not a longer budget.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

ensure_dev_image

exec docker run --rm \
    "${DEV_RUN_ARGS[@]}" \
    --env "RES_VENDORED_DIR=/work/vendored" \
    "$DEV_IMAGE" \
    bash -c '
        set -euo pipefail
        cargo fmt --all -- --check
        cargo clippy --all-targets --all-features -- --deny warnings
        cargo test --all-features "$@"
    ' bash "$@"
