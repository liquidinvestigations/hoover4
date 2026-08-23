---
name: querying-the-datastores
description: Answers "is the data actually there" against ClickHouse, Manticore and the object store. Use when asked "how many rows", "did it index", "check the table", "is it in the database", "what's in clickhouse", "query manticore", "list the buckets", "find this document", or when a count has to be confirmed rather than assumed. Ships the client invocations as scripts so the credentials are never typed or guessed, and covers the per-collection database and bucket naming, the counts that answer each pipeline stage, and three result-reading traps that return a plausible answer instead of raising.
allowed-tools: Bash, Read, Grep, Glob
---

# Querying the datastores

Every claim about data ends here. Reading the code that writes a row is not evidence that the
row exists.

## Run the scripts; do not retype the client line

```
.agents/skills/querying-the-datastores/scripts/ch.sh "SELECT count() FROM ..."
.agents/skills/querying-the-datastores/scripts/manticore.sh "SHOW TABLES"
.agents/skills/querying-the-datastores/scripts/garage.sh bucket list
```

`ch.sh` takes the user and password **from the ClickHouse container's own environment**, so
there is no credential in any tracked file and no second form to get wrong. Two different
hand-typed spellings were in circulation before this script existed; that is what it is for.

## Naming

- **ClickHouse**: one database per collection, plus a global database for everything that is
  not collection-scoped. `ch.sh "SHOW DATABASES"` lists what actually exists. Do not
  construct the name from a collection name you were told.
- **Manticore**: one denormalised page table per shard, plus a per-collection entities table
  and a per-collection tree table. There is no join; the page table carries what a result
  needs.
- **Object store**: a bucket per collection, plus a system bucket. **Readers take the bucket
  out of the row's stored path** rather than rebuilding it, and derived output lives under a
  prefix that the disk-scan stage must never walk.

## What to count for each question

| question | count |
|---|---|
| did the scan see the files | rows in the file table for the collection and dataset |
| are the bytes stored | rows in the blob table, and the object store's own listing |
| did text extraction produce anything | text-page rows, grouped by the extractor key |
| did entity extraction run | entity-hit rows, and the scanned-marker rows beside them |
| did indexing land | per-shard counts in the search engine, against the file count |
| where is the time going | the stored stage timing samples |

`reference/queries.md` has the shape of each of these, and how to trace a single document end
to end by path, by hash and by id.

## Three traps that return an answer instead of raising

**A result row matches by column name.** A row is deserialised by name, not by position, so a
renamed or aliased column silently binds nothing and you read a default.

**An alias shadows the column it is derived from.** `SELECT toDate(ts) AS ts` produces a
column named `ts` that is no longer the column you filtered on, and every later reference
resolves to the alias.

**An aggregate returns a row over an empty match.** `SELECT count() FROM t WHERE <nothing
matches>` returns one row containing zero. "There is a row" is not "there is data". Read
the value, and for existence questions ask for the rows themselves.

## The one query family that must not be cached

The collection's folder tree changes while ingestion runs, so it is read through the uncached
primitive deliberately. A stale tree is worse than a slow one. Ordinary search keeps using
the caching primitive. That cache is what keeps repeated facet fan-outs off the search
engine.

## References

- `reference/queries.md`, the recurring diagnostics with their exact shape, tracing one
  document end to end, and reading the stage timing samples.
