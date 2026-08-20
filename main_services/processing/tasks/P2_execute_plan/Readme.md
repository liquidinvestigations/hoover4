# P2 - Execute Plan

This stage executes processing plans by downloading planned blobs, coordinating per-file parsing, and marking plans as finished.

## Key Responsibilities

- Enumerate pending plans and schedule execution in batches.
- Download plan files from MinIO or ClickHouse into temp directories.
- Spawn per-file parsing workflows and record processing errors.
- Cleanup temporary artifacts and mark plans complete.

## Entry Points

- Workflows: `ExecutePlans`, `ExecuteSinglePlan`, `ProcessItemsBatched` in `workflows.py`
- Activities: plan listing, download, cleanup, and completion markers in `activities.py`
- Submit helper: `submit_job.py`

## Technical Details

Plan execution runs in parallel batches of 16 and uses continuation to avoid large
histories. Download timeouts scale by total plan size; cleanup mirrors the same budget.
The stage records failures into `processing_errors` and relies on P3 for actual file
parsing.

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
- Run via `submit_job.py` for manual execution.

## Navigation

- [Go Back](../Readme.md)
- [P1 - Compute Plans](../P1_compute_plans/Readme.md)
- [P3 - Parse Files](../P3_parse_files/Readme.md)
