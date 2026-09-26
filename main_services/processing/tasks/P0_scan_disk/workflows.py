"""Temporal workflows for recursive disk scanning and ingestion."""

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import Any, Callable, List, Sequence
from dataclasses import dataclass, replace
import asyncio
import hashlib
import json
import logging
log = logging.getLogger(__name__)

# Import our activities, passing them through the sandbox
with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.workflow_window import run_with_window
    from tasks.P0_scan_disk.activities import (
        plan_folder_ranges, scan_folder_range,
        reconcile_deleted_files,
        ListDiskFolderParams, ScanFolderRangeParams,
        ReconcileDeletedFilesParams,
    )
    from tasks.P_admin.rerun_params import ReconcileErrorsParams, SelectErrorsParams
    from tasks.P_admin.rerun_selection import (
        reconcile_selected_errors,
        select_historical_errors,
    )
    from tasks.visibility import dataset_search_attributes


def _child_workflow_id(prefix: str, params: Any) -> str:
    # Stable JSON for hashing. Accepts dicts or dataclass instances.
    try:
        from dataclasses import is_dataclass, asdict
        if is_dataclass(params):
            base = asdict(params)
        elif isinstance(params, dict):
            base = params
        else:
            # Best-effort fallback
            base = getattr(params, "__dict__", {"value": str(params)})
        payload = json.dumps(base, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except Exception:
        payload = json.dumps({"value": str(params)}).encode("utf-8")
    digest = hashlib.md5(payload).hexdigest()[:32]
    return f"{prefix}-{digest}"


RANGE_WINDOW = 8
SUBFOLDER_WINDOW = 16
HISTORY_EVENTS_PER_RUN = 10_000


def _history_budget_reached() -> bool:
    info = workflow.info()
    return (
        info.get_current_history_length() > HISTORY_EVENTS_PER_RUN
        or info.is_continue_as_new_suggested()
    )


async def run_ranges_until_budget(
    ranges: Sequence[tuple[str, str]],
    run_range: Callable[[str, str], Any],
    limit: int,
) -> int:
    """Run a range window and stop after the first observed history budget."""
    started = 0
    pending: List[Any] = []
    index_of = {}
    results: List[Any] = [None] * len(ranges)
    stop_starting = False
    limit = max(1, limit)
    while started < len(ranges) or pending:
        while not stop_starting and started < len(ranges) and len(pending) < limit:
            if started and _history_budget_reached():
                stop_starting = True
                break
            future = asyncio.ensure_future(run_range(*ranges[started]))
            pending.append(future)
            index_of[future] = started
            started += 1
        if not pending:
            break
        done, remaining = await workflow.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        pending = list(remaining)
        for future in sorted(done, key=lambda item: index_of[item]):
            index = index_of.pop(future)
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001 -- preserve range order below.
                results[index] = exc
                stop_starting = True
        if stop_starting and not pending:
            for result in results[:started]:
                if isinstance(result, Exception):
                    raise result
    return started


@dataclass
class HandleFoldersParams:
    collectionname: str
    collection_dataset: str
    dataset_path: str
    folder_path: str
    after_name: str = ""
    container_hash: str = ""
    root_path_prefix: str = ""


@workflow.defn
class HandleFolders:
    """Workflow that scans one folder through bounded name ranges."""
    @workflow.run
    async def run(self, params: HandleFoldersParams) -> str:
        plan = await workflow.execute_activity(
            plan_folder_ranges,
            ListDiskFolderParams(
                params.collectionname, params.collection_dataset, params.dataset_path,
                params.folder_path, params.after_name, params.container_hash,
                params.root_path_prefix,
            ),
            start_to_close_timeout=timedelta(minutes=50),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        edges = [params.after_name] + plan.boundaries
        if not plan.more_after:
            edges.append("")
        ranges = list(zip(edges[:-1], edges[1:]))
        children = asyncio.Semaphore(SUBFOLDER_WINDOW)

        async def one_range(after_name: str, until_name: str) -> None:
            result = await workflow.execute_activity(
                scan_folder_range,
                ScanFolderRangeParams(ListDiskFolderParams(
                    params.collectionname, params.collection_dataset, params.dataset_path,
                    params.folder_path, after_name, params.container_hash,
                    params.root_path_prefix,
                ), until_name),
                start_to_close_timeout=timedelta(hours=6),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )

            def child_factory(folder_path: str):
                async def start_child():
                    async with children:
                        child_params = replace(params, folder_path=folder_path, after_name="")
                        return await workflow.execute_child_workflow(
                            HandleFolders.run,
                            child_params,
                            id=_child_workflow_id("HandleFolders", child_params),
                            task_queue="processing-common-queue",
                            search_attributes=dataset_search_attributes(params.collection_dataset),
                        )
                return start_child

            child_results = await run_with_window(
                [child_factory(folder) for folder in result.subfolders], SUBFOLDER_WINDOW)
            for child_result in child_results:
                if isinstance(child_result, Exception):
                    raise child_result

        started = await run_ranges_until_budget(ranges, one_range, RANGE_WINDOW)
        if started < len(ranges):
            workflow.continue_as_new(replace(params, after_name=ranges[started - 1][1]))
        if plan.more_after:
            workflow.continue_as_new(replace(params, after_name=plan.more_after))
        return f"handled {params.folder_path}"


@dataclass
class IngestDiskDatasetParams:
    collectionname: str
    collection_dataset: str
    dataset_path: str
    op_id: str = ""


@workflow.defn
class IngestDiskDataset:
    """Workflow that starts a recursive disk ingestion from a dataset root."""
    @workflow.run
    async def run(self, params: IngestDiskDatasetParams) -> str:
        log.info("Starting ingestion for %s", params.collection_dataset)
        log.info("Dataset path: %s", params.dataset_path)

        # Read before the walk, never after: every row the walk ingests or touches
        # carries a later `updated_at`, so this is the line that separates "the scan
        # confirmed this path" from "the scan did not find it".
        scan_started_at = int(workflow.now().timestamp())

        # Seed with root folder
        args = HandleFoldersParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            dataset_path=params.dataset_path,
            folder_path="/",
        )
        await workflow.execute_child_workflow(
            HandleFolders.run,
            args,
            task_queue="processing-common-queue",
            id=_child_workflow_id("HandleFolders", args),
            search_attributes=dataset_search_attributes(params.collection_dataset),
        )

        # The walk finished, so it is authoritative for the paths under its root and
        # anything it did not confirm is gone. This runs only after a complete walk: a
        # scan that failed part-way through has confirmed nothing about the paths it
        # never reached, and reconciling on it would delete them.
        removed = await workflow.execute_activity(
            reconcile_deleted_files,
            ReconcileDeletedFilesParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                scan_started_at=scan_started_at,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        log.info("Finished disk ingestion for %s", params.collection_dataset)

        return (f"started ingestion for {params.collection_dataset} "
                f"({removed.tombstoned} paths gone, {removed.deindexed} de-indexed)")


@workflow.defn
class IngestAndProcessDataset:
    """Scan, plan and execute, in that order, for a newly created dataset.

    `IngestDiskDataset` alone only walks the disk. The plan stages after it are separate
    workflows because they must not start until the scan has finished. Computing plans
    over a half-scanned dataset silently plans a subset of the files.

    This workflow sequences the three stages on the server, for the admin UI and for
    `main.py add-disk-dataset` alike, through the `Operation` workflow. The CLI only
    follows the operation, for one minute by default, so a dataset is *processed* rather
    than merely scanned and left sitting there looking finished.
    """

    @workflow.run
    async def run(self, params: IngestDiskDatasetParams) -> str:
        with workflow.unsafe.imports_passed_through():
            from tasks.P1_compute_plans.activities import ComputePlansParams
            from tasks.P1_compute_plans.workflows import ComputePlans
            from tasks.P2_execute_plan.workflows import ExecutePlans, ExecutePlansParams

        attributes = dataset_search_attributes(params.collection_dataset)

        # Children are keyed on the parent's RUN, not on the dataset. A fixed
        # `<stage>-<dataset>` id collides with the same stage of a run that is still
        # alive, so starting a second ingest of a dataset while the first is running
        # fails on the child rather than doing the work. The run id is the one
        # identifier that is unique per run and stable across replay, which is what a
        # child workflow id has to be.
        run = workflow.info().run_id

        await workflow.execute_child_workflow(
            IngestDiskDataset.run,
            params,
            id=f"ingest-disk-{params.collection_dataset}-{run}",
            task_queue="processing-common-queue",
            search_attributes=attributes,
        )
        await workflow.execute_child_workflow(
            ComputePlans.run,
            ComputePlansParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
            ),
            id=f"compute-plans-{params.collection_dataset}-{run}",
            task_queue="processing-common-queue",
            search_attributes=attributes,
        )
        if params.op_id:
            selection = await workflow.execute_activity(
                select_historical_errors,
                SelectErrorsParams(
                    op_id=params.op_id,
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                ),
                task_queue="processing-common-queue",
                start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
        await workflow.execute_child_workflow(
            ExecutePlans.run,
            ExecutePlansParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                base_temp_dir="/tmp/hoover4",
                op_id=params.op_id,
            ),
            id=f"execute-plans-{params.collection_dataset}-{run}",
            task_queue="processing-common-queue",
            search_attributes=attributes,
        )
        if params.op_id:
            reconciliation = await workflow.execute_activity(
                reconcile_selected_errors,
                ReconcileErrorsParams(
                    op_id=params.op_id,
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                ),
                task_queue="processing-common-queue",
                start_to_close_timeout=timedelta(minutes=60),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
            return {
                "message": f"ingested and processed {params.collection_dataset}",
                "selector_counts": {
                    "errors_before_run": selection.errors_before_run,
                    "selected_errors": selection.selected_errors,
                    "removed_stage_off_errors": selection.removed_stage_off_errors,
                    "without_plan_errors": selection.without_plan_errors,
                    **reconciliation,
                },
            }
        return f"ingested and processed {params.collection_dataset}"
