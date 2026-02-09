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

Plan execution runs in parallel batches and uses continuation to avoid large histories. Download timeouts scale by total plan size; cleanup mirrors the same budget. The stage records failures into `processing_errors` and relies on P3 for actual file parsing.

## Usage

- Triggered automatically after plan creation in `main.py`.
- Run via `submit_job.py` for manual execution.

## Navigation

- [Go Back](../Readme.md)
- [P1 - Compute Plans](../P1_compute_plans/Readme.md)
- [P3 - Parse Files](../P3_parse_files/Readme.md)
