# P2 - Execute Plan

This stage executes processing plans by downloading planned blobs, coordinating per-file parsing, and marking plans as finished.

## Key Responsibilities

- Enumerate pending plans and schedule execution in batches.
- Download plan files from Garage or ClickHouse into temp directories.
- Spawn per-file parsing workflows and record processing errors.
- Cleanup temporary artifacts and mark plans complete.

## Entry Points

- Workflows: `ExecutePlans`, `ExecuteSinglePlan`, `ProcessItemsBatched` in `workflows.py`
- Activities: plan listing, download, cleanup, and completion markers in `activities.py`
- Submit helper: `submit_job.py`

## Technical Details

### Nothing here waits for a batch to drain

Every fan-out in this stage keeps K in flight rather than starting K and gathering them
(`tasks/workflow_window.py`). The difference is not stylistic: per-file wall time on this
pipeline has a p99 roughly fifteen times its p50, so a barrier makes every group cost its
slowest member, and a handful of large files idle a whole group's worth of slots for tens
of seconds each. `ExecutePlans` keeps 16 plans in flight, `ProcessItemsBatched` 32 files.

### A plan is driven by several sibling workflows, not one

Temporal serialises workflow tasks *within* an execution — a workflow makes one decision
at a time no matter how many workers are idle — and a per-file chain is about a dozen of
those round trips deep. One driver is therefore a latency ceiling rather than a capacity
one, and measurably so: a synthetic fan-out on this cluster tops out near 50 executions a
second from a single parent and passes 150 from thirty-two. `ExecuteSinglePlan` splits
its items into groups of `PLAN_GROUP_SIZE` and runs one `ProcessItemsBatched` per group,
which costs a start event each and lifts the ceiling in proportion.

A child workflow is keyed by the item hash, so **a plan may not list a hash twice**.
`get_plan_items_metadata` joins `blobs`, which is a ReplacingMergeTree it does not read
`FINAL`, so a hash whose rows have not merged yet joins more than once; the query
collapses that with `LIMIT 1 BY`, and `ExecuteSinglePlan` drops duplicates again before
grouping. Sequential batches used to tolerate a duplicate — the second start reused a
completed id — but sibling drivers run them at the same time, where the second is a
`WorkflowAlreadyStartedError` and the file silently never parses.

`ProcessItemsBatched` also continues as new past `MAX_ITEMS_PER_RUN` items. Each file is
a child workflow and so a handful of events on that execution's history; Temporal's
51,200-event cap is a hard failure of the whole plan with nothing partial recorded, not a
slowdown.

Download timeouts scale by total plan size; cleanup mirrors the same budget. The stage
records failures into `processing_errors` and relies on P3 for actual file parsing.

### P4 and P5 run together

`ExecuteSinglePlan` starts `ExtractEntitiesForPlan` and `ChunkEmbedForPlan` in one
gather. They read the same `text_content` and write disjoint tables — entities and the
`nlp_processed` watermark against `text_chunks` and `text_chunk_vectors` — and they run
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

After the children, the tree is rebuilt a second time and then copied into Manticore
`<coll>_vfs`. The second rebuild is not redundant: the pre-loop one cannot see structure
this batch's own P3 produced, and an archive member whose content already had a blob adds
a `vfs_files` row without adding a plan, so nothing restarts to pick it up. Both calls sit
**before** the continuation and restart hand-offs, so every invocation indexes the plans
it executed — indexing only on the terminal invocation means a child that raises, or one
that finds no plans left, leaves the browser on the previous ingest.

The copy is incremental: `REPLACE` in multi-row chunks of 512, then a delete of Manticore
rows whose `node_key` is not in the current ClickHouse tree. There is no dataset-wide
`DELETE` first, so the file browser never sees an empty tree because of this activity.

`build_email_graph` stays inside `IndexDatasetPlan` (collection-scoped, still per plan).

## Usage

- Triggered automatically after plan creation in `main.py`.
- `submit_job.py` holds one `async def` and no entry point: it is a helper `main.py`
  imports, not a script. To start this stage by hand, start the `ExecutePlans` workflow
  from the Temporal UI or from the dataset's page in the admin UI.

## Navigation

- [Go Back](../Readme.md)
- [P1 - Compute Plans](../P1_compute_plans/Readme.md)
- [P3 - Parse Files](../P3_parse_files/Readme.md)
