# Storage model

Where bytes and rows live, what deduplication means for the tables above them, and the two
keys that cross between stores.

## Contents

- [Three stores, one corpus](#three-stores-one-corpus)
- [Content-addressed blobs](#content-addressed-blobs)
- [ClickHouse: a database per collection](#clickhouse-a-database-per-collection)
- [The file tree, and what deletion means](#the-file-tree-and-what-deletion-means)
- [The object store: a bucket per collection](#the-object-store-a-bucket-per-collection)
- [Derived output is never source](#derived-output-is-never-source)
- [The search engine: one denormalised table per shard](#the-search-engine-one-denormalised-table-per-shard)
- [A chat artefact id is a lookup key, never a capability](#a-chat-artefact-id-is-a-lookup-key-never-a-capability)

## Three stores, one corpus

| store | holds | keyed by |
|---|---|---|
| ClickHouse | every row: files, blobs, parsed content, entities, plans, users, chat | `(collection_dataset, hash)` for document data |
| the object store | the bytes of every ingested file, plus derived output | the path recorded in the blob row |
| the search engine | one denormalised copy of what a result needs | `(collection_dataset, file_hash)` |

Nothing is authoritative in two places. The search engine is a copy that can be rebuilt from
ClickHouse; the object store holds bytes ClickHouse only points at.

## Content-addressed blobs

A blob is identified by a content hash, and the same content ingested twice is one blob. The
row also carries the auxiliary hashes a user might paste, the size, and either the object
path or a flag saying the value is small enough to live in ClickHouse itself.

The consequence for every count above it: **the blob count is below the file count on any
real corpus**, because two paths holding the same content are two files and one blob. Parsed
content, entities and chunks all hang off the *hash*, so they are computed once however many
paths point at them.

**Document identity in the index is the pair, not the hash alone.** The same content in two
datasets of one collection is indexed twice, deliberately, because those are two documents
from a reader's point of view. The stack verification asserts exactly that.

## ClickHouse: a database per collection

One global database holds what is not collection-scoped: users, groups, the collection
registry, the dataset registry, sessions, settings, the search cache, chat, model
configuration, the stage timing samples, and the short-window telemetry tables.

Every collection has its own database holding its blobs, its file tree, its parsed content,
its plans and errors, and its term dictionaries. **A dataset's collection is fixed when the
dataset is created** and cannot be moved; creating a collection provisions its database, and
deleting one (allowed only when it holds no datasets) drops it.

The backend resolves the right database per query, immediately after the permission check, so
an unauthorised dataset never reaches a database name. The mapping from dataset to collection
is immutable and is cached in process.

## The file tree, and what deletion means

`vfs_files` holds one current row per path. Three properties of its key decide what the
table can answer:

- **The container hash is part of the sort key.** Without it, two containers holding the same
  inner path collapse into one row and the second container loses its children.
- **The content hash is deliberately *not* in the sort key.** With it, a file whose content
  changed at the same path inserts a second row beside the old one, and the tree then holds
  two versions of one path with no way to say which is current.
- **Deletion is a mark on the row, not a separate tombstone table.** A rescan that finds a
  path gone writes one row, and readers need no anti-join. The rescan is authoritative for
  the paths under its root, which is what makes deletion detectable at all.

The table is a replacing engine versioned on an update timestamp with the deletion mark as
its delete column, so the newest row for a path wins. **A plain count therefore counts
superseded rows and tombstones**: every consumer either reads the final state explicitly or
is wrong.

Removing a document from the index is driven by **reachability from live paths**, not by
walking tombstones: a blob still reachable through another path stays indexed.

## The object store: a bucket per collection

Buckets are named for the collection they hold, alongside one system bucket for everything
that is not collection data.

**Readers take the bucket out of the blob row's stored path.** A reader that rebuilds the
bucket name from its own configuration works on one collection and fails on the next, and
fails by not finding an object rather than by erroring.

## Derived output is never source

Everything the system generates rather than ingests (searchable PDFs, captured chat
artefacts) lives under a `derived/` prefix, and **the disk-scan stage must never walk it.**

The reason is a loop, not tidiness: an artefact the scanner can see would be ingested,
re-derived by the stage that produced it, and produce another, forever. A blob row pointing
into `derived/` is the signature of that loop having started, which is why the stack
verification asserts that no blob row references the prefix.

## The search engine: one denormalised table per shard

A collection's searchable data lives in a dynamic number of shard tables, capped by the
indexing planner on both text bytes and row count, plus one entities table and one tree table
per collection.

**Each document's metadata is denormalised onto every one of its page rows, and there is no
join.** The join this replaced was the single most expensive thing in the search path (a
per-row lookup evaluated before any predicate), and it was also silently wrong, because the
engine's outer join drops unmatched left rows. Denormalised costs about fifteen per cent more
disk and turns a thirteen-second facet into a one-second one. Do not reintroduce a join.

How queries fan out over those shards, and what is exact versus approximate across them, is
[Search architecture](Search_Architecture.md).

## A chat artefact id is a lookup key, never a capability

An artefact id reaches the backend through a tool payload that a language model wrote. Every
read resolves it to its owning session and username and enforces owner-or-admin.

**Someone else's id is a 403, not a 404.** Collapsing the two hides a real permission failure
behind an apparent missing row, and the difference is exactly what an audit of that surface
needs to see. The username is denormalised onto the artefact row so the check never has to
join.

The rows are the **sole** index of those objects' existence. Nothing else in the system
knows they are there, so retention tombstones the row first, deletes the object, and only
then drops the row. A store-level expiry cannot remove an object, which is why the order is
that way round.
