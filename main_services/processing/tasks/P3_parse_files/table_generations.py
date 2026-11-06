"""Serialize generation commands and OCR plan claims while parsers run concurrently."""

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import activity, workflow

with workflow.unsafe.imports_passed_through():
    from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
    from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError
    from tasks.heartbeat import HEARTBEAT_TIMEOUT, with_heartbeat

PLANNER_QUEUE = "processing-index-planner-queue"


@dataclass
class GenerationCommand:
    collectionname: str
    file_hash: str
    action: str
    token: str = ""
    generation: int = 0
    owner_op: str = ""
    manifest: bytes = b""
    expected_columns: int = -1


@workflow.defn
class TableGenerationCommand:
    """Run short generation and OCR plan commands through the single-consumer storage queue."""

    @workflow.run
    async def run(self, command: GenerationCommand) -> int:
        return await workflow.execute_activity(
            apply_table_generation_command, command, task_queue=PLANNER_QUEUE,
            start_to_close_timeout=timedelta(minutes=10), heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3))


def send_command(command: GenerationCommand, *, deadline_seconds: float = 120) -> int:
    """Wait for a short command without retaining cell data in workflow history."""
    from temporalio.client import Client

    async def send():
        import time
        from tasks.heartbeat import stop_if_worker_is_stopping
        from tasks.temporal_readiness import CONNECT_TIMEOUT_SECONDS, START_RPC_TIMEOUT, TEMPORAL_ADDRESS
        client = await asyncio.wait_for(Client.connect(TEMPORAL_ADDRESS), CONNECT_TIMEOUT_SECONDS)
        workflow_id = f"table-generation-{command.collectionname}-{command.file_hash}"
        deadline = time.monotonic() + deadline_seconds
        owned = None

        async def wait_result(handle):
            task = asyncio.create_task(handle.result())
            try:
                while not task.done():
                    stop_if_worker_is_stopping()
                    if time.monotonic() >= deadline:
                        raise TimeoutError("The metadata command exceeded its deadline")
                    await asyncio.wait({task}, timeout=1)
                return await task
            finally:
                if not task.done():
                    task.cancel()

        try:
            while time.monotonic() < deadline:
                stop_if_worker_is_stopping()
                try:
                    owned = await client.start_workflow(
                        TableGenerationCommand.run, command, id=workflow_id,
                        task_queue="processing-common-queue", rpc_timeout=START_RPC_TIMEOUT,
                        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE)
                    return await wait_result(owned)
                except WorkflowAlreadyStartedError:
                    try:
                        await wait_result(client.get_workflow_handle(workflow_id))
                    except TimeoutError:
                        raise
                    except Exception:
                        stop_if_worker_is_stopping()
            raise TimeoutError("The metadata command exceeded its deadline")
        except BaseException:
            if owned is not None:
                try:
                    await asyncio.wait_for(owned.cancel(rpc_timeout=START_RPC_TIMEOUT), 30)
                except Exception:
                    pass
            raise

    return asyncio.run(send())


def _record(client, command, generation, state):
    from database.clickhouse import insert_durable
    insert_durable(client, "table_generation_owners",
                   [[command.file_hash, generation, command.token, command.owner_op, state]],
                   column_names=["file_hash", "generation", "attempt_token", "owner_op", "state"])


def complete_column_coverage(client, dataset: str, file_hash: str, generation: int) -> bool:
    """Verify that every stored cell column has corresponding dataset metadata."""
    rows = client.query(
        "SELECT count() FROM (SELECT DISTINCT sheet_id, column_id FROM table_cells FINAL "
        "WHERE file_hash = {hash:String} AND generation = {generation:UInt32}) "
        "WHERE (sheet_id, column_id) NOT IN (SELECT sheet_id, column_id FROM table_columns FINAL "
        "WHERE collection_dataset = {dataset:String} AND hash = {hash:String} AND generation = {generation:UInt32})",
        parameters={"dataset": dataset, "hash": file_hash, "generation": generation}).result_rows
    return bool(rows) and int(rows[0][0]) == 0


@activity.defn
@with_heartbeat
def apply_table_generation_command(command: GenerationCommand) -> int:
    """Allocate, publish, or retire a generation under serialized storage access."""
    import pyarrow as pa
    from database.clickhouse import get_collection_client, insert_arrow_durable

    with get_collection_client(command.collectionname) as client:
        if command.action == "claim_ocr_plan":
            from tasks.P3_parse_files.automatic_ocr import claim_automatic_plan
            return claim_automatic_plan(client, command)
        if command.action in ("publish_ocr_plan", "fail_ocr_plan", "apply_ocr_plan"):
            from tasks.P3_parse_files.automatic_ocr import apply_automatic_state_command
            return apply_automatic_state_command(client, command)
        owners = client.query(
            "SELECT generation, attempt_token, owner_op, state FROM table_generation_owners FINAL "
            "WHERE file_hash = {hash:String}", parameters={"hash": command.file_hash}).result_rows
        if command.action == "allocate":
            for generation, token, _, state in owners:
                if token == command.token:
                    if state == "retired":
                        raise ApplicationError("The table attempt is retired", non_retryable=True)
                    return int(generation)
            maxima = [int(row[0]) for row in owners]
            for table, column in (("table_documents", "hash"), ("table_cells", "file_hash")):
                rows = client.query(f"SELECT max(generation) FROM {table} "
                                    f"WHERE {column} = {{hash:String}}",
                                    parameters={"hash": command.file_hash}).result_rows
                maxima.extend(int(row[0] or 0) for row in rows)
            generation = max(maxima, default=0) + 1
            if generation > 2 ** 32 - 1:
                raise ApplicationError("Table generation limit reached", non_retryable=True)
            _record(client, command, generation, "writing")
            return generation
        owner = next((row for row in owners if int(row[0]) == command.generation), None)
        if command.action == "publish":
            manifest = pa.ipc.open_stream(command.manifest).read_all()
            row = manifest.to_pylist()[0]
            if row["hash"] != command.file_hash or int(row["generation"]) != command.generation:
                raise ApplicationError("The table publication identity changed", non_retryable=True)
            if owner is not None:
                if owner[3] == "retired" or (owner[3] == "writing" and owner[1] != command.token):
                    raise ApplicationError("The table attempt cannot publish", non_retryable=True)
            elif command.generation != 0:
                # Existing generations remain readable during the additive upgrade.
                rows = client.query(
                    "SELECT count() FROM table_documents FINAL WHERE hash = {hash:String} "
                    "AND generation = {generation:UInt32} AND status = 'ok'",
                    parameters={"hash": command.file_hash, "generation": command.generation}).result_rows
                if not rows or not rows[0][0]:
                    raise ApplicationError("The table generation has no owner", non_retryable=True)
            published = client.query(
                "SELECT generation FROM table_documents FINAL WHERE collection_dataset = {dataset:String} "
                "AND hash = {hash:String} AND status IN ('ok', 'empty') LIMIT 1",
                parameters={"dataset": row["collection_dataset"], "hash": command.file_hash}).result_rows
            if published and int(published[0][0]) > command.generation:
                raise ApplicationError("A newer table generation is published", non_retryable=True)
            if row["status"] == "ok":
                for table, column, expected in (("table_cells", "file_hash", row["cell_count"]),
                                                ("table_sheets", "hash", row["sheet_count"])):
                    sql = f"SELECT count() FROM {table} FINAL WHERE {column} = {{hash:String}} AND generation = {{generation:UInt32}}"
                    parameters = {"hash": command.file_hash, "generation": command.generation}
                    if table == "table_sheets":
                        sql += " AND collection_dataset = {dataset:String}"
                        parameters["dataset"] = row["collection_dataset"]
                    actual = client.query(sql, parameters=parameters).result_rows
                    if not actual or int(actual[0][0]) != int(expected):
                        raise RuntimeError("A table publication has incomplete stored rows")
            if row["status"] == "ok" and not complete_column_coverage(
                    client, row["collection_dataset"], command.file_hash, command.generation):
                raise RuntimeError("A table publication has incomplete stored columns")
            if row["status"] == "ok" and command.expected_columns < 0:
                raise RuntimeError("A table publication has no prepared column count")
            if row["status"] == "ok" and command.expected_columns >= 0:
                actual = client.query(
                    "SELECT count() FROM table_columns FINAL WHERE collection_dataset = {dataset:String} "
                    "AND hash = {hash:String} AND generation = {generation:UInt32}",
                    parameters={"dataset": row["collection_dataset"], "hash": command.file_hash,
                                "generation": command.generation}).result_rows
                if not actual or int(actual[0][0]) != command.expected_columns:
                    raise RuntimeError("A table publication has incomplete stored columns")
            if row["status"] == "ok" and row["reader"] == "sqlite":
                from tasks.P3_parse_files.table_text import stored_text_identity
                expected = int(row["text_page_count"]), row["text_digest"]
                if not row["text_complete"] or stored_text_identity(client, row["collection_dataset"], command.file_hash) != expected:
                    raise RuntimeError("A table publication has incomplete stored text")
            insert_arrow_durable(client, "table_documents", manifest)
            if owner is not None:
                command.token, command.owner_op = owner[1], owner[2]
                _record(client, command, command.generation, "published")
            return command.generation
        if command.action == "retire":
            if owner is None or owner[3] not in ("published", "retired"):
                raise ApplicationError("Writer termination is not verified", non_retryable=True)
            references = client.query(
                "SELECT count() FROM table_documents FINAL WHERE hash = {hash:String} "
                "AND generation = {generation:UInt32} AND status = 'ok'",
                parameters={"hash": command.file_hash, "generation": command.generation}).result_rows
            if references and references[0][0]:
                return 0
            command.token, command.owner_op = owner[1], owner[2]
            _record(client, command, command.generation, "retired")
            return command.generation
        raise ApplicationError("Unknown table generation command", non_retryable=True)


def delete_retired_generation(client, file_hash: str, generation: int) -> None:
    """Delete an authorized retired generation outside the command queue."""
    from database.clickhouse import insert_durable
    rows = client.query(
        "SELECT state FROM table_generation_owners FINAL WHERE file_hash = {hash:String} "
        "AND generation = {generation:UInt32}",
        parameters={"hash": file_hash, "generation": generation}).result_rows
    if rows != [("retired",)]:
        raise RuntimeError("The table generation has no retirement authorization")
    for table, column in (("table_cells", "file_hash"), ("table_sheets", "hash"), ("table_columns", "hash")):
        client.command(f"DELETE FROM {table} WHERE {column} = {{hash:String}} "
                       "AND generation = {generation:UInt32} SETTINGS mutations_sync = 2",
                       parameters={"hash": file_hash, "generation": generation})
    insert_durable(client, "processing_output_receipts",
                   [["", file_hash, "table_generation", str(generation), "retirement-1", "deleted", ""]],
                   column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id"])
