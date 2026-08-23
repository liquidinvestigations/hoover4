#!/usr/bin/env bash
#
# Builds the release image: optimised binaries plus the vendored data the service reads at startup,
# and nothing else. No toolchain, no sources, no bind mount. It runs anywhere on its own.
# Pass --force (-f) to rebuild from scratch.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

force=""
case "${1:-}" in
    -f|--force) force="yes" ;;
    "") ;;
    *) echo "usage: $0 [--force]" >&2; exit 2 ;;
esac

build_args=()
if [[ -n "$force" ]]; then
    build_args+=(--no-cache --pull=always)
fi

exec docker build "${build_args[@]}" \
    --file "${REPO_ROOT}/Dockerfile.release" \
    --tag "$REL_IMAGE" \
    "$REPO_ROOT"
