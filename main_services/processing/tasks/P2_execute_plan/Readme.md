# P2 - Execute Plan

This stage executes processing plans by downloading planned blobs, running the batched parse of each group of files, and marking plans as finished.

## Key Responsibilities

- Enumerate pending plans and schedule execution in batches.
- Download plan files from Garage or ClickHouse into temp directories.
- Run one stage activity for each parse stage over the files of a group, and record processing errors.
- Keep a source id from the workflow run and an ordinal for each failed file result.
- Cleanup temporary artifacts and mark plans complete.

The Error helper records each source id with its failed document hash.

## Entry Points

- Workflows: `ExecutePlans`, `ExecuteSinglePlan`, `ProcessItemsBatched` in `workflows.py`
- Activities: plan listing, download, cleanup, and completion markers in `activities.py`
- Submit helper: `submit_job.py`

## Technical Details

### Nothing here waits for a batch to drain

Every fan-out of workflows in this stage keeps K in flight rather than starting K and
gathering them (`tasks/workflow_window.py`). A barrier makes every group cost its slowest
member. `ExecutePlans` keeps 16 plans in flight, and `ExecuteSinglePlan` keeps
`MAX_PLAN_DRIVERS` groups in flight.

Inside one group, `ProcessItemsBatched` has barriers. Each stage activity runs its files
one after another, and the second stage starts when both detector stages have returned.
So a slow file delays the other files of its group.

### A plan is driven by several sibling workflows, not one

Temporal serialises workflow tasks *within* an execution (a workflow makes one decision
at a time no matter how many workers are idle), and the stages of a group are up to six of
those round trips deep. One driver is therefore a latency ceiling rather than a capacity
one, and measurably so: a synthetic fan-out on this cluster tops out near 50 executions a
second from a single parent and passes 150 from thirty-two. `ExecuteSinglePlan` splits
its items into groups of `PLAN_GROUP_SIZE` and runs one `ProcessItemsBatched` per group,
which costs a start event each and lifts the ceiling in proportion.

A stage extracts a container into a folder named by the item hash, so **a plan may not
list a hash twice**: two items of one hash would extract into one folder, and the member
scan of one would remove the folder under the other.
`get_plan_items_metadata` joins `blobs`, which is a ReplacingMergeTree it does not read
`FINAL`, so a hash whose rows have not merged yet joins more than once; the query
collapses that with `LIMIT 1 BY`, and `ExecuteSinglePlan` drops duplicates again before
grouping.

### One group runs one activity for each stage

`ProcessItemsBatched` starts no child workflow. It schedules each stage activity of
`tasks/P3_parse_files/batch_runner.py` by its name in `STAGE_QUEUES`, with the files of
that stage, and it gets one `FileResult` for each file. `run_stage` is its one catch
point: a stage activity that fails gives each of its files a failed result, except the
files that its last heartbeat detail lists as finished. So the history of a group grows
with its stages, and not with its files. After the stages, the group records the detector
errors, best effort, and then the parser errors of every file, in item order.

Download timeouts scale by total plan size; cleanup mirrors the same budget. The stage
records failures into `processing_errors` and relies on P3 for actual file parsing.

### P4 and P5 run together

`ExecuteSinglePlan` starts `ExtractEntitiesForPlan` and `ChunkEmbedForPlan` in one
gather. They read the same `text_content` and write disjoint tables (entities and the
`nlp_processed` watermark against `text_chunks` and `text_chunk_vectors`), and they run
on different worker queues, so in sequence each left the other tier idle for its whole
stage. Both must still complete before `IndexDatasetPlan`: P6 reads the `entity_hit` rows
and copies the vectors into the shard's HNSW table.
`tests/unit/test_pipeline_stage_order.py` pins both the ordering and the pairing.

The dataset tree is rebuilt once per `ExecutePlans` batch, before the per-plan children:
`build_vfs_nodes` then `resolve_canonical_file_type`, both on `processing-indexing-queue`.
`document_metadata` (used by the P6 page writer) reads ancestor closures from ClickHouse
`vfs_nodes`, so those writers must not run against an empty tree. Nested extraction
restarts `ExecutePlans` after `ComputePlans`, and that next invocation rebuilds once for
the new blobs.

After the children, the tree is rebuilt a second time, page-row folder attributes are rewritten for documents whose locations changed, and the tree is copied into Manticore `<coll>_vfs`. The second rebuild is not redundant: the pre-loop one cannot see structure this batch's own P3 produced, and an archive member whose content already had a blob adds a `vfs_files` row without adding a plan, so nothing restarts to pick it up. A rescan that adds a path for already processed bytes also produces no pending plans. That invocation still rebuilds the tree and rewrites those page-row attributes. Both calls sit **before** the continuation and restart hand-offs, so every invocation indexes the plans it executed. Indexing only on the terminal invocation means a child that raises, or one that finds no plans left, leaves the browser on the previous ingest.

The copy is incremental: `REPLACE` in multi-row chunks of 512, then a delete of Manticore
rows whose `node_key` is not in the current ClickHouse tree. There is no dataset-wide
`DELETE` first, so the file browser never sees an empty tree because of this activity.

`build_email_graph` runs after the tree copy and the facet-term index, once for each
`ExecutePlans` batch that ran plans, and before the hand-offs for the same reason. It is
collection-scoped and runs on `processing-email-graph-queue`, one process of one slot. A
batch that ran no plan skips it. `tests/unit/test_pipeline_stage_order.py` pins its place,
its queue and that condition.

## Usage

- Triggered automatically after plan creation in `main.py`.
- `submit_job.py` holds one `async def` and no entry point: it is a helper `main.py`
  imports, not a script. To start this stage by hand, start the `ExecutePlans` workflow
  from the Temporal UI or from the dataset's page in the admin UI.

## Navigation

- [Go Back](../Readme.md)
- [P1 - Compute Plans](../P1_compute_plans/Readme.md)
- [P3 - Parse Files](../P3_parse_files/Readme.md)
