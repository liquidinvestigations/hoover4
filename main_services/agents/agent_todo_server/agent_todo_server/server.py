"""FastMCP server exposing one agent plan and one workspace per chat conversation.

Tools:
    ``update_plan``  sets the goal and the whole step list with the status of each step

The workspace tools ``read_file``, ``write_file`` and ``patch_file`` are in `workspace.py`.

**This server holds no rules of its own.** Every shape, every limit and every rule
about statuses, reasons and identities lives in `database.chat_todos`, which the
chat workflow reads directly. A check re-implemented here would be a second copy that
drifts, and the disagreement would surface as a model told its write was accepted while
the workflow reads a list that never changed. What this module adds is exactly three
things: the caller's identity out of the request headers, typed arguments, and a
refusal the model can read.

One plan tool takes the whole list and returns the whole list. With four todo tools, the
agent model called `write_todo` when it meant to write a report file, and it read the
short results of the list tools as a fault. The store gives every id.
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any, Literal, NoReturn, Optional

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field, model_serializer

from agent_todo_server import workspace
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
    "Keep the plan for this conversation with `update_plan`. Send the goal in one or two "
    "sentences and the whole list of steps, each with its text and its status, pending or "
    "done. Give a done step a short note, such as found or not found. Send the whole list "
    "again when a step ends or the plan changes. The result shows the whole plan."
)


class TodoItem(BaseModel):
    """One row of the plan, with the status a reader sees."""

    id: str = Field(description="Short stable identifier, unique within the list")
    text: str = Field(description="What this step is")
    status: str = Field(description="pending or done")
    note: str = Field(default="", description="Why a done step ended")
    replaces_id: str = Field(default="", description="The id of the step this step replaces")


class PlanStep(BaseModel):
    """One step of an `update_plan` call."""

    text: str = Field(description="The step, as a short sentence.")
    status: Literal["pending", "done"] = Field(default="pending", description="pending, or done when the work of the step ended.")
    note: str = Field(default="", description="For a done step, a short reason, such as found or not found.")


class TodoResponse(BaseModel):
    """The whole plan after the call, whether the call changed it or not.

    A refusal is a tool error whose text is this response, with the *unchanged* plan
    beside its `error`: the model has just been told its write did not happen and the
    next thing it needs is what the plan actually says.
    """

    success: bool = Field(description="Whether the call was accepted")
    goal: str = Field(default="", description="The long-term objective")
    items: list[TodoItem] = Field(default_factory=list, description="The plan, in order")
    version: int = Field(
        default=0, description="Update counter. 0 means nothing has ever been written"
    )
    summary: str = Field(default="", description="How much of the plan is resolved")
    unchanged: bool = Field(default=False, description="True when the call changed nothing")
    error: Optional[str] = Field(
        default=None, description="Why the call was refused, in words to act on"
    )

    @model_serializer
    def _slim_result(self) -> dict[str, Any]:
        items = [item.model_dump(exclude_defaults=True) for item in self.items]
        if not self.success:
            return {"success": False, "error": self.error, "version": self.version, "items": items}
        out = {"goal": self.goal, "items": items, "version": self.version, "summary": self.summary}
        if self.unchanged:
            out["unchanged"] = True
        return out


mcp = FastMCP(
    name=os.getenv("SERVER_NAME", "hoover4_todo"),
    instructions=os.getenv("SERVER_INSTRUCTIONS", SERVER_INSTRUCTIONS),
)


def _caller() -> Caller:
    """Whose plan the in-flight request is about."""
    return parse_caller(dict(get_http_headers()))


def _response(todo: dict, error: str | None = None) -> TodoResponse:
    """One snapshot rendered for the model.

    The items carry display statuses, so a legacy `in_progress` reads as pending and a
    legacy `cancelled` as done with its note. The stored row is unchanged.
    """
    return TodoResponse(
        success=error is None,
        goal=todo.get("goal", ""),
        items=[TodoItem(**item) for item in chat_todos.display_items(todo.get("items", []))],
        version=int(todo.get("version", 0)),
        summary=chat_todos.summarise(todo),
        unchanged=bool(todo.get("unchanged")),
        error=error,
    )


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
    name="update_plan",
    description=(
        "Set the plan of this conversation: the goal and the whole list of steps, each "
        "with its status. Use it for work with several steps. Send the whole list again "
        "when a step ends or the plan changes. A step with the same text keeps its id. "
        "The result shows the whole plan. This tool only keeps the plan. It writes no "
        "file and no answer."
    ),
)
def update_plan(
    goal: Annotated[str, Field(description="The task goal in one or two sentences.")],
    steps: Annotated[list[PlanStep], Field(description="The whole ordered list of steps, each with text and status.")],
) -> TodoResponse:
    try:
        caller = _caller()
    except CallerUnknown as exc:
        return _refused(None, str(exc))
    try:
        todo = chat_todos.update_plan(caller.username, caller.session_id, goal,
                                      [step.model_dump() for step in steps])
    except chat_todos.TodoError as exc:
        return _refused(caller, str(exc))
    log.info(
        "update_plan user=%s session=%s v%s %s",
        caller.username,
        caller.session_id,
        todo["version"],
        chat_todos.summarise(todo),
    )
    return _response(todo)


workspace.register(mcp)


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
