#!/bin/bash
# Thin alias for muscle memory. The real thing is deploy.py at the repo root.
set -e
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
exec "$SCRIPT_DIR/../deploy" "$@"
