"""Workflows for executing processing plans and per-file parsing tasks."""

from temporalio import workflow
from temporalio.common import RetryPolicy
from datetime import timedelta
import traceback
import math
import asyncio
import logging
from dataclasses import dataclass

from tasks.P3_parse_files.workflows import ParseSingleFileParams
from tasks.workflow_window import run_with_window

log = logging.getLogger(__name__)

# How many per-item results one `record_processing_errors` activity carries. The rows
# are small and mostly absent; the point of the chunk is to keep a single insert off a
# plan-sized list, not to bound anything the workflow does.
ERROR_REPORT_CHUNK = 500

# Items one `ProcessItemsBatched` run covers before continuing as new. Each item is a
# child workflow, and each child workflow is a handful of events on this execution's
# history; the 51,200-event cap is a hard failure of the whole plan, not a slowdown.
MAX_ITEMS_PER_RUN = 2000

# Items one `ProcessItemsBatched` execution drives. A plan is split into groups of this
# size and the groups run as siblings, because a single workflow execution decides one
# thing at a time and a per-file chain is a dozen decisions deep -- one driver is a
# latency ceiling, not a capacity one. Small enough that a plan of any realistic size
# gets several drivers; large enough that the drivers themselves stay a rounding error
# against the files they carry.
PLAN_GROUP_SIZE = 100

# Sibling drivers one plan may run at once. Each drives a 32-file window, so this is
# also the bound on files in flight per plan -- without it a large corpus multiplies
# plans in flight by groups by window and puts thousands of executions on the server at
# once, which is a different failure from the one the siblings fix.
MAX_PLAN_DRIVERS = 8


# Import activities and sibling workflows through the sandbox
with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
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
    from tasks.P3_parse_files.document_dates import (
        resolve_document_dates,
        ResolveDocumentDatesParams,
    )
    from tasks.P4_extract_entities.workflows import (
        ExtractEntitiesForPlan,
        ExtractEntitiesForPlanParams,
        ScanRegexEntitiesForPlan,
        ScanRegexEntitiesForPlanParams,
    )
    from tasks.P5_chunk_embed.workflows import ChunkEmbedForPlan, ChunkEmbedForPlanParams
    from tasks.P6_index_data.workflows import (
        INDEXING_TASK_QUEUE,
        IndexDatasetPlan,
        IndexDatasetPlanParams,
    )
    from tasks.P6_index_data.activities import (
        build_vfs_nodes,
        index_entity_terms,
        index_vfs_structure,
        resolve_canonical_file_type,
    )
    from tasks.P6_index_data.params import BuildVfsNodesParams, ResolveCanonicalFileTypeParams
    from tasks.visibility import dataset_search_attributes


@dataclass
class ExecutePlansParams:
    collectionname: str
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
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        # 1) Fetch up to 1001 plan hashes (to know if we need to execute_as_new)
        plan_hashes = await workflow.execute_activity(
            list_pending_plans,
            ListPendingPlansParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, starting_plan_hash=(params.starting_plan_hash or "")),
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        if not plan_hashes:
            # Check if there are new unplanned blobs; if so, compute more plans and restart
            count = await workflow.execute_activity(
                count_new_blobs,
                CountNewBlobsParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
                start_to_close_timeout=timedelta(minutes=15),
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            )
            if count:
                await workflow.execute_child_workflow(
                    ComputePlans.run,
                    {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset},
                    id=f"compute-plans-{params.collection_dataset}",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )
                # execute_as_new with no starting hash
                return await workflow.execute_child_workflow(
                    ExecutePlans.run,
                    {
                        "collectionname": params.collectionname,
                        "collection_dataset": params.collection_dataset,
                        "starting_plan_hash": None,
                        "base_temp_dir": params.base_temp_dir,
                        "recursivity_depth": recursivity_depth + 1,
                    },
                    id=f"execute-plans-{params.collection_dataset}-restart",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )
            log.info(f"[P2] No plans to execute")
            return "no plans"

        # 2) If more than 1000, keep the 101st for continuation
        continuation_hash = None
        if len(plan_hashes) > 1000:
            continuation_hash = plan_hashes[1000]
            plan_hashes = plan_hashes[:1000]
            log.info(f"[P2] Continuation hash: {continuation_hash}")

        # Dataset-scoped tree, once per ExecutePlans invocation, before any per-plan
        # writer. document_metadata builds ancestor closures from ClickHouse vfs_nodes,
        # so those writers must not run against an empty tree. Nested extraction
        # restarts ExecutePlans after ComputePlans, and that next invocation rebuilds
        # once for the new blobs.
        #
        # Canonical file type is NOT here. It reads `file_types`, which P3 writes inside
        # the per-plan children below, so a pass at this point reads an empty table on a
        # first ingest and writes nothing at all. Each plan resolves its own documents,
        # and a dataset-wide sweep after the children catches the ones whose evidence
        # crossed a plan boundary.
        vfs_params = BuildVfsNodesParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
        )
        await workflow.execute_activity(
            build_vfs_nodes,
            vfs_params,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=INDEXING_TASK_QUEUE,
        )

        # 3) Run per-plan child workflows, 16 in flight. Plans differ in size by orders
        # of magnitude, so a barrier here costs the largest plan in each group of 16.
        CONCURRENCY = 16

        def _plan_factory(ph):
            return lambda: workflow.execute_child_workflow(
                ExecuteSinglePlan.run,
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset, "plan_hash": ph, "base_temp_dir": params.base_temp_dir},
                id=f"execute-plan-{params.collection_dataset}-{ph}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )

        plan_results = await run_with_window(
            [_plan_factory(ph) for ph in plan_hashes], CONCURRENCY)
        for res in plan_results:
            if isinstance(res, Exception):
                raise res

        # Rebuild the tree over what this batch just discovered, then copy it into
        # Manticore. The pre-loop rebuild cannot see structure the batch's own P3
        # produced -- an archive member whose content already had a blob adds a
        # `vfs_files` row without adding a plan, so nothing restarts to pick it up.
        # Both are dataset-scoped and once per invocation, not once per plan, which
        # is what made this stage quadratic. Manticore vfs does not need to exist
        # for the per-plan writers: `plan_shards` creates the table and they write
        # pages and vectors, not the tree.
        #
        # This sits BEFORE the continuation and restart returns on purpose. Placing
        # it after them means the tree is only ever indexed by whichever invocation
        # happens to be terminal, so a child that raises -- or one that finds no
        # plans left to run -- leaves the browser showing the previous ingest.
        await workflow.execute_activity(
            build_vfs_nodes,
            vfs_params,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=INDEXING_TASK_QUEUE,
        )
        # The dataset-wide sweep, with the children's detections and evidence now all
        # present. Each plan already resolved its own documents; this catches a document
        # whose evidence arrived in a different plan from its detections, and it is what
        # makes the empty-archive demotion see a container's real member count.
        await workflow.execute_activity(
            resolve_canonical_file_type,
            ResolveCanonicalFileTypeParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                item_hashes=[],
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=INDEXING_TASK_QUEUE,
        )
        await workflow.execute_activity(
            index_vfs_structure,
            vfs_params,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=INDEXING_TASK_QUEUE,
        )
        # The facet-term index, alongside the structure index and for the same reason:
        # it is one table per collection rebuilt from ClickHouse, and it is what lets the
        # filter pane's search boxes ask the corpus instead of the buckets on screen.
        await workflow.execute_activity(
            index_entity_terms,
            vfs_params,
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=2),
            task_queue=INDEXING_TASK_QUEUE,
        )

        if continuation_hash:
            # Use execute_as_new semantics by re-invoking ourselves fresh via child
            return await workflow.execute_child_workflow(
                ExecutePlans.run,
                {
                    "collectionname": params.collectionname,
                    "collection_dataset": params.collection_dataset,
                    "starting_plan_hash": continuation_hash,
                    "base_temp_dir": params.base_temp_dir,
                    "recursivity_depth": recursivity_depth + 1,
                },
                id=f"execute-plans-{params.collection_dataset}-cont-{continuation_hash}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )

        # After finishing this batch, check for newly created blobs -> compute new plans and restart
        count = await workflow.execute_activity(
            count_new_blobs,
            CountNewBlobsParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset),
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )
        if count:
            await workflow.execute_child_workflow(
                ComputePlans.run,
                {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset},
                id=f"compute-plans-{params.collection_dataset}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )
            try:
                return await workflow.execute_child_workflow(
                    ExecutePlans.run,
                    {
                        "collectionname": params.collectionname,
                        "collection_dataset": params.collection_dataset,
                        "starting_plan_hash": None,
                        "base_temp_dir": params.base_temp_dir,
                        "recursivity_depth": recursivity_depth + 1,
                    },
                    id=f"execute-plans-{params.collection_dataset}-restart-{recursivity_depth+1}",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )
            except Exception as e:
                log.error(f"[P2] Error executing restart plans: {e}")
                return f"error executing restart plans: {e}"

        return f"executed {len(plan_hashes)} plans"


@dataclass
class ExecuteSinglePlanParams:
    collectionname: str
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
            GetPlanItemsMetadataParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
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
            DownloadPlanFilesParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, items=items, base_temp_dir=params.base_temp_dir),
            start_to_close_timeout=timedelta(seconds=dl_secs),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        # 3) Process the downloaded files. The plan's items are split across several
        # sibling workflows rather than driven from one.
        #
        # Temporal serialises workflow tasks WITHIN an execution: a workflow makes one
        # decision at a time, no matter how many workers are free. A per-file chain is
        # about a dozen of those round trips deep, so one driver's rate is capped by its
        # own task loop, and measurably so -- a synthetic fan-out on this cluster tops
        # out near 50 executions a second from one parent and passes 150 from thirty-two.
        # Sibling drivers cost nothing but their own start event and lift that ceiling
        # in proportion.
        # Deduplicate before splitting. A child workflow is keyed by the item hash, so
        # the same hash landing in two groups means two concurrent starts of one id --
        # a WorkflowAlreadyStartedError that loses the file. `get_plan_items_metadata`
        # is the one that must not produce duplicates and no longer does; this stays as
        # the guard, because the cost of being wrong here is a file that never parses
        # and the cost of the guard is a set.
        seen_hashes: set = set()
        unique_items = []
        for it in items:
            key = (it.get("item_hash") or "") if isinstance(it, dict) else ""
            if key in seen_hashes:
                continue
            seen_hashes.add(key)
            unique_items.append(it)
        if len(unique_items) != len(items):
            log.warning("[P2] plan %s listed %d items for %d distinct hashes",
                        params.plan_hash, len(items), len(unique_items))

        # The plan's documents, for the activities below that are scoped to them rather
        # than to the whole dataset.
        plan_item_hashes = [
            h for h in ((it.get("item_hash") or "") if isinstance(it, dict) else ""
                        for it in unique_items) if h
        ]

        item_groups = [
            unique_items[i:i + PLAN_GROUP_SIZE]
            for i in range(0, len(unique_items), PLAN_GROUP_SIZE)
        ] or [[]]

        def _group_factory(index, group):
            return lambda: workflow.execute_child_workflow(
                ProcessItemsBatched.run,
                ProcessItemsBatchedParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    out_dir=dl.get("out_dir"),
                    items=group,
                ),
                id=f"process-batches-{params.collection_dataset}-{params.plan_hash}-{index}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )

        group_results = await run_with_window(
            [_group_factory(i, g) for i, g in enumerate(item_groups)],
            MAX_PLAN_DRIVERS,
        )
        for res in group_results:
            if isinstance(res, Exception):
                raise res

        # Delete timeout: time at 100 kbps
        del_secs = 900+math.ceil(total_bytes / BPS_100_K)

        # 4) Cleanup (TODO: pin activity to worker)
        await workflow.execute_activity(
            cleanup_plan_dir,
            CleanupPlanDirParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, base_temp_dir=params.base_temp_dir),
            start_to_close_timeout=timedelta(seconds=del_secs),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        # 5) Date resolution. Reads what the parse stages just wrote (tika_metadata,
        # email_headers.date_sent_known) plus P0's archive mtimes, and writes the
        # document_dates rows. Must run after parsing and before indexing: P6 builds the
        # `dates` search attribute from that table, so a document indexed first is
        # permanently undated until something re-indexes it.
        await workflow.execute_activity(
            resolve_document_dates,
            ResolveDocumentDatesParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                plan_hash=params.plan_hash,
            ),
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        # 5b) One definitive type per document in this plan, from what its parsers
        # actually produced. It sits here, after parsing and before indexing, for the
        # same reason date resolution does: `document_metadata` reads the result, and a
        # document with no canonical row produces no metadata row at all, losing its
        # file type, its MIME and its extensions, and taking the whole File types facet
        # with it.
        await workflow.execute_activity(
            resolve_canonical_file_type,
            ResolveCanonicalFileTypeParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                item_hashes=plan_item_hashes,
            ),
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
            task_queue=INDEXING_TASK_QUEUE,
        )

        # 6+7) NLP, regex scanning and chunk+embed, together. All three read the
        # `text_content` the parse stages just wrote and write to disjoint tables --
        # entities and the nlp_processed watermark, regex_entity_hit and regex_scanned,
        # text_chunks and text_chunk_vectors -- and only indexing needs all of them. They
        # also run on different worker queues and against different services, so running
        # them in sequence left a tier idle for the others' whole duration. All must
        # finish before step 8: P6 reads the entity rows and copies the vectors into the
        # shard's HNSW table.
        stage_results = await asyncio.gather(
            workflow.execute_child_workflow(
                ExtractEntitiesForPlan.run,
                ExtractEntitiesForPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
                id=f"extract-entities-{params.collection_dataset}-{params.plan_hash}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            ),
            workflow.execute_child_workflow(
                ScanRegexEntitiesForPlan.run,
                ScanRegexEntitiesForPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
                id=f"scan-regex-entities-{params.collection_dataset}-{params.plan_hash}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            ),
            workflow.execute_child_workflow(
                ChunkEmbedForPlan.run,
                ChunkEmbedForPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
                id=f"chunk-embed-{params.collection_dataset}-{params.plan_hash}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            ),
            return_exceptions=True,
        )
        for res in stage_results:
            if isinstance(res, Exception):
                raise res

        # 8) Indexing stage
        await workflow.execute_child_workflow(
            IndexDatasetPlan.run,
            IndexDatasetPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            id=f"index-dataset-plan-{params.collection_dataset}-{params.plan_hash}",
            task_queue="processing-common-queue",
            search_attributes=dataset_search_attributes(params.collection_dataset),
        )

        # 9) Mark finished
        await workflow.execute_activity(
            mark_plan_finished,
            MarkPlanFinishedParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash),
            start_to_close_timeout=timedelta(minutes=25),
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=ACTIVITY_MAX_ATTEMPTS),
        )

        log.info(f"[P2] Finished plan {params.collection_dataset} {params.plan_hash}")

        return f"finished {params.plan_hash}"


@dataclass
class ProcessItemsBatchedParams:
    collectionname: str
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

        # A child workflow costs about five history events here, so a run that covers
        # more than MAX_ITEMS_PER_RUN items walks toward Temporal's 51,200-event hard
        # cap. Hitting it fails the whole plan with nothing partial recorded, which is
        # far worse than the continuation this costs. P1 caps a plan at 1000 items, so
        # this is a guard against a future plan sizing, not something today's traffic
        # reaches.
        this_run = params.items[:MAX_ITEMS_PER_RUN]
        remaining = params.items[MAX_ITEMS_PER_RUN:]

        # A sliding window, not batches. Per-file wall time on this pipeline has a p99
        # about fifteen times its p50, so a barrier every 32 files means a handful of
        # large files idle 31 slots for tens of seconds each -- most of the parse
        # phase went there. With a window the next file starts the moment one finishes.
        CONCURRENCY = 32
        started_at = workflow.now()
        item_hashes = [
            (it.get("item_hash") or "") if isinstance(it, dict) else ""
            for it in this_run
        ]

        def _factory(it):
            args = ParseSingleFileParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                plan_hash=params.plan_hash,
                item_hash=it.get('item_hash'),
                file_path=f"{params.out_dir}/{it.get('item_hash')}",
                file_size_bytes=it.get('file_size_bytes'),
            )
            return lambda: workflow.execute_child_workflow(
                ParseSingleFile.run,
                args,
                id=f"parse-file-{params.collection_dataset}-{params.plan_hash}-{it.get('item_hash')}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            )

        results = await run_with_window([_factory(it) for it in this_run], CONCURRENCY)

        # Error rows are written once for the whole run rather than once per batch:
        # the activity that writes them is itself a Temporal execution, and one per 32
        # files is a cost the window no longer has any reason to pay.
        for i in range(0, len(results), ERROR_REPORT_CHUNK):
            chunk = results[i:i + ERROR_REPORT_CHUNK]
            await record_errors_from_results(
                chunk,
                task_ids=["P3_ParseSingleFile"] * len(chunk),
                starts=[started_at] * len(chunk),
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                item_hashes=item_hashes[i:i + ERROR_REPORT_CHUNK],
            )

        if remaining:
            workflow.continue_as_new(ProcessItemsBatchedParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                plan_hash=params.plan_hash,
                out_dir=params.out_dir,
                items=remaining,
            ))
        return f"processed {len(results)} items"


