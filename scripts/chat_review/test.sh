#!/usr/bin/env bash
# Run offline review tests against the current checkout in the worker image.
set -euo pipefail
root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
image=${CHAT_REVIEW_IMAGE:-localhost/hoover4_hoover4-worker:latest}
exec docker run --rm --network none -v "$root:/repo:ro" -w /repo \
    --entrypoint /opt/pysetup/.venv/bin/python "$image" \
    -B -m pytest scripts/chat_review/tests -q -p no:cacheprovider "$@"
