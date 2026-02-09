# P4 - Index Data

This stage indexes parsed text and metadata into Manticore and ClickHouse to enable search and entity retrieval.

## Key Responsibilities

- Load plan item hashes and fetch text content for indexing.
- Extract named entities and store entity hits for search.
- Build metadata indexes for file types, MIME types, extensions, and paths.

## Entry Points

- Workflow: `IndexDatasetPlan` in `workflows.py`
- Activities: `index_text_content`, `index_metadatas`, `fetch_plan_hashes` in `activities.py`
- Helpers: `string_term_encodings.py` and `extract_ner_from_text.py`

## Technical Details

Indexing batches items in fixed chunk sizes to limit transaction sizes. Entity extraction calls the configured NER service and stores both raw hits in ClickHouse and encoded term IDs for Manticore. String term IDs are derived from deterministic hashes and stored in lookup tables for reuse.

## Usage

- Triggered by P2 after successful plan execution.
- Indexing activities run on `processing-indexing-queue`.

## Navigation

- [Go Back](../Readme.md)
- [P3 - Parse Files](../P3_parse_files/Readme.md)
