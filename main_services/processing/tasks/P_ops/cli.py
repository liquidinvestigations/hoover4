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
import sys
import time
from typing import NoReturn

import click

log = logging.getLogger(__name__)

#: How often the tail re-reads the row. Fast enough to read as live, slow enough that ten
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


def tail_operation(op_id: str, deadline_seconds: float | None = None) -> str:
    """Print an operation's progress until it reaches a terminal state.

    Returns the terminal state, `detached` on Ctrl-C, or `following` when
    `deadline_seconds` passes before a terminal state. With no deadline it follows the
    operation to its end.

    Ctrl-C here detaches and returns; it does not cancel. The distinction is the point
    of the whole layer, so the message says it in as many words rather than leaving a
    caller to guess whether they have just destroyed twenty minutes of work.
    """
    from database.operations import TERMINAL_STATES, get_operation

    deadline = None if deadline_seconds is None else time.monotonic() + deadline_seconds
    last = ""
    row = None
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
            if deadline is not None and time.monotonic() >= deadline:
                return "following"
            pause = TAIL_INTERVAL_SECONDS
            if deadline is not None:
                pause = max(0.0, min(pause, deadline - time.monotonic()))
            time.sleep(pause)
    except KeyboardInterrupt:
        click.echo("")
        state = row["state"] if row else "pending"
        click.echo(f"Detached from {op_id}. The operation is still {state}: this "
                   f"command was only watching it, and stopping it stops nothing.")
        click.echo(where_to_look(op_id))
        return "detached"


def end_process(code: int) -> NoReturn:
    """Flush stdout and stderr, then end the process with `code` at once.

    `os._exit` skips the interpreter's exit handlers. The Temporal client leaves a
    runtime thread that can keep a normal exit waiting for hours after the last line.
    This command holds no file and no lock that needs a handler.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def submit_operation(kind: str, collectionname: str = "", collection_dataset: str = "",
                     dataset_path: str = "", detail: dict | None = None,
                     user_id: str = "cli", rerun_of: str = "") -> str:
    """Take the lock, write the row, start the workflow. Returns the operation id.

    The row is written first: an operation that has a workflow and no row is invisible
    to everything except Temporal, and Temporal forgets. If the workflow start then
    fails, the row is landed in `errored` here rather than left holding the lock.
    """
    import temporalio.common

    from database.operations import DRIVEN_KINDS, create_operation, finish_operation

    if kind not in DRIVEN_KINDS:
        raise ValueError(f"Operation kind has no workflow driver: {kind}")

    from .params import OperationParams

    row = create_operation(kind, collectionname, collection_dataset,
                           detail=detail, user_id=user_id, rerun_of=rerun_of)
    op_id = row["op_id"]

    async def _start():
        from ..temporal_readiness import START_RPC_TIMEOUT, connect_when_ready
        from ..visibility import ensure_search_attributes_ready, start_with_attribute_retry
        from .workflows import Operation

        client = await connect_when_ready()
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
            rpc_timeout=START_RPC_TIMEOUT,
        ))

    try:
        asyncio.run(_start())
    except Exception as exc:
        finish_operation(op_id, "errored", f"{type(exc).__name__}: {exc}")
        raise
    return op_id


def request_cancel(op_id: str) -> str:
    """Run the cancellation finalizer and wait for its terminal result."""
    import temporalio.common
    from temporalio.exceptions import WorkflowAlreadyStartedError
    from database.operations import get_operation

    row = get_operation(op_id)
    if row is None:
        raise click.ClickException(f"No operation with id {op_id}.")

    async def _cancel():
        from ..temporal_readiness import START_RPC_TIMEOUT, connect_when_ready
        from .workflows import CancelOperation

        client = await connect_when_ready()
        finalizer_id = f"cancel-{op_id}"
        try:
            handle = await client.start_workflow(
                CancelOperation.run, op_id, id=finalizer_id,
                task_queue="operations-queue",
                id_conflict_policy=temporalio.common.WorkflowIDConflictPolicy.USE_EXISTING,
                id_reuse_policy=temporalio.common.WorkflowIDReusePolicy.REJECT_DUPLICATE,
                rpc_timeout=START_RPC_TIMEOUT,
            )
        except WorkflowAlreadyStartedError:
            handle = client.get_workflow_handle(finalizer_id)
        return await handle.result()

    return asyncio.run(_cancel())


# ----------------------------------------------------------------- board repair

#: The reason of a replacement that `board-replace-fact` records in the `fact_replaced` event.
REPLACE_REASON = "The stored text was not the report of the explore. The report replaces it."
#: The seconds that `board-replace-fact` waits for the command writer.
REPLACE_WAIT_SECONDS = 180


def replace_request_id(fact_id: str) -> str:
    """The request id of the replacement of one finding. A second run names the same
    request, so it writes nothing new."""
    return f"replace_fact:{fact_id}:1"


def pinned_report(owner: str, session_id: str, answer_seq: int) -> dict:
    """The report version `{name, version}` of a finding: the report of the first conversion
    row of the session after the answer, else the report that the answer row pinned. Empty
    when neither names one."""
    import json

    from database.clickhouse import get_global_client
    from tasks.P_board import model as m

    with get_global_client() as client:
        rows = client.query(
            "SELECT seq, role, tool_output, usage_json FROM chat_messages FINAL "
            "WHERE username = {u:String} AND session_id = {s:String} AND seq >= {q:UInt32} "
            "AND ((role = 'tool' AND tool_name = {t:String}) OR (role = 'assistant' AND seq = {q:UInt32})) "
            "ORDER BY seq",
            parameters={"u": owner, "s": session_id, "q": int(answer_seq), "t": m.SUBMIT_FACT_TOOL},
        ).result_rows

    def report_of(text: str, key: str = "report") -> dict:
        try:
            value = json.loads(text or "{}").get(key)
        except (ValueError, AttributeError):
            return {}
        ok = (isinstance(value, dict) and isinstance(value.get("name"), str)
              and isinstance(value.get("version"), int) and value["version"] > 0)
        return {"name": value["name"], "version": value["version"]} if ok else {}

    for _seq, role, tool_output, _usage in rows:
        if role == "tool" and report_of(tool_output):
            return report_of(tool_output)
    for _seq, role, _output, usage_json in rows:
        if role == "assistant" and report_of(usage_json):
            return report_of(usage_json)
    return {}


def classify_report(board, intent, version) -> dict:
    """The small call of `convert_explore_report` for a report version: the kind, the open
    questions and the slug in the board language. The second attempt turns off the
    reasoning phase. When both attempts fail, the values of the code
    (`conversion.fallback_args`). Each call is an `llm_call_events` row of kind
    `board_convert`."""
    import time

    from tasks.llm_endpoints import chat_model, endpoint as llm_endpoint
    from tasks.P_agent import summarize
    from tasks.P_agent.model_timeouts import TIMEOUTS
    from tasks.P_board import activities as act
    from tasks.P_board import conversion

    model = chat_model()
    language = act.board_language(board)
    error = ""
    for attempt in range(conversion.CONVERT_ATTEMPTS):
        body = conversion.request_body(model, act._task_text(intent), version.name, version.content,
                                       version.citations, attempt == 0, language)
        started = time.monotonic()
        try:
            response = summarize.post_or_raise(
                llm_endpoint(), body,
                timeout=(act.CONVERT_CONNECT_SECONDS, TIMEOUTS.board_reason_request_seconds))
        except summarize.TransportFailure as exc:
            error = str(exc)
            act._record_llm_call(board.owner, board.board_id, model, {},
                                 int((time.monotonic() - started) * 1000), False, error, 0,
                                 kind="board_convert")
            continue
        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            error = f"the request was refused: HTTP {response.status_code}: {response.text[:200]}"
            act._record_llm_call(board.owner, board.board_id, model, {}, latency_ms, False, error, 0,
                                 kind="board_convert")
            continue
        reply = response.json()
        usage = (reply.get("usage") or {}) if isinstance(reply, dict) else {}
        try:
            args = conversion.parse_reply(reply)
        except conversion.MalformedConversion as exc:
            error = f"the reply is malformed: {exc}"
            act._record_llm_call(board.owner, board.board_id, model, usage, latency_ms, False, error,
                                 len(response.text), kind="board_convert")
            continue
        act._record_llm_call(board.owner, board.board_id, model, usage, latency_ms, True, "",
                             len(response.text), kind="board_convert")
        return args
    return conversion.fallback_args(version.content, version.citations, error)


def board_replace_fact(board_id: str, fact_id: str, reason: str = REPLACE_REASON) -> dict:
    """Submit the `replace_fact` command that replaces finding `fact_id` with its pinned
    report, and return `{"request_id", "state", "fact_id", "error"}`.

    A run whose request exists already sends no model call and submits nothing: it returns
    the state of that request. Otherwise the run checks the finding as the command writer
    does, reads the pinned report version, runs the small call, and submits the command.
    The dispatcher starts the command writer of the board on its next pass, and this
    function waits up to `REPLACE_WAIT_SECONDS` for the receipt.
    """
    import click

    from database import board_commands as bc
    from database import boards
    from database import chat_workspace as store
    from tasks.P_board import activities as act
    from tasks.P_board import commands as cmd
    from tasks.P_board import conversion

    request_id = replace_request_id(fact_id)
    board = boards.read_board(board_id)
    if board is None or board.is_deleted:
        raise click.ClickException(f"The board {board_id} does not exist or is dropped.")
    if not any(i.request_id == request_id for i in bc.read_inputs(board_id)):
        _events, facts, folded = act._read(board)
        fact = next((f for f in facts if f.fact_id == fact_id), None)
        if fact is None:
            raise click.ClickException(f"The board has no fact {fact_id}.")
        if fact_id in folded.rejected:
            raise click.ClickException(f"The fact {fact_id} is rejected or replaced already.")
        intent = folded.intents.get(fact.intent_id) if fact.intent_id else None
        if intent is None or intent.fact_id != fact_id:
            raise click.ClickException(f"The fact {fact_id} is not the finding of its intent.")
        report = pinned_report(board.owner, fact.session_id, fact.answer_seq)
        version = (store.read_version(board.owner, fact.session_id, report["name"], report["version"])
                   if report else None)
        if version is None:
            raise click.ClickException(f"The session {fact.session_id} has no pinned report for {fact_id}.")
        args = classify_report(board, intent, version)
        kind, citations, problems = conversion.resolve(version.content, args["kind"], version.citations)
        if args.get("model_error"):
            problems.insert(0, "the kind and the open questions came from the code, the model call "
                               f"failed: {args['model_error']}")
        new_fact = {"kind": kind, "claimed_kind": args["kind"], "text": version.content,
                    "session_id": fact.session_id, "answer_seq": fact.answer_seq,
                    "slug": args["slug"][:conversion.MAX_SLUG_CHARS],
                    "open_questions": args["open_questions"], "problems": problems, "report": report}
        bc.submit(board_id, request_id, cmd.REPLACE_FACT, cmd.REPAIR_ACTOR,
                  {"fact_id": fact_id, "reason": reason, "fact": new_fact, "citations": citations})
    deadline = time.monotonic() + REPLACE_WAIT_SECONDS
    while True:
        receipt = bc.read_receipts(board_id).get(request_id)
        if receipt is not None and receipt.state in (bc.COMMITTED, bc.REJECTED):
            return {"request_id": request_id, "state": receipt.state,
                    "fact_id": str((receipt.result or {}).get("fact_id") or ""), "error": receipt.error}
        if time.monotonic() >= deadline:
            return {"request_id": request_id, "state": receipt.state if receipt else "pending",
                    "fact_id": "", "error": ""}
        time.sleep(TAIL_INTERVAL_SECONDS)
