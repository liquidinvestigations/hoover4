"""The processing update coordinator and the workflow of one update operation.

`ProcessingUpdates` is a singleton (id `processing-updates`). The worker starts it at
bootstrap with `USE_EXISTING`, and the website starts it with a signal when it is closed,
so a closed coordinator returns on the next worker start or settings save. Its state is
in the database, not in its history: a new run reads the live update operations and the
stored checks, so it never repeats a completed step.

Each pass runs `check_processing_updates`. A pass that finds no change writes no row and
starts no operation, so a deployment that changes no version, setting or input starts
no update operation. A coordinator that starts is not an update run. The coordinator
starts at most one automatic operation at a time across the installation, collection
prerequisites first, and waits for its terminal row before it starts the next. A failed
or cancelled step does not start again automatically at the same fingerprint, so later
datasets continue.

It waits `IDLE_WAIT` between passes, `ACTIVE_WAIT` while its operation runs, and wakes
at once on a `request_check` signal, which a settings save and a page request send. It
continues as new after `PASSES_PER_RUN` passes.

`RunProcessingUpdate` is the child of an `update_dataset` or `update_collection`
operation. It snapshots the requested steps, then runs each step in registry order:
record the attempt, run the work, verify the output, record the applied fingerprint. A
step that fails is recorded and the next step runs. The operation errors when a step
failed.
"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from tasks.failure_chain import failure_message, is_cancellation
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P_admin.updates.activities import (
        apply_search_schema,
        begin_update_step,
        check_processing_updates,
        detect_update_files,
        finish_update_step,
        list_update_detection_plans,
        list_update_table_plans,
        list_update_virus_plans,
        retire_cached_searches,
        stale_virus_attributes,
        scan_update_files,
        list_update_vector_plans,
        obsolete_ocr_variants,
        reparse_update_tables,
        restore_missing_image_previews,
        prepare_table_update,
        refresh_update_checks,
        report_update_progress,
        settle_update_step,
        snapshot_processing_update,
        submit_automatic_update,
        update_operation_state,
    )
    from tasks.P_admin.updates.pdf_text_layer import scan_pdf_text_layers
    from tasks.P_admin.updates.params import (
        CheckUpdatesParams,
        RunUpdateParams,
        StepParams,
        SubmitUpdateParams,
        TablePlanParams,
        TablePlansParams,
        UpdateProgressParams,
        VirusPlansParams,
        VectorPlansParams,
    )
    from tasks.P_admin.updates.archive_members import restore_archive_members, finish_archive_members
    from tasks.P_admin.updates.table_receipts import TableReceiptParams, record_table_update_receipts
    from tasks.P_admin.updates.registry import SCOPE_DATASET
    from tasks.P6_index_data.params import RefreshDocumentLocationsParams, RefreshDocumentLocationsResult
    from tasks.visibility import dataset_search_attributes
    from tasks.workflow_window import run_with_window

COORDINATOR_ID = "processing-updates"
IDLE_WAIT = timedelta(minutes=2)
ACTIVE_WAIT = timedelta(seconds=30)
PASSES_PER_RUN = 200
VECTOR_PLAN_WINDOW = 4
_TERMINAL = ("finished", "errored", "cancelled", "missing")
_RETRY = RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS)


@dataclass
class CoordinatorState:
    #: The automatic update operation that this coordinator waits for.
    active_op: str = ""
    #: Check requests that arrived before a continue-as-new.
    requests: list = field(default_factory=list)


@workflow.defn
class ProcessingUpdates:
    """The singleton that keeps processing updates going. See the module docstring."""

    def __init__(self) -> None:
        self._requests: list = []

    @workflow.signal
    def request_check(self, request: dict) -> None:
        """Calculate a scope now. `{"scope_id": ..., "force": true}`, `*` for every scope."""
        self._requests.append(request or {})

    @workflow.run
    async def run(self, state: "CoordinatorState | None" = None) -> str:
        state = state or CoordinatorState()
        self._requests.extend(state.requests)
        for _ in range(PASSES_PER_RUN):
            forced = sorted({str(r.get("scope_id") or "*") for r in self._requests if r.get("force")})
            self._requests = []
            result = None
            try:
                result = await workflow.execute_activity(
                    check_processing_updates, CheckUpdatesParams(forced),
                    start_to_close_timeout=timedelta(minutes=60),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3))
            except ActivityError as exc:
                if is_cancellation(exc):
                    raise
                workflow.logger.warning("processing update check failed: %s", exc)
            if state.active_op:
                current = await workflow.execute_activity(update_operation_state, state.active_op,
                                                          start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
                if current in _TERMINAL:
                    state.active_op = ""
            if result is not None and result.automatic and not state.active_op:
                for candidate in result.candidates:
                    kind = "update_dataset" if candidate.scope_kind == SCOPE_DATASET else "update_collection"
                    stamp = int(workflow.now().timestamp() * 1_000_000)
                    op_id = f"{kind}-{candidate.scope_id}-{stamp}-{workflow.uuid4().hex[:12]}"
                    outcome = await workflow.execute_activity(
                        submit_automatic_update, SubmitUpdateParams(op_id, candidate), start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
                    status, _, named = outcome.partition(":")
                    if status == "running":
                        state.active_op = named
                        break
                    if status == "started":
                        await self._start(candidate, named)
                        state.active_op = named
                        break
            wait = ACTIVE_WAIT if state.active_op else IDLE_WAIT
            try:
                await workflow.wait_condition(lambda: bool(self._requests), timeout=wait)
            except asyncio.TimeoutError:
                pass
        state.requests = list(self._requests)
        workflow.continue_as_new(state)

    async def _start(self, candidate, op_id: str) -> None:
        """Start the `Operation` child, which outlives this run (`ABANDON`)."""
        try:
            await workflow.start_child_workflow(
                "Operation",
                {"op_id": op_id,
                 "kind": "update_dataset" if candidate.scope_kind == SCOPE_DATASET else "update_collection",
                 "collectionname": candidate.collectionname,
                 "collection_dataset": candidate.collection_dataset,
                 "detail": {"steps": list(candidate.steps),
                            "fingerprints": dict(candidate.fingerprints), "automatic": True}},
                id=op_id, task_queue="operations-queue",
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
        except WorkflowAlreadyStartedError:
            workflow.logger.info("operation %s started earlier", op_id)


@workflow.defn
class RunProcessingUpdate:
    """The steps of one update operation. See the module docstring."""

    @workflow.run
    async def run(self, params: RunUpdateParams) -> dict:
        snapshot = await workflow.execute_activity(snapshot_processing_update, params, start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        total = len(snapshot.steps)
        failures, done = [], 0
        for step in snapshot.steps:
            step_params = StepParams(params.op_id, params.scope_kind, params.collectionname,
                                     params.collection_dataset, params.automatic, step)
            await self._progress(params, step.step_id, "running", done, total)
            await workflow.execute_activity(begin_update_step, step_params, start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            try:
                summary = await self._run_step(params, step_params)
            except Exception as exc:
                if is_cancellation(exc):
                    raise
                message = failure_message(exc)
                step_params.state, step_params.error = "failed", message
                await workflow.execute_activity(finish_update_step, step_params, start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
                failures.append(f"{step.step_id}: {message}")
                done += 1
                await self._progress(params, step.step_id, "failed", done, total, message)
                continue
            step_params.state = summary
            outcome = await workflow.execute_activity(settle_update_step, step_params, start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            done += 1
            if not outcome.settled:
                failures.append(f"{step.step_id}: {outcome.message}")
            await self._progress(params, step.step_id, "succeeded" if outcome.settled else "failed",
                                 done, total, outcome.message)
        await workflow.execute_activity(refresh_update_checks, params, start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if failures:
            raise ApplicationError("Update steps failed: " + "; ".join(failures)[:3000],
                                   non_retryable=True)
        return {"steps": [step.step_id for step in snapshot.steps]}

    async def _progress(self, params: RunUpdateParams, step_id: str, state: str,
                        done: int, total: int, message: str = "") -> None:
        await workflow.execute_activity(
            report_update_progress,
            UpdateProgressParams(params.op_id, params.collectionname, params.collection_dataset,
                                 step_id, state, done, total, message or ""),
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)

    def _child(self, params: RunUpdateParams) -> dict:
        common = dict(task_queue="processing-common-queue")
        if params.collection_dataset:
            common["search_attributes"] = dataset_search_attributes(params.collection_dataset)
        return common

    async def _run_step(self, params: RunUpdateParams, step: StepParams) -> str:
        step_id = step.step.step_id
        if step_id == "unfinished":
            counts = await workflow.execute_child_workflow(
                "ExecutePlans",
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                 "base_temp_dir": "/tmp/hoover4", "op_id": params.op_id},
                id=f"update-unfinished-{params.op_id}", **self._child(params))
            return json.dumps(counts, sort_keys=True)
        if step_id == "failed_files":
            return await self._failed_files(params, step)
        if step_id == "archive_members":
            done = await workflow.execute_child_workflow(
                UpdateDatasetArchiveMembers.run,
                TablePlansParams(params.op_id, params.collectionname, params.collection_dataset),
                id=f"update-archive-members-{params.op_id}", **self._child(params))
            return f"reconciled {done} split archives"
        if step_id == "image_previews":
            done = await workflow.execute_child_workflow(
                UpdateDatasetImagePreviews.run,
                TablePlansParams(params.op_id, params.collectionname, params.collection_dataset),
                id=f"update-previews-{params.op_id}", **self._child(params))
            return f"published {done} image previews"
        if step_id == "ocr":
            return await self._ocr(params, step)
        if step_id == "pdf_text":
            return await self._pdf_text(params, step)
        if step_id == "vectors":
            detail = json.loads(step.step.detail or "{}")
            done = await workflow.execute_child_workflow(
                UpdateDatasetVectors.run,
                VectorPlansParams(params.op_id, params.collectionname, params.collection_dataset,
                                  str(detail.get("model", ""))),
                id=f"update-vectors-{params.op_id}", **self._child(params))
            return f"embedded and indexed {done} plans"
        if step_id == "virus_scan":
            result = await workflow.execute_child_workflow(
                UpdateDatasetVirusScan.run,
                VirusPlansParams(params.op_id, params.collectionname, params.collection_dataset),
                id=f"update-virus-{params.op_id}", **self._child(params))
            return json.dumps(result, sort_keys=True)
        if step_id == "ocr_detection":
            result = await workflow.execute_child_workflow(
                UpdateDatasetOcrDetection.run,
                VirusPlansParams(params.op_id, params.collectionname, params.collection_dataset),
                id=f"update-detection-{params.op_id}", **self._child(params))
            return json.dumps(result, sort_keys=True)
        if step_id == "tables":
            done = await workflow.execute_child_workflow(
                UpdateDatasetTables.run,
                TablePlansParams(params.op_id, params.collectionname, params.collection_dataset),
                id=f"update-tables-{params.op_id}", **self._child(params))
            return f"read the tables of {done} plans again"
        if step_id == "search_terms":
            await workflow.execute_activity(
                "index_entity_terms",
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset},
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=RetryPolicy(maximum_attempts=2))
            return "filter terms written"
        if step_id == "folder_counts":
            await workflow.execute_activity(
                "build_vfs_nodes",
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset},
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=RetryPolicy(maximum_attempts=2))
            return "folder counts written"
        if step_id == "search_schema":
            return await self._search_schema(params, step)
        raise ApplicationError(f"no work for update step {step_id}", non_retryable=True)

    async def _failed_files(self, params: RunUpdateParams, step: StepParams) -> str:
        detail = json.loads(step.step.detail or "{}")
        tasks = list(detail.get("automatic_tasks" if params.automatic else "manual_tasks") or [])
        if not tasks:
            return "no failed file to retry"
        selection = await workflow.execute_activity(
            "select_historical_errors",
            {"op_id": params.op_id, "collectionname": params.collectionname,
             "collection_dataset": params.collection_dataset, "task_names": tasks},
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        counts = {}
        if selection.get("plan_hashes"):
            counts = await workflow.execute_child_workflow(
                "ExecutePlans",
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                 "base_temp_dir": "/tmp/hoover4", "op_id": params.op_id},
                id=f"update-retry-{params.op_id}", **self._child(params))
        reconciliation = await workflow.execute_activity(
            "reconcile_selected_errors",
            {"op_id": params.op_id, "collectionname": params.collectionname,
             "collection_dataset": params.collection_dataset},
            start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        return json.dumps({"selected_errors": selection.get("selected_errors", 0),
                           "plans_run": counts.get("plans_run", 0), **reconciliation}, sort_keys=True)

    async def _ocr(self, params: RunUpdateParams, step: StepParams) -> str:
        result = await workflow.execute_child_workflow(
            "RerunOcr",
            {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
             "op_id": params.op_id},
            id=f"update-ocr-{params.op_id}", **self._child(params))
        obsolete = await workflow.execute_activity(obsolete_ocr_variants, step, start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        purged = {}
        if obsolete["variants"] or obsolete["pairs"]:
            purge = {"collectionname": params.collectionname,
                     "collection_dataset": params.collection_dataset,
                     "variants": obsolete["variants"], "removed_pairs": obsolete["pairs"]}
            purged = await workflow.execute_activity("purge_dropped_ocr_variants", purge, start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            await workflow.execute_activity("delete_orphaned_derived_pdfs", purge, start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        return json.dumps({"plans": result.get("plans", 0), "removed": obsolete, "purged": purged},
                          sort_keys=True)

    async def _pdf_text(self, params: RunUpdateParams, step: StepParams) -> str:
        counts = await workflow.execute_activity(scan_pdf_text_layers, step, start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        result = {}
        if counts["unbuilt_parts"]:
            result = await workflow.execute_child_workflow(
                "RerunOcr",
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                 "op_id": params.op_id},
                id=f"update-pdf-text-{params.op_id}", **self._child(params))
        return json.dumps({**counts, "plans": result.get("plans", 0)}, sort_keys=True)

    async def _search_schema(self, params: RunUpdateParams, step: StepParams) -> str:
        result = await workflow.execute_activity(apply_search_schema, step, start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if result["rebuild"]:
            # A column of another type needs new tables. The rebuild drops the shard tables
            # and indexes every finished plan again, so search is incomplete while it runs.
            await workflow.execute_activity(
                "prepare_reindex_collection",
                {"collectionname": params.collectionname, "vectors_only": False},
                task_queue="operations-queue", start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT)
            await workflow.execute_child_workflow(
                "RebuildCollectionPlans",
                {"op_id": params.op_id, "collectionname": params.collectionname, "vectors_only": False},
                id=f"update-rebuild-{params.op_id}", task_queue="operations-queue")
        return json.dumps(result, sort_keys=True)


@workflow.defn
class UpdateDatasetVectors:
    """Embedding and vector indexing of the plans whose files lack current vectors.

    Pages of at most 100 plans, four at a time, with continue-as-new after each page.
    """

    @workflow.run
    async def run(self, params: VectorPlansParams) -> int:
        plans = await workflow.execute_activity(list_update_vector_plans, params, start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not plans:
            if params.failed:
                raise ApplicationError(f"{params.failed} plans failed embedding or indexing",
                                       non_retryable=True)
            return params.done
        common = dict(task_queue="processing-common-queue",
                      search_attributes=dataset_search_attributes(params.collection_dataset))

        async def plan(plan_hash: str):
            child = {"collectionname": params.collectionname,
                     "collection_dataset": params.collection_dataset,
                     "plan_hash": plan_hash, "op_id": params.op_id}
            await workflow.execute_child_workflow(
                "ChunkEmbedForPlan", child,
                id=f"update-embed-{params.op_id}-{plan_hash}", **common)
            await workflow.execute_child_workflow(
                "IndexDatasetPlan", {**child, "vectors_only": True},
                id=f"update-index-vectors-{params.op_id}-{plan_hash}", **common)

        results = await run_with_window([lambda h=h: plan(h) for h in plans], VECTOR_PLAN_WINDOW)
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                if is_cancellation(result):
                    raise result
                failed += 1
        workflow.continue_as_new(VectorPlansParams(
            params.op_id, params.collectionname, params.collection_dataset, params.model,
            plans[-1], params.done + len(plans), params.failed + failed))


@workflow.defn
class UpdateDatasetTables:
    """Read selected tables and update all output that depends on their text."""

    @workflow.run
    async def run(self, params: TablePlansParams) -> int:
        plans = await workflow.execute_activity(list_update_table_plans, params, start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not plans:
            if params.failed:
                raise ApplicationError(f"{params.failed} plans failed table reading or indexing",
                                       non_retryable=True)
            return params.done
        common = dict(task_queue="processing-common-queue",
                      search_attributes=dataset_search_attributes(params.collection_dataset))

        async def plan(plan_hash: str):
            durable = workflow.patched("table-update-text-dependencies")
            prepared = await workflow.execute_activity(
                prepare_table_update if durable else reparse_update_tables,
                TablePlanParams(params.op_id, params.collectionname, params.collection_dataset, plan_hash),
                task_queue="processing-common-queue", start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            generations = prepared if durable else {}
            hashes = list(prepared) if durable else prepared
            if not hashes:
                return
            await workflow.execute_activity(
                "resolve_canonical_file_type",
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                 "item_hashes": hashes},
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            async def receipt(stages):
                await workflow.execute_activity(
                    record_table_update_receipts,
                    TableReceiptParams(params.collectionname, params.collection_dataset,
                                       params.op_id, hashes, stages, generations),
                    start_to_close_timeout=timedelta(minutes=10), heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=_RETRY)

            if durable:
                await receipt(["parse", "text"])
                for name, stage in (("ExtractEntitiesForPlan", "entities"),
                                    ("ScanRegexEntitiesForPlan", "regex"), ("ChunkEmbedForPlan", "embed")):
                    await workflow.execute_child_workflow(
                        name,
                        {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                         "plan_hash": plan_hash, "op_id": params.op_id, "item_hashes": hashes,
                         "fail_on_errors": True},
                        id=f"update-tables-{name}-{params.op_id}-{plan_hash}", **common)
                    await receipt([stage])
            await workflow.execute_child_workflow(
                "IndexDatasetPlan",
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                 "plan_hash": plan_hash, "op_id": params.op_id, "item_hashes": hashes,
                 **({"fail_on_errors": True} if durable else {})},
                id=f"update-index-tables-{params.op_id}-{plan_hash}", **common)
            if durable:
                await receipt(["index_text", "index_vectors"])

        results = await run_with_window([lambda h=h: plan(h) for h in plans], VECTOR_PLAN_WINDOW)
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                if is_cancellation(result):
                    raise result
                failed += 1
        workflow.continue_as_new(TablePlansParams(
            params.op_id, params.collectionname, params.collection_dataset,
            plans[-1], params.done + len(plans), params.failed + failed))


@workflow.defn
class UpdateDatasetVirusScan:
    """The antivirus scan of the files that the `virus_scan` step selects, plan by plan.

    The scans run on the antivirus queue, so they share its slots with new ingestion. After
    the last page, `stale_virus_attributes` finds the files whose search rows hold another
    `virus_hit`, and `IndexDatasetPlan` writes those rows again. Pages of at most 100 plans, four at a time, with continue-as-new after each.
    """

    @workflow.run
    async def run(self, params: VirusPlansParams) -> dict:
        plans = await workflow.execute_activity(list_update_virus_plans, params, start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not plans:
            scope = TablePlansParams(params.op_id, params.collectionname, params.collection_dataset)
            stale = await workflow.execute_activity(
                stale_virus_attributes, scope,
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)

            async def reindex(plan_hash: str, hashes: list):
                # Manticore cannot update a columnar attribute, so the rows are written again.
                await workflow.execute_child_workflow(
                    "IndexDatasetPlan",
                    {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                     "plan_hash": plan_hash, "op_id": params.op_id, "item_hashes": hashes},
                    id=f"update-index-virus-{params.op_id}-{plan_hash}", task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset))

            results = await run_with_window([lambda p=p, h=h: reindex(p, h) for p, h in sorted(stale.items())],
                                            VECTOR_PLAN_WINDOW)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            if stale:
                await workflow.execute_activity(
                    retire_cached_searches, scope, task_queue="processing-indexing-queue",
                    start_to_close_timeout=timedelta(minutes=5), heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=_RETRY)
            if params.failed:
                raise ApplicationError(f"{params.failed} plans failed the antivirus scan", non_retryable=True)
            return {"plans": params.done, "reindexed_files": sum(len(h) for h in stale.values())}

        async def plan(plan_hash: str):
            await workflow.execute_activity(
                scan_update_files,
                TablePlanParams(params.op_id, params.collectionname, params.collection_dataset, plan_hash),
                task_queue="processing-clamav-queue", start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)

        results = await run_with_window([lambda h=h: plan(h) for h in plans], VECTOR_PLAN_WINDOW)
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                if is_cancellation(result):
                    raise result
                failed += 1
        workflow.continue_as_new(VirusPlansParams(
            params.op_id, params.collectionname, params.collection_dataset,
            plans[-1], params.done + len(plans), params.failed + failed))


@workflow.defn
class UpdateDatasetOcrDetection:
    """The OCR detection of the files that the `ocr_detection` step selects, plan by plan.

    The requests run on the OCR queue, so they share its slots with new ingestion. After the
    last page, the location refresh rewrites the search rows whose OCR attributes changed.
    Pages of at most 100 plans, four at a time, with continue-as-new after each.
    """

    @workflow.run
    async def run(self, params: VirusPlansParams) -> dict:
        plans = await workflow.execute_activity(
            list_update_detection_plans, params, start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not plans:
            refreshed = await workflow.execute_activity(
                "refresh_stale_document_locations",
                RefreshDocumentLocationsParams(params.collectionname, params.collection_dataset, []),
                result_type=RefreshDocumentLocationsResult,
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            scope = TablePlansParams(params.op_id, params.collectionname, params.collection_dataset)
            if refreshed.refreshed_count:
                await workflow.execute_activity(
                    retire_cached_searches, scope, task_queue="processing-indexing-queue",
                    start_to_close_timeout=timedelta(minutes=5), heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=_RETRY)
            if params.failed:
                raise ApplicationError(f"{params.failed} plans failed OCR detection", non_retryable=True)
            return {"plans": params.done, "refreshed_files": refreshed.refreshed_count}

        async def plan(plan_hash: str):
            await workflow.execute_activity(
                detect_update_files,
                TablePlanParams(params.op_id, params.collectionname, params.collection_dataset, plan_hash),
                task_queue="processing-ocr-queue", start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)

        results = await run_with_window([lambda h=h: plan(h) for h in plans], VECTOR_PLAN_WINDOW)
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                if is_cancellation(result):
                    raise result
                failed += 1
        workflow.continue_as_new(VirusPlansParams(
            params.op_id, params.collectionname, params.collection_dataset,
            plans[-1], params.done + len(plans), params.failed + failed))


@workflow.defn
class UpdateDatasetImagePreviews:
    """Restore missing previews in bounded batches without repeating OCR."""

    @workflow.run
    async def run(self, params: TablePlansParams) -> int:
        count = await workflow.execute_activity(
            restore_missing_image_previews, params, start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if count:
            workflow.continue_as_new(TablePlansParams(params.op_id, params.collectionname,
                params.collection_dataset, done=params.done + count))
        return params.done


@workflow.defn
class UpdateDatasetArchiveMembers:
    """Reconcile split archives, then complete processing of their current members."""

    @workflow.run
    async def run(self, params: TablePlansParams) -> int:
        count = await workflow.execute_activity(
            restore_archive_members, params, start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if count:
            workflow.continue_as_new(TablePlansParams(params.op_id, params.collectionname,
                params.collection_dataset, done=params.done + count))
        common = dict(task_queue="processing-common-queue",
                      search_attributes=dataset_search_attributes(params.collection_dataset))
        await workflow.execute_child_workflow(
            "ComputePlans", {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset},
            id=f"archive-update-plans-{params.op_id}", **common)
        counts = await workflow.execute_child_workflow(
            "ExecutePlans", {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                             "base_temp_dir": "/tmp/hoover4", "op_id": params.op_id},
            id=f"archive-update-process-{params.op_id}", **common)
        if counts.get("failed_plans") or counts.get("failed_dataset_steps"):
            raise ApplicationError("Archive member processing did not complete", non_retryable=True)
        await workflow.execute_activity(
            finish_archive_members, params, start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        return params.done
