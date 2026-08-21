#!/usr/bin/env bash
# Show what a container actually received for a variable, rather than what a file says.
set -euo pipefail
c="$1"; shift
if [ "$#" -eq 0 ]; then
  docker exec "$c" env | sort
else
  for v in "$@"; do
    printf '%s\t' "$v"
    docker exec "$c" sh -lc "printenv $v" || echo '(unset)'
  done
fi
