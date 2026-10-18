"""`WorkspaceWriter`: the serialized writer of the workspace files of one chat session.

ClickHouse has no compare-and-write, and two worker processes can run tool calls of one
session at once. So every write and patch of a session goes through one workflow, whose id is
`workspace-<session_id>`. The session tool server sends each command with
signal-with-start, and polls the receipt of its operation id (`database.chat_workspace`).

**One command at a time.** The workflow takes the commands in the order of arrival. For each
one, `prepare_workspace_mutation` reads the receipt of the operation, the current version of
the file and the citation evidence of the session, and returns the outcome
(`mutations.prepare`). The outcome is in the workflow history before
`commit_workspace_mutation` writes the version row and the receipt. A retry of the commit
writes the same rows, so it cannot allocate another version.

**Repeated operations.** A command whose operation id has a receipt returns that receipt and
changes nothing. A version whose operation id equals the command's, without a receipt, is a
commit that stopped after the version row. The preparation then returns that version, and the
commit writes the missing receipt.

**Lifetime.** The workflow completes after `IDLE` without a command, and continues as new
after `COMMANDS_PER_RUN` commands with the commands that wait, which bounds its history. A
deleted session refuses every command, so a late command cannot recreate its files.

The workflow makes no model call. It runs on `chat-queue` with the short activity limits.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT, with_heartbeat
    from tasks.P_workspace.mutations import Command, Prepared

#: The prefix of the workflow id of a session's writer.
WRITER_WORKFLOW_PREFIX = "workspace-"
#: The signal that carries one command.
SUBMIT_SIGNAL = "submit"
#: The time without a command after which the writer completes.
IDLE = timedelta(minutes=15)
#: Commands of one run before it continues as new.
COMMANDS_PER_RUN = 200
#: Rounds of the commit of one prepared command, each with the storage retry, before the
#: writer goes on. A later command reads the stored state again.
COMMIT_ROUNDS = 6
COMMIT_PAUSE = timedelta(seconds=10)

_SHORT = timedelta(seconds=60)
STORAGE_RETRY = RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS)


def writer_workflow_id(session_id: str) -> str:
    return f"{WRITER_WORKFLOW_PREFIX}{session_id}"


@dataclass
class WriterStart:
    username: str
    session_id: str
    #: The commands that waited when the previous run continued as new.
    pending: List[Command] = field(default_factory=list)


@dataclass
class CommitInput:
    command: Command
    prepared: Prepared


def _committed_result(version) -> dict:
    return {"success": True, "name": version.name, "version": version.version,
            "lines": len(version.content.splitlines()), "chars": len(version.content),
            "citations": [c.get("handle") for c in version.citations if c.get("handle")]}


@activity.defn
@with_heartbeat
def prepare_workspace_mutation(cmd: Command) -> Prepared:
    """The outcome of one command, from the stored receipt or from the current file."""
    from database import chat_workspace as store
    from tasks.P_agent import reports
    from tasks.P_workspace import mutations

    receipt = store.read_receipt(cmd.username, cmd.session_id, cmd.operation_id)
    if receipt is not None:
        return Prepared(ok=receipt.ok, result=receipt.result, name=receipt.name,
                        found_version=receipt.version, replay=True)
    if store.session_deleted(cmd.username, cmd.session_id):
        return mutations.failure(cmd, "This conversation was deleted, so its files cannot change.", None)
    head = (store.read_version(cmd.username, cmd.session_id, cmd.name)
            if not store.valid_name(cmd.name) else None)
    if head is not None and cmd.operation_id and head.operation_id == cmd.operation_id:
        return Prepared(ok=True, result=_committed_result(head), name=head.name,
                        found_version=head.version)
    entries = reports.session_citation_entries(cmd.username, cmd.session_id)
    return mutations.prepare(cmd, head, entries)


@activity.defn
@with_heartbeat
def commit_workspace_mutation(inp: CommitInput) -> None:
    """Write the prepared version, then the receipt of the operation."""
    from database import chat_workspace as store

    cmd, prepared = inp.command, inp.prepared
    if prepared.version is not None:
        store.write_version(prepared.version)
    store.write_receipt(cmd.username, cmd.session_id, store.Receipt(
        cmd.operation_id, prepared.name or cmd.name, prepared.found_version, prepared.ok,
        prepared.result))


@workflow.defn
class WorkspaceWriter:
    """Handle the workspace commands of one session in order."""

    def __init__(self) -> None:
        self._queue: List[Command] = []

    @workflow.signal(name=SUBMIT_SIGNAL)
    def submit(self, cmd: Command) -> None:
        self._queue.append(cmd)

    @workflow.run
    async def run(self, start: WriterStart) -> int:
        self._queue = list(start.pending) + self._queue
        handled = 0
        while True:
            if not self._queue:
                try:
                    await workflow.wait_condition(lambda: bool(self._queue), timeout=IDLE)
                except asyncio.TimeoutError:
                    pass
                if not self._queue:
                    return handled
            await self._apply(self._queue.pop(0))
            handled += 1
            if handled >= COMMANDS_PER_RUN:
                workflow.continue_as_new(WriterStart(start.username, start.session_id,
                                                     list(self._queue)))

    async def _apply(self, cmd: Command) -> None:
        try:
            prepared: Prepared = await workflow.execute_activity(
                prepare_workspace_mutation, cmd, start_to_close_timeout=_SHORT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=STORAGE_RETRY,
            )
        except ActivityError as exc:
            # No receipt is written. The tool server reports a retryable failure, and the
            # worker's next attempt of the tool call sends the command again.
            workflow.logger.warning("workspace prepare failed for %s: %s", cmd.operation_id, exc)
            return
        if prepared.replay:
            return
        for _ in range(COMMIT_ROUNDS):
            try:
                await workflow.execute_activity(
                    commit_workspace_mutation, CommitInput(cmd, prepared),
                    start_to_close_timeout=_SHORT, heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STORAGE_RETRY,
                )
                return
            except ActivityError as exc:
                workflow.logger.warning("workspace commit failed for %s: %s", cmd.operation_id, exc)
                await workflow.sleep(COMMIT_PAUSE)


__all__ = ["COMMANDS_PER_RUN", "CommitInput", "IDLE", "SUBMIT_SIGNAL", "WRITER_WORKFLOW_PREFIX",
           "WorkspaceWriter", "WriterStart", "commit_workspace_mutation",
           "prepare_workspace_mutation", "writer_workflow_id"]
