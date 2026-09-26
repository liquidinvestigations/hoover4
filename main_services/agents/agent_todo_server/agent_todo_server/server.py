"""FastMCP server exposing one agent todo list per chat conversation.

Tools:
    ``read_todo``   the whole list, cheap, callable any time
    ``write_todo``  replaces the goal and the steps, the plan-first call
    ``edit_todo``   replaces the steps and keeps the goal
    ``mark_todo``   one status for a list of step ids

The plan tools of a deep-research plan run register on this server from `plan_tools`.

**This server holds no rules of its own.** Every shape, every limit and both of the
rules that stop the plan protocol being gamed live in `database.chat_todos`, which the
chat workflow reads directly. A check re-implemented here would be a second copy that
drifts, and the disagreement would surface as a model told its write was accepted while
the workflow reads a list that never changed. What this module adds is exactly three
things: the caller's identity out of the request headers, typed arguments, and a
refusal the model can read.

Four tools rather than one dispatch tool with a `mode` argument. Each has a different
argument shape (no arguments, a goal and a list of step strings, a list of step strings,
a list of step ids with one status), and a typed schema is what makes a model call it
correctly the first time. No argument is a JSON object, so the store gives every id.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal, Optional

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from agent_todo_server.identity import Caller, CallerUnknown, parse_caller

# The store, imported from the pipeline package rather than copied: the chat workflow
# reads the same module, and two copies of the cancellation rule would eventually
# disagree about whether a plan was abandoned or finished.
from database import chat_todos

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format=os.getenv("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
)
log = logging.getLogger(__name__)

SERVER_INSTRUCTIONS = (
    "Keep the plan for this conversation. Call `read_todo` to see it. The call is cheap "
    "and you can make it at any point. When `needs_plan` is true there is no live plan, "
    "so write one with `write_todo`: a goal of one or two sentences and `steps`, a list "
    "of the steps you intend to take. The server gives each step its id. As you work, "
    "call `mark_todo` with the step `ids`, first with in_progress and then with done. "
    "When a step becomes unnecessary or a new one appears, call `edit_todo` with the full "
    "list of `steps`. When the goal changes, call `write_todo` again. A step you abandon "
    "is `cancelled` and needs a note that says why, because a cancelled step counts as "
    "settled and the note is the only record of the decision."
)


class TodoItem(BaseModel):
    """One row of the plan, exactly as it is stored."""

    id: str = Field(description="Short stable identifier, unique within the list")
    text: str = Field(description="What this step is")
    status: str = Field(description="pending, in_progress, done or cancelled")
    note: str = Field(default="", description="Why, for a cancelled or surprising item")


class TodoResponse(BaseModel):
    """The whole list after the call, whether the call changed it or not.

    A refusal returns the *unchanged* list alongside its `error` rather than an error
    on its own: the model has just been told its write did not happen and the next
    thing it needs is what the plan actually says.
    """

    success: bool = Field(description="Whether the call was accepted")
    goal: str = Field(default="", description="The long-term objective")
    items: list[TodoItem] = Field(default_factory=list, description="The plan, in order")
    version: int = Field(
        default=0, description="Update counter. 0 means nothing has ever been written"
    )
    needs_plan: bool = Field(
        default=True,
        description="True when there is no plan yet or every item is settled",
    )
    summary: str = Field(default="", description="How much of the plan is resolved")
    error: Optional[str] = Field(
        default=None, description="Why the call was refused, in words to act on"
    )


mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_todo"),
    instructions=os.getenv("SERVER_INSTRUCTIONS", SERVER_INSTRUCTIONS),
)


def _caller() -> Caller:
    """Whose plan the in-flight request is about."""
    return parse_caller(dict(get_http_headers()))


def _response(todo: dict, error: str | None = None) -> TodoResponse:
    """One snapshot rendered for the model, with the two derived facts it acts on."""
    return TodoResponse(
        success=error is None,
        goal=todo.get("goal", ""),
        items=[TodoItem(**item) for item in todo.get("items", [])],
        version=int(todo.get("version", 0)),
        needs_plan=chat_todos.needs_plan(todo),
        summary=chat_todos.summarise(todo),
        error=error,
    )


# The step lists are typed lists of strings. The agent decodes a JSON string argument
# against this schema before the call (`research_agent/tool_args.py`), so a parser that
# sends a list as a string still reaches the store.


def _refused(caller: Caller | None, message: str) -> TodoResponse:
    """A refusal carrying the plan as it still stands.

    With no identified caller there is no list to read, so the refusal goes out on the
    empty one -- an unauthenticated call must not be answered with someone's plan.
    """
    if caller is None:
        return _response(chat_todos.empty_todo(), error=message)
    return _response(
        chat_todos.read_todo(caller.username, caller.session_id), error=message
    )


@mcp.tool(
    name="read_todo",
    description=(
        "Read the plan for this conversation: the goal, every step and its status. "
        "Cheap and safe to call at any time. `needs_plan` is true when there is no "
        "plan yet or every step is already settled, which is when you should write one."
    ),
)
def read_todo() -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    todo = chat_todos.read_todo(caller.username, caller.session_id)
    log.info(
        "read_todo user=%s session=%s %s",
        caller.username,
        caller.session_id,
        chat_todos.summarise(todo),
    )
    return _response(todo)


@mcp.tool(
    name="write_todo",
    description=(
        "Write the plan for this conversation, as a goal and a list of steps. Call it at "
        "the start of a piece of work, and again when the goal changes. Give goal as one "
        "or two sentences. Give steps as a list of short sentences, in the order you mean "
        "to do them. The server numbers the steps 1, 2, 3, and each step starts as pending."
    ),
)
def write_todo(goal: str, steps: list[str]) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    try:
        todo = chat_todos.write_steps(caller.username, caller.session_id, goal, steps)
    except chat_todos.TodoError as exc:
        return _refused(caller, str(exc))
    log.info(
        "write_todo user=%s session=%s v%s %s",
        caller.username,
        caller.session_id,
        todo["version"],
        chat_todos.summarise(todo),
    )
    return _response(todo)


@mcp.tool(
    name="edit_todo",
    description=(
        "Replace the steps of the plan and keep the goal. Give the full list of steps you "
        "want, in order. A step with the same text as before keeps its id and its status. "
        "A step you leave out is removed."
    ),
)
def edit_todo(steps: list[str]) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    try:
        todo = chat_todos.edit_steps(caller.username, caller.session_id, steps)
    except chat_todos.TodoError as exc:
        return _refused(caller, str(exc))
    log.info(
        "edit_todo user=%s session=%s v%s %s",
        caller.username,
        caller.session_id,
        todo["version"],
        chat_todos.summarise(todo),
    )
    return _response(todo)


@mcp.tool(
    name="mark_todo",
    description=(
        "Set the status of one or more steps in one call. Give ids as a list of step ids "
        "from the plan, and one status for all of them: pending, in_progress, done or "
        "cancelled. A cancelled step needs a note that says why, and the call is refused "
        "without it. Mark a step when you start it and when you finish it."
    ),
)
def mark_todo(
    ids: list[str],
    status: Literal["pending", "in_progress", "done", "cancelled"],
    note: str = "",
) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    try:
        todo = chat_todos.mark_steps(caller.username, caller.session_id, ids, status, note)
    except chat_todos.TodoError as exc:
        return _refused(caller, str(exc))
    log.info(
        "mark_todo user=%s session=%s v%s %s",
        caller.username,
        caller.session_id,
        todo["version"],
        chat_todos.summarise(todo),
    )
    return _response(todo)


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Any):
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "hoover4-agent-todo"})


# The plan tools register on the same server. They import `mcp` from this module.
from agent_todo_server import plan_tools  # noqa: E402,F401


def main() -> None:
    log.info("Starting Hoover4 agent todo MCP server")
    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8088")),
    )


if __name__ == "__main__":
    # Run as `__main__`, this file is a second copy of the module, and the plan tools are on
    # the `mcp` of the imported copy. Serve that copy.
    from agent_todo_server.server import main as imported_main

    imported_main()
