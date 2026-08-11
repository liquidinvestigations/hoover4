#!/bin/bash
set -e

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]:-$0}"; )" &> /dev/null && pwd 2> /dev/null; )";
# . processing/.venv/Scripts/activate
cd $SCRIPT_DIR
# `-t` only when there is a terminal to allocate. A long ingest belongs under nohup,
# tmux or a non-interactive ssh, and `docker exec -t` fails outright in all three.
TTY=()
[ -t 0 ] && TTY=(-t)
set -x
time docker exec -i "${TTY[@]}" hoover4-worker uv run "main.py" "$@"
