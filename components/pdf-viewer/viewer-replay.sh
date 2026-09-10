#!/bin/bash
# Apply the parent-owned viewer source patch onto the pinned nested revision, then rebuild.
set -euo pipefail
cd "$(dirname "$0")"

PINNED=7c6586887e65280fdf09c16fe74da05e7df75bbf
NESTED=embed-pdf-viewer
PATCH=patches/scroll-strategy-lifecycle.patch

actual=$(git -C "$NESTED" rev-parse HEAD)
if [ "$actual" != "$PINNED" ]; then
    echo "nested revision $actual does not match pinned $PINNED" >&2
    exit 1
fi

patch_abs=$(readlink -f "$PATCH")
verify_dir=$(mktemp -d)
trap 'rm -rf "$verify_dir"' EXIT
git -C "$NESTED" archive HEAD | tar -x -C "$verify_dir"
( cd "$verify_dir" && git apply "$patch_abs" )

if git -C "$NESTED" apply --check "$patch_abs"; then
    git -C "$NESTED" apply "$patch_abs"
else
    echo "nested working tree already carries the patch"
fi

bash viewer-rebuild.sh
