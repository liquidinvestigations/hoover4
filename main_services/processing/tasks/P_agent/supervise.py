"""The agent run sweep: it ends the runs whose workflow closed without an ending.

`supervise_agent_runs` runs on `operations-queue`, in the orchestration worker, after the
operation sweep of each `CollectEtaSamples` pass. That worker has a Temporal client, which
`describe()` needs.

A workflow that fails on a code error writes no state. Each pass reads at most
`SWEEP_LIMIT` running rows that started more than `SWEEP_GRACE_SECONDS` ago from
`agent_runs FINAL`, and reads the workflow of each with `describe()`. For a closed or absent
workflow, the sweep writes the `cancelled` ending when the turn has a stop row, and the
`failed` ending with the cause otherwise. The turn uuid of the ending comes from the start
input of the closed workflow, because the run row has no column for it.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
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


async def sweep(client, now: datetime | None = None, *, username: str | None = None,
                grace_seconds: int = SWEEP_GRACE_SECONDS) -> dict:
    """One pass. `username` limits the pass to one owner, for a test.

    Returns the count of the rows it ended.
    """
    from database import agent_runs
    from tasks.P_agent.activities import WriteEndingParams, _write_ending

    before = (now or _now()) - timedelta(seconds=grace_seconds)
    owner = " AND username = {u:String}" if username else ""
    params = {"t": before, "u": username or ""}
    counts = {"ended": 0}

    for row in _rows("state = 'running' AND started_at < {t:DateTime64(3)}" + owner, params):
        try:
            closed, cause = await _closed(client, row.workflow_id)
            if not closed:
                continue
            start = await _start_input(client, row.workflow_id) if row.workflow_id else None
            stopped = agent_runs.turn_is_stopped(row.username, row.session_id, row.turn_seq)
            _write_ending(WriteEndingParams(
                row.run_id, row.username, row.session_id,
                agent_runs.CANCELLED if stopped else agent_runs.FAILED,
                error="" if stopped else cause, turn_uuid=start.turn_uuid if start else "",
            ))
            counts["ended"] += 1
            log.info("[agent sweep] ended run %s: %s", row.run_id, "cancelled" if stopped else cause)
        except Exception:  # noqa: BLE001 - one row never stops the pass
            log.exception("[agent sweep] could not supervise run %s", row.run_id)

    return counts


__all__ = ["SWEEP_GRACE_SECONDS", "SWEEP_LIMIT", "supervise_agent_runs", "sweep"]
