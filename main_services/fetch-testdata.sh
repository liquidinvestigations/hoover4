#!/bin/bash
# Make sure `testdata/hoover-testdata` exists at the commit the fixtures are pinned to.
#
# `testdata/` is gitignored and `hoover-testdata` is a separate upstream checkout, not a
# submodule -- so nothing in this repository records which revision the tests were written
# against. That is fine until a fixture moves upstream and a check starts failing for a
# reason that is nowhere in the diff. Hence the pin below.
#
# Idempotent and non-destructive:
#   * missing        -> clone, then check out TESTDATA_COMMIT
#   * present, right -> say so and exit
#   * present, wrong -> WARN and exit 0 (this tree is edited by hand on purpose; the
#                       script's job is to tell you, not to throw your work away)
#
# Usage: ./fetch-testdata.sh [--check]
#   --check   report only; never clone. For CI and for verify-stack.sh.
set -euo pipefail

TESTDATA_REPO="${TESTDATA_REPO:-https://github.com/liquidinvestigations/hoover-testdata}"
# The revision every fixture path in verify-stack.sh and backend/tests/stack_integration.rs
# was written against. Bump it together with those paths, never on its own.
TESTDATA_COMMIT="${TESTDATA_COMMIT:-57a8300e73c6b524e3eed10c13a051c134de6998}"

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

TESTDATA_DIR="${HOOVER4_TESTDATA_DIR:-$SCRIPT_DIR/../testdata}"
TARGET="$TESTDATA_DIR/hoover-testdata"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

if [ ! -d "$TARGET/.git" ]; then
    if [ "$CHECK_ONLY" = "1" ]; then
        echo "MISSING - $TARGET (run ./fetch-testdata.sh to clone it)"
        exit 1
    fi
    echo "cloning $TESTDATA_REPO -> $TARGET"
    mkdir -p "$TESTDATA_DIR"
    git clone "$TESTDATA_REPO" "$TARGET"
    git -C "$TARGET" checkout --detach "$TESTDATA_COMMIT"
    echo "OK   - hoover-testdata at $TESTDATA_COMMIT"
    exit 0
fi

HEAD_COMMIT="$(git -C "$TARGET" rev-parse HEAD)"
if [ "$HEAD_COMMIT" = "$TESTDATA_COMMIT" ]; then
    echo "OK   - hoover-testdata at the pinned commit ${TESTDATA_COMMIT:0:12}"
else
    # Deliberately not `exit 1`: the tree is expected to carry local edits (the fixtures
    # are ours to shape), and a hard failure here would block every run over a difference
    # that is usually intentional.
    echo "WARN - hoover-testdata is at ${HEAD_COMMIT:0:12}, pinned is ${TESTDATA_COMMIT:0:12}"
    echo "       If a fixture path fails to resolve, this is the first thing to check."
fi

# The fixture directories the checks name. Listed here rather than discovered so that a
# missing one is reported once, by name, instead of as an ingest that quietly does nothing.
missing=0
for path in \
    disk-files/pdf-doc-txt \
    eml-2-attachment \
    zip-in-multiple-locations \
    many-children/deep-stuff \
    many-children/the-directory
do
    if [ ! -e "$TARGET/data/$path" ]; then
        echo "MISSING - data/$path"
        missing=$((missing + 1))
    fi
done
[ "$missing" = "0" ] && echo "OK   - every pinned fixture path is present" || exit 1
