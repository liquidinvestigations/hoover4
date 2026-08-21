#!/usr/bin/env bash
# Print the heading outline of a markdown file with line numbers, so a section can be read
# directly instead of paging the whole document.
set -euo pipefail
for f in "$@"; do
  echo "=== $f"
  grep -n '^#\{1,3\} ' "$f" || echo "(no headings)"
done
