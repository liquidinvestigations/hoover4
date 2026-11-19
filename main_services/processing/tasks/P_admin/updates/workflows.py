"""The processing update coordinator and the workflow of one update operation.

`ProcessingUpdates` is a singleton (id `processing-updates`). The worker starts it at
bootstrap with `USE_EXISTING`, and the website starts it with a signal when it is closed,
so a closed coordinator returns on the next worker start or settings save. Its state is
in the database, not in its history: a new run reads the live update operations and the
stored checks, so it never repeats a completed step.

Each pass runs `check_processing_updates`. A pass that finds no change writes no row and
starts no operation, so a deployment that changes no version, setting or input starts
no update operation. A coordinator that starts is not an update run. The coordinator
starts one automatic operation for each track of a dataset (`registry.py`), collection
prerequisites first. It starts an operation only while the cap class of the operation has
a free slot, so each track uses its own slots, and at most one operation of a dataset is
live at a time. Candidates of one class take turns by dataset, so one dataset with much
work does not keep the others waiting. A failed or cancelled step does not start again
automatically at the same fingerprint, so later datasets continue. A coordinator run that
started before the tracks (patch `TRACKS_PATCH`) keeps one automatic operation at a time.

It waits `IDLE_WAIT` between passes, `ACTIVE_WAIT` while an operation runs, and wakes
at once on a `request_check` signal, which a settings save and a page request send. It
continues as new after `PASSES_PER_RUN` passes. Its state names the live operations that
it started. A new run reads the live automatic operations from the database again and
starts the workflow of a row that stays `pending`, for example when the coordinator
stopped between the insert of the row and the start of its workflow.

`RunProcessingUpdate` is the child of an `update_dataset` or `update_collection`
operation. It snapshots the requested steps, then runs each step in registry order:
record the attempt, run the work, verify the output, record the applied fingerprint. A
step that fails is recorded and the next step runs. The operation errors when a step
failed.
"""

import asyncio
import dataclasses
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
        list_update_text_row_plans,
        list_update_virus_plans,
        retire_cached_searches,
        stale_virus_attributes,
        stale_virus_plan_hashes,
        list_virus_attribute_plans,
        scan_update_files,
        list_update_vector_plans,
        obsolete_ocr_variants,
        operation_start_params,
        reparse_update_tables,
        restore_missing_image_previews,
        prepare_table_update,
        refresh_update_checks,
        report_update_progress,
        settle_update_step,
        snapshot_processing_update,
        submit_automatic_update,
        update_operation_state,
        update_windows,
        verify_update_vector_plan,
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
    from tasks.P_admin.updates.entities import EntityUpdateParams, list_entity_update_hashes, finish_entity_update
    from tasks.P_admin.updates.registry import PROFILE_TRACKS, SCOPE_DATASET, STEPS
    from tasks.P6_index_data.params import RefreshDocumentLocationsParams, RefreshDocumentLocationsResult
    from tasks.visibility import dataset_search_attributes
    from tasks.workflow_window import run_with_window

COORDINATOR_ID = "processing-updates"
#: The patch of the coordinator run that starts one operation for each track.
TRACKS_PATCH = "processing-update-tracks"
#: The live operations that one coordinator state can name.
MAX_ACTIVE_OPS = 64
IDLE_WAIT = timedelta(minutes=2)
ACTIVE_WAIT = timedelta(seconds=30)
PASSES_PER_RUN = 200
VECTOR_PLAN_WINDOW = 4
_TERMINAL = ("finished", "errored", "cancelled", "missing")
_RETRY = RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS)
#: The policy of an activity that `with_remote_outage_retry` wraps. The wrapper ends the
#: retries at the ordinary failure limit or at the end of the outage budget.
_REMOTE_RETRY = RetryPolicy(maximum_attempts=0)


@dataclass
class CoordinatorState:
    #: The automatic update operation of a run before the tracks. A tracks run moves it
    #: into `active_ops`.
    active_op: str = ""
    #: Check requests that arrived before a continue-as-new.
    requests: list = field(default_factory=list)
    #: The live automatic operations that this coordinator started, at most `MAX_ACTIVE_OPS`.
    active_ops: list = field(default_factory=list)
    #: The scope id that each cap class started last. The next pass starts after it.
    cursors: dict = field(default_factory=dict)
    #: Pending rows that this run tried to start once, so it tries each one once.
    restarted: list = field(default_factory=list)


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
        if workflow.patched(TRACKS_PATCH):
            return await self._tracks(state)
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

    async def _tracks(self, state: CoordinatorState) -> str:
        """The passes of a coordinator that starts one operation for each track."""
        if state.active_op:
            state.active_ops = [*state.active_ops, state.active_op]
            state.active_op = ""
        for _ in range(PASSES_PER_RUN):
            forced = sorted({str(r.get("scope_id") or "*") for r in self._requests if r.get("force")})
            self._requests = []
            result = None
            try:
                result = await workflow.execute_activity(
                    check_processing_updates, CheckUpdatesParams(forced, tracks=True),
                    start_to_close_timeout=timedelta(minutes=60),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=RetryPolicy(maximum_attempts=3))
            except ActivityError as exc:
                if is_cancellation(exc):
                    raise
                workflow.logger.warning("processing update check failed: %s", exc)
            if result is not None:
                await self._reconcile(state, result.live)
                if result.automatic:
                    await self._submit(state, result)
            wait = ACTIVE_WAIT if state.active_ops else IDLE_WAIT
            try:
                await workflow.wait_condition(lambda: bool(self._requests), timeout=wait)
            except asyncio.TimeoutError:
                pass
        state.requests = list(self._requests)
        workflow.continue_as_new(state)

    async def _reconcile(self, state: CoordinatorState, live: dict) -> None:
        """Keep the live operations, and start a row that waits without its workflow.

        A row that this state does not name and that is still `pending` lost its start,
        for example when a coordinator stopped after the insert. `_start` of a workflow
        that exists changes nothing. Each such row gets one start in a run.
        """
        state.active_ops = [op for op in state.active_ops if op in live]
        for op_id, row_state in sorted(live.items()):
            if op_id in state.active_ops or len(state.active_ops) >= MAX_ACTIVE_OPS:
                continue
            if row_state == "pending" and op_id not in state.restarted:
                state.restarted = [*state.restarted[-(MAX_ACTIVE_OPS - 1):], op_id]
                await self._start_row(op_id)
            state.active_ops.append(op_id)

    async def _submit(self, state: CoordinatorState, result) -> None:
        """Start candidates while their cap class has a free slot, one for each scope."""
        free = dict(result.capacity)
        taken = set()
        for candidate in self._ordered(state, result.candidates):
            name = cap_class_of(candidate)
            if free.get(name, 0) <= 0 or candidate.scope_id in taken:
                continue
            if len(state.active_ops) >= MAX_ACTIVE_OPS:
                break
            kind = "update_dataset" if candidate.scope_kind == SCOPE_DATASET else "update_collection"
            stamp = int(workflow.now().timestamp() * 1_000_000)
            op_id = f"{kind}-{candidate.scope_id}-{stamp}-{workflow.uuid4().hex[:12]}"
            outcome = await workflow.execute_activity(
                submit_automatic_update, SubmitUpdateParams(op_id, candidate),
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            status, _, named = outcome.partition(":")
            if status == "held":
                continue
            taken.add(candidate.scope_id)
            if status == "started":
                await self._start(candidate, named)
                free[name] -= 1
                state.cursors = {**state.cursors, name: candidate.scope_id}
            if named not in state.active_ops:
                state.active_ops.append(named)

    @staticmethod
    def _ordered(state: CoordinatorState, candidates: list) -> list:
        """Collections first. Each class then starts after the scope that it started last."""
        def key(candidate):
            cursor = state.cursors.get(cap_class_of(candidate), "")
            first = STEP_ORDER[candidate.steps[0]] if candidate.steps else 0
            return (candidate.scope_kind == SCOPE_DATASET, candidate.scope_id <= cursor,
                    candidate.scope_id, first)
        return sorted(candidates, key=key)

    async def _start_row(self, op_id: str) -> None:
        """Start the `Operation` workflow of a stored row, from the row's own values."""
        params = await workflow.execute_activity(
            operation_start_params, op_id, start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if params:
            await self._start_child(op_id, params)

    async def _start(self, candidate, op_id: str) -> None:
        """Start the `Operation` child, which outlives this run (`ABANDON`)."""
        detail = {"steps": list(candidate.steps),
                  "fingerprints": dict(candidate.fingerprints), "automatic": True}
        if getattr(candidate, "track", ""):
            detail.update(track=candidate.track, profile=PROFILE_TRACKS)
        await self._start_child(op_id, {
            "op_id": op_id,
            "kind": "update_dataset" if candidate.scope_kind == SCOPE_DATASET else "update_collection",
            "collectionname": candidate.collectionname,
            "collection_dataset": candidate.collection_dataset,
            "detail": detail})

    async def _start_child(self, op_id: str, params: dict) -> None:
        try:
            await workflow.start_child_workflow(
                "Operation", params,
                id=op_id, task_queue="operations-queue",
                parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
        except WorkflowAlreadyStartedError:
            workflow.logger.info("operation %s started earlier", op_id)


#: The run order of each step, for the order of candidates.
STEP_ORDER = {step.step_id: index for index, step in enumerate(STEPS)}


def cap_class_of(candidate) -> str:
    """The cap class of a candidate: `update_<track>`, or `update_collection`."""
    if candidate.scope_kind != SCOPE_DATASET:
        return "update_collection"
    return f"update_{candidate.track}" if candidate.track else "update_dataset"


@workflow.defn
class RunProcessingUpdate:
    """The steps of one update operation. See the module docstring."""

    def __init__(self) -> None:
        #: The recorded windows of a tracked operation (`update_windows`). Empty for a
        #: legacy operation, whose children keep their constant windows.
        self._windows: dict = {}

    @workflow.run
    async def run(self, params: RunUpdateParams) -> dict:
        snapshot = await workflow.execute_activity(snapshot_processing_update, params, start_to_close_timeout=timedelta(minutes=60),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if params.profile == PROFILE_TRACKS:
            self._windows = await workflow.execute_activity(
                update_windows, start_to_close_timeout=timedelta(minutes=2),
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

    def _ocr_profile(self, params: RunUpdateParams) -> dict:
        """The `RerunOcr` input of a tracked operation: no NER or embedding, its OCR window.

        A legacy operation adds nothing, so its input stays as it was.
        """
        if params.profile != PROFILE_TRACKS:
            return {}
        return {"separated": True, "ocr_window": self._window(params, "ocr")}

    def _window(self, params: RunUpdateParams, name: str) -> int:
        """The recorded window of a tracked operation, or 0 for the constant of a legacy one."""
        return int(self._windows.get(name, 0)) if params.profile == PROFILE_TRACKS else 0

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
                                  str(detail.get("model", "")),
                                  verify=workflow.patched("vector-update-verify"),
                                  window=self._window(params, "embed")),
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
        if step_id == "entities":
            done = await workflow.execute_child_workflow(
                UpdateDatasetEntities.run,
                EntityUpdateParams(params.collectionname, params.collection_dataset, params.op_id,
                                   window=self._window(params, "ner")),
                id=f"update-entities-{params.op_id}", **self._child(params))
            return f"updated named entities for {done} files"
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
        if step_id == "text_rows":
            done = await workflow.execute_child_workflow(
                UpdateDatasetTextRows.run,
                TablePlansParams(params.op_id, params.collectionname, params.collection_dataset),
                id=f"update-text-rows-{params.op_id}", **self._child(params))
            return f"split the text of {done} plans again"
        if step_id == "page_text":
            done = await workflow.execute_activity(
                "rewrite_page_text",
                EntityUpdateParams(params.collectionname, params.collection_dataset, params.op_id),
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=RetryPolicy(maximum_attempts=2))
            return f"indexed text replaced in {done} files"
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
        automatic = workflow.patched("automatic-ocr-v1")
        arguments = {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                     "op_id": params.op_id, **self._ocr_profile(params)}
        if automatic:
            arguments["automatic_mode"] = "languages" not in json.loads(step.step.detail or "{}")
        result = await workflow.execute_child_workflow(
            "RerunOcr", arguments,
            id=f"update-ocr-{params.op_id}", **self._child(params))
        if automatic and arguments["automatic_mode"]:
            return json.dumps(result, sort_keys=True)
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
                 "op_id": params.op_id, **self._ocr_profile(params)},
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
            if params.verify:
                await workflow.execute_activity(
                    verify_update_vector_plan,
                    TablePlanParams(params.op_id, params.collectionname, params.collection_dataset, plan_hash),
                    task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)

        results = await run_with_window([lambda h=h: plan(h) for h in plans],
                                        params.window or VECTOR_PLAN_WINDOW)
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                if is_cancellation(result):
                    raise result
                failed += 1
        workflow.continue_as_new(VectorPlansParams(
            params.op_id, params.collectionname, params.collection_dataset, params.model,
            plans[-1], params.done + len(plans), params.failed + failed, params.verify, params.window))


@workflow.defn
class UpdateDatasetTextRows:
    """Split stored text again, then run the stages that read the text rows.

    Pages of at most 100 plans, four at a time, with continue-as-new after each page.
    """

    @workflow.run
    async def run(self, params: TablePlansParams) -> int:
        plans = await workflow.execute_activity(list_update_text_row_plans, params, start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not plans:
            if params.failed:
                raise ApplicationError(f"{params.failed} plans failed the text split or its stages",
                                       non_retryable=True)
            return params.done
        common = dict(task_queue="processing-common-queue",
                      search_attributes=dataset_search_attributes(params.collection_dataset))

        async def plan(plan_hash: str):
            await workflow.execute_activity(
                "rewrite_text_rows",
                TablePlanParams(params.op_id, params.collectionname, params.collection_dataset, plan_hash),
                task_queue="processing-common-queue", start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            child = {"collectionname": params.collectionname,
                     "collection_dataset": params.collection_dataset,
                     "plan_hash": plan_hash, "op_id": params.op_id}
            await asyncio.gather(*(
                workflow.execute_child_workflow(name, child, id=f"update-text-{stage}-{params.op_id}-{plan_hash}", **common)
                for name, stage in (("ExtractEntitiesForPlan", "entities"), ("ScanRegexEntitiesForPlan", "regex"),
                                    ("ChunkEmbedForPlan", "embed"))))
            await workflow.execute_child_workflow(
                "IndexDatasetPlan", child, id=f"update-text-index-{params.op_id}-{plan_hash}", **common)

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
    the last page, the attribute pages compare the search rows of each plan with the verdicts.
    `stale_virus_plan_hashes` finds the files of one plan whose search rows hold another
    `virus_hit`, and `IndexDatasetPlan` writes those rows again. Pages of at most 100 plans,
    four at a time, with continue-as-new after each.
    """

    @workflow.run
    async def run(self, params: VirusPlansParams) -> dict:
        if params.attributes:
            return await self._attribute_page(params)
        plans = await workflow.execute_activity(list_update_virus_plans, params, start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not plans and workflow.patched("virus-attribute-pages"):
            return await self._attribute_page(dataclasses.replace(params, attributes=True))
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

    async def _attribute_page(self, params: VirusPlansParams) -> dict:
        """Write the search rows of the stale files of at most 100 plans again."""
        plans = await workflow.execute_activity(
            list_virus_attribute_plans, params, start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not plans:
            if params.reindexed:
                await workflow.execute_activity(
                    retire_cached_searches, TablePlansParams(params.op_id, params.collectionname, params.collection_dataset),
                    task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            if params.failed:
                raise ApplicationError(f"{params.failed} plans failed the antivirus scan", non_retryable=True)
            return {"plans": params.done, "reindexed_files": params.reindexed}

        async def reindex(plan_hash: str) -> int:
            hashes = await workflow.execute_activity(
                stale_virus_plan_hashes,
                TablePlanParams(params.op_id, params.collectionname, params.collection_dataset, plan_hash),
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            if hashes:
                # Manticore cannot update a columnar attribute, so the rows are written again.
                await workflow.execute_child_workflow(
                    "IndexDatasetPlan",
                    {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset,
                     "plan_hash": plan_hash, "op_id": params.op_id, "item_hashes": hashes},
                    id=f"update-index-virus-{params.op_id}-{plan_hash}", task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset))
            return len(hashes)

        results = await run_with_window([lambda h=h: reindex(h) for h in plans], VECTOR_PLAN_WINDOW)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        workflow.continue_as_new(dataclasses.replace(
            params, attributes=True, stale_after=plans[-1], reindexed=params.reindexed + sum(results)))


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


#: Files in one NER batch of an entity update.
ENTITY_UPDATE_BATCH = 100
#: Batches that one entity update run lists before it continues as new.
ENTITY_UPDATE_BATCHES_PER_RUN = 16
#: Batches in flight at once in a legacy operation. A tracked operation records its own
#: window (`update_windows`).
ENTITY_UPDATE_WINDOW = 4


@workflow.defn
class UpdateDatasetEntities:
    """Rewrite bounded NER pages without repeating regex or embedding work."""
    @workflow.run
    async def run(self, params: EntityUpdateParams) -> int:
        if workflow.patched("entity-update-window"):
            return await self._windowed(params)
        hashes = await workflow.execute_activity(list_entity_update_hashes, params,
            start_to_close_timeout=timedelta(minutes=10), heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        terms_at_end = workflow.patched("entity-terms-at-end")
        if not hashes:
            if terms_at_end:
                await workflow.execute_activity("finish_entity_terms",
                    EntityUpdateParams(params.collectionname,params.collection_dataset,params.op_id),
                    task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            return params.done
        await workflow.execute_activity("extract_entities_for_hashes",
            {"collectionname":params.collectionname,"collection_dataset":params.collection_dataset,
             "plan_hash":"entity-update","hashes":hashes,"op_id":params.op_id},
            task_queue="processing-nlp-queue", start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_REMOTE_RETRY)
        await workflow.execute_activity(finish_entity_update,
            EntityUpdateParams(params.collectionname,params.collection_dataset,params.op_id,hashes,
                               terms_at_end=terms_at_end),
            task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        workflow.continue_as_new(EntityUpdateParams(params.collectionname,params.collection_dataset,
            params.op_id,after=hashes[-1],done=params.done + len(hashes)))

    async def _windowed(self, params: EntityUpdateParams) -> int:
        """Run batches of 100 files with up to `window` (else `ENTITY_UPDATE_WINDOW`) in flight.

        One batch at a time left the GPU idle while a batch read text and saved results.
        Each batch writes the rows of its own files only. The dataset terms follow the last batch.
        """
        from tasks.workflow_window import run_with_window
        listed = dataclasses.replace(params, limit=ENTITY_UPDATE_BATCH * ENTITY_UPDATE_BATCHES_PER_RUN)
        hashes = await workflow.execute_activity(list_entity_update_hashes, listed,
            start_to_close_timeout=timedelta(minutes=10), heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
        if not hashes:
            await workflow.execute_activity("finish_entity_terms",
                EntityUpdateParams(params.collectionname,params.collection_dataset,params.op_id),
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)
            return params.done

        async def batch(chunk):
            await workflow.execute_activity("extract_entities_for_hashes",
                {"collectionname":params.collectionname,"collection_dataset":params.collection_dataset,
                 "plan_hash":"entity-update","hashes":chunk,"op_id":params.op_id},
                task_queue="processing-nlp-queue", start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_REMOTE_RETRY)
            await workflow.execute_activity(finish_entity_update,
                EntityUpdateParams(params.collectionname,params.collection_dataset,params.op_id,chunk,terms_at_end=True),
                task_queue="processing-indexing-queue", start_to_close_timeout=timedelta(minutes=30),
                heartbeat_timeout=HEARTBEAT_TIMEOUT, retry_policy=_RETRY)

        chunks = [hashes[start:start + ENTITY_UPDATE_BATCH] for start in range(0, len(hashes), ENTITY_UPDATE_BATCH)]
        results = await run_with_window([lambda chunk=chunk: batch(chunk) for chunk in chunks],
                                        params.window or ENTITY_UPDATE_WINDOW)
        for result in results:
            if isinstance(result, BaseException):
                raise result
        workflow.continue_as_new(EntityUpdateParams(params.collectionname,params.collection_dataset,
            params.op_id,after=hashes[-1],done=params.done + len(hashes),window=params.window))
