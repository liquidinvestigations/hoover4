"""The three tools that read the skill store and the tool catalogue.

`search_skills` lists the skills of a run that match a request. `read_skill` gives the text
of one skill. `read_tool` gives the full description and the arguments of one tool of the
run. The tools are local to the agent service, like
`search_agent_tools`, and `tool_catalogue.build_snapshot` builds them for each step context.

A refusal raises `ToolException`, so the result of the call has status `error` and its
text is the JSON refusal.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from langchain_core.tools import StructuredTool, ToolException
from pydantic import BaseModel, Field, field_validator

from research_agent.skill_store import (
    SkillContext,
    listed_skills,
    render_skill,
    search_skills,
)

SEARCH_SKILLS = "search_skills"
READ_SKILL = "read_skill"
READ_TOOL = "read_tool"
ASK_USER = "ask_user"
SKILL_TOOLS = (SEARCH_SKILLS, READ_SKILL, READ_TOOL, ASK_USER)

#: The most characters a `search_skills` query may hold.
QUERY_MAX_CHARS = 160
#: The most characters a skill or tool name argument may hold.
NAME_MAX_CHARS = 64

READ_SKILL_HINT = "Read a skill with read_skill."
NO_SKILL_TEXT = "No skill matches this request."

DESCRIPTIONS = {
    SEARCH_SKILLS: "Find skills by a few words. An empty query lists every skill of this run.",
    READ_SKILL: "Read one skill, a short text that describes one method.",
    READ_TOOL: (
        "Read the full text and the arguments of one tool."
    ),
    ASK_USER: (
        "Ask the person one question and wait for the answer. Use this when the request "
        "has two meanings or needs a fact that only the person knows."
    ),
}


class SearchSkillsArgs(BaseModel):
    query: str = Field(
        default="",
        max_length=QUERY_MAX_CHARS,
        description="A few words about the work, for example `read an email`. Empty lists every skill.",
    )


class ReadSkillArgs(BaseModel):
    name: str = Field(
        min_length=1, max_length=NAME_MAX_CHARS, description="The name of one skill."
    )


class ReadToolArgs(BaseModel):
    name: str = Field(
        min_length=1, max_length=NAME_MAX_CHARS, description="The name of one tool."
    )


class AskUserArgs(BaseModel):
    question: str = Field(min_length=1, max_length=500, description="One question for the person.")
    options: List[str] = Field(default_factory=list, max_length=6,
                               description="Up to six possible answers.")

    @field_validator("options")
    @classmethod
    def valid_options(cls, options: List[str]) -> List[str]:
        if any(not 1 <= len(option) <= 80 for option in options):
            raise ValueError("Each option needs 1 to 80 characters.")
        return options


def _refusal(error: str, message: str) -> str:
    return json.dumps({"success": False, "error": error, "message": message})


def search_skills_result(query: str, ctx: SkillContext) -> Dict[str, Any]:
    """The result of one `search_skills` call as a dict."""
    matches = search_skills(query, ctx)
    return {"matches": matches, "text": READ_SKILL_HINT if matches else NO_SKILL_TEXT}


def _is_listed(name: str, ctx: SkillContext) -> bool:
    return any(skill.name == name for skill in listed_skills(ctx))


def read_skill_result(name: str, ctx: SkillContext) -> str:
    """The text of a read_skill result: render_skill(name, ctx) for a listed skill, else
    the JSON refusal unknown_skill. The tool object passes context.skill_context."""
    if _is_listed(name, ctx):
        return render_skill(name, ctx)
    names = ", ".join(skill.name for skill in listed_skills(ctx))
    return _refusal("unknown_skill", f"No skill is named {name!r}. The skills are {names}.")


def read_tool_result(name: str, snapshot: Any) -> Dict[str, Any]:
    """The result of one `read_tool` call as a dict, or the refusal as a dict with
    `success` false."""
    from research_agent.tool_catalogue import SEARCH_TOOL, tool_schema

    tool = snapshot.tools_by_name.get(name)
    if tool is None:
        message = f"No tool of this run is named {name!r}."
        if SEARCH_TOOL in snapshot.tools_by_name:
            message += f" Find tools with {SEARCH_TOOL}."
        return json.loads(_refusal("tool_unavailable", message))
    schema = tool_schema(tool)
    return {
        "tool": name,
        "description": (getattr(tool, "description", "") or "").strip(),
        "parameters": {
            "properties": schema.get("properties") or {},
            "required": list(schema.get("required") or []),
        },
    }


def read_tool_name(content: Any) -> Optional[str]:
    """The tool name out of one successful `read_tool` result, or `None`."""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tool"), str):
        return None
    return data["tool"]


def make_skill_tools(
    snapshot_of: Callable[[], Any], context_of: Callable[[], SkillContext]
) -> List[StructuredTool]:
    """Return the tools over the snapshot and the skill context that the two
    functions return when a tool runs."""

    async def search_skills_tool(query: str = "") -> str:
        return json.dumps(search_skills_result(query, context_of()))

    async def read_skill_tool(name: str) -> str:
        ctx = context_of()
        text = read_skill_result(name, ctx)
        if not _is_listed(name, ctx):
            raise ToolException(text)
        return text

    async def read_tool_tool(name: str) -> str:
        result = read_tool_result(name, snapshot_of())
        if result.get("success") is False:
            raise ToolException(json.dumps(result))
        return json.dumps(result)

    async def ask_user_tool(question: str, options: List[str] | None = None) -> str:
        return json.dumps({"success": True, "asked": True, "question": question,
                           "options": options or []})

    def build(name, coroutine, schema):
        return StructuredTool.from_function(
            coroutine=coroutine,
            name=name,
            description=DESCRIPTIONS[name],
            args_schema=schema,
            handle_tool_error=True,
        )

    return [
        build(SEARCH_SKILLS, search_skills_tool, SearchSkillsArgs),
        build(READ_SKILL, read_skill_tool, ReadSkillArgs),
        build(READ_TOOL, read_tool_tool, ReadToolArgs),
        build(ASK_USER, ask_user_tool, AskUserArgs),
    ]


__all__ = [
    "ASK_USER", "DESCRIPTIONS", "NO_SKILL_TEXT", "READ_SKILL", "READ_SKILL_HINT", "READ_TOOL",
    "SEARCH_SKILLS", "SKILL_TOOLS", "make_skill_tools", "read_skill_result",
    "read_tool_name", "read_tool_result", "search_skills_result",
]
