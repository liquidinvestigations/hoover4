# Recurring diagnostics

Run each through the scripts beside this file. The table names below are stable; the
database name is per collection, so list it first rather than constructing it.

## Contents

- [Finding the database](#finding-the-database)
- [Per-stage counts](#per-stage-counts)
- [Tracing one document](#tracing-one-document)
- [Progress and timing](#progress-and-timing)
- [Search engine](#search-engine)
- [Object store](#object-store)
- [Reading a result honestly](#reading-a-result-honestly)

## Finding the database

```
ch.sh "SHOW DATABASES"
```

One database per collection, named for it, plus a global database holding everything that is
not collection-scoped: the collection registry, users and groups, sessions, chat, model
configuration, stage timing samples and the operations table.

## Per-stage counts

Each answers one stage's "did it happen".

| stage | table | reads as |
|---|---|---|
| disk scan | `vfs_files`, `vfs_directories`, `vfs_nodes` | what the scan found |
| bytes stored | `blobs`, `blob_values` | content-addressed blobs; duplicates collapse, so this is below the file count on any real corpus |
| planning | `processing_plans`, `processing_plan_finished` | what work was scheduled and what completed |
| text extraction | `text_content` | one row per page or segment, grouped by `extracted_by` |
| file typing | `file_types`, `file_type_canonical` | the canonical type resolved per hash |
| entity extraction | `entity_hit`, `regex_entity_hit`, `regex_scanned` | model hits, pattern hits, and the marker that a document was scanned at all |
| indexing | `index_state`, `manticore_shards`, `manticore_shard_assignments` | which shard a file went to, and whether the shard is live |
| errors | `processing_errors` | the stage's own record of what it could not do |

`vfs_files` is a replacing table keyed on collection, container and path, with a deletion
flag. Counting it without accounting for that counts tombstones as files, filter them out
or use the final-state form.

## Tracing one document

Three entry points, all in the collection database:

- **by path**: `vfs_files` on the path column gives the container hash and the blob hash;
- **by blob hash**: `blobs` gives the stored object path and size, `text_content` gives its
  pages per extractor, `regex_entity_hit` gives its pattern hits;
- **by id**. Whatever id you have came from the search engine, which carries the hash beside
  it.

The stored object path in `blobs` is the authority for **which bucket** the bytes are in.
Rebuilding that from configuration works on one collection and fails on the next.

## Progress and timing

Stage timing samples live in the global database's `processing_eta_samples`. Its stage
identifiers are stored strings that are mirrored as constants in the shared Rust types. The
admin processing view reads the same values, so a stage identifier that exists on one side
only makes a bar disappear with no error.

`processing_task_runs` carries per-task durations, which is what answers "where is the time
going" before any tuning decision: `tuning-the-pipeline`.

## Search engine

```
manticore.sh "SHOW TABLES"
manticore.sh "SELECT count(*) FROM <collection>_<shard>_pages"
manticore.sh "SHOW TABLE <collection>_<shard>_pages STATUS"
```

One denormalised page table per shard, a per-collection entities table, and a per-collection
tree table. No join: the page table carries what a result needs.

The tree table is read **uncached** by the site, deliberately, because it changes while
ingestion runs.

## Object store

```
garage.sh bucket list
garage.sh bucket info <bucket>
garage.sh status
```

A bucket per collection plus a system bucket. Derived output (searchable PDFs, chat
artefacts) lives under a prefix that the disk-scan stage must never walk, and the
end-to-end verification asserts that no blob row references it.

## Reading a result honestly

- A row binds **by column name**. A renamed or aliased column silently binds nothing.
- An alias **shadows** the column it derives from: after `AS ts`, `ts` is the alias.
- An aggregate returns a row over an empty match. `count()` returning one row of `0` is not
  "there is data". For existence, ask for the rows.
- An enum is written by **name** and read back as an **ordinal**. A comparison against the
  name on the read side matches nothing and raises nothing.
