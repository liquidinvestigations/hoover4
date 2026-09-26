"""Plan storage: the plan tree, its versioned snapshots, the plan run state, the section
documents and the decision rows of a deep-research plan.

The tables are in migration `00031_agent_plans.sql`:

| table | writer | key |
|---|---|---|
| `agent_plan_snapshots` | the plan tools in `agent_todo_server` | `(plan_id, version)` |
| `agent_plan_runs` | `open_run` and `write_ending` of the planner and organizer runs, and the website for a cancel in `awaiting_review` | `run_id`, versioned by `state_version` |
| `agent_plan_documents` | the `AgentRun` activities | `(run_id, document_id)` |
| `agent_plan_decisions` | the website, `decide_plan` | `(run_id, decision_id)` |

`agent_plan_runs.run_id` is the plan run id, which every `agent_runs` row of the plan
carries as `plan_run_id`. A document's `run_id` is that plan run id too, so every document
of a plan is one prefix read. Its `document_id` is a `uuid5` of the agent run id and the
kind, so a retry writes the same row.

Every read uses `FINAL` and the full owner prefix `(username, session_id)`.

**The tree.** A plan is a versioned whole-tree snapshot. A node has an immutable UUID, a
parent, an ordinal and one line of text. The root node's id derives from the plan id, its
parent is null, and it cannot move or go. Every other node has a parent. A **section** is a
node with at least one leaf child, and its tasks are those leaves. A flat plan of top-level
leaves is one section, the root's.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
from typing import Any, Iterable

#: Fixed namespace constant. It never changes, because every root id and every document id
#: derives from it.
PLAN_NAMESPACE = uuid.UUID("7f1c2a44-0d3e-5b86-9c21-6a4e8d0b5f13")

#: The most nodes a plan holds, the root included (plan 16 decision on plan bounds).
MAX_NODES = 150
#: The most characters in the text of one node.
MAX_NODE_TEXT = 120
#: The most characters in a rejection comment.
MAX_COMMENT_CHARS = 10_000
#: The most corrections of one section.
MAX_CORRECTIONS = 2

#: Plan run states.
PLANNING = "planning"
REVISING = "revising"
AWAITING_REVIEW = "awaiting_review"
EXECUTING = "executing"
COMPLETED = "completed"
FAILED = "failed"
CANCELLED = "cancelled"
TERMINAL_STATES = (COMPLETED, FAILED, CANCELLED)
#: The states in which the plan tools accept a mutation.
MUTABLE_STATES = (PLANNING, REVISING)

#: The briefing purposes of an organizer's sub-agent.
PURPOSES = ("execute", "review", "correct")
#: The defect class of a review whose report has no valid verdict block.
NO_VERDICT = "no-verdict"


class PlanError(ValueError):
    """A plan operation was refused. The message is written for the model to act on."""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def root_node_id(plan_id: str) -> str:
    return str(uuid.uuid5(PLAN_NAMESPACE, f"plan-root:{plan_id}"))


def document_id(agent_run_id: str, kind: str) -> str:
    """The id of the document of one kind that one agent run writes."""
    return str(uuid.uuid5(PLAN_NAMESPACE, f"document:{agent_run_id}:{kind}"))


# ------------------------------------------------------------------------------ the tree


@dataclass(frozen=True)
class PlanNode:
    node_id: str
    parent_id: str | None
    ordinal: int
    text: str


@dataclass(frozen=True)
class PlanSnapshot:
    plan_id: str
    version: int
    nodes: tuple[PlanNode, ...]

    @property
    def checksum(self) -> str:
        return hashlib.sha256(nodes_json(self.nodes).encode()).hexdigest()

    @property
    def root_id(self) -> str:
        return root_node_id(self.plan_id)


def _ordered(nodes: Iterable[PlanNode]) -> list[PlanNode]:
    """The nodes in tree order: the root, then each subtree in ordinal order."""
    nodes = list(nodes)
    children: dict[str | None, list[PlanNode]] = {}
    for node in nodes:
        children.setdefault(node.parent_id, []).append(node)
    out: list[PlanNode] = []
    seen: set[str] = set()

    def walk(parent: str | None) -> None:
        for node in sorted(children.get(parent, []), key=lambda n: (n.ordinal, n.node_id)):
            if node.node_id in seen:
                continue
            seen.add(node.node_id)
            out.append(node)
            walk(node.node_id)

    walk(None)
    # A node that no walk reached is in a cycle. It is kept, so the validator sees it.
    out.extend(n for n in nodes if n.node_id not in seen)
    return out


def nodes_json(nodes: Iterable[PlanNode]) -> str:
    """The canonical JSON of a tree, in tree order. One text for one tree."""
    return json.dumps([asdict(n) for n in _ordered(nodes)], sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def nodes_from_json(text: str) -> tuple[PlanNode, ...]:
    return tuple(PlanNode(str(n["node_id"]), n.get("parent_id"), int(n["ordinal"]),
                          str(n["text"])) for n in json.loads(text or "[]"))


def validate(snapshot: PlanSnapshot) -> None:
    """Refuse a tree that breaks a rule. Raises `PlanError` with the rule it broke."""
    nodes = snapshot.nodes
    root_id = snapshot.root_id
    if len(nodes) > MAX_NODES:
        raise PlanError(
            f"the plan has {len(nodes)} nodes and the limit is {MAX_NODES}, the root "
            "included. Merge or remove nodes."
        )
    ids = [n.node_id for n in nodes]
    if len(set(ids)) != len(ids):
        raise PlanError("two nodes have the same id")
    by_id = {n.node_id: n for n in nodes}
    roots = [n for n in nodes if n.parent_id is None]
    if len(roots) != 1 or roots[0].node_id != root_id:
        raise PlanError("the plan must have exactly one root node, with the root id")
    siblings: set[tuple[str | None, int]] = set()
    for node in nodes:
        text = node.text
        if not text.strip():
            raise PlanError("a node text is empty")
        if "\n" in text or "\r" in text:
            raise PlanError("a node text must be one line")
        if len(text) > MAX_NODE_TEXT:
            raise PlanError(
                f"a node text has {len(text)} characters and the limit is {MAX_NODE_TEXT}"
            )
        if node.ordinal < 1:
            raise PlanError("a node ordinal starts at 1")
        if node.parent_id is not None and node.parent_id not in by_id:
            raise PlanError(f"node {node.node_id} names an unknown parent")
        key = (node.parent_id, node.ordinal)
        if key in siblings:
            raise PlanError("two sibling nodes have the same ordinal")
        siblings.add(key)
    for node in nodes:
        seen = set()
        current = node
        while current.parent_id is not None:
            if current.node_id in seen:
                raise PlanError("the plan tree has a cycle")
            seen.add(current.node_id)
            current = by_id[current.parent_id]


def children_of(snapshot: PlanSnapshot, parent_id: str) -> list[PlanNode]:
    return sorted((n for n in snapshot.nodes if n.parent_id == parent_id),
                  key=lambda n: n.ordinal)


def sections(snapshot: PlanSnapshot) -> list[tuple[PlanNode, list[PlanNode]]]:
    """Each section in tree order, with its tasks: a node with at least one leaf child.

    The root counts. The Rust copy is `has_section` in `website/common/src/plan_types.rs`.
    The two copies are one rule and change in one patch.
    """
    parents = {n.parent_id for n in snapshot.nodes if n.parent_id is not None}
    out = []
    for node in _ordered(snapshot.nodes):
        leaves = [c for c in children_of(snapshot, node.node_id) if c.node_id not in parents]
        if leaves:
            out.append((node, leaves))
    return out


def section_ids(snapshot: PlanSnapshot) -> set[str]:
    return {node.node_id for node, _ in sections(snapshot)}


def render_tree(snapshot: PlanSnapshot) -> str:
    """The tree as indented lines, one node a line, with each node id."""
    depth = {snapshot.root_id: 0}
    lines = []
    for node in _ordered(snapshot.nodes):
        level = 0 if node.parent_id is None else depth.get(node.parent_id, 0) + 1
        depth[node.node_id] = level
        lines.append(f"{'  ' * level}{node.ordinal}. {node.text} [{node.node_id}]")
    return "\n".join(lines)


def _clean_text(text: Any) -> str:
    return str(text if text is not None else "").strip()


def _renumber(nodes: list[PlanNode], parent_id: str | None,
              order: list[str] | None = None) -> list[PlanNode]:
    """Give the children of `parent_id` ordinals from one, in `order` or their current one."""
    kids = sorted((n for n in nodes if n.parent_id == parent_id), key=lambda n: n.ordinal)
    ids = order if order is not None else [n.node_id for n in kids]
    position = {node_id: i + 1 for i, node_id in enumerate(ids)}
    return [replace(n, ordinal=position[n.node_id]) if n.parent_id == parent_id else n
            for n in nodes]


def _new_node_id(plan_id: str, version: int) -> str:
    """The id of the node that the mutation writing `version` adds. One mutation adds at
    most one node, so the id is unique and a retry computes the same id."""
    return str(uuid.uuid5(PLAN_NAMESPACE, f"node:{plan_id}:{version}"))


def _find(snapshot: PlanSnapshot, node_id: Any) -> PlanNode:
    wanted = _clean_text(node_id)
    for node in snapshot.nodes:
        if node.node_id == wanted:
            return node
    raise PlanError(f"no node has the id {wanted!r}. Call read_plan to see the ids.")


def _subtree(snapshot: PlanSnapshot, node_id: str) -> set[str]:
    out = {node_id}
    changed = True
    while changed:
        changed = False
        for n in snapshot.nodes:
            if n.parent_id in out and n.node_id not in out:
                out.add(n.node_id)
                changed = True
    return out


def initial_snapshot(plan_id: str, query: str) -> PlanSnapshot:
    """Version 1: the root node alone, with the first line of the query as its text."""
    first = " ".join(_clean_text(query).split()) or "Research plan"
    return PlanSnapshot(plan_id, 1, (PlanNode(root_node_id(plan_id), None, 1,
                                              first[:MAX_NODE_TEXT]),))


def apply(snapshot: PlanSnapshot, operation: str, **args: Any) -> PlanSnapshot:
    """Apply one mutation to `snapshot` and return the validated next version.

    | operation | arguments | rule |
    |---|---|---|
    | `append_node` | `text` | a new child of the root, last |
    | `append_child` | `parent_id`, `text` | a new child of the parent, last |
    | `move_node` | `node_id`, `new_parent_id`, `position` | refuses the root and a move under its own subtree |
    | `edit_node` | `node_id`, `text` | accepts the root |
    | `remove_node` | `node_id` | removes the subtree, refuses the root |
    """
    version = snapshot.version + 1
    nodes = list(snapshot.nodes)
    root_id = snapshot.root_id
    if operation in ("append_node", "append_child"):
        parent = root_id if operation == "append_node" else _find(snapshot, args.get("parent_id")).node_id
        siblings = children_of(snapshot, parent)
        nodes.append(PlanNode(_new_node_id(snapshot.plan_id, version), parent,
                              len(siblings) + 1, _clean_text(args.get("text"))))
    elif operation == "edit_node":
        node = _find(snapshot, args.get("node_id"))
        nodes = [replace(n, text=_clean_text(args.get("text"))) if n.node_id == node.node_id
                 else n for n in nodes]
    elif operation == "remove_node":
        node = _find(snapshot, args.get("node_id"))
        if node.node_id == root_id:
            raise PlanError("the root node cannot be removed. Edit its text instead.")
        gone = _subtree(snapshot, node.node_id)
        nodes = _renumber([n for n in nodes if n.node_id not in gone], node.parent_id)
    elif operation == "move_node":
        node = _find(snapshot, args.get("node_id"))
        if node.node_id == root_id:
            raise PlanError("the root node cannot be moved")
        target = _find(snapshot, args.get("new_parent_id") or root_id).node_id
        if target in _subtree(snapshot, node.node_id):
            raise PlanError("a node cannot move under itself or its own subtree")
        try:
            position = int(args.get("position") or 0)
        except (TypeError, ValueError):
            raise PlanError("position must be a whole number from 1") from None
        old_parent = node.parent_id
        nodes = _renumber([n for n in nodes if n.node_id != node.node_id], old_parent)
        order = [n.node_id for n in sorted((n for n in nodes if n.parent_id == target),
                                           key=lambda n: n.ordinal)]
        position = max(1, min(position or len(order) + 1, len(order) + 1))
        order.insert(position - 1, node.node_id)
        nodes.append(replace(node, parent_id=target, ordinal=0))
        nodes = _renumber(nodes, target, order)
    else:
        raise PlanError(f"unknown plan operation {operation!r}")
    new = PlanSnapshot(snapshot.plan_id, version, tuple(nodes))
    validate(new)
    return new


# -------------------------------------------------------------------------- storage


def _client():
    from database.clickhouse import get_global_client

    return get_global_client()


def _insert(table: str, rows: list[list[Any]], columns: list[str]) -> None:
    from database.clickhouse import insert_durable

    with _client() as client:
        insert_durable(client, table, rows, column_names=columns)


SNAPSHOT_COLUMNS = ["plan_id", "username", "session_id", "version", "nodes_json", "checksum",
                    "idempotency_key", "created_at"]


def read_snapshot(username: str, session_id: str, plan_id: str,
                  version: int | None = None) -> PlanSnapshot | None:
    """The newest snapshot, or the snapshot at `version`. None when there is none."""
    where = " AND version = {v:UInt64}" if version else ""
    with _client() as client:
        rows = client.query(
            "SELECT version, nodes_json FROM agent_plan_snapshots FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND plan_id = {p:UUID}"
            + where + " ORDER BY version DESC LIMIT 1",
            parameters={"u": username, "s": session_id, "p": plan_id, "v": int(version or 0)},
        ).result_rows
    if not rows:
        return None
    return PlanSnapshot(plan_id, int(rows[0][0]), nodes_from_json(rows[0][1]))


def snapshot_by_key(username: str, session_id: str, plan_id: str,
                    idempotency_key: uuid.UUID) -> PlanSnapshot | None:
    """The newest snapshot that a mutation with `idempotency_key` wrote, or None."""
    with _client() as client:
        rows = client.query(
            "SELECT version, nodes_json FROM agent_plan_snapshots FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND plan_id = {p:UUID} "
            "AND idempotency_key = {k:UUID} ORDER BY version DESC LIMIT 1",
            parameters={"u": username, "s": session_id, "p": plan_id, "k": str(idempotency_key)},
        ).result_rows
    if not rows:
        return None
    return PlanSnapshot(plan_id, int(rows[0][0]), nodes_from_json(rows[0][1]))


def write_snapshot(username: str, session_id: str, snapshot: PlanSnapshot,
                   idempotency_key: uuid.UUID | None = None) -> None:
    """Write one version with a synchronous insert.

    `idempotency_key` is the key of the mutation that made this version, which
    [`snapshot_by_key`] finds on a retry. With no key, the key is derived from the
    version, so a retry of the same write replaces the row with equal content."""
    key = idempotency_key or uuid.uuid5(PLAN_NAMESPACE, f"snapshot:{snapshot.plan_id}:{snapshot.version}")
    _insert("agent_plan_snapshots", [[
        uuid.UUID(snapshot.plan_id), username, session_id, snapshot.version,
        nodes_json(snapshot.nodes), snapshot.checksum, key, _now(),
    ]], SNAPSHOT_COLUMNS)


def create_plan(username: str, session_id: str, plan_id: str, query: str) -> PlanSnapshot:
    """Write version 1 with the root node, once. A second call returns the stored tree."""
    existing = read_snapshot(username, session_id, plan_id)
    if existing is not None:
        return existing
    snapshot = initial_snapshot(plan_id, query)
    write_snapshot(username, session_id, snapshot)
    return snapshot


def mutate(username: str, session_id: str, plan_id: str, operation: str, *,
           idempotency_key: uuid.UUID | None = None, **args: Any) -> PlanSnapshot:
    """Read the newest version, apply one operation, and write version plus one.

    The caller holds the plan run's lock, so the next holder reads the version this wrote.
    `idempotency_key` goes into the snapshot row, see [`write_snapshot`].
    """
    current = read_snapshot(username, session_id, plan_id)
    if current is None:
        raise PlanError("this plan has no tree yet")
    new = apply(current, operation, **args)
    write_snapshot(username, session_id, new, idempotency_key)
    return new


# ----------------------------------------------------------------------- plan runs


@dataclass
class PlanRunRow:
    """One `agent_plan_runs` row, with the column names of the migration."""

    run_id: str
    plan_id: str
    username: str
    session_id: str
    start_seq: int = 0
    state: str = PLANNING
    reviewed_version: int = 0
    approved_version: int = 0
    review_round: int = 0
    sections_json: str = "[]"
    state_version: int = 1
    updated_at: datetime | None = None


PLAN_RUN_COLUMNS = [f.name for f in fields(PlanRunRow)]


def is_terminal(row: PlanRunRow) -> bool:
    return row.state in TERMINAL_STATES


def read_plan_run(username: str, session_id: str, plan_run_id: str) -> PlanRunRow | None:
    with _client() as client:
        rows = client.query(
            f"SELECT {', '.join(PLAN_RUN_COLUMNS)} FROM agent_plan_runs FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND run_id = {r:UUID}",
            parameters={"u": username, "s": session_id, "r": plan_run_id},
        ).result_rows
    if not rows:
        return None
    data = dict(zip(PLAN_RUN_COLUMNS, rows[0]))
    data["run_id"], data["plan_id"] = str(data["run_id"]), str(data["plan_id"])
    for name in ("start_seq", "reviewed_version", "approved_version", "review_round",
                 "state_version"):
        data[name] = int(data[name] or 0)
    return PlanRunRow(**data)


def _write_plan_run_row(row: PlanRunRow) -> None:
    values = asdict(replace(row, updated_at=_now()))
    values["run_id"], values["plan_id"] = uuid.UUID(row.run_id), uuid.UUID(row.plan_id)
    _insert("agent_plan_runs", [[values[c] for c in PLAN_RUN_COLUMNS]], PLAN_RUN_COLUMNS)


def create_plan_run(row: PlanRunRow) -> PlanRunRow:
    """Write a new plan run row at `state_version` 1, or return the stored one."""
    existing = read_plan_run(row.username, row.session_id, row.run_id)
    if existing is not None:
        return existing
    row = replace(row, state_version=1)
    _write_plan_run_row(row)
    return row


def write_plan_run(username: str, session_id: str, plan_run_id: str,
                   **changes: Any) -> PlanRunRow | None:
    """Write `changes` at the read `state_version` plus one.

    Returns None and writes nothing when the row does not exist or is terminal. A write
    whose changes the row already holds writes nothing, so the second of two equal cancel
    writes changes nothing.
    """
    current = read_plan_run(username, session_id, plan_run_id)
    if current is None or is_terminal(current):
        return None
    unknown = set(changes) - set(PLAN_RUN_COLUMNS)
    if unknown:
        raise ValueError(f"unknown plan run columns: {sorted(unknown)}")
    if all(getattr(current, k) == v for k, v in changes.items()):
        return current
    new = replace(current, **changes, state_version=current.state_version + 1)
    _write_plan_run_row(new)
    return new


# ----------------------------------------------------------------------- documents

DOCUMENT_COLUMNS = ["document_id", "run_id", "node_id", "username", "session_id", "role",
                    "kind", "attempt", "body_inline", "artifact_id", "body_bytes",
                    "body_sha256", "created_at"]


@dataclass
class PlanDocument:
    document_id: str
    node_id: str
    role: str
    kind: str
    attempt: int
    body: str
    created_at: datetime | None = None


def write_document(username: str, session_id: str, plan_run_id: str, agent_run_id: str,
                   node_id: str, role: str, kind: str, body: str, attempt: int = 0) -> str:
    """Write one document of a plan run. Returns its id. A retry writes the same row."""
    doc_id = document_id(agent_run_id, kind)
    data = body.encode()
    _insert("agent_plan_documents", [[
        uuid.UUID(doc_id), uuid.UUID(plan_run_id), uuid.UUID(node_id), username, session_id,
        role, kind, int(attempt), body, "", len(data), hashlib.sha256(data).hexdigest(),
        _now(),
    ]], DOCUMENT_COLUMNS)
    return doc_id


def read_documents(username: str, session_id: str, plan_run_id: str) -> list[PlanDocument]:
    """Every document of a plan run, oldest first."""
    with _client() as client:
        rows = client.query(
            "SELECT toString(document_id), toString(node_id), role, kind, attempt, "
            "body_inline, created_at FROM agent_plan_documents FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND run_id = {r:UUID} "
            "ORDER BY created_at, document_id",
            parameters={"u": username, "s": session_id, "r": plan_run_id},
        ).result_rows
    return [PlanDocument(d, n, role, kind, int(a), body, at)
            for d, n, role, kind, a, body, at in rows]


# ----------------------------------------------------------------------- decisions


@dataclass
class PlanDecision:
    decision_id: str
    action: str
    reviewed_version: int
    comment: str


def read_decision(username: str, session_id: str, plan_run_id: str,
                  decision_id: str) -> PlanDecision | None:
    with _client() as client:
        rows = client.query(
            "SELECT action, reviewed_version, comment FROM agent_plan_decisions FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND run_id = {r:UUID} "
            "AND decision_id = {d:UUID}",
            parameters={"u": username, "s": session_id, "r": plan_run_id, "d": decision_id},
        ).result_rows
    if not rows:
        return None
    action, version, comment = rows[0]
    return PlanDecision(decision_id, str(action), int(version), str(comment))


# ------------------------------------------------------------------------ sections

_VERDICT_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_verdict(report: str) -> tuple[str, list[str]]:
    """The verdict of a review report: its last fenced JSON block.

    Returns `("accept" | "reject", defect_classes)`. A report with no valid block counts as
    a reject with the defect class `no-verdict`.
    """
    for block in reversed(_VERDICT_BLOCK.findall(report or "")):
        try:
            value = json.loads(block)
        except ValueError:
            continue
        verdict = value.get("verdict") if isinstance(value, dict) else None
        if verdict in ("accept", "reject"):
            classes = value.get("defect_classes") or []
            if not isinstance(classes, list):
                classes = [str(classes)]
            return verdict, [str(c) for c in classes]
    return "reject", [NO_VERDICT]


@dataclass
class SectionRun:
    """The first run of one sub-agent thread of a plan section, as `section_states` reads it.

    `state` is the state of the thread's newest run.
    """

    node_id: str
    purpose: str
    state: str
    started_at: datetime


def section_states(snapshot: PlanSnapshot, runs: list[SectionRun],
                   documents: list[PlanDocument]) -> list[dict[str, Any]]:
    """The `sections_json` entries of an approved tree.

    For each section: the state of its newest sub-agent run, the count of corrections, the
    verdict of its newest review (empty before the first review), the open defect classes of
    that review, and whether it failed. A section is failed
    when it has no `review` document with verdict `accept` newer than its newest `execute`
    or `correct` run.
    """
    out = []
    for node, tasks in sections(snapshot):
        mine = sorted((r for r in runs if r.node_id == node.node_id),
                      key=lambda r: r.started_at)
        work = [r for r in mine if r.purpose in ("execute", "correct")]
        last_work = work[-1].started_at if work else None
        reviews = [d for d in documents if d.node_id == node.node_id and d.kind == "review"]
        reviews.sort(key=lambda d: d.created_at or datetime.min)
        accepted = any(
            parse_verdict(d.body)[0] == "accept"
            and (last_work is None or (d.created_at and d.created_at >= last_work))
            for d in reviews
        ) and bool(work)
        classes = parse_verdict(reviews[-1].body)[1] if reviews else []
        out.append({
            "node_id": node.node_id,
            "title": node.text,
            "tasks": len(tasks),
            "state": mine[-1].state if mine else "",
            "corrections": sum(1 for r in mine if r.purpose == "correct"),
            "review": parse_verdict(reviews[-1].body)[0] if reviews else "",
            "defect_classes": [] if accepted else classes,
            "failed": not accepted,
        })
    return out


def failed_sections_table(entries: list[dict[str, Any]]) -> str:
    """The generated `Failed sections` table, or empty when no section failed."""
    failed = [e for e in entries if e.get("failed")]
    if not failed:
        return ""
    lines = ["## Failed sections", "", "| section | open defect classes |", "|---|---|"]
    for entry in failed:
        title = str(entry.get("title") or "").replace("|", "/")
        classes = ", ".join(entry.get("defect_classes") or []) or "no accepted review"
        lines.append(f"| {title} | {classes} |")
    return "\n".join(lines)


__all__ = [
    "AWAITING_REVIEW", "CANCELLED", "COMPLETED", "EXECUTING", "FAILED", "MAX_COMMENT_CHARS",
    "MAX_CORRECTIONS", "MAX_NODES", "MAX_NODE_TEXT", "MUTABLE_STATES", "NO_VERDICT",
    "PLANNING", "PLAN_NAMESPACE", "PURPOSES", "PlanDecision", "PlanDocument", "PlanError",
    "PlanNode", "PlanRunRow", "PlanSnapshot", "REVISING", "SectionRun", "TERMINAL_STATES",
    "apply", "children_of", "create_plan", "create_plan_run", "document_id",
    "failed_sections_table", "initial_snapshot", "is_terminal", "mutate", "nodes_json",
    "parse_verdict", "read_decision", "read_documents", "read_plan_run", "read_snapshot",
    "render_tree", "root_node_id", "section_ids", "section_states", "sections", "validate",
    "write_document", "write_plan_run", "write_snapshot",
]
