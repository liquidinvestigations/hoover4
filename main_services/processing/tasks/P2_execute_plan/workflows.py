"""Workflows for executing processing plans and the batched parse of each group."""

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError
from datetime import timedelta
import dataclasses
import traceback
import math
import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from tasks.workflow_window import run_with_window

log = logging.getLogger(__name__)

# Items one `ProcessItemsBatched` execution drives. A plan is split into groups of this
# size and the groups run as siblings, because a single workflow execution decides one
# thing at a time -- one driver is a latency ceiling, not a capacity one. Each group runs
# one activity for each parse stage over its files, so its history grows with the stages
# and not with the files.
PLAN_GROUP_SIZE = 100

# Sibling drivers one plan may run at once. Without this bound a large corpus multiplies
# plans in flight by groups and puts thousands of stage activities on the server at once,
# which is a different failure from the one the siblings fix.
MAX_PLAN_DRIVERS = 8


# Import activities and sibling workflows through the sandbox
with workflow.unsafe.imports_passed_through():
    from tasks.heartbeat import ACTIVITY_MAX_ATTEMPTS, HEARTBEAT_TIMEOUT
    from tasks.P3_parse_files.batch_runner import (
        FILE_BASE_SECONDS,
        STAGE_QUEUES,
        BatchFile,
        BatchResult,
        ContainerFolder,
        FileResult,
        ScanContainerFoldersParams,
        StageBatchParams,
        file_error,
        folder_stage_timeout_seconds,
        stage_failure_results,
        stage_timeout_seconds,
    )
    from tasks.P3_parse_files.workflows import (
        ROUTE_ERROR_NAMES,
        _detector_error_task_ids,
        _detector_results_for_error_capture,
        combine_detector_results,
        detector_results_for_file,
        ocr_error_name,
        ocr_pdf_error_name,
        route_stages,
    )
    from tasks.P3_parse_files.parse_mime import LOCAL_DETECTORS
    from tasks.text_sources import OCR_ENGINES
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
    from tasks.P3_parse_files.parse_common import record_errors_from_results, source_execution_id
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
        refresh_stale_document_locations,
        resolve_canonical_file_type,
    )
    from tasks.P6_index_data.params import BuildVfsNodesParams, RefreshDocumentLocationsParams, ResolveCanonicalFileTypeParams
    from tasks.visibility import dataset_search_attributes


@dataclass
class ExecutePlansParams:
    collectionname: str
    collection_dataset: str
    base_temp_dir: str
    starting_plan_hash: str | None = None
    recursivity_depth: int | None = None
    op_id: str = ""


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
            ListPendingPlansParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, starting_plan_hash=(params.starting_plan_hash or ""), op_id=params.op_id),
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
                        "op_id": params.op_id,
                    },
                    id=f"execute-plans-{params.collection_dataset}-restart",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )
            log.info("[P2] No plans to execute; refreshing locations if they changed")

        vfs_params = BuildVfsNodesParams(
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
        )
        continuation_hash = None

        if plan_hashes:
            # 2) If more than 1000, keep the 101st for continuation
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
                    {"collectionname": params.collectionname, "collection_dataset": params.collection_dataset, "plan_hash": ph, "base_temp_dir": params.base_temp_dir, "op_id": params.op_id},
                    id=f"execute-plan-{params.collection_dataset}-{ph}",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )

            plan_results = await run_with_window(
                [_plan_factory(ph) for ph in plan_hashes], CONCURRENCY)
            for res in plan_results:
                if isinstance(res, Exception):
                    raise res

        # Rebuild the tree over current vfs_files, rewrite page-row folder
        # attributes for documents whose locations changed, then copy the tree
        # into Manticore. This runs when the invocation executed plans and when it
        # did not: a disk rescan of known bytes, and an archive member whose content
        # already had a blob, add vfs_files rows without adding a plan.
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
        if plan_hashes:
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
            refresh_stale_document_locations,
            RefreshDocumentLocationsParams(
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                item_hashes=[],
            ),
            start_to_close_timeout=timedelta(minutes=45),
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
                    "op_id": params.op_id,
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
                        "op_id": params.op_id,
                    },
                    id=f"execute-plans-{params.collection_dataset}-restart-{recursivity_depth+1}",
                    task_queue="processing-common-queue",
                    search_attributes=dataset_search_attributes(params.collection_dataset),
                )
            except Exception as e:
                log.error(f"[P2] Error executing restart plans: {e}")
                return f"error executing restart plans: {e}"

        if not plan_hashes:
            return "no plans"
        return f"executed {len(plan_hashes)} plans"


@dataclass
class ExecuteSinglePlanParams:
    collectionname: str
    collection_dataset: str
    plan_hash: str
    base_temp_dir: str
    op_id: str = ""


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
        # decision at a time, no matter how many workers are free. The stages of a group
        # are up to six of those round trips deep, so one driver's rate is capped by its
        # own task loop, and measurably so -- a synthetic fan-out on this cluster tops
        # out near 50 executions a second from one parent and passes 150 from thirty-two.
        # Sibling drivers cost nothing but their own start event and lift that ceiling
        # in proportion.
        # Deduplicate before splitting. A stage extracts a container into a folder named
        # by the item hash, so two items of one hash, in one group or in two, would
        # extract into one folder, and the member scan of one would remove the folder
        # under the other. `get_plan_items_metadata` must not produce duplicates and does
        # not. This set stays as the guard, because its cost is small.
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
                    op_id=params.op_id,
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
                ExtractEntitiesForPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, op_id=params.op_id),
                id=f"extract-entities-{params.collection_dataset}-{params.plan_hash}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            ),
            workflow.execute_child_workflow(
                ScanRegexEntitiesForPlan.run,
                ScanRegexEntitiesForPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, op_id=params.op_id),
                id=f"scan-regex-entities-{params.collection_dataset}-{params.plan_hash}",
                task_queue="processing-common-queue",
                search_attributes=dataset_search_attributes(params.collection_dataset),
            ),
            workflow.execute_child_workflow(
                ChunkEmbedForPlan.run,
                ChunkEmbedForPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, op_id=params.op_id),
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
            IndexDatasetPlanParams(collectionname=params.collectionname, collection_dataset=params.collection_dataset, plan_hash=params.plan_hash, op_id=params.op_id),
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
    op_id: str = ""


@workflow.defn
class ProcessItemsBatched:
    """Parse the files of one group of a plan, one stage activity at a time.

    Each stage runs one activity over every file of the group that takes that stage. The
    group starts no child workflow. The member scan of every folder that the group
    extracted is one activity too.
    """
    @workflow.run
    async def run(self, params: ProcessItemsBatchedParams) -> str:
        if not params.items:
            return "no items"

        files = [
            BatchFile(
                item_hash=(it.get("item_hash") or "") if isinstance(it, dict) else "",
                file_path=f"{params.out_dir}/{(it.get('item_hash') or '') if isinstance(it, dict) else ''}",
                file_size_bytes=int((it.get("file_size_bytes") or 0) if isinstance(it, dict) else 0),
            )
            for it in params.items
        ]
        starts: Dict[Tuple[str, str], Any] = {}

        async def run_stage(name: str, items: List[Any], engine: str = "") -> List[FileResult]:
            """The one catch point of the group: one result for each item, in item order."""
            if not items:
                return []
            starts[name, engine] = workflow.now()
            folders = name == "scan_container_folders"
            if folders:
                arg: Any = ScanContainerFoldersParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    folders=items,
                    op_id=params.op_id,
                )
                keys = [folder.container_hash for folder in items]
                timeout = folder_stage_timeout_seconds(items)
            else:
                arg = StageBatchParams(
                    collectionname=params.collectionname,
                    collection_dataset=params.collection_dataset,
                    plan_hash=params.plan_hash,
                    files=items,
                    op_id=params.op_id,
                    engine=engine,
                )
                keys = [file.item_hash for file in items]
                timeout = stage_timeout_seconds(name, [file.file_size_bytes for file in items])
            try:
                batch = await workflow.execute_activity(
                    name,
                    arg,
                    result_type=BatchResult,
                    start_to_close_timeout=timedelta(seconds=timeout),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    # No attempt limit. The runner fails the stage after consecutive
                    # attempts that finish no new file.
                    retry_policy=RetryPolicy(maximum_attempts=0),
                    task_queue=STAGE_QUEUES[name],
                )
                return batch.results
            except ActivityError as exc:
                return stage_failure_results(name, keys, exc)

        # Stage 1: the local detectors and Tika, at once.
        detect, tika = await asyncio.gather(
            run_stage("detect_mime_batch", files),
            run_stage("run_tika_batch", files),
        )
        detector_results = [detector_results_for_file(d, t) for d, t in zip(detect, tika)]
        combined = [combine_detector_results(results) for results in detector_results]
        routes = [route_stages(types) for types in combined]

        def with_route(route: str) -> List[int]:
            return [index for index, file_routes in enumerate(routes) if route in file_routes]

        # The result of each parser entry of each file, by its error name. A chain
        # result is the first failed result of its steps, or the result of its last step.
        entries: List[Dict[str, FileResult]] = [{} for _ in files]
        entry_starts: List[Dict[str, Tuple[str, str]]] = [{} for _ in files]
        ocr_pdf_entries: List[Dict[str, FileResult]] = [{} for _ in files]

        def put(index: int, error_name: str, result: FileResult, stage: Tuple[str, str],
                into: Optional[List[Dict[str, FileResult]]] = None) -> None:
            (entries if into is None else into)[index][error_name] = result
            entry_starts[index].setdefault(error_name, stage)

        def batch_file(index: int, **fields: Any) -> BatchFile:
            return dataclasses.replace(files[index], **fields)

        async def single(name: str, route: str, error_name: str, engine: str = "",
                         with_types: bool = False) -> None:
            indexes = with_route(route)
            items = [
                batch_file(i, mime_types=combined[i]["mime_types"],
                           mime_encodings=combined[i]["mime_encodings"])
                if with_types else files[i]
                for i in indexes
            ]
            for i, result in zip(indexes, await run_stage(name, items, engine)):
                put(i, error_name, result, (name, engine))

        # Each folder, with the file index and the chain error name it belongs to.
        folders: List[Tuple[int, ContainerFolder]] = []

        def add_folder(index: int, result: FileResult, error_name: str, count_key: str = "") -> None:
            value = result.value if isinstance(result.value, dict) else {}
            if result.status == "failed" or not value.get("out_dir"):
                return
            if count_key and not int(value.get(count_key) or 0) > 0:
                return
            folders.append((index, ContainerFolder(
                container_hash=files[index].item_hash,
                out_dir=value["out_dir"],
                error_task_name=error_name,
                source_size_bytes=files[index].file_size_bytes,
                member_count=int(value.get("member_count") or 0),
            )))

        async def email_chain() -> None:
            indexes = with_route("email")
            headers = await run_stage("parse_email_headers_batch", [files[i] for i in indexes])
            passed = []
            for i, result in zip(indexes, headers):
                put(i, "email_scan", result, ("parse_email_headers_batch", ""))
                if result.status != "failed":
                    passed.append(i)
            attachments = await run_stage("extract_email_attachments_batch",
                                          [files[i] for i in passed])
            for i, result in zip(passed, attachments):
                put(i, "email_scan", result, ("parse_email_headers_batch", ""))
                add_folder(i, result, "email_scan", "attachment_count")

        async def archive_stage() -> None:
            indexes = with_route("archive")
            items = [batch_file(i, mime_types=combined[i]["mime_types"]) for i in indexes]
            for i, result in zip(indexes, await run_stage("extract_archive_batch", items)):
                put(i, "archive_scan", result, ("extract_archive_batch", ""))
                add_folder(i, result, "archive_scan", "entry_count")

        ocr_pdf_tasks: List[Any] = []

        async def ocr_pdf_stage(indexes: List[int], items: List[BatchFile], engine: str) -> None:
            results = await run_stage("run_ocr_pdf_batch", items, engine)
            for i, result in zip(indexes, results):
                put(i, ocr_pdf_error_name(engine), result, ("run_ocr_pdf_batch", engine),
                    into=ocr_pdf_entries)

        async def pdf_chain() -> None:
            indexes = with_route("pdf")
            meta = await run_stage("pdf_metadata_batch", [files[i] for i in indexes])
            passed: List[int] = []
            items: List[BatchFile] = []
            for i, result in zip(indexes, meta):
                put(i, "pdf_process", result, ("pdf_metadata_batch", ""))
                if result.status == "failed":
                    continue
                value = result.value if isinstance(result.value, dict) else {}
                passed.append(i)
                items.append(batch_file(i, page_count=int(value.get("page_count") or 0),
                                        pdf_size_bytes=int(value.get("size_bytes") or 0)))
            for engine in OCR_ENGINES:
                ocr_pdf_tasks.append(asyncio.create_task(ocr_pdf_stage(passed, items, engine)))
            for i, result in zip(passed, await run_stage("pdf_extract_batch", items)):
                put(i, "pdf_process", result, ("pdf_metadata_batch", ""))
                add_folder(i, result, "pdf_process")

        async def video_stage() -> None:
            indexes = with_route("video")
            for i, result in zip(indexes, await run_stage("video_batch", [files[i] for i in indexes])):
                put(i, "video_process", result, ("video_batch", ""))
                add_folder(i, result, "video_process")

        async def containers() -> None:
            await asyncio.gather(email_chain(), archive_stage(), pdf_chain(), video_stage())
            scan = await run_stage("scan_container_folders", [folder for _, folder in folders])
            # Matched by position: one file can extract two folders with one hash.
            for (i, folder), result in zip(folders, scan):
                if result.status == "failed":
                    entries[i][folder.error_task_name] = result

        # Stage 2: every chain at once.
        stage_two = [
            single("extract_plaintext_batch", "text", "extract_plaintext_chunks"),
            single("parse_office_xml_batch", "office_xml", "parse_office_xml_and_store"),
            single("parse_table_batch", "table", "parse_table_and_store", with_types=True),
            single("parse_image_metadata_batch", "image", "parse_image_metadata_and_store"),
        ]
        stage_two += [single("run_ocr_batch", "image", ocr_error_name(engine), engine=engine)
                      for engine in OCR_ENGINES]
        stage_two += [single("parse_audio_metadata_batch", "audio",
                             "parse_audio_metadata_and_store"), containers()]
        await asyncio.gather(*stage_two)
        await asyncio.gather(*ocr_pdf_tasks)

        # Stage 3: the detector errors, best effort, then the parser errors.
        run_id = workflow.info().run_id
        parser_names: List[List[str]] = []
        parser_results: List[List[Any]] = []
        for i, file_routes in enumerate(routes):
            names = []
            for route in file_routes:
                names.append(ROUTE_ERROR_NAMES[route])
                if route == "image":
                    names += [ocr_error_name(engine) for engine in OCR_ENGINES]
            names = [name for name in names if name in entries[i]]
            parser_names.append(names)
            parser_results.append([_as_error_input(entries[i][name]) for name in names])

        detector_names = list(LOCAL_DETECTORS) + ["tika"]
        detector_inputs: List[Any] = []
        detector_task_ids: List[str] = []
        for i, results in enumerate(detector_results):
            detector_inputs += _detector_results_for_error_capture(
                detector_names, results, parser_names[i], parser_results[i])
            detector_task_ids += _detector_error_task_ids(
                detector_names, results, parser_names[i], parser_results[i])
        detector_start = starts.get(("detect_mime_batch", ""), workflow.now())
        try:
            await record_errors_from_results(
                detector_inputs,
                source_execution_ids=[source_execution_id(run_id, "P3.group.detector", n)
                                      for n in range(len(detector_inputs))],
                task_ids=detector_task_ids,
                starts=[detector_start] * len(detector_inputs),
                collectionname=params.collectionname,
                collection_dataset=params.collection_dataset,
                item_hashes=[file.item_hash for file in files for _ in detector_names],
                op_id=params.op_id,
                default_task_name="detector_error_unknown",
            )
        except Exception:
            # Best effort: a detector that failed must not also fail the parse. The log
            # line keeps the loss visible.
            log.exception("[P3] failed to record detector errors for %s group of plan %s",
                          params.collection_dataset, params.plan_hash)

        parser_inputs: List[Any] = []
        parser_task_ids: List[str] = []
        parser_starts: List[Any] = []
        parser_hashes: List[str] = []
        for i, file in enumerate(files):
            named = list(zip(parser_names[i], parser_results[i]))
            named += [(name, _as_error_input(ocr_pdf_entries[i][name]))
                      for name in (ocr_pdf_error_name(engine) for engine in OCR_ENGINES)
                      if name in ocr_pdf_entries[i]]
            for name, result in named:
                parser_inputs.append(result)
                parser_task_ids.append(name)
                parser_starts.append(starts.get(entry_starts[i][name], workflow.now()))
                parser_hashes.append(file.item_hash)
        await record_errors_from_results(
            parser_inputs,
            source_execution_ids=[source_execution_id(run_id, "P3.group.parser", n)
                                  for n in range(len(parser_inputs))],
            task_ids=parser_task_ids,
            starts=parser_starts,
            collectionname=params.collectionname,
            collection_dataset=params.collection_dataset,
            item_hashes=parser_hashes,
            op_id=params.op_id,
            start_to_close_timeout_seconds=FILE_BASE_SECONDS,
        )
        return f"processed {len(files)} items"


def _as_error_input(result: FileResult) -> Any:
    """A failed result as the exception that the error recorder reads, else its value."""
    return file_error(result) if result.status == "failed" else result.value
