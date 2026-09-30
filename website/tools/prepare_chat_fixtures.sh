#!/usr/bin/env bash
# Write the stored chat sessions that the chat screenshot cases open by name.
#
# Usage: website/tools/prepare_chat_fixtures.sh --username NAME [--only cards,web]
#
# NAME is the account that the screenshot run signs in as. The script runs
# prepare_chat_fixtures.py in the worker container and writes the map from fixture name
# to session id to website/test_reports/chat_fixtures.json. take-screenshots.sh reads
# that file when HOOVER4_SCREENSHOT_CHAT_FIXTURES is not set.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
out="$repo_root/website/test_reports/chat_fixtures.json"
mkdir -p "$repo_root/website/test_reports"
staging="$(docker exec hoover4-worker mktemp -d /tmp/chat-fixtures.XXXXXX)"
docker cp "$repo_root/website/tools/prepare_chat_fixtures.py" "hoover4-worker:$staging/prepare_chat_fixtures.py"

set +e
docker exec -w /app hoover4-worker uv run python "$staging/prepare_chat_fixtures.py" "$@" > "$out.pending"
status=$?
set -e
docker exec hoover4-worker rm -rf "$staging"
if [ "$status" -ne 0 ]; then
    rm -f "$out.pending"
    exit "$status"
fi
mv "$out.pending" "$out"
cat "$out"
