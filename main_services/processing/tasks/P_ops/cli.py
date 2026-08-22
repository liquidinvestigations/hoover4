"""Submit an operation and follow it, in a way that survives the caller dying.

The shape every command here takes is: take the lock, write the row, start the
workflow under the operation's own id, print that id, then *watch*. Watching is the
only part that lives in this process, and it is the only part that can be lost.

That is the whole design. Before it, the sequencing of a multi-stage ingest lived in
the CLI, so killing the CLI stranded the work half-done with no record that it had
ever been asked for. Now the sequencing is a workflow, the record is a row, and
Ctrl-C ends a *view*.
"""

import asyncio
import logging
import os
import time

import click

log = logging.getLogger(__name__)

#: How often the tail re-reads the row. Fast enough to feel live, slow enough that ten
#: watchers of the same operation are not a load problem.
TAIL_INTERVAL_SECONDS = 3


def where_to_look(op_id: str) -> str:
    """One line telling a detaching caller where its operation can be watched.

    The base URL is configuration, never a literal: this file ships to every
    deployment and none of them share an address. With no URL configured the command
    that works everywhere is printed instead, which is the more useful half anyway.
    """
    base = os.environ.get("HOOVER4_ADMIN_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"Watch it at {base}/admin/operations, or with `main.py operations show {op_id}`."
    return f"Watch it with `main.py operations show {op_id}`."


def format_row(row: dict) -> str:
    """One operation as a single line: state, progress, and an estimate if there is one."""
    progress = ""
    if row["progress_total"]:
        progress = f" {row['progress_done']}/{row['progress_total']}"
        if row["eta_seconds"]:
            progress += f" (~{row['eta_seconds']}s left)"
    elif row["progress_done"]:
        progress = f" {row['progress_done']}"
    target = row["collection_dataset"] or row["collectionname"] or "-"
    return f"{row['op_id']}  {row['kind']}  {target}  {row['state']}{progress}"


def tail_operation(op_id: str) -> str:
    """Print an operation's progress until it reaches a terminal state.

    Ctrl-C here detaches and returns; it does not cancel. The distinction is the point
    of the whole layer, so the message says it in as many words rather than leaving a
    caller to guess whether they have just destroyed twenty minutes of work.
    """
    from database.operations import TERMINAL_STATES, get_operation

    last = ""
    try:
        while True:
            row = get_operation(op_id)
            if row is None:
                click.echo(f"{op_id}: no row yet")
            else:
                line = format_row(row)
                if line != last:
                    click.echo(line)
                    last = line
                if row["state"] in TERMINAL_STATES:
                    if row["state"] != "finished" and row["error"]:
                        click.echo(row["error"])
                    return row["state"]
            time.sleep(TAIL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        click.echo("")
        click.echo(f"Detached from {op_id}. The operation is still running: this "
                   f"command was only watching it, and stopping it stops nothing.")
        click.echo(where_to_look(op_id))
        return "detached"


def submit_operation(kind: str, collectionname: str = "", collection_dataset: str = "",
                     dataset_path: str = "", detail: dict | None = None,
                     user_id: str = "cli", rerun_of: str = "") -> str:
    """Take the lock, write the row, start the workflow. Returns the operation id.

    The row is written first: an operation that has a workflow and no row is invisible
    to everything except Temporal, and Temporal forgets. If the workflow start then
    fails, the row is landed in `errored` here rather than left holding the lock.
    """
    import temporalio.common
    from temporalio.client import Client as TemporalClient

    from database.operations import create_operation, finish_operation

    from .params import OperationParams

    row = create_operation(kind, collectionname, collection_dataset,
                           detail=detail, user_id=user_id, rerun_of=rerun_of)
    op_id = row["op_id"]

    async def _start():
        from ..visibility import ensure_search_attributes_ready, start_with_attribute_retry
        from .workflows import Operation

        client = await TemporalClient.connect("temporal:7233")
        await ensure_search_attributes_ready(client)
        await start_with_attribute_retry(lambda: client.start_workflow(
            Operation.run,
            OperationParams(
                op_id=op_id, kind=kind, collectionname=collectionname,
                collection_dataset=collection_dataset, dataset_path=dataset_path,
                detail=detail or {},
            ),
            # The operation id IS the workflow id. It already carries a timestamp, so
            # the reuse policy decides nothing and a conflict is a genuine one.
            id=op_id,
            task_queue="operations-queue",
            id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.FAIL,
        ))

    try:
        asyncio.run(_start())
    except Exception as exc:
        finish_operation(op_id, "errored", f"{type(exc).__name__}: {exc}")
        raise
    return op_id


def request_cancel(op_id: str) -> str:
    """Ask Temporal to cancel an operation and land its row in `cancelled`.

    The row is written here rather than by the workflow because a cancelled workflow
    cannot schedule further activities: a cleanup write attempted inside it would be
    cancelled with it, and the row would stay non-terminal for ever, holding the lock
    that cancelling was meant to release.
    """
    from database.operations import finish_operation, get_operation

    row = get_operation(op_id)
    if row is None:
        raise click.ClickException(f"No operation with id {op_id}.")

    async def _cancel():
        from temporalio.client import Client as TemporalClient
        client = await TemporalClient.connect("temporal:7233")
        handle = client.get_workflow_handle(op_id)
        await handle.cancel()

    try:
        asyncio.run(_cancel())
    except Exception as exc:
        # A workflow the server no longer knows about is the normal case for an
        # operation whose history has aged out. The row still has to be released.
        log.warning("Temporal cancellation of %s: %s", op_id, exc)
    finish_operation(op_id, "cancelled", "Cancelled by request.")
    return op_id
