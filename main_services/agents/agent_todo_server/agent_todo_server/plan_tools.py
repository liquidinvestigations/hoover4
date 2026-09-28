"""The plan tools: read and change the plan tree of a deep-research plan run.

Tools:
    ``read_plan``           the tree with the number path and the id of each node, and its sections
    ``append_node``         a new top-level node
    ``append_child``        a new child of a node
    ``move_node``           a node to a new parent and position
    ``edit_node``           the text of a node, the root included
    ``remove_node``         a node and its subtree
    ``read_plan_document``  one page of a prompt, report, review or final report

**Which plan.** The server reads the agent run id from `X-Hoover4-Agent-Run`, reads that
run's `agent_runs` row under the owner from the other headers, and takes its `plan_run_id`.
A child row copies the `plan_run_id`, so the sub-agents of a planner reach the plan too. No
tool argument names a plan, a run or an owner.

**No role check.** Every run kind of the plan may call every plan tool. The plan run state
is the only rule: a mutation is valid only in `planning` or `revising`. After approval the
tree is frozen, and `read_plan` returns the approved version.

**A parent by id or by number path.** `append_child` and `move_node` accept the parent as a
node id or as the number path that `read_plan` shows (`root`, `1`, `1.2`). A value that names
no node is refused with the path, id and text of the nodes. Every other node argument takes
the id only, so a wrong number never edits or removes a node.

**One writer at a time.** Parallel runs can change one plan, and each version is one row.
The server holds one `asyncio.Lock` for each plan run. A mutation takes the lock, reads the
newest version, applies the change, writes version plus one, and releases the lock, so the
next holder reads the new version. This holds because the server runs as one process.

**One version for each mutation key.** A mutation that carries `X-Hoover4-Idempotency-Key`
stores the key on the version it writes. A second call with that key writes nothing and
returns that version. A mutation with no key writes a new version each time.

The tree rules live in `database.agent_plans`, which the worker reads as well.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Optional

from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field, model_serializer

from agent_todo_server.identity import Caller, CallerUnknown, agent_run_id, parse_caller
from agent_todo_server.server import mcp
from database import agent_plans, agent_runs

log = logging.getLogger(__name__)

#: The header that carries the key of one plan mutation. A retried mutation carries the
#: same key, and the server answers it with the version the first call wrote.
IDEMPOTENCY_HEADER = "x-hoover4-idempotency-key"

#: The most characters `read_plan_document` returns in one call.
DOCUMENT_PAGE_CHARS = 16_000

#: One lock for each plan run. An entry is never removed: a plan run id is small and the
#: server restarts with each deployment.
_LOCKS: dict[str, asyncio.Lock] = {}


def plan_lock(plan_run_id: str) -> asyncio.Lock:
    lock = _LOCKS.get(plan_run_id)
    if lock is None:
        lock = _LOCKS[plan_run_id] = asyncio.Lock()
    return lock


class PlanRefused(Exception):
    """A plan call was refused. `code` is stable, and the message says what to do."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PlanSection(BaseModel):
    node_id: str
    title: str
    tasks: list[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    """The tree after the call, or the refusal and the tree as it still stands."""

    success: bool
    plan_state: str = ""
    version: int = 0
    tree: str = Field(default="", description="One node a line, with its outline number")
    root_node_id: str = ""
    sections: list[PlanSection] = Field(default_factory=list)
    code: Optional[str] = Field(default=None, description="The refusal code")
    error: Optional[str] = None

    @model_serializer
    def _slim_result(self) -> dict[str, Any]:
        out: dict[str, Any] = {"plan_state": self.plan_state, "version": self.version,
                               "tree": self.tree}
        if not self.success:
            out.update(success=False, code=self.code, error=self.error)
        return out


class PlanDocumentPage(BaseModel):
    success: bool
    document_id: str = ""
    kind: str = ""
    node_id: str = ""
    offset: int = 0
    next_offset: Optional[int] = None
    total_chars: int = 0
    text: str = ""
    code: Optional[str] = None
    error: Optional[str] = None


@dataclass
class PlanContext:
    caller: Caller
    run: Any
    plan_run: agent_plans.PlanRunRow


def _headers() -> dict[str, str]:
    return dict(get_http_headers())


def _context(headers: dict[str, str]) -> PlanContext:
    """The caller, its agent run and the plan run it serves, or `PlanRefused`."""
    try:
        caller = parse_caller(headers)
        run_id = agent_run_id(headers)
    except CallerUnknown as exc:
        raise PlanRefused("caller_unknown", str(exc)) from exc
    run = agent_runs.read_run(caller.username, caller.session_id, run_id)
    if run is None:
        raise PlanRefused("run_unknown", "this agent run has no row")
    if not run.plan_run_id:
        raise PlanRefused("no_plan", "this agent run serves no plan")
    plan_run = agent_plans.read_plan_run(caller.username, caller.session_id, run.plan_run_id)
    if plan_run is None:
        raise PlanRefused("no_plan", "the plan run of this agent run has no row")
    if agent_plans.is_terminal(plan_run):
        raise PlanRefused("run_closed", f"the plan run is {plan_run.state}")
    return PlanContext(caller, run, plan_run)


def _read_version(plan_run: agent_plans.PlanRunRow) -> int | None:
    """The version `read_plan` shows: the newest while the tree can change, the approved
    version after approval. None means the newest."""
    if plan_run.state in agent_plans.MUTABLE_STATES:
        return None
    return plan_run.approved_version or plan_run.reviewed_version or None


def _response(ctx: PlanContext, snapshot: agent_plans.PlanSnapshot | None,
              refused: PlanRefused | None = None) -> PlanResponse:
    out = PlanResponse(success=refused is None, plan_state=ctx.plan_run.state,
                       code=refused.code if refused else None,
                       error=str(refused) if refused else None)
    if snapshot is not None:
        out.version = snapshot.version
        out.tree = agent_plans.render_tree(snapshot)
        out.root_node_id = snapshot.root_id
        out.sections = [PlanSection(node_id=node.node_id, title=node.text,
                                    tasks=[leaf.text for leaf in leaves])
                        for node, leaves in agent_plans.sections(snapshot)]
    return out


def _snapshot(ctx: PlanContext, version: int | None = None):
    return agent_plans.read_snapshot(ctx.caller.username, ctx.caller.session_id,
                                     ctx.plan_run.plan_id, version)


def idempotency_key(headers: dict[str, str]) -> uuid.UUID | None:
    """The UUID in `X-Hoover4-Idempotency-Key`, or None for a missing or malformed value."""
    lowered = {key.lower(): value for key, value in headers.items()}
    try:
        return uuid.UUID(str(lowered.get(IDEMPOTENCY_HEADER, "")).strip())
    except ValueError:
        return None


async def _mutate(operation: str, **args: Any) -> PlanResponse:
    headers = _headers()
    key = idempotency_key(headers)
    try:
        ctx = await asyncio.to_thread(_context, headers)
    except PlanRefused as exc:
        return PlanResponse(success=False, code=exc.code, error=str(exc))
    async with plan_lock(ctx.plan_run.run_id):
        # Read again under the lock: a decision can have moved the state since.
        try:
            ctx = await asyncio.to_thread(_context, headers)
        except PlanRefused as exc:
            return PlanResponse(success=False, code=exc.code, error=str(exc))
        if key is not None:
            stored = await asyncio.to_thread(
                agent_plans.snapshot_by_key, ctx.caller.username, ctx.caller.session_id,
                ctx.plan_run.plan_id, key)
            if stored is not None:
                # A retry of a mutation that landed: answer with the version it wrote.
                return _response(ctx, stored)
        current = await asyncio.to_thread(_snapshot, ctx)
        named = args.pop("version")
        if current is not None and named != current.version:
            seen = await asyncio.to_thread(_snapshot, ctx, named) if 0 < named < current.version else None
            values = [args[field] for field in ("node_id", "parent_id", "new_parent_id")
                      if args.get(field)]
            if seen is None or any(agent_plans.resolve_node(seen, value) !=
                                   agent_plans.resolve_node(current, value) for value in values):
                return _response(ctx, current, PlanRefused(
                    "stale_version", f"The plan is at version {current.version}, and this call names "
                    f"version {named}. Read the tree below and name its nodes again."))
        if ctx.plan_run.state not in agent_plans.MUTABLE_STATES:
            refused = PlanRefused(
                "plan_frozen",
                f"the plan is {ctx.plan_run.state} and can change only while it is planned. "
                "Read it with read_plan.",
            )
            return _response(ctx, await asyncio.to_thread(
                _snapshot, ctx, _read_version(ctx.plan_run)), refused)
        try:
            new = await asyncio.to_thread(
                agent_plans.mutate, ctx.caller.username, ctx.caller.session_id,
                ctx.plan_run.plan_id, operation, idempotency_key=key, **args)
        except agent_plans.PlanError as exc:
            return _response(ctx, await asyncio.to_thread(_snapshot, ctx),
                             PlanRefused("invalid_plan_change", str(exc)))
    log.info("%s user=%s session=%s plan=%s v%s", operation, ctx.caller.username,
             ctx.caller.session_id, ctx.plan_run.plan_id, new.version)
    return _response(ctx, new)


@mcp.tool(
    name="read_plan",
    description=(
        "Read the plan tree of this research plan: every node with its number path, "
        "indented under its parent. The root has the path root, a "
        "top-level node a number such as 2, and its children 2.1 and 2.2. A section is a "
        "node with at least one leaf child, the root included, and its tasks are those "
        "leaves. After approval this returns the approved version."
    ),
)
async def read_plan() -> PlanResponse:
    try:
        ctx = await asyncio.to_thread(_context, _headers())
    except PlanRefused as exc:
        return PlanResponse(success=False, code=exc.code, error=str(exc))
    return _response(ctx, await asyncio.to_thread(_snapshot, ctx,
                                                  _read_version(ctx.plan_run)))


@mcp.tool(
    name="append_node",
    description=(
        "Add a top-level node to the plan, as the last child of the root. Give version "
        "from the last plan result. Several calls of one reply can give the same version."
    ),
)
async def append_node(version: int, text: str = "") -> PlanResponse:
    return await _mutate("append_node", version=version, text=text)


@mcp.tool(
    name="append_child",
    description=(
        "Add a node as the last child of `parent_id`. `parent_id` is the id of a node, or "
        "its number path from read_plan, such as 1 or 1.2. `text` is one line of at most "
        "120 characters. A node with leaf children is a section, and the leaves are its tasks. "
        "Give version from the last plan result. Calls of one reply can give the same version."
    ),
)
async def append_child(version: int, parent_id: str = "", text: str = "") -> PlanResponse:
    return await _mutate("append_child", version=version, parent_id=parent_id, text=text)


@mcp.tool(
    name="move_node",
    description=(
        "Move a node and its subtree under `new_parent_id` at `position` (1 is first). "
        "`new_parent_id` is a node id or a number path such as 1.2. "
        "An empty `new_parent_id` means the root. The root cannot move. "
        "A position of 0 puts the node last. Give version from the last plan result. "
        "Calls of one reply can give the same version."
    ),
)
async def move_node(version: int, node_id: str = "", new_parent_id: str = "",
                    position: Annotated[int, Field(ge=0)] = 0) -> PlanResponse:
    return await _mutate("move_node", version=version, node_id=node_id, new_parent_id=new_parent_id,
                         position=position)


@mcp.tool(
    name="edit_node",
    description=("Replace the text of one node, the root included. Give node_id as an outline "
                 "number such as 1.2. Give version from the last plan result. "
                 "Calls of one reply can give the same version."),
)
async def edit_node(version: int, node_id: str = "", text: str = "") -> PlanResponse:
    return await _mutate("edit_node", version=version, node_id=node_id, text=text)


@mcp.tool(
    name="remove_node",
    description=("Remove one node and its whole subtree. The root cannot be removed. "
                 "Give node_id as an outline number such as 1.2. Give version from the last "
                 "plan result. Calls of one reply can give the same version."),
)
async def remove_node(version: int, node_id: str = "") -> PlanResponse:
    return await _mutate("remove_node", version=version, node_id=node_id)


@mcp.tool(
    name="read_plan_document",
    description=(
        "Read one page of a document of this plan: a sub-agent's prompt, report or "
        "review, or the final report. Give `offset` from `next_offset` to read on. With no "
        "`document_id`, the result lists the documents in `text`, one a line."
    ),
)
async def read_plan_document(document_id: str = "",
                             offset: Annotated[int, Field(ge=0)] = 0) -> PlanDocumentPage:
    try:
        ctx = await asyncio.to_thread(_context, _headers())
    except PlanRefused as exc:
        return PlanDocumentPage(success=False, code=exc.code, error=str(exc))
    documents = await asyncio.to_thread(agent_plans.read_documents, ctx.caller.username,
                                        ctx.caller.session_id, ctx.plan_run.run_id)
    wanted = (document_id or "").strip()
    if not wanted:
        listing = "\n".join(f"{d.document_id} {d.kind} node {d.node_id} "
                            f"{len(d.body)} characters" for d in documents)
        return PlanDocumentPage(success=True, text=listing, total_chars=len(listing))
    doc = next((d for d in documents if d.document_id == wanted), None)
    if doc is None:
        return PlanDocumentPage(success=False, code="document_unknown",
                                error="this plan has no document with that id")
    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    end = min(len(doc.body), start + DOCUMENT_PAGE_CHARS)
    return PlanDocumentPage(
        success=True, document_id=doc.document_id, kind=doc.kind, node_id=doc.node_id,
        offset=start, next_offset=end if end < len(doc.body) else None,
        total_chars=len(doc.body), text=doc.body[start:end],
    )
