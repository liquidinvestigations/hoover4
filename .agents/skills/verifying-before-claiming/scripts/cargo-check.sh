#!/usr/bin/env bash
# Type-check the whole Rust workspace inside hoover4-website.
# Rust is at /usr/local/cargo/bin there and is not on PATH.
set -uo pipefail
docker exec hoover4-website sh -lc \
  'export PATH=/usr/local/cargo/bin:$PATH && cd /app && cargo check --offline --all-targets 2>&1' \
  | grep -E '^(error|warning: unused|warning: unreachable)|^error\[|Finished|Compiling [a-z_]+ v' \
  | tail -60
exit "${PIPESTATUS[0]}"
