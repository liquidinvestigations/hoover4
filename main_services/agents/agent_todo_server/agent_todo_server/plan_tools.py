"""The plan tools: read and write the plan tree of a deep-research plan run.

Tools:
    ``read_plan``           the tree with the number path of each node, and its sections
    ``write_plan``          the whole tree below the root, at the current version
    ``read_plan_document``  one page of a prompt, report or final report
    ``read_plan_report``    one page of the typed report of a section's sub-agent

**Which plan.** The server reads the agent run id from `X-Hoover4-Agent-Run`, reads that
run's `agent_runs` row under the owner from the other headers, and takes its `plan_run_id`.
A child row copies the `plan_run_id`, so the sub-agents of a plan reach the plan too. No
tool argument names a plan, a run or an owner.

**No role check.** Every run kind of the plan may call every plan tool. The plan run state
is the only rule: a write is valid only in `planning` or `revising`. After approval the
tree is frozen, and `read_plan` returns the approved version.

**A whole tree for each write.** `write_plan` takes the children of the root as nested
nodes, each with its text, an optional `node_id` and its own children. The parent and the
order of each node come from its place in the input. A `node_id`, or a number path of the
current tree, keeps a node's identity. A node with no `node_id` is new.

**One writer at a time, at the exact version.** Parallel runs can change one plan, and each
version is one row. The server holds one `asyncio.Lock` for each plan run. A write takes the
lock, reads the newest version, and writes version plus one only when the call names the
newest version. A call that names another version gets the current tree and writes
nothing. This holds because the server runs as one process.

**One version for each write key.** A write that carries `X-Hoover4-Idempotency-Key` stores
the key on the version it writes. A second call with that key writes nothing and returns
that version, before the version test. A write with no key writes a new version each time.

The tree rules live in `database.agent_plans`, which the worker reads as well.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Annotated, Any, Optional

from fastmcp.server.dependencies import get_http_headers
from pydantic import BaseModel, Field, field_validator, model_serializer

from agent_common.result_pages import canonical_json
from agent_todo_server.identity import Caller, CallerUnknown, agent_run_id, parse_caller
from agent_todo_server.server import mcp
from database import agent_plans, agent_runs

log = logging.getLogger(__name__)

#: The header that carries the key of one plan mutation. A retried mutation carries the
#: same key, and the server answers it with the version the first call wrote.
IDEMPOTENCY_HEADER = "x-hoover4-idempotency-key"

#: The most characters `read_plan_document` returns in one call.
DOCUMENT_PAGE_CHARS = 16_000

#: The most bytes of one `read_plan_report` page, when the call has no smaller page share.
REPORT_PAGE_BYTES = 16_000

#: The longest text of one report unit. A longer text is several units.
REPORT_TEXT_CHARS = 4_000

#: The header that carries the page share of a call.
PAGE_SHARE_HEADER = "x-hoover4-page-share"

#: The evidence lists of a typed report, in the order a page shows them.
REPORT_LISTS = ("documents_read", "citations", "notes", "artifacts", "documents_found")

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


class PlanChild(BaseModel):
    """One top-level node of a `write_plan` tree. The nodes under it have the same three
    fields at every depth. The schema lists them as plain objects, because FastMCP inlines
    a schema reference, and a node that names its own model has no finite schema.
    `agent_plans.build_tree` checks every level."""

    text: str = Field(description="One line of at most 120 characters")
    node_id: str | int = Field(
        default="",
        description="The id or number path of this node in the current tree, to keep it. "
                    "Leave it empty for a new node.")
    children: list[dict[str, Any]] = Field(
        default_factory=list,
        description="The nodes under this node, in their order. Each has text, node_id and "
                    "children, as this node has.")

    @field_validator("node_id")
    @classmethod
    def _node_id_text(cls, value: str | int) -> str:
        """A number path sent as a JSON number, such as 2, is the text "2", as it is in a
        nested node, which `agent_plans.build_tree` reads as text."""
        return str(value)


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


class PlanReportPage(BaseModel):
    """One page of a typed report: its units in `items`, and `more`, the cursor of the
    next page, when units remain."""

    success: bool
    node: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    more: Optional[str] = None
    code: Optional[str] = None
    error: Optional[str] = None

    @model_serializer
    def _slim_result(self) -> dict[str, Any]:
        if not self.success:
            return {"success": False, "code": self.code, "error": self.error}
        out: dict[str, Any] = {"node": self.node, "items": self.items, "total": self.total}
        if self.more:
            out["more"] = self.more
        return out


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


async def _write(version: int, children: list[dict[str, Any]]) -> PlanResponse:
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
                # A retry of a write that landed: answer with the version it wrote.
                return _response(ctx, stored)
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
                agent_plans.replace_tree, ctx.caller.username, ctx.caller.session_id,
                ctx.plan_run.plan_id, children, version=version, idempotency_key=key)
        except agent_plans.StaleVersion as exc:
            return _response(ctx, exc.current, PlanRefused("stale_version", str(exc)))
        except agent_plans.PlanError as exc:
            current = await asyncio.to_thread(_snapshot, ctx)
            message = str(exc)
            if "names no node of version" in message and current is not None:
                paths = agent_plans.node_paths(current)
                allowed = [path for path in paths.values() if path != agent_plans.ROOT_PATH]
                message += (" Use node_id only to keep an existing node. "
                            "Omit node_id for every new node, including its children. "
                            f"Allowed number paths in version {current.version}: "
                            f"{', '.join(allowed) if allowed else 'none'}.")
            return _response(ctx, current, PlanRefused("invalid_plan_change", message))
    log.info("write_plan user=%s session=%s plan=%s v%s", ctx.caller.username,
             ctx.caller.session_id, ctx.plan_run.plan_id, new.version)
    return _response(ctx, new)


@mcp.tool(
    name="read_plan",
    description=(
        "Read the plan tree of this research plan: every node with its number path, "
        "indented under its parent. The root has the path root, a top-level node a number "
        "such as 2, and its children 2.1 and 2.2. Each top-level node is a section, and "
        "one researcher runs it with every node under it. After approval this returns "
        "the approved version."
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
    name="write_plan",
    description=(
        "Write the whole plan tree below the root. `children` holds the top-level nodes in "
        "order. Each node has `text` (one line of at most 120 characters), `children` (the "
        "nodes under it) and, to keep a node of the current tree, its `node_id` or number "
        "path. Each top-level node is a section that one researcher runs with all its "
        "nodes. A plan has at most 4 sections and 150 nodes. Give `version` from the last "
        "plan result. A call that names another version writes nothing and returns the "
        "current tree."
    ),
)
async def write_plan(version: int, children: list[PlanChild]) -> PlanResponse:
    return await _write(version, [child.model_dump() for child in children or []])


@mcp.tool(
    name="read_plan_document",
    description=(
        "Read one page of a document of this plan: a sub-agent's prompt or report, or "
        "the final report. Give `offset` from `next_offset` to read on. With no "
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
                            f"{d.body_bytes or len(d.body.encode())} bytes" for d in documents)
        return PlanDocumentPage(success=True, text=listing, total_chars=len(listing))
    doc = next((d for d in documents if d.document_id == wanted), None)
    if doc is None:
        return PlanDocumentPage(success=False, code="document_unknown",
                                error="this plan has no document with that id")
    try:
        body = await asyncio.to_thread(agent_plans.document_body, ctx.caller.username,
                                       ctx.caller.session_id, doc)
    except Exception as exc:  # noqa: BLE001 - a body or object store failure
        log.warning("the document %s was not read: %s", doc.document_id, exc)
        return PlanDocumentPage(success=False, code="document_unreadable",
                                error="the document cannot be read now. Try again later.")
    try:
        start = max(0, int(offset or 0))
    except (TypeError, ValueError):
        start = 0
    end = min(len(body), start + DOCUMENT_PAGE_CHARS)
    return PlanDocumentPage(
        success=True, document_id=doc.document_id, kind=doc.kind, node_id=doc.node_id,
        offset=start, next_offset=end if end < len(body) else None,
        total_chars=len(body), text=body[start:end],
    )


def _chunks(text: str) -> list[str]:
    text = text or ""
    return [text[i:i + REPORT_TEXT_CHARS]
            for i in range(0, len(text), REPORT_TEXT_CHARS)] or [""]


def _text_units(part: str, text: str, **extra: Any) -> list[dict[str, Any]]:
    chunks = _chunks(text)
    units = []
    for i, chunk in enumerate(chunks):
        unit = {"part": part, **extra, "text": chunk}
        if len(chunks) > 1:
            unit.update(chunk=i + 1, chunks=len(chunks))
        units.append(unit)
    return units


def report_units(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The units of a typed report in page order: the execution, the final answer, the
    newest model texts, the diagnostics, then one unit for each evidence entry. A long
    text is several units, so each unit fits a page."""
    units: list[dict[str, Any]] = [{"part": "execution", **(report.get("execution") or {})}]
    final = report.get("final_answer")
    if isinstance(final, dict):
        units += _text_units("final_answer", str(final.get("text") or ""),
                             source=final.get("source"))
    for text in report.get("recent_text") or []:
        units += _text_units("recent_text", str(text.get("text") or ""),
                             source=text.get("source"))
    units.append({"part": "diagnostics", **(report.get("diagnostics") or {})})
    for name in REPORT_LISTS:
        units += [{"part": name, **entry} for entry in report.get(name) or []]
    return units


def report_digest(units: list[dict[str, Any]]) -> str:
    """The first 16 hex characters of the SHA-256 of the canonical units."""
    return hashlib.sha256(canonical_json(units).encode("utf-8")).hexdigest()[:16]


def report_page(node: str, units: list[dict[str, Any]], start: int, limit: int,
                digest: str | None = None) -> PlanReportPage:
    """The page of `units` from `start` that fits `limit` bytes, with at least one unit.
    `more` is `<digest>:<next unit>`.

    The page is built forward: each unit adds its canonical bytes and one comma to the
    bytes of an empty page with the longest cursor, so the page is serialized once."""
    digest = digest or report_digest(units)
    empty = PlanReportPage(success=True, node=node, items=[], total=len(units),
                           more=f"{digest}:{len(units)}")
    size = len(canonical_json(empty.model_dump()).encode("utf-8"))
    end = start
    while end < len(units):
        added = len(canonical_json(units[end]).encode("utf-8")) + (1 if end > start else 0)
        if end > start and size + added > limit:
            break
        size += added
        end += 1
    more = f"{digest}:{end}" if end < len(units) else None
    return PlanReportPage(success=True, node=node, items=units[start:end],
                          total=len(units), more=more)


def _page_limit(headers: dict[str, str]) -> int:
    lowered = {key.lower(): value for key, value in headers.items()}
    try:
        share = int(str(lowered.get(PAGE_SHARE_HEADER, "")).strip())
    except ValueError:
        return REPORT_PAGE_BYTES
    return min(share, REPORT_PAGE_BYTES) if share > 0 else REPORT_PAGE_BYTES


def _section_report(ctx: PlanContext, node_value: str) -> tuple[str, list[dict[str, Any]]]:
    """The node id and the report units of the newest sub-agent thread of a plan node, or
    `PlanRefused`. A thread with no typed report gives its text report as one legacy
    text, and a thread with neither is refused."""
    user, session = ctx.caller.username, ctx.caller.session_id
    snapshot = _snapshot(ctx, _read_version(ctx.plan_run))
    node = agent_plans.resolve_node(snapshot, node_value) if snapshot else None
    if node is None:
        raise PlanRefused("node_unknown", "no node of the plan has this id or number path. "
                          "Read the tree with read_plan.")
    threads = [row for row in agent_runs.read_plan_threads(user, session, ctx.plan_run.run_id)
               if row.plan_node_id == node]
    if not threads:
        raise PlanRefused("no_report", "no sub-agent ran for this node")
    first = threads[-1]
    report = agent_plans.read_report_data(user, session, ctx.plan_run.run_id, first.run_id)
    if report is not None:
        return node, report_units(report)
    wanted = agent_plans.document_id(first.run_id, "report")
    legacy = next((d for d in agent_plans.read_documents(user, session, ctx.plan_run.run_id)
                   if d.document_id == wanted), None)
    if legacy is None:
        raise PlanRefused("report_missing", "the sub-agent of this node has no report yet")
    try:
        body = agent_plans.document_body(user, session, legacy)
    except Exception as exc:  # noqa: BLE001 - a body or object store failure
        log.warning("the report %s was not read: %s", legacy.document_id, exc)
        raise PlanRefused("report_unreadable", "the report of this node cannot be read now. "
                          "Try again later.") from exc
    return node, _text_units("legacy_text", body)


@mcp.tool(
    name="read_plan_report",
    description=(
        "Read one page of the report of the sub-agent of a plan node: how its run ended, "
        "its final answer, its newest texts, and each document it read, cited or failed "
        "to read, with its notes. Give node_id as a node id or a number path such as 1. "
        "Give cursor from `more` to read the next page."
    ),
)
async def read_plan_report(node_id: str = "", cursor: str = "") -> PlanReportPage:
    # The whole read runs in a thread: the storage reads, the digest and the page build
    # of a long report would hold the event loop that every run of the server shares.
    return await asyncio.to_thread(_read_plan_report, _headers(), node_id, cursor)


def _read_plan_report(headers: dict[str, str], node_id: str, cursor: str) -> PlanReportPage:
    try:
        ctx = _context(headers)
        node, units = _section_report(ctx, node_id)
    except PlanRefused as exc:
        return PlanReportPage(success=False, code=exc.code, error=str(exc))
    digest = report_digest(units)
    start = 0
    if (cursor or "").strip():
        named, _, index = cursor.strip().partition(":")
        if named != digest:
            return PlanReportPage(success=False, code="report_changed",
                                  error="the report changed after this cursor. Read it again "
                                        "with no cursor.")
        try:
            start = int(index)
        except ValueError:
            start = -1
        if not 0 <= start < len(units):
            return PlanReportPage(success=False, code="invalid_cursor",
                                  error="the cursor names no unit of the report")
    return report_page(node, units, start, _page_limit(headers), digest)
