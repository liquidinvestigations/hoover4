"""FastMCP server exposing one agent todo list per chat conversation.

Tools:
    ``read_todo``   the whole list, cheap, callable any time
    ``write_todo``  replaces goal and items wholesale -- the plan-first call
    ``edit_todo``   rewrites the rows and leaves the goal alone
    ``mark_todo``   batched status changes by item id

**This server holds no rules of its own.** Every shape, every limit and both of the
rules that stop the plan protocol being gamed live in `database.chat_todos`, which the
chat workflow reads directly. A check re-implemented here would be a second copy that
drifts, and the disagreement would surface as a model told its write was accepted while
the workflow reads a list that never changed. What this module adds is exactly three
things: the caller's identity out of the request headers, the argument coercion models
need, and a refusal the model can read.

Four tools rather than one dispatch tool with a `mode` argument. Each has a genuinely
different argument shape -- no arguments, a goal plus rows, rows alone, marks -- and a
typed schema is what makes a model call it correctly the first time.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field

from agent_common import batching

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
    "Keep the plan for this conversation. Call `read_todo` to see it -- it is cheap and "
    "safe to call at any point. When `needs_plan` comes back true there is no live plan, "
    "so write one with `write_todo`: a one-line goal and the steps you intend to take. "
    "As you work, `mark_todo` each step in_progress and then done. If the plan itself "
    "changes -- a step turns out to be unnecessary, or a new one appears -- use "
    "`edit_todo` to rewrite the rows, or `write_todo` to replace the whole plan when the "
    "goal has moved. An item you are abandoning is `cancelled` and must carry a note "
    "saying why, because a cancelled item counts as settled and the note is the whole "
    "record of the decision."
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
    description="""Replace the whole plan for this conversation -- the goal and every step. Use it at the start of a piece of work, and again whenever the objective itself changes.

Args:
    goal: str
        One or two sentences saying what this conversation is trying to achieve.
    items: list[{id, text, status, note}]
        The steps, in the order you mean to do them, e.g.
        [{"id": "1", "text": "find the contract", "status": "pending"}]
        `id` may be omitted and is then numbered for you. `status` defaults to pending.
""",
)
def write_todo(goal: str = "", items: Any = None) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    try:
        todo = chat_todos.write_todo(
            caller.username, caller.session_id, goal, batching.as_objects(items)
        )
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
    description="""Rewrite the steps of the plan without touching the goal. Use it to add a step you did not foresee, reword one, or drop one that turned out to be unnecessary.

Send the list you want to end up with, not a patch -- every step you still want, including the ones that have not changed. Anything you leave out is removed.

Args:
    items: list[{id, text, status, note}]
        The complete list of steps after your edit. Keep each step's existing `id` and
        `status` so its progress is not reset.
""",
)
def edit_todo(items: Any = None) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    try:
        todo = chat_todos.edit_todo(
            caller.username, caller.session_id, batching.as_objects(items)
        )
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
    description="""Change the status of one or more steps. Mark several at once rather than one call per step.

Args:
    marks: list[{id, status, note}]
        e.g. [{"id": "1", "status": "done"}, {"id": "2", "status": "in_progress"}]
        `status` is pending, in_progress, done or cancelled. A step you are giving up on
        is `cancelled` and MUST carry a `note` saying why -- a cancelled step counts as
        settled, so the note is the entire record of the decision, and the call is
        refused without it.
""",
)
def mark_todo(marks: Any = None) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    try:
        todo = chat_todos.mark_todo(
            caller.username, caller.session_id, batching.as_objects(marks)
        )
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


def main() -> None:
    log.info("Starting Hoover4 agent todo MCP server")
    mcp.run(
        transport="http",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8088")),
    )


if __name__ == "__main__":
    main()
