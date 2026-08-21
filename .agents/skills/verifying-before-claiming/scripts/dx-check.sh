#!/usr/bin/env bash
# Catch Dioxus hook-order and rsx! defects that cargo check does not see.
set -uo pipefail
docker exec hoover4-website sh -lc \
  'export PATH=/usr/local/cargo/bin:$PATH && cd /app && dx check --package frontend 2>&1' \
  | tail -60
exit "${PIPESTATUS[0]}"
