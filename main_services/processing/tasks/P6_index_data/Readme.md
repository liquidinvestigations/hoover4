# P6 - Index Data

This stage indexes parsed text and metadata into Manticore to enable search and entity retrieval. It is P6, not P4 or P5: entity extraction (P4) and chunk embedding (P5) both run before it.

## Key Responsibilities

- Load plan item hashes and fetch text content for indexing.
- Read the `entity_hit` rows written by the P4 entity-extraction stage and map entity values to string-term ids (cache hits — P4 already populated the `ner` term dictionary; ids are content-derived via `hash_string_to_uint63`).
- Build metadata indexes for file types, MIME types, extensions, and paths.

## Entry Points

- Workflow: `IndexDatasetPlan` in `workflows.py`
- Activities: `index_text_content`, `index_metadatas` in `activities.py`
- Helpers: `string_term_encodings.py`; `fetch_plan_hashes` and `clean_text` are shared and live in `tasks/plan_utils.py`

## Technical Details

Indexing batches items in fixed chunk sizes (`INDEX_ROW_CHUNK_SIZE = 512`) to limit transaction sizes. Entity MVAs (`ner_per/org/loc/misc`) are built from `entity_hit`; if a segment has no `nlp_processed` watermark the stage logs a WARNING and indexes it with empty entity MVAs — a missing entity list must not block search. String term IDs are derived from deterministic hashes and stored in lookup tables for reuse.

## Usage

- Triggered by P2 after the P4 entity-extraction stage completes.
- Indexing activities run on `processing-indexing-queue`.

## Navigation

- [Go Back](../Readme.md)
- [P4 - Extract Entities](../P4_extract_entities/Readme.md)
