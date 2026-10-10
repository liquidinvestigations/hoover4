"""FastMCP server exposing one agent todo list per chat conversation.

Tools:
    ``read_todo``   the whole list, cheap, callable any time
    ``write_todo``  sets the goal and the steps, the plan-first call
    ``edit_todo``   revises the steps and keeps the goal and the done steps
    ``mark_todo``   pending, or done with a reason, for a list of step ids

**This server holds no rules of its own.** Every shape, every limit and every rule
about statuses, reasons and identities lives in `database.chat_todos`, which the
chat workflow reads directly. A check re-implemented here would be a second copy that
drifts, and the disagreement would surface as a model told its write was accepted while
the workflow reads a list that never changed. What this module adds is exactly three
things: the caller's identity out of the request headers, typed arguments, and a
refusal the model can read.

Four tools rather than one dispatch tool with a `mode` argument. Each has a different
argument shape (no arguments, a goal and a list of step strings, a list of step strings
with optional replacement entries, a list of step ids with one status and a reason), and
a typed schema is what makes a model call it correctly the first time. The store gives
every id. The only object argument is the optional replacement entry of `edit_todo`.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any, Literal, NoReturn, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field, PrivateAttr, model_serializer

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
    "of the steps you intend to take. The server gives each step its id. A step is "
    "pending until its work ends. Then call `mark_todo` with its `ids`, status done and "
    "a short reason in `note`, such as found, not found or replaced. Done steps stay in "
    "the list. To revise the steps for the same goal, call `edit_todo` with the full "
    "list of `steps`. When a new step replaces an old one, add a replacement entry with "
    "the old id, the new text and the reason. When the goal changes, call `write_todo` "
    "again."
)


class TodoItem(BaseModel):
    """One row of the plan, with the status a reader sees."""

    id: str = Field(description="Short stable identifier, unique within the list")
    text: str = Field(description="What this step is")
    status: str = Field(description="pending or done")
    note: str = Field(default="", description="Why a done step ended")
    replaces_id: str = Field(default="", description="The id of the step this step replaces")


class Replacement(BaseModel):
    """One replacement entry of `edit_todo`."""

    id: str = Field(description="The id of the step that the new step replaces.")
    text: str = Field(description="The new step text. It must also be in steps.")
    note: str = Field(description="Why the old step ended, such as replaced by a narrower search.")


class TodoResponse(BaseModel):
    """The whole list after the call, whether the call changed it or not.

    A refusal is a tool error whose text is this response, with the *unchanged* list
    beside its `error`: the model has just been told its write did not happen and the
    next thing it needs is what the plan actually says.
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
    unchanged: bool = Field(default=False, description="True when the call changed nothing")
    error: Optional[str] = Field(
        default=None, description="Why the call was refused, in words to act on"
    )
    _result_kind: str = PrivateAttr(default="read")

    @model_serializer
    def _slim_result(self) -> dict[str, Any]:
        items = [item.model_dump(exclude_defaults=True) for item in self.items]
        if not self.success:
            return {"success": False, "error": self.error, "version": self.version, "items": items}
        if self._result_kind == "write":
            out = {"version": self.version, "ids": [item.id for item in self.items],
                   "summary": self.summary}
            if self.unchanged:
                out["unchanged"] = True
            return out
        if self._result_kind in ("edit", "mark"):
            opened = [{"id": item.id, "text": item.text, "status": item.status}
                      for item in self.items if item.status != "done"]
            out = {"version": self.version, "summary": self.summary, "open": opened}
            if self.unchanged:
                out["unchanged"] = True
            if self.needs_plan:
                out["needs_plan"] = True
            return out
        out = {"goal": self.goal, "items": items, "version": self.version,
               "summary": self.summary}
        if self.needs_plan:
            out["needs_plan"] = True
        return out


mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_todo"),
    instructions=os.getenv("SERVER_INSTRUCTIONS", SERVER_INSTRUCTIONS),
)


def _caller() -> Caller:
    """Whose plan the in-flight request is about."""
    return parse_caller(dict(get_http_headers()))


def _response(todo: dict, error: str | None = None, kind: str = "read") -> TodoResponse:
    """One snapshot rendered for the model, with the derived facts it acts on.

    The items carry display statuses, so a legacy `in_progress` reads as pending and a
    legacy `cancelled` as done with its note. The stored row is unchanged.
    """
    response = TodoResponse(
        success=error is None,
        goal=todo.get("goal", ""),
        items=[TodoItem(**item) for item in chat_todos.display_items(todo.get("items", []))],
        version=int(todo.get("version", 0)),
        needs_plan=chat_todos.needs_plan(todo),
        summary=chat_todos.summarise(todo),
        unchanged=bool(todo.get("unchanged")),
        error=error,
    )
    response._result_kind = kind
    return response


# The step lists are typed lists of strings. The agent decodes a JSON string argument
# against this schema before the call (`research_agent/tool_args.py`), so a parser that
# sends a list as a string still reaches the store.


#: The refusal of `edit_todo` in a conversation that has no plan yet.
NO_PLAN_ERROR = "No plan exists yet. Call write_todo first."


def _refused(caller: Caller | None, message: str) -> NoReturn:
    """Refuse the call as a tool error whose text is the plan as it still stands.

    A tool error marks the result as failed, so the agent keeps the refusal as a failed
    result. With no identified caller there is no list to read, so the refusal goes out
    on the empty one -- an unauthenticated call must not be answered with someone's plan.
    """
    if caller is None:
        todo = chat_todos.empty_todo()
    else:
        todo = chat_todos.read_todo(caller.username, caller.session_id)
    raise ToolError(_response(todo, error=message).model_dump_json())


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
        "to do them. A new goal starts a new list: the server numbers the steps 1, 2, 3, "
        "and each step starts as pending. The same goal again keeps the done steps, as "
        "edit_todo does."
    ),
)
def write_todo(goal: Annotated[str, Field(description='The task goal in one or two sentences.')], steps: Annotated[list[str], Field(description='The complete ordered list of step sentences.')]) -> TodoResponse:
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
    return _response(todo, kind="write")


@mcp.tool(
    name="edit_todo",
    description=(
        "Revise the steps of the plan and keep the goal. This tool takes steps and an "
        "optional replacements argument. steps is a list of short sentences, the full list "
        "of steps you want, in order. Each step is a plain sentence, with no id and no "
        "status. A step with the same text as before keeps its id and its status. Done "
        "steps stay in the list. An open step you leave out becomes done with the reason "
        "removed from plan. When a new step replaces an old one, give a replacements "
        "entry with id, the old step id, text, the new step text from steps, and note, "
        "why the old step ended. The old step becomes done and stays directly above the "
        "new one. This tool takes no goal. Only write_todo takes a goal. To set a status, "
        "use mark_todo."
    ),
)
def edit_todo(
    steps: Annotated[list[str], Field(description='The complete ordered list of current step sentences. Matching text retains its identity and status.')],
    replacements: Annotated[list[Replacement], Field(description='Optional. One entry for each old step that a new step replaces.')] = [],
) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    if not chat_todos.read_todo(caller.username, caller.session_id).get("version"):
        return _refused(caller, NO_PLAN_ERROR)
    try:
        todo = chat_todos.edit_steps(caller.username, caller.session_id, steps,
                                     [entry.model_dump() for entry in replacements])
    except chat_todos.TodoError as exc:
        return _refused(caller, str(exc))
    log.info(
        "edit_todo user=%s session=%s v%s %s",
        caller.username,
        caller.session_id,
        todo["version"],
        chat_todos.summarise(todo),
    )
    return _response(todo, kind="edit")


@mcp.tool(
    name="mark_todo",
    description=(
        "Set the status of one or more steps in one call. This tool takes three "
        "arguments. ids is a list of step ids from the plan, such as 1 and 2. status is "
        "one status for all of them: pending or done. note is a short reason, such as "
        "found, not found or replaced. A done step needs a note, and the call is refused "
        "without it. This tool takes no goal and no steps. Only write_todo takes a goal, "
        "and only write_todo and edit_todo take steps. Mark a step done when its work "
        "ends."
    ),
)
def mark_todo(
    ids: Annotated[list[str], Field(description='Copy returned step identifiers as a list of strings.')],
    status: Annotated[Literal["pending", "done"], Field(description='One status for every selected step. Done requires a note.')],
    note: Annotated[str, Field(description='A short reason, such as found or not found. Required when status is done.')] = "",
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
    return _response(todo, kind="mark")


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
