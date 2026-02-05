#!/bin/bash
set -e

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
# . processing/.venv/Scripts/activate
cd $SCRIPT_DIR
set -x
time docker exec -it hoover4-worker uv run "main.py" "$@"
