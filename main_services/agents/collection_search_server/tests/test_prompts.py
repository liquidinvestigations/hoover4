"""The drift test for the server's `instructions`.

`instructions` is read by whichever agent connects, at tool-discovery time, before it has
written a single query. It names the tools in the order they are used, and a name that no
longer exists is worse than no instruction at all, because the model tries it.

Two checks, and the first is the one that fails silently: the tool list the prose renders from is
compared to the tools `server.py` has actually registered with `@mcp.tool`. A rename that
touches only one of the two fails here.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from collection_search_server import prompts

#: Backticked words that are deliberately not tools: fields and arguments the prose names.
NOT_TOOLS = frozenset({"page_text", "error", "max_results"})

BACKTICKED = re.compile(r"`([a-z][a-z0-9_]*)`")


def test_the_declared_tools_are_the_tools_the_server_registers():
    """`SERVER_TOOLS` is a pin, and this is what keeps it accurate.

    The instructions string is handed to the FastMCP constructor before a single tool has
    been decorated, so the list cannot be read off the server at render time. It can be
    read off it here.

    `asyncio.run` rather than an async test: this image installs pytest and not
    pytest-asyncio, and an async test would be collected, skipped and reported as passing.
    """
    from collection_search_server.server import mcp

    registered = set(asyncio.run(mcp.get_tools()))
    assert registered == set(prompts.SERVER_TOOLS), (
        "collection_search_server/prompts/ declares "
        f"{sorted(prompts.SERVER_TOOLS)} but the server registers {sorted(registered)}"
    )


def test_the_instructions_name_only_registered_tools():
    named = {
        word
        for word in BACKTICKED.findall(prompts.SERVER_INSTRUCTIONS)
        if word not in NOT_TOOLS
    }
    unknown = named - set(prompts.SERVER_TOOLS)
    assert not unknown, f"the server instructions name {sorted(unknown)}, which it does not register"


def test_every_registered_tool_is_mentioned():
    named = set(BACKTICKED.findall(prompts.SERVER_INSTRUCTIONS))
    missing = set(prompts.SERVER_TOOLS) - named
    assert not missing, f"the server instructions never mention {sorted(missing)}"


def test_naming_an_unregistered_tool_is_an_error_under_strict_rendering():
    with pytest.raises(prompts.UnboundToolError):
        prompts.render(tools=[name for name in prompts.SERVER_TOOLS if name != "read_documents"], strict=True)


def test_the_match_syntax_stands_alone():
    """It is handed back verbatim when a query fails to parse, so it has to read alone."""
    assert "page_text` is the ONLY searchable field" in prompts.MATCH_SYNTAX
    assert prompts.MATCH_SYNTAX in prompts.SERVER_INSTRUCTIONS
