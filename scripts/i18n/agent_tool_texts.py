"""Collect the English tool texts of the research agent into `tool_texts/en.json`.

Usage, from the repository root. The first command reads the tools of every MCP server
that the full research agent connects to, inside its running container:

    docker exec -i hoover4-full-research-agent python - --servers \
        < scripts/i18n/agent_tool_texts.py > /tmp/server-tool-texts.json

The second command adds the tools and the result texts of the agent itself, read from the
source in the agent image, and writes `research_agent/tool_texts/en.json`:

    docker run --rm -i -v "$PWD/main_services/agents/research_agent":/src \
        -v "$PWD/main_services/agents/agent_common/agent_common":/common/agent_common:ro \
        -v /tmp/server-tool-texts.json:/servers.json:ro -e PYTHONPATH=/common:/src -w /src \
        hoover4-research-agent:local python - --write /servers.json \
        < scripts/i18n/agent_tool_texts.py

The file is the sorted list of every tool description, every parameter description and
every agent result text that `localization.localize_text` reads.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, List


def descriptions(schema: Any) -> Iterable[str]:
    """Every `description` string of a JSON schema."""
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "description" and isinstance(value, str):
                yield value
            else:
                yield from descriptions(value)
    elif isinstance(schema, list):
        for item in schema:
            yield from descriptions(item)


def tool_texts(tools: Iterable[Any]) -> List[str]:
    """The description and the parameter descriptions of each tool."""
    from research_agent.tool_catalogue import tool_schema

    out: List[str] = []
    for tool in tools:
        out.append((getattr(tool, "description", "") or "").strip())
        out.extend(descriptions(tool_schema(tool)))
    return out


async def server_texts() -> List[str]:
    """The texts of every tool of the MCP servers of this container."""
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from research_agent.agent import acl_headers

    urls = [u for u in os.getenv("MCP_SERVERS", "").split(",") if u]
    headers = acl_headers("i18n", [], "i18n", "i18n")
    client = MultiServerMCPClient({
        f"mcp_server_{i}": {"url": url, "transport": "streamable_http", "headers": headers}
        for i, url in enumerate(urls)
    })
    return tool_texts(await client.get_tools())


def local_texts() -> List[str]:
    """The texts of the tools that the agent builds itself, and its result texts."""
    from research_agent import skill_tools, stumbles, tool_catalogue

    snapshot = tool_catalogue.build_snapshot([], ["search_agent_tools", "search_skills",
                                                  "read_skill", "read_tool", "write_note"], "chat")
    return tool_texts(snapshot.tools_for()) + [
        tool_catalogue.NO_MATCH_TEXT, tool_catalogue.MATCH_TEXT, skill_tools.READ_SKILL_HINT,
        skill_tools.NO_SKILL_TEXT, stumbles.SKILL_LINE,
    ]


def main() -> int:
    if "--servers" in sys.argv:
        print(json.dumps(asyncio.run(server_texts()), ensure_ascii=False))
        return 0
    if "--write" in sys.argv:
        servers = json.loads(Path(sys.argv[sys.argv.index("--write") + 1]).read_text())
        texts = sorted({t.strip() for t in servers + local_texts() if t and t.strip()})
        target = Path("research_agent/tool_texts/en.json")
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(texts, ensure_ascii=False, indent=1) + "\n")
        print(f"{len(texts)} texts in {target}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
