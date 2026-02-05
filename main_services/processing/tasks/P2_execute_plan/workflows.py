from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
import traceback
import math
import asyncio
import logging
from dataclasses import dataclass

from tasks.P3_parse_files.workflows import ParseSingleFileParams

log = logging.getLogger(__name__)


# Import activities and sibling workflows through the sandbox
with workflow.unsafe.imports_passed_through():
    from tasks.P2_execute_plan.activities import (
        list_pending_plans,
        get_plan_items_metadata,
        download_plan_files,
        cleanup_plan_dir,
        mark_plan_finished,
        ensure_temp_dir_exists,
        record_processing_errors,
        ListPendingPlansParams,
        GetPlanItemsMetadataParams,
        DownloadPlanFilesParams,
        CleanupPlanDirParams,
        EnsureTempDirExistsParams,
        MarkPlanFinishedParams,
    )
    from tasks.P1_compute_plans.activities import count_new_blobs, CountNewBlobsParams
    from tasks.P1_compute_plans.workflows import ComputePlans
    from tasks.P3_parse_files.workflows import ParseSingleFile
    from tasks.P3_parse_files.parse_common import record_errors_from_results
    from tasks.P4_index_data.workflows import IndexDatasetPlan, IndexDatasetPlanParams


@dataclass
class ExecutePlansParams:
    collection_dataset: str
    base_temp_dir: str
    starting_plan_hash: str | None = None
    recursivity_depth: int | None = None


@workflow.defn
class ExecutePlans:
    """Workflow that enumerates pending plans and runs them in batches."""
    @workflow.run
    async def run(self, params: ExecutePlansParams) -> str:
        recursivity_depth: int = int(params.recursivity_depth or 0)

        if recursivity_depth > 100:
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(
                f"recursivity_depth too large: {recursivity_depth}", non_retryable=True
            )

        # Ensure temp dir exists
        await workflow.execute_activity(
            ensure_temp_dir_exists,
            EnsureTempDirExistsParams(base_temp_dir=params.base_temp_dir),
            start_to_close_timeout=timedelta(minutes=12),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 1) Fetch up to 1001 plan hashes (to know if we need to execute_as_new)
        plan_hashes = await workflow.execute_activity(
            list_pending_plans,
            ListPendingPlansParams(collection_dataset=params.collection_dataset, starting_plan_hash=(params.starting_plan_hash or "")),
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not plan_hashes:
            # Check if there are new unplanned blobs; if so, compute more plans and restart
            count = await workflow.execute_activity(
                count_new_blobs,
                CountNewBlobsParams(collection_dataset=params.collection_dataset),
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if count:
                await workflow.execute_child_workflow(
                    ComputePlans.run,
                    {"collection_dataset": params.collection_dataset},
                    id=f"compute-plans-{params.collection_dataset}",
                    task_queue="processing-common-queue",
                )
                # execute_as_new with no starting hash
                return await workflow.execute_child_workflow(
                    ExecutePlans.run,
                    {
                        "collection_dataset": params.collection_dataset,
                        "starting_plan_hash": None,
                        "base_temp_dir": params.base_temp_dir,
                        "recursivity_depth": recursivity_depth + 1,
                    },
                    id=f"execute-plans-{params.collection_dataset}-restart",
                    task_queue="processing-common-queue",
                )
            log.info(f"[P2] No plans to execute")
            return "no plans"

        # 2) If more than 1000, keep the 101st for continuation
        continuation_hash = None
        if len(plan_hashes) > 1000:
            continuation_hash = plan_hashes[1000]
            plan_hashes = plan_hashes[:1000]
            log.info(f"[P2] Continuation hash: {continuation_hash}")

        # 3) Run per-plan child workflows, in parallel batches of 16
        CONCURRENCY = 16
        for i in range(0, len(plan_hashes), CONCURRENCY):
            batch = plan_hashes[i:i + CONCURRENCY]
            futs = []
            for ph in batch:
                futs.append(
                    workflow.execute_child_workflow(
                        ExecuteSinglePlan.run,
                        {"collection_dataset": params.collection_dataset, "plan_hash": ph, "base_temp_dir": params.base_temp_dir},
                        id=f"execute-plan-{params.collection_dataset}-{ph}",
                        task_queue="processing-common-queue",
                    )
                )
            if futs:
                await asyncio.gather(*futs)

        if continuation_hash:
            # Use execute_as_new semantics by re-invoking ourselves fresh via child
            return await workflow.execute_child_workflow(
                ExecutePlans.run,
                {
                    "collection_dataset": params.collection_dataset,
                    "starting_plan_hash": continuation_hash,
                    "base_temp_dir": params.base_temp_dir,
                    "recursivity_depth": recursivity_depth + 1,
                },
                id=f"execute-plans-{params.collection_dataset}-cont-{continuation_hash}",
                task_queue="processing-common-queue",
            )

        # After finishing this batch, check for newly created blobs -> compute new plans and restart
        count = await workflow.execute_activity(
            count_new_blobs,
            CountNewBlobsParams(collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if count:
            await workflow.execute_child_workflow(
                ComputePlans.run,
                {"collection_dataset": params.collection_dataset},
                id=f"compute-plans-{params.collection_dataset}",
                task_queue="processing-common-queue",
            )
            try:
                return await workflow.execute_child_workflow(
                    ExecutePlans.run,
                    {
                        "collection_dataset": params.collection_dataset,
                        "starting_plan_hash": None,
                        "base_temp_dir": params.base_temp_dir,
                        "recursivity_depth": recursivity_depth + 1,
                    },
                    id=f"execute-plans-{params.collection_dataset}-restart-{recursivity_depth+1}",
                    task_queue="processing-common-queue",
                )
            except Exception as e:
                log.error(f"[P2] Error executing restart plans: {e}")
                return f"error executing restart plans: {e}"

        return f"executed {len(plan_hashes)} plans"


@dataclass
class ExecuteSinglePlanParams:
    collection_dataset: str
    plan_hash: str
    base_temp_dir: str


@workflow.defn
class ExecuteSinglePlan:
    """Workflow that downloads plan files, processes them, and finalizes."""
    @workflow.run
    async def run(self, params: ExecuteSinglePlanParams) -> str:
        log.info(f"[P2] Executing {params.plan_hash}")

        # 1) Join metadata
        items = await workflow.execute_activity(
            get_plan_items_metadata,
            GetPlanItemsMetadataParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # Compute total size for dynamic timeouts
        total_bytes = 0
        try:
            for it in items:
                total_bytes += int(it["file_size_bytes"])
        except Exception:
            total_bytes = 0

        # Speeds in bytes/sec assuming kbps = kilobits per second
        BPS_100_K = 100_000 // 8  # 12_500
        BPS_10_K = 10_000 // 8    # 1_250

        # Download timeout: 900s base + time at 100 kbps
        dl_secs = 900 + math.ceil(total_bytes / BPS_100_K)

        # 2) Download locally (TODO: pin activity to worker)
        dl = await workflow.execute_activity(
            download_plan_files,
            DownloadPlanFilesParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, items=items, base_temp_dir=params.base_temp_dir),
            start_to_close_timeout=timedelta(seconds=dl_secs),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 3) Process downloaded files via batched child workflow
        await workflow.execute_child_workflow(
            ProcessItemsBatched.run,
            ProcessItemsBatchedParams(
                collection_dataset=params.collection_dataset,
                plan_hash=params.plan_hash,
                out_dir=dl.get("out_dir"),
                items=items,
            ),
            id=f"process-batches-{params.collection_dataset}-{params.plan_hash}",
            task_queue="processing-common-queue",
        )

        # Delete timeout: time at 100 kbps
        del_secs = 900+math.ceil(total_bytes / BPS_100_K)

        # 4) Cleanup (TODO: pin activity to worker)
        await workflow.execute_activity(
            cleanup_plan_dir,
            CleanupPlanDirParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, base_temp_dir=params.base_temp_dir),
            start_to_close_timeout=timedelta(seconds=del_secs),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        await workflow.execute_child_workflow(
            IndexDatasetPlan.run,
            IndexDatasetPlanParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            id=f"index-dataset-plan-{params.collection_dataset}-{params.plan_hash}",
            task_queue="processing-common-queue",
        )

        # 5) Mark finished (global activity)
        await workflow.execute_activity(
            mark_plan_finished,
            MarkPlanFinishedParams(collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=25),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        log.info(f"[P2] Finished plan {params.collection_dataset} {params.plan_hash}")

        return f"finished {params.plan_hash}"


@dataclass
class ProcessItemsBatchedParams:
    collection_dataset: str
    plan_hash: str
    out_dir: str
    items: list


@workflow.defn
class ProcessItemsBatched:
    """Workflow that spawns per-file child workflows in parallel."""
    @workflow.run
    async def run(self, params: ProcessItemsBatchedParams) -> str:
        if not params.items:
            return "no items"

        # Spawn child workflows in parallel batches of up to 32
        CONCURRENCY = 32
        processed = 0
        for i in range(0, len(params.items), CONCURRENCY):
            batch = params.items[i:i + CONCURRENCY]
            futs = []
            starts = []
            item_hashes = []
            for it in batch:
                args = ParseSingleFileParams(
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    item_hash=it.get('item_hash'),
                    file_path=f"{params.out_dir}/{it.get('item_hash')}",
                    file_size_bytes=it.get('file_size_bytes'),
                )
                futs.append(
                    workflow.execute_child_workflow(
                        ParseSingleFile.run,
                        args,
                        id=f"parse-file-{params.collection_dataset}-{params.plan_hash}-{it.get('item_hash')}",
                        task_queue="processing-common-queue",
                    )
                )
                starts.append(workflow.now())
                item_hashes.append((it.get("item_hash") or "") if isinstance(it, dict) else "")

            results = await asyncio.gather(*futs, return_exceptions=True)
            await record_errors_from_results(
                results,
                task_ids=["P3_ParseSingleFile"] * len(batch),
                starts=starts,
                collection_dataset=params.collection_dataset,
                item_hashes=item_hashes,
            )
            processed += len(batch)

        return f"processed {processed} items"


