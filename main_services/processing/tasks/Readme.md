# Processing Tasks Definitions

This section contains code for the Temporal workflows for processing and indexing datasets.

The following sections describe each layer of the processing architecture.

## P0 - Scan Disk

This section is responsible for the initial contact with the user data; disk datasets are listed and statistics are computed for the size and number of files to be ingested.

- Top-level workflow: `IngestDiskDataset`
- Input: User Data
- Output: VFS (virtual filesystem) data, saved in clickhouse tables `vfs_files` and `vfs_directories`

## P1 - Compute Plans

The statistics from the previous steps are used to split processing into chunks that will be scheduled separately.

## P2 - Execute Plan

This workflow takes plan chunks computed earlier and schedules them on workers.

## P3 - Parse Files

This workflow contains code to process the various data types found in the dataset.

## P4 - Index Data

This workflow aggregates the metadata from the previous steps and indexes it in the other databases (search db, vector db). Text-based processing (NER) is also done at this time.