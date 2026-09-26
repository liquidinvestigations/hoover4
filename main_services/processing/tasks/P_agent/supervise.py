"""The agent run sweep: it ends the runs whose workflow closed without an ending.

`supervise_agent_runs` runs on `operations-queue`, in the orchestration worker, after the
operation sweep of each `CollectEtaSamples` pass. That worker has a Temporal client, which
`describe()` and `start_workflow` need.

A workflow that fails on a code error writes no state, and a `write_ending` or `fan_in` that
fails after all its retries leaves a parent waiting for ever. Each pass reads two sets, at
most `SWEEP_LIMIT` rows each, from `agent_runs FINAL`:

1. **Running rows** that started more than `SWEEP_GRACE_SECONDS` ago. The sweep reads the
   workflow of each with `describe()`. A row with a parent is read only when the parent is
   `waiting_for_children` and the parent's workflow is closed, because until then the
   parent's `delegate_step` or its retry can still start the child. A row whose parent
   is terminal is also read, because no attempt of a terminal parent starts a child. For
   a closed or absent workflow, the sweep writes the `cancelled` ending when the turn has
   a stop row, and the `failed` ending with the cause otherwise. It then runs `fan_in`.
2. **Waiting rows** in `waiting_for_children`, last written more than `SWEEP_GRACE_SECONDS`
   ago, with no continuation and a closed workflow. When every row of the run's batch is
   terminal, or the batch has no row, the sweep runs `continue_run`.

A continuation that either set returns starts with `client.start_workflow` and a reuse
policy that rejects a duplicate id. A refused duplicate counts as started. The input of the
continuation copies the settings (collections, model, internet switch, turn uuid) from the
start input of the closed workflow of the run, or of the nearest ancestor whose workflow
history holds one, because the run row has no columns for them.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from ..heartbeat import with_heartbeat

log = logging.getLogger(__name__)

#: A running or waiting row younger than this is left alone. The operation sweep uses the
#: same grace for a running row.
SWEEP_GRACE_SECONDS = 120
#: The most rows each of the two reads of one pass returns.
SWEEP_LIMIT = 500

#: The cause of a `failed` ending when the run's workflow does not exist.
WORKFLOW_ABSENT = "The workflow of this run does not exist."


@activity.defn
@with_heartbeat
def supervise_agent_runs() -> None:
    """One pass of the agent run sweep."""
    asyncio.run(_supervise_agent_runs())


async def _supervise_agent_runs() -> None:
    client = await Client.connect("temporal:7233")
    await sweep(client)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rows(where: str, parameters: dict):
    from database import agent_runs

    with agent_runs._client() as client:
        rows = client.query(
            f"SELECT {', '.join(agent_runs.RUN_COLUMNS)} FROM agent_runs FINAL WHERE "
            + where + f" ORDER BY started_at LIMIT {SWEEP_LIMIT}",
            parameters=parameters,
        ).result_rows
    return [agent_runs._from_db(r) for r in rows]


async def _closed(client, workflow_id: str) -> tuple[bool, str]:
    """Whether a workflow is closed or absent, and the cause of a failed ending."""
    try:
        description = await client.get_workflow_handle(workflow_id).describe()
    except RPCError as exc:
        if exc.status == RPCStatusCode.NOT_FOUND:
            return True, WORKFLOW_ABSENT
        raise
    if description.status == WorkflowExecutionStatus.RUNNING:
        return False, ""
    return True, (f"The workflow of this run ended with status {description.status.name} "
                  "and did not write the state of the run.")


async def _start_input(client, workflow_id: str):
    """The `AgentRunInput` a closed workflow started with, or None."""
    from tasks.P_agent.activities import AgentRunInput

    try:
        history = await client.get_workflow_handle(workflow_id).fetch_history()
    except RPCError:
        return None
    for event in history.events:
        if event.HasField("workflow_execution_started_event_attributes"):
            payloads = event.workflow_execution_started_event_attributes.input.payloads
            if not payloads:
                return None
            values = await client.data_converter.decode(payloads, [AgentRunInput])
            return values[0] if values else None
    return None


async def _settings(client, row):
    """The input of a run that the sweep starts or ends: the ids of `row`, and the settings
    of the nearest run of its chain whose workflow input can be read."""
    from database import agent_runs
    from tasks.P_agent.activities import AgentRunInput

    current = row
    seen = 0
    while current is not None and seen < 8:
        found = await _start_input(client, current.workflow_id) if current.workflow_id else None
        if found is not None:
            return replace(found, run_id=row.run_id, kind=row.kind)
        parent_id = current.continues_run_id or current.parent_run_id
        current = (agent_runs.read_run(row.username, row.session_id, parent_id)
                   if parent_id else None)
        seen += 1
    return AgentRunInput(run_id=row.run_id, username=row.username,
                         session_id=row.session_id, kind=row.kind)


async def _start_continuation(client, row, continuation) -> bool:
    """Start a continuation that `fan_in` or `continue_run` wrote. False for none."""
    from tasks.P_agent import workflows

    if not continuation.run_id:
        return False
    inp = replace(await _settings(client, row), run_id=continuation.run_id,
                  plan_run_id="", decision_id="")
    try:
        await client.start_workflow(
            workflows.AgentRun.run, inp, id=continuation.workflow_id,
            task_queue=workflows.CHAT_TASK_QUEUE,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        log.info("[agent sweep] %s is already started", continuation.workflow_id)
    return True


async def sweep(client, now: datetime | None = None, *, username: str | None = None,
                grace_seconds: int = SWEEP_GRACE_SECONDS) -> dict:
    """One pass over the two sets. `username` limits the pass to one owner, for a test.

    Returns the counts of the rows it ended and the continuations it started.
    """
    from database import agent_runs
    from tasks.P_agent.activities import (
        WriteEndingParams, _continue_run, _fan_in, _write_ending,
    )

    before = (now or _now()) - timedelta(seconds=grace_seconds)
    owner = " AND username = {u:String}" if username else ""
    params = {"t": before, "u": username or ""}
    counts = {"ended": 0, "continued": 0}

    for row in _rows("state = 'running' AND started_at < {t:DateTime64(3)}" + owner, params):
        try:
            if row.parent_run_id:
                parent = agent_runs.read_run(row.username, row.session_id, row.parent_run_id)
                if parent is None:
                    continue
                # A terminal parent starts no child, so only the child's own workflow counts.
                if not agent_runs.is_terminal(parent):
                    if parent.state != agent_runs.WAITING_FOR_CHILDREN:
                        continue
                    if not (await _closed(client, parent.workflow_id))[0]:
                        continue
            closed, cause = await _closed(client, row.workflow_id)
            if not closed:
                continue
            settings = await _settings(client, row)
            stopped = agent_runs.turn_is_stopped(row.username, row.session_id, row.turn_seq)
            _write_ending(WriteEndingParams(
                row.run_id, row.username, row.session_id,
                agent_runs.CANCELLED if stopped else agent_runs.FAILED,
                error="" if stopped else cause, turn_uuid=settings.turn_uuid,
            ))
            counts["ended"] += 1
            log.info("[agent sweep] ended run %s: %s", row.run_id, "cancelled" if stopped else cause)
            continuation = _fan_in(row.username, row.session_id, row.run_id)
            counts["continued"] += int(await _start_continuation(client, row, continuation))
        except Exception:  # noqa: BLE001 - one row never stops the pass
            log.exception("[agent sweep] could not supervise run %s", row.run_id)

    waiting = _rows(
        "state = 'waiting_for_children' AND updated_at < {t:DateTime64(3)}" + owner, params)
    for row in waiting:
        try:
            if _rows("continues_run_id = {c:UUID}",
                     {"c": row.run_id}):
                continue
            if not (await _closed(client, row.workflow_id))[0]:
                continue
            batch = _rows("parent_run_id = {p:UUID} AND batch_id = {b:UUID}",
                          {"p": row.run_id, "b": row.delegated_batch_id}) \
                if row.delegated_batch_id else []
            if not all(agent_runs.is_terminal(r) for r in batch):
                continue
            continuation = _continue_run(row.username, row.session_id, row.run_id)
            counts["continued"] += int(await _start_continuation(client, row, continuation))
        except Exception:  # noqa: BLE001 - one row never stops the pass
            log.exception("[agent sweep] could not continue run %s", row.run_id)
    return counts


__all__ = ["SWEEP_GRACE_SECONDS", "SWEEP_LIMIT", "supervise_agent_runs", "sweep"]
