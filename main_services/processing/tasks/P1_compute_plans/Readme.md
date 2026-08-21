# P1 - Compute Plans

This stage creates processing plans from newly ingested blobs. Plans define batch boundaries for downstream execution and are stored in ClickHouse.

## Key Responsibilities

- Identify blobs that have not been planned.
- Batch blobs into plans based on size and item count limits.
- Record plan membership and plan metadata in ClickHouse.

## Entry Points

- Workflow: `ComputePlans` in `workflows.py`
- Activities: `count_new_blobs`, `compute_plans` in `activities.py`
- Submit helper: `submit_job.py` (invoked by `main.py add-disk-dataset`)

## Technical Details

Plans are built with a 1 GB total size cap and up to 1000 items per plan. Plan hashes are derived from a stable JSON payload of sorted item hashes. The workflow runs with time budgets derived from blob counts to maintain throughput targets.

## Usage

- Triggered automatically after dataset ingestion in `main.py`.
- `submit_job.py` holds one `async def` and no entry point: it is a helper `main.py`
  imports, not a script. To start this stage by hand, start the `ComputePlans` workflow
  from the Temporal UI or from the dataset's page in the admin UI.

## Navigation

- [Go Back](../Readme.md)
- [P0 - Scan Disk](../P0_scan_disk/Readme.md)
- [P2 - Execute Plan](../P2_execute_plan/Readme.md)
