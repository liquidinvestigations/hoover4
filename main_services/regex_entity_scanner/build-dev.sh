#!/usr/bin/env bash
#
# Builds the development image. Pass --force (-f) to rebuild even when the image already exists,
# ignoring the layer cache and re-pulling the base image.

source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

force=""
case "${1:-}" in
    -f|--force) force="yes" ;;
    "") ;;
    *) echo "usage: $0 [--force]" >&2; exit 2 ;;
esac

if [[ -z "$force" ]] && image_exists "$DEV_IMAGE"; then
    echo "${DEV_IMAGE} already built; pass --force to rebuild"
    exit 0
fi

build_args=()
if [[ -n "$force" ]]; then
    build_args+=(--no-cache --pull=always)
fi

exec docker build "${build_args[@]}" \
    --file "${REPO_ROOT}/Dockerfile.devel" \
    --tag "$DEV_IMAGE" \
    "$REPO_ROOT"
