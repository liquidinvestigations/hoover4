# Datastore diagnostics

The recurring queries against ClickHouse, the search engine and the object store, and what
each one answers. **The scripts beside the querying skill are what gets run**; this page
explains what each is for.

```
.agents/skills/querying-the-datastores/scripts/ch.sh "<query>"
.agents/skills/querying-the-datastores/scripts/manticore.sh "<sql>"
.agents/skills/querying-the-datastores/scripts/garage.sh <command>
```

## Contents

- [The credential question, settled](#the-credential-question-settled)
- [Finding the database](#finding-the-database)
- [Per-stage counts](#per-stage-counts)
- [Tracing one document](#tracing-one-document)
- [Progress and timing](#progress-and-timing)
- [The search engine](#the-search-engine)
- [The object store](#the-object-store)
- [Three traps that return an answer instead of raising](#three-traps-that-return-an-answer-instead-of-raising)

## The credential question, settled

Two hand-typed spellings of the client invocation have been in circulation, which is the
reason this page exists. **The canonical form takes the user and password out of the server
container's own environment**, so there is nothing to remember, nothing to get wrong, and no
credential in any tracked file:

```
docker exec -i clickhouse sh -lc \
  'clickhouse-client -u "$CLICKHOUSE_USER" --password "$CLICKHOUSE_PASSWORD" --query "$1"' _ "<query>"
```

That is what `ch.sh` runs. It is also correct after a credential change, which a written-down
pair is not.

## Finding the database

```
ch.sh "SHOW DATABASES"
```

One database per collection, named for it, plus one global database. **List them; do not
construct a name** from a collection name you were told — the naming convention is the
backend's business, and a typo produces "table does not exist" rather than anything useful.

The global database holds the collection and dataset registries, users, groups and
permissions, sessions, settings, the search cache, chat, model configuration, the stage
timing samples, the operations table, and the short-window telemetry.

## Per-stage counts

Each answers one stage's "did it happen", in pipeline order.

| question | tables |
|---|---|
| did the scan see the files | `vfs_files`, `vfs_directories`, `vfs_nodes` |
| are the bytes stored | `blobs`, `blob_values`, and the object store's own listing |
| what was planned, and what finished | `processing_plans`, `processing_plan_finished` |
| did text extraction produce anything | `text_content`, grouped by `extracted_by` |
| what type is each file | `file_types`, `file_type_canonical` |
| did entity extraction run | `entity_hit`, `regex_entity_hit`, `regex_scanned` |
| did chunking and embedding run | `text_chunks`, `text_chunk_vectors` |
| did indexing land | `index_state`, `manticore_shards`, `manticore_shard_assignments` |
| what failed | `processing_errors` |

Two counting rules that catch people out:

- **The blob count is below the file count** on any real corpus, because content is
  deduplicated. That is not a missing-data signal.
- **`vfs_files` is a replacing table with a deletion mark.** A plain count includes
  superseded rows and tombstones; read the final state, or filter the mark.

## Tracing one document

Three entry points, all in the collection's database:

- **by path** — `vfs_files` gives the container hash and the content hash;
- **by content hash** — `blobs` gives the stored object path and size, `text_content` gives
  its pages per extractor, the entity tables give its hits;
- **by search result** — whatever identifier the search engine returned carries the hash
  beside it.

**The stored object path in `blobs` is the authority for which bucket the bytes are in.**
Rebuilding it from configuration works on one collection and fails on the next.

## Progress and timing

`processing_eta_samples` in the global database carries the rolling per-stage progress the
admin processing view draws. Its stage identifiers are stored strings mirrored as constants
in the shared Rust types — a stage identifier that exists on one side only makes a bar
disappear with no error anywhere.

`processing_task_runs` carries per-activity durations, one row per **attempt**: a retry is a
second execution and gets a second row, which is what makes "this task costs forty minutes"
include the time spent failing. That is the table to read before any tuning decision.

## The search engine

```
manticore.sh "SHOW TABLES"
manticore.sh "SELECT count(*) FROM <collection>_<shard>_pages"
manticore.sh "SHOW TABLE <collection>_<shard>_pages STATUS"
```

One denormalised page table per shard, one entities table per collection, one tree table per
collection, and a disposable nearest-neighbour table per shard. There is no join: the page
table carries what a result needs.

**The tree table is read uncached by the site**, deliberately, because it changes while
ingestion runs and a stale tree is worse than a slow one. Ordinary search goes through the
cache, which is what keeps repeated facet fan-outs off the engine.

**The index is not the authority on which datasets exist.** It keeps whatever was written
under a name until something deletes it, so an abandoned ingest goes on producing buckets
with real counts. The registry is the authority, and the purge entry point is what removes
orphan rows.

## The object store

```
garage.sh bucket list
garage.sh bucket info <bucket>
garage.sh status
```

A bucket per collection plus a system bucket. Derived output lives under a prefix the
disk-scan stage must never walk, and the stack verification asserts that no blob row
references it — a row that does is the signature of a re-ingestion loop having started.

The store's image carries no shell, so its command-line tool is invoked directly rather than
through one.

## Three traps that return an answer instead of raising

**A result row binds by column name.** A renamed or aliased column silently binds nothing and
the reader sees a default.

**An alias shadows the column it derives from.** After `AS ts`, every later reference to `ts`
resolves to the alias — which is how sibling aggregates end up nested inside one another. The
fix is to aggregate under a distinct inner name and rename on the way out, because renaming
the outer alias breaks the name-based binding above.

**An aggregate returns a row over an empty match.** A count returning one row containing zero
is not "there is data". For existence questions, ask for the rows.
