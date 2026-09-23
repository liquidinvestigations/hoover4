#!/usr/bin/env bash
# Check that a collection MCP result page remains canonical through its tool call.
set -euo pipefail

container="${AGENT_PAGE_CONTAINER:-hoover4-mcp-collections}"
tool="${AGENT_PAGE_TOOL:-list_collections}"

page_digest="$(docker exec -i "$container" env AGENT_PAGE_TOOL="$tool" MCP_TEST_USER="${MCP_TEST_USER:-agent-contract-user}" MCP_TEST_COLLECTIONS="${MCP_TEST_COLLECTIONS:-}" python - <<'PY'
import asyncio
import hashlib
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from agent_common.result_pages import is_canonical_page


async def main():
    headers = {}
    if os.getenv("MCP_TEST_USER"):
        headers["x-hoover4-user"] = os.environ["MCP_TEST_USER"]
    if os.getenv("MCP_TEST_COLLECTIONS"):
        headers["x-hoover4-collections"] = os.environ["MCP_TEST_COLLECTIONS"]
    async with Client(StreamableHttpTransport("http://127.0.0.1:8085/mcp", headers=headers)) as client:
        result = await client.call_tool(os.environ["AGENT_PAGE_TOOL"], {})
    text = result.content[0].text
    if not is_canonical_page(text):
        raise SystemExit("result is not a canonical page")
    print(hashlib.sha256(text.encode("utf-8")).hexdigest())


asyncio.run(main())
PY
)"
printf 'canonical page digest: %s\n' "$page_digest"

session_id="${AGENT_PAGE_STORED_SESSION_ID:-}"
seq="${AGENT_PAGE_STORED_SEQ:-}"
if [[ -z "$session_id" || -z "$seq" ]]; then
  echo 'stored row: not checked'
  exit 0
fi
if [[ ! "$session_id" =~ ^[a-zA-Z0-9-]+$ || ! "$seq" =~ ^[0-9]+$ ]]; then
  echo 'stored row selector is invalid' >&2
  exit 1
fi
row="$(docker exec clickhouse sh -lc 'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "$1"' _ "SELECT base64Encode(tool_output) FROM Hoover4_Processing.chat_messages FINAL WHERE session_id = '$session_id' AND seq = $seq AND tool_name = '$tool' LIMIT 1" )"
if [[ -z "$row" ]]; then
  echo 'stored row: not checked'
  exit 0
fi
stored_digest="$(printf '%s' "$row" | base64 -d | sha256sum | cut -d' ' -f1)"
broker_digest="${AGENT_PAGE_BROKER_SHA256:-}"
if [[ -z "$broker_digest" ]]; then
  echo 'stored row exists but the broker call measure digest was not supplied' >&2
  exit 1
fi
if [[ "$stored_digest" != "$broker_digest" ]]; then
  printf 'stored row digest differs from broker call measure: %s != %s\n' "$stored_digest" "$broker_digest" >&2
  exit 1
fi
printf 'stored row digest matches broker call measure: %s\n' "$stored_digest"
