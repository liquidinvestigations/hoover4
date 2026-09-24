"""The tool pack table against the tools the MCP servers list.

This file is copied into every MCP server image as `tests/shared/`. In each image it builds
the server that the image holds, lists its tools through the server's own `list_tools`
(over an in-memory client), and asserts that each name is in exactly one pack. A tool that
no pack names is refused for every agent run, so a new tool with no pack fails here.
"""

import asyncio
import importlib
import importlib.util
import os
import sys
from types import SimpleNamespace

import pytest

from agent_common.tool_packs import ALL, PACKS, RUN_KINDS, allowed_tools, pack_of, packs_for

# The image's own server sources are in the working directory, and some images import
# them from there rather than from an installed package.
sys.path.insert(0, os.getcwd())

#: (module, server attribute) for each of the five MCP servers.
SERVERS = (
    ("collection_search_server.server", "mcp"),
    ("metasearch_server.server", "mcp"),
    ("whois_server.server", "whois_server"),
    ("agent_todo_server.server", "mcp"),
    ("browser_use_server.server", "mcp"),
)


def test_each_tool_name_is_in_exactly_one_pack():
    names = [name for tools in PACKS.values() for name in tools]
    assert len(names) == len(set(names))


def test_every_run_kind_gets_every_pack_by_default():
    for kind in RUN_KINDS:
        assert packs_for(kind, ALL) == frozenset(PACKS)
        assert packs_for(kind, "") == frozenset(PACKS)


def test_a_narrowed_setting_gives_only_its_packs():
    assert allowed_tools("subagent", "collections,catalogue") == (
        PACKS["collections"] | PACKS["catalogue"]
    )


def test_an_unknown_pack_or_kind_raises():
    with pytest.raises(ValueError):
        packs_for("chat", "collections,browsr")
    with pytest.raises(ValueError):
        packs_for("executor", ALL)


def _present_server():
    for module, attribute in SERVERS:
        try:
            if importlib.util.find_spec(module) is not None:
                return module, attribute
        except ModuleNotFoundError:
            continue
    return None


async def _browser_tools(server_module):
    """Register the browser server's tools over a stub sidecar that lists the default
    interactive tools and one tool the server registers disabled."""
    exposed = sorted(server_module.exposed_tools())
    specs = [
        SimpleNamespace(
            name=name, title=None, description=name, outputSchema=None,
            inputSchema={"type": "object", "properties": {}},
        )
        for name in exposed + ["browser_evaluate"]
    ]

    async def list_tools():
        return specs

    async def template():
        return SimpleNamespace(client=SimpleNamespace(list_tools=list_tools))

    server_module.router.template = template
    await server_module._register_tools()


async def _listed_names(module, attribute):
    from fastmcp import Client

    server_module = importlib.import_module(module)
    if module == "browser_use_server.server":
        await _browser_tools(server_module)
    async with Client(getattr(server_module, attribute)) as client:
        return sorted(tool.name for tool in await client.list_tools())


def test_every_tool_this_image_lists_is_in_one_pack():
    present = _present_server()
    if present is None:
        pytest.skip("no MCP server package in this image")
    names = asyncio.run(_listed_names(*present))
    assert names, f"{present[0]} lists no tool"
    unpacked = [name for name in names if pack_of(name) is None]
    assert unpacked == [], f"{present[0]} lists tools that no pack names: {unpacked}"
