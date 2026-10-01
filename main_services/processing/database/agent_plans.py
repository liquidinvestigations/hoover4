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
of a plan is one prefix read. Its `document_id` is a `uuid5` of an id and the kind, so a
retry writes the same row. The kinds are `prompt`, `report` (text) and `report_data` (the
typed report of `tasks/P_agent/reports.py`) of a sub-agent thread, keyed by the thread's
first run, `final` of the organizer, and `execution_settings` of the plan run, keyed by the
plan run id. A body above `INLINE_BODY_BYTES` is a required artifact whose id is the
document id, and the row keeps its id, size and digest (`document_body` reads it).

Every read uses `FINAL` and the full owner prefix `(username, session_id)`.

**The tree.** A plan is a versioned whole-tree snapshot. A node has an immutable UUID, a
parent, an ordinal and one line of text. The root node's id derives from the plan id, its
parent is null, and it cannot move or go. Every other node has a parent. `replace_tree`
writes a whole new tree from nested input at the exact current version.

**Sections.** A **section** is a direct child of the root, and its assignment is its whole
subtree. A child of the root with no children is a section of one task. The
`execution_settings` document holds `plan_contract` `PLAN_CONTRACT`, which marks a plan of
this rule. A plan run with no such document is older: its section was a node with leaf
children, and its stored `sections_json` keeps that meaning.
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
#: The most sections of a plan: direct children of the root. `replace_tree` refuses a tree
#: with more. Mirrors `MAX_PLAN_SECTIONS` in `website/common/src/plan_types.rs`. The skill
#: `method_planner` of the research agent states the same number.
MAX_SECTIONS = 4

#: The plan contract of a plan whose sections are the direct children of the root. The
#: `execution_settings` document of the plan run holds it. A plan run with no such document
#: is older, and its section was a node with leaf children.
PLAN_CONTRACT = 2

#: The document kind of the frozen execution settings of a plan run.
EXECUTION_SETTINGS_KIND = "execution_settings"

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

#: The purpose of the sub-agent that the controller starts for a section. Older plan runs
#: also hold `correct` and `review` rows.
EXECUTE = "execute"
#: The defect class of a review whose report has no valid verdict block. Plan runs from
#: before the review purpose went can hold such reports.
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
                f"a node text has {len(text)} characters and the limit is {MAX_NODE_TEXT}, "
                "so the change was not made. Send it again with a shorter text."
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
    """Each section in tree order, with its tasks. A section is a direct child of the root.
    Its tasks are the leaves of its subtree, or the section itself when it has no child.

    The Rust copy is `section_count` in `website/common/src/plan_types.rs`. The two copies
    are one rule and change in one patch.
    """
    parents = {n.parent_id for n in snapshot.nodes if n.parent_id is not None}
    ordered = _ordered(snapshot.nodes)
    out = []
    for node in children_of(snapshot, snapshot.root_id):
        below = _subtree(snapshot, node.node_id) - {node.node_id}
        leaves = [n for n in ordered if n.node_id in below and n.node_id not in parents]
        out.append((node, leaves or [node]))
    return out


def section_ids(snapshot: PlanSnapshot) -> set[str]:
    return {node.node_id for node, _ in sections(snapshot)}


#: The number path of the root in `render_tree` and in a node argument.
ROOT_PATH = "root"


def node_paths(snapshot: PlanSnapshot) -> dict[str, str]:
    """The number path of each node id, in tree order. The root is `ROOT_PATH`, a child
    of the root is its ordinal (`2`), and a deeper node adds its ordinal (`2.1`)."""
    paths: dict[str, str] = {}
    for node in _ordered(snapshot.nodes):
        if node.parent_id is None:
            paths[node.node_id] = ROOT_PATH
            continue
        parent = paths.get(node.parent_id, ROOT_PATH)
        paths[node.node_id] = str(node.ordinal) if parent == ROOT_PATH else f"{parent}.{node.ordinal}"
    return paths


def render_tree(snapshot: PlanSnapshot, node_id: str | None = None) -> str:
    """The tree as indented lines, with one number path per node. With `node_id`, only
    the subtree of that node."""
    paths = node_paths(snapshot)
    keep = _subtree(snapshot, node_id) if node_id else None
    lines = []
    for node in _ordered(snapshot.nodes):
        if keep is not None and node.node_id not in keep:
            continue
        path = paths[node.node_id]
        level = 0 if path == ROOT_PATH else path.count(".") + 1
        lines.append(f"{'  ' * level}{path}. {node.text}")
    return "\n".join(lines)


def _clean_text(text: Any) -> str:
    return str(text if text is not None else "").strip()


def resolve_node(snapshot: PlanSnapshot, value: Any) -> str | None:
    """The node id named by an id or an outline number, if it exists."""
    wanted = _clean_text(value).rstrip(".")
    if not wanted or wanted.lower() == ROOT_PATH:
        return snapshot.root_id
    paths = node_paths(snapshot)
    for node in snapshot.nodes:
        if node.node_id == wanted or paths[node.node_id] == wanted:
            return node.node_id
    return None


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


class StaleVersion(PlanError):
    """A tree write named a version that is not the current one. `current` is the tree
    as it stands, which the caller returns in place of a write."""

    def __init__(self, current: PlanSnapshot, named: Any):
        super().__init__(
            f"The plan is at version {current.version}, and this call names version "
            f"{named}. Read the tree below and send the whole tree again with version "
            f"{current.version}.")
        self.current = current


def _new_node_id(plan_id: str, key: str, path: str) -> str:
    """The id of a new node at number path `path` of the tree that the write with `key`
    submits. A retry of the same write computes the same ids."""
    return str(uuid.uuid5(PLAN_NAMESPACE, f"node:{plan_id}:{key}:{path}"))


def build_tree(current: PlanSnapshot, children: Any, key: str) -> PlanSnapshot:
    """The validated next version of `current` from nested input. Raises `PlanError`.

    `children` is the list of the root's children. Each child is a mapping with `text`, an
    optional `node_id` and optional `children` of the same shape. The parent and the
    ordinal of each node come from its place in the input. A `node_id` keeps the identity
    of a node of `current`, and it may be a number path of `current`. A node with no
    `node_id` gets a new id from `key` and its place. The root keeps its id and its text.
    """
    if children is None:
        children = []
    if not isinstance(children, list):
        raise PlanError("children must be a list of nodes, each with text and children")
    root = next(n for n in current.nodes if n.parent_id is None)
    nodes: list[PlanNode] = [root]
    used: set[str] = {root.node_id}

    def walk(items: list, parent_id: str, prefix: str) -> None:
        for ordinal, item in enumerate(items, start=1):
            if len(nodes) >= MAX_NODES:
                raise PlanError(
                    f"the plan has more than {MAX_NODES} nodes, the root included. Merge "
                    "or remove nodes.")
            if not isinstance(item, dict):
                raise PlanError("each node must be an object with text and children")
            path = f"{prefix}{ordinal}"
            named = _clean_text(item.get("node_id"))
            if named:
                node_id = resolve_node(current, named)
                if node_id is None or node_id == root.node_id:
                    raise PlanError(
                        f"node_id {named!r} names no node of version {current.version} "
                        "other than the root. Leave node_id out for a new node.")
            else:
                node_id = _new_node_id(current.plan_id, key, path)
            if node_id in used:
                raise PlanError(f"node_id {named or node_id!r} appears twice in the tree")
            used.add(node_id)
            nodes.append(PlanNode(node_id, parent_id, ordinal, _clean_text(item.get("text"))))
            kids = item.get("children") or []
            if not isinstance(kids, list):
                raise PlanError("children must be a list of nodes")
            walk(kids, node_id, f"{path}.")

    walk(children, root.node_id, "")
    new = PlanSnapshot(current.plan_id, current.version + 1, tuple(nodes))
    validate(new)
    count = len(children_of(new, new.root_id))
    if count > MAX_SECTIONS:
        raise PlanError(f"The tree has {count} top-level nodes, and a plan has at most "
                        f"{MAX_SECTIONS}. Each top-level node is a section that one "
                        "researcher runs. Merge sections, or put tasks under a section.")
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


def replace_tree(username: str, session_id: str, plan_id: str, children: Any, *,
                 version: int, idempotency_key: uuid.UUID | None = None) -> PlanSnapshot:
    """Write the whole tree `children` as the version after `version`.

    A write whose `idempotency_key` already wrote a version returns that version first,
    whatever the current version is. Otherwise `version` must equal the current version,
    or `StaleVersion` carries the current tree and nothing is written. The caller holds the
    plan run's lock, so the next holder reads the version this wrote.
    """
    if idempotency_key is not None:
        stored = snapshot_by_key(username, session_id, plan_id, idempotency_key)
        if stored is not None:
            return stored
    current = read_snapshot(username, session_id, plan_id)
    if current is None:
        raise PlanError("this plan has no tree yet")
    if version != current.version:
        raise StaleVersion(current, version)
    key = str(idempotency_key) if idempotency_key is not None else f"v{current.version + 1}"
    new = build_tree(current, children, key)
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
    #: The inline body. Empty when the body is in the artifact `artifact_id`.
    body: str
    created_at: datetime | None = None
    artifact_id: str = ""
    body_bytes: int = 0
    body_sha256: str = ""


#: The largest body in bytes that a document row holds inline. A larger body is a required
#: artifact of kind `agent_plan_document`, and the row keeps its id, size and digest.
INLINE_BODY_BYTES = 262_144

#: The `chat_artifacts` kind of a document body. Mirrors
#: `agent_common.artifacts.KIND_AGENT_PLAN_DOCUMENT`, which the worker cannot import.
ARTIFACT_KIND = "agent_plan_document"

#: The object prefix of every chat artifact. Mirrors `agent_common.s3_store.DERIVED_PREFIX`.
ARTIFACT_PREFIX = "derived/chat-artifacts"


class DocumentBodyError(RuntimeError):
    """A document body in an artifact was not written, or was not read with its digest."""


def _safe_component(component: str) -> str:
    """Mirrors `agent_common.s3_store._safe`: a path part that cannot leave the prefix."""
    cleaned = "".join(c for c in (component or "") if c.isalnum() or c in "-_.")
    return (cleaned.lstrip(".") or "unknown")[:128]


def artifact_key(session_id: str, artifact_id: str) -> str:
    """The object key of a document body. Mirrors `agent_common.s3_store.artifact_key`
    with the file name `detail.json`, which `write_required` uses."""
    return (f"{ARTIFACT_PREFIX}/{_safe_component(session_id)}/"
            f"{_safe_component(artifact_id)}/detail.json")


def _artifact_digest(username: str, session_id: str, artifact_id: str) -> str | None:
    with _client() as client:
        rows = client.query(
            "SELECT body_sha256 FROM chat_artifacts FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} AND artifact_id = {a:String} AND is_deleted = 0 "
            "AND status = 'ok'",
            parameters={"u": username, "s": session_id, "a": artifact_id},
        ).result_rows
    return str(rows[0][0]) if rows else None


def _write_body_artifact(username: str, session_id: str, artifact_id: str,
                         data: bytes) -> None:
    """Store a document body as a required artifact, by the contract of
    `agent_common.artifacts.write_required`: the object first, then the row, then a read of
    the row that confirms the digest. The id and every column come from the document, so a
    retry writes the same object and row. Any failure raises `DocumentBodyError`."""
    import io

    from database import s3

    digest = hashlib.sha256(data).hexdigest()
    key = artifact_key(session_id, artifact_id)
    try:
        client = s3.get_s3_client()
        if not client.bucket_exists(s3.SYSTEM_BUCKET):
            client.make_bucket(s3.SYSTEM_BUCKET)
        client.put_object(s3.SYSTEM_BUCKET, key, io.BytesIO(data), length=len(data),
                          content_type="application/json")
        _insert("chat_artifacts", [[
            artifact_id, session_id, username, ARTIFACT_KIND, "plan_document", key,
            len(data), "ok", digest, artifact_id,
        ]], ["artifact_id", "session_id", "username", "kind", "tool_name", "body_key",
             "body_bytes", "status", "body_sha256", "idempotency_key"])
        stored = _artifact_digest(username, session_id, artifact_id)
    except Exception as exc:  # noqa: BLE001 - one failure class for the caller
        raise DocumentBodyError(f"the body of document {artifact_id} was not stored: "
                                f"{exc}") from exc
    if stored != digest:
        raise DocumentBodyError(f"the body of document {artifact_id} read back with digest "
                                f"{stored!r}, not {digest}")


def write_document(username: str, session_id: str, plan_run_id: str, agent_run_id: str,
                   node_id: str, role: str, kind: str, body: str, attempt: int = 0) -> str:
    """Write one document of a plan run. Returns its id. A retry writes the same row.

    A body above `INLINE_BODY_BYTES` is stored first as a required artifact whose id is the
    document id. The row then holds the artifact id, the size and the digest, and no body.
    """
    doc_id = document_id(agent_run_id, kind)
    data = body.encode()
    inline, artifact = body, ""
    if len(data) > INLINE_BODY_BYTES:
        _write_body_artifact(username, session_id, doc_id, data)
        inline, artifact = "", doc_id
    _insert("agent_plan_documents", [[
        uuid.UUID(doc_id), uuid.UUID(plan_run_id), uuid.UUID(node_id), username, session_id,
        role, kind, int(attempt), inline, artifact, len(data),
        hashlib.sha256(data).hexdigest(), _now(),
    ]], DOCUMENT_COLUMNS)
    return doc_id


def read_documents(username: str, session_id: str, plan_run_id: str) -> list[PlanDocument]:
    """Every document of a plan run, oldest first. A body in an artifact is not read:
    `document_body` reads it."""
    with _client() as client:
        rows = client.query(
            "SELECT toString(document_id), toString(node_id), role, kind, attempt, "
            "body_inline, created_at, artifact_id, body_bytes, body_sha256 "
            "FROM agent_plan_documents FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND run_id = {r:UUID} "
            "ORDER BY created_at, document_id",
            parameters={"u": username, "s": session_id, "r": plan_run_id},
        ).result_rows
    return [PlanDocument(d, n, role, kind, int(a), body, at, str(art or ""), int(size or 0),
                         str(sha or ""))
            for d, n, role, kind, a, body, at, art, size, sha in rows]


def document_body(username: str, session_id: str, document: PlanDocument) -> str:
    """The whole body of a document of the owner. A body in an artifact is read from the
    owner's artifact row and checked against the digest of the document row."""
    if not document.artifact_id:
        return document.body
    from database import s3

    with _client() as client:
        rows = client.query(
            "SELECT body_key FROM chat_artifacts FINAL WHERE username = {u:String} "
            "AND session_id = {s:String} AND artifact_id = {a:String} AND is_deleted = 0 "
            "AND status = 'ok'",
            parameters={"u": username, "s": session_id, "a": document.artifact_id},
        ).result_rows
    if not rows:
        raise DocumentBodyError(f"the body of document {document.document_id} has no "
                                "artifact row of this owner")
    response = s3.get_s3_client().get_object(s3.SYSTEM_BUCKET, str(rows[0][0]))
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    if document.body_sha256 and hashlib.sha256(data).hexdigest() != document.body_sha256:
        raise DocumentBodyError(f"the body of document {document.document_id} does not "
                                "match its digest")
    return data.decode("utf-8")


def read_report_data(username: str, session_id: str, plan_run_id: str,
                     first_run_id: str) -> dict | None:
    """The typed report of a plan sub-agent thread from its `report_data` document, or
    None when the thread has none, or when its body cannot be read or parsed. A report
    from before the typed document has only the `report` text, which `read_documents`
    returns."""
    import logging

    wanted = document_id(first_run_id, "report_data")
    doc = next((d for d in read_documents(username, session_id, plan_run_id)
                if d.document_id == wanted and d.kind == "report_data"), None)
    if doc is None:
        return None
    try:
        value = json.loads(document_body(username, session_id, doc))
    except Exception as exc:  # noqa: BLE001 - a body, object store or parse failure
        logging.getLogger(__name__).warning(
            "the typed report %s was not read: %s", doc.document_id, exc)
        return None
    return value if isinstance(value, dict) else None


def execution_settings_id(plan_run_id: str) -> str:
    """The id of the `execution_settings` document of a plan run."""
    return document_id(plan_run_id, EXECUTION_SETTINGS_KIND)


def write_execution_settings(username: str, session_id: str, plan_run_id: str,
                             root_id: str, settings: dict[str, Any]) -> None:
    """Write the frozen execution settings of a plan run. A retry writes the same row."""
    body = json.dumps(settings, sort_keys=True, ensure_ascii=False)
    write_document(username, session_id, plan_run_id, plan_run_id, root_id, "controller",
                   EXECUTION_SETTINGS_KIND, body)


def read_execution_settings(username: str, session_id: str,
                            plan_run_id: str) -> dict[str, Any] | None:
    """The frozen execution settings of a plan run, or None for a plan run from before
    them: `{"model", "internet_tools", "plan_contract", "model_source"}`."""
    wanted = execution_settings_id(plan_run_id)
    doc = next((d for d in read_documents(username, session_id, plan_run_id)
                if d.document_id == wanted and d.kind == EXECUTION_SETTINGS_KIND), None)
    if doc is None:
        return None
    try:
        value = json.loads(document_body(username, session_id, doc))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


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
    """The sub-agent thread of one section, as `section_states` reads it.

    `state`, `end_reason` and `error` are those of the thread's newest run. `run_id` is the
    thread's first run, which keys its report documents. `report` is `typed` for a
    `report_data` document, `text` for a `report` document alone, and empty for none.
    `incomplete` is the `execution.incomplete` flag of the typed report.
    """

    node_id: str
    state: str
    run_id: str = ""
    end_reason: str = ""
    error: str = ""
    report: str = ""
    incomplete: bool = False


def section_cause(run: SectionRun | None) -> str:
    """Why a section failed, or empty when it did not. The outcome of the thread and its
    report decide it: no run, a run that did not complete, a run that stopped at a limit,
    a report that states incomplete execution, or no report."""
    if run is None:
        return "no run"
    if run.state in ("running", "waiting_for_children", "pending"):
        return ""
    if run.state != "completed":
        return f"the run ended {run.state}" + (f": {run.error}" if run.error else "")
    if run.end_reason:
        return f"the run stopped before an answer ({run.end_reason})"
    if not run.report:
        return "no report"
    if run.incomplete:
        return "the report states incomplete execution"
    return ""


def section_states(snapshot: PlanSnapshot, runs: list[SectionRun]) -> list[dict[str, Any]]:
    """The `sections_json` entries of an approved tree: for each section, the state of its
    sub-agent thread, whether it failed, and the cause. `corrections`, `review` and
    `defect_classes` stay at their empty values, so older readers find the same keys."""
    by_node = {run.node_id: run for run in runs}
    out = []
    for node, tasks in sections(snapshot):
        run = by_node.get(node.node_id)
        cause = section_cause(run)
        out.append({
            "node_id": node.node_id,
            "title": node.text,
            "tasks": len(tasks),
            "state": run.state if run else "",
            "end_reason": run.end_reason if run else "",
            "corrections": 0,
            "review": "",
            "defect_classes": [],
            "failed": bool(cause),
            "cause": cause,
        })
    return out


def failure_cause(entry: dict[str, Any]) -> str:
    """Why a failed section failed. An entry from before `cause` derives it from its
    state: no run, the state its run ended in, or no report."""
    if entry.get("cause"):
        return str(entry["cause"])
    state = str(entry.get("state") or "")
    if not state:
        return "no run"
    if state != "completed":
        return f"the run ended `{state}`"
    return "no report"


def failed_sections_table(entries: list[dict[str, Any]]) -> str:
    """The generated `Failed sections` table, or empty when no section failed."""
    failed = [e for e in entries if e.get("failed")]
    if not failed:
        return ""
    lines = ["## Failed sections", "", "| section | cause |", "|---|---|"]
    for entry in failed:
        title = str(entry.get("title") or "").replace("|", "/")
        lines.append(f"| {title} | {failure_cause(entry)} |")
    return "\n".join(lines)


__all__ = [
    "AWAITING_REVIEW", "CANCELLED", "COMPLETED", "DocumentBodyError", "EXECUTE",
    "EXECUTING", "EXECUTION_SETTINGS_KIND", "FAILED", "INLINE_BODY_BYTES",
    "MAX_COMMENT_CHARS", "MAX_NODES", "MAX_NODE_TEXT", "MAX_SECTIONS", "MUTABLE_STATES",
    "NO_VERDICT", "PLANNING", "PLAN_CONTRACT", "PLAN_NAMESPACE", "PlanDecision",
    "PlanDocument", "PlanError", "PlanNode", "PlanRunRow", "PlanSnapshot", "REVISING",
    "SectionRun", "StaleVersion", "TERMINAL_STATES", "artifact_key", "build_tree",
    "children_of", "create_plan", "create_plan_run", "document_body", "document_id",
    "execution_settings_id", "failed_sections_table", "failure_cause", "initial_snapshot",
    "is_terminal", "node_paths", "nodes_json", "parse_verdict", "read_decision",
    "read_documents", "read_execution_settings", "read_plan_run", "read_report_data",
    "read_snapshot", "render_tree", "replace_tree", "resolve_node", "root_node_id",
    "section_cause", "section_ids", "section_states", "sections", "validate",
    "write_document", "write_execution_settings", "write_plan_run", "write_snapshot",
]
