"""The served server lists the plan tools.

The image starts `python -m agent_todo_server`. Each case starts a fresh interpreter the same
way, replaces `FastMCP.run` so that it prints the tools of the server it was asked to serve,
and reads that list. A start that serves a second copy of `server.py` lists only the four todo
tools.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

TODO_TOOLS = {"read_todo", "write_todo", "edit_todo", "mark_todo"}
PLAN_TOOLS = {
    "read_plan",
    "append_node",
    "append_child",
    "move_node",
    "edit_node",
    "remove_node",
    "read_plan_document",
}

PROBE = """
import asyncio, json, runpy, sys
import fastmcp

def run(self, **_kwargs):
    print(json.dumps(sorted(asyncio.run(self.get_tools()))))

fastmcp.FastMCP.run = run
runpy.run_module(sys.argv[1], run_name="__main__", alter_sys=True)
"""


def served_tools(module: str) -> set[str]:
    result = subprocess.run(
        [sys.executable, "-c", PROBE, module],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return set(json.loads(result.stdout.strip().splitlines()[-1]))


@pytest.mark.parametrize("module", ["agent_todo_server", "agent_todo_server.server"])
def test_the_served_server_lists_the_plan_tools(module):
    tools = served_tools(module)
    assert PLAN_TOOLS <= tools
    assert TODO_TOOLS <= tools
