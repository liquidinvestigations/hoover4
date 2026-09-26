#!/usr/bin/env bash
# Check the batch result budget through the page broker, as the step endpoints apply it.
#
# Inside the full research agent container, the script loads the collection server's tools
# with the agent's own connection settings. It computes the shares of one model step of
# three parallel `search_collections` calls with `batch_budget`, as `/model_step` does, and
# runs each call with its share, as `/tool_call` does. Each call receives its page share in
# the `X-Hoover4-Page-Share` header, and the broker returns the call measure beside the
# page. The results are the same on every run while the indexed data does not change.
#
# Exit status 0 when the three pages total at most 24,000 UTF-8 bytes, every page is
# canonical and returns at least one unit, and the digest of each call measure is the
# SHA-256 of the output that the call returned. Exit status 1 otherwise.
#
# Settings: AGENT_BUDGET_CONTAINER (default hoover4-full-research-agent), MCP_TEST_USER
# (default agent-contract-user), MCP_TEST_COLLECTIONS (default testdata) and
# AGENT_BUDGET_QUERIES (three queries separated by commas).
set -euo pipefail

container="${AGENT_BUDGET_CONTAINER:-hoover4-full-research-agent}"

docker exec -i "$container" env \
    MCP_TEST_USER="${MCP_TEST_USER:-agent-contract-user}" \
    MCP_TEST_COLLECTIONS="${MCP_TEST_COLLECTIONS:-testdata}" \
    AGENT_BUDGET_QUERIES="${AGENT_BUDGET_QUERIES:-the,report,page}" \
    python - <<'PY'
import asyncio
import hashlib
import json
import os
import sys

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent_common.result_pages import SAFE_MODE_BATCH_BYTES, is_canonical_page
from research_agent import execution
from research_agent.agent import acl_headers
from research_agent.tool_catalogue import build_snapshot

TOOL = "search_collections"


async def main() -> int:
    urls = [u for u in os.environ.get("MCP_SERVERS", "").split(",") if ":8085/" in u]
    if not urls:
        print("FAIL: MCP_SERVERS names no collection server")
        return 1
    collections = [c for c in os.environ["MCP_TEST_COLLECTIONS"].split(",") if c]
    headers = acl_headers(os.environ["MCP_TEST_USER"], collections, "batch-budget-check", "batch-budget-check")
    client = MultiServerMCPClient({"collections": {
        "url": urls[0], "transport": "streamable_http", "headers": headers,
        "httpx_client_factory": execution.page_share_client,
    }})
    tools = [t for t in await client.get_tools() if t.name == TOOL]
    snapshot = build_snapshot(tools, {TOOL}, "chat")
    tool = snapshot.tools_by_name[TOOL]
    queries = os.environ["AGENT_BUDGET_QUERIES"].split(",")[:3]
    calls = [
        {"id": f"call-{i}", "name": TOOL, "args": {"collectionname": collections, "query": q}}
        for i, q in enumerate(queries)
    ]
    messages = [HumanMessage(content="batch budget check"), AIMessage(content="", tool_calls=calls)]
    budget = execution.batch_budget([TOOL] * len(calls), messages)
    failed = False
    total = 0
    for call, share in zip(calls, budget.shares):
        token = execution._PAGE_SHARE.set(int(share))
        try:
            result = await tool.ainvoke({"type": "tool_call", **call})
        finally:
            execution._PAGE_SHARE.reset(token)
        content = execution._text_of(result.content if isinstance(result, ToolMessage) else result)
        measure, _ = execution.split_measure(result.artifact if isinstance(result, ToolMessage) else None)
        size = len(content.encode("utf-8"))
        total += size
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        page = json.loads(content) if is_canonical_page(content) else None
        units = page.get("returned_units", 0) if page else 0
        problems = []
        if page is None:
            problems.append(f"the output is not a canonical page: {content[:300]}")
        elif units <= 0:
            problems.append(f"the page returned no unit: {content[:200]}")
        if measure is None:
            problems.append("no call measure")
        elif measure.get("page_sha256") != digest:
            problems.append(f"measure digest {measure.get('page_sha256')} differs from the output digest {digest}")
        elif measure.get("page_bytes") != size:
            problems.append(f"measure bytes {measure.get('page_bytes')} differ from the output bytes {size}")
        share = measure.get("page_share") if measure else None
        status = "FAIL" if problems else "PASS"
        print(f"{status} {call['id']} query={call['args']['query']!r} bytes={size} share={share} units={units} digest={digest}")
        for problem in problems:
            print(f"     {problem}")
        failed = failed or bool(problems)
    if total > SAFE_MODE_BATCH_BYTES:
        print(f"FAIL the batch is {total} bytes, over {SAFE_MODE_BATCH_BYTES}")
        failed = True
    else:
        print(f"PASS the batch is {total} bytes, at most {SAFE_MODE_BATCH_BYTES}")
    return 1 if failed else 0


sys.exit(asyncio.run(main()))
PY
