"""The server's `instructions`, rendered from the tools it actually registers.

`instructions` is the one piece of prose every agent reads at tool-discovery time,
whichever agent connects and whatever system prompt it was given. It therefore has to
agree with the tools this server exposes, and prose that only *claims* to agree goes stale
the first time a tool is renamed.

So the text lives in the `.md.j2` files beside this module and this loader renders them
with named parameters, of which `tools` decides the rendered prose: **`tools`, the names this
server registers**. `SERVER_TOOLS` is that list, and `tests/test_prompts.py` fails when it
stops matching what `server.py` has actually decorated with `@mcp.tool`, which is what
makes a renamed tool a test failure rather than a sentence nobody corrected.

`SERVER_INSTRUCTIONS` env var still overrides the whole thing, for experiments.

Everything the syntax block claims was verified against a live shard, not taken from
Manticore's documentation. Several documented spellings are a hard 500 on this
deployment. See `main_services/agents/README.md` for the full battery.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined

log = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent

#: The tools this server registers, by name. Pinned here rather than read off the FastMCP
#: instance because the instructions string is handed to the constructor before a single
#: `@mcp.tool` has run. The test that compares this list to the registered one is what
#: keeps the pin honest.
SERVER_TOOLS: Tuple[str, ...] = (
    "list_collections",
    "search_collections",
    "read_documents",
    "list_document_entities",
    "cite_documents",
)


class UnboundToolError(RuntimeError):
    """A template named a tool this server does not register."""


def _environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        # Kept, so that a block ends with its own newline and the blank line that follows
        # an `{% include %}` survives as a paragraph break. With it stripped, `trim_blocks`
        # eats the other half of the pair and two paragraphs run together.
        keep_trailing_newline=True,
    )


def render(
    template: str = "server_instructions.md.j2",
    *,
    tools: Optional[Iterable[str]] = None,
    strict: bool = False,
) -> str:
    """Render one of this server's templates against the tools it registers.

    `strict` turns a template naming an unregistered tool into `UnboundToolError` rather
    than a logged warning. The drift test renders strict; the running server does not, so
    a stale sentence is a failing test and never a server that will not start.
    """
    names: List[str] = list(tools) if tools is not None else list(SERVER_TOOLS)
    present = set(names)

    def tool(tool_name: str) -> str:
        if tool_name not in present:
            if strict:
                raise UnboundToolError(
                    f"this server does not register {tool_name!r}, but its prose names it"
                )
            log.warning("server instructions name %s, which is not registered", tool_name)
        return f"`{tool_name}`"

    context = {
        "tools": names,
        "tool": tool,
        "has": lambda tool_name: tool_name in present,
    }
    return _environment().get_template(template).render(**context).strip()


def server_instructions(tools: Optional[Iterable[str]] = None) -> str:
    """The FastMCP `instructions` string for this server."""
    return render("server_instructions.md.j2", tools=tools)


def match_syntax(tools: Optional[Iterable[str]] = None) -> str:
    """The Manticore MATCH syntax alone, for the tool description that repeats it."""
    return render("_blocks/match_syntax.md.j2", tools=tools)


#: Rendered once at import, because both are read from module scope: `SERVER_INSTRUCTIONS`
#: by the FastMCP constructor, and `MATCH_SYNTAX` by the two error paths that hand the
#: syntax back to a model whose query would not parse.
SERVER_INSTRUCTIONS = server_instructions()
MATCH_SYNTAX = match_syntax()


__all__ = [
    "MATCH_SYNTAX",
    "SERVER_INSTRUCTIONS",
    "SERVER_TOOLS",
    "TEMPLATE_DIR",
    "UnboundToolError",
    "match_syntax",
    "render",
    "server_instructions",
]
