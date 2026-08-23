# P_ops — the operations layer

Everything long that a person can start is an **operation**: a row in the global
`operations` table, and a Temporal workflow whose id *is* that row's `op_id`.

## Why the identity matters more than the table

A command that drives multi-stage work from the client is only as durable as the client.
When the sequencing of scan → compute plans → execute plans lived in the CLI, killing the
CLI left a half-built collection and no record anywhere that the command had been run: the
workflow history ages out in a day, and the terminal was gone.

Making the operation id the workflow id fixes both halves at once. The caller's only unique
knowledge is a string it has already printed, so anything holding that string can find the
execution again, and the row outlives the history because it has no retention at all.

That is why Ctrl-C in the CLI **detaches**. It ends a view. Nothing the work depends on is
in the process that was watching.

## The lock

A second dispatch is refused while a non-terminal row exists for the same kind and target.
Which identifier is "the target" is a property of the kind — a dataset kind locks on the
dataset, a collection kind on the collection — so a dataset-scoped operation is not blocked
by a collection-scoped one that is not touching it.

**A stale row is not free.** There is deliberately no timeout that releases the lock when a
run stops reporting: a run that stopped updating may still have activities in flight, and
releasing on a clock would start a second writer beside a live one. Cancelling the operation
is how a lock is released early, and it lands the row in `cancelled` — a state of its own,
not a failure, and re-runnable, because every pipeline stage is idempotent.

The lock check and the row insert are not atomic, and cannot be against ClickHouse. The
workflow id is the second guard: two dispatches that both pass the check still mint
different ids and both run, and the stages underneath them tolerate that.

## Who writes the row

The **workflow** writes `running` on entry, refreshes progress while the real work runs
beneath it, and writes exactly one of `finished` or `errored` with `finished_at` set. That
terminal write is what releases the lock, so it is on the way out of every path.

`cancelled` is the exception, and it is written by whoever requested the cancellation. A
cancelled workflow cannot schedule further activities, so a cleanup write attempted inside
it would be cancelled with it and the row would stay non-terminal for ever, holding the lock
that cancelling was meant to release.

**A row that has already landed terminal is never moved again.** A cancellation lands the
row from outside while the workflow is still unwinding, and the workflow's own failure path
arrives a moment later; without that rule the late write relabels the cancellation as an
error, and the row then reports the opposite of what happened.

**And the workflow's own late write says `cancelled` too.** A cancellation reaches the
failure path wrapped as an activity failure, so the guard above is not enough on its own:
the two writes can land in the same second and whichever is second decides the state. The
state is therefore read off the failure chain — a chain containing a cancellation is a
cancellation — so both writers agree and the order between them stops mattering.

## What each kind drives

`add_dataset` and `rescan_dataset` drive the ingest chain, and `compute_plans` and
`execute_plans` drive one of its stages alone; `reindex_collection` rebuilds a collection's
shard tables from its finished plans; `ensure_collection` and `drop_collection_database`
provision and remove a collection's database; `purge_dataset`, `delete_dataset`,
`change_ocr_languages` and `retry_failed_files` each drive their own child workflow or
chain of them; `export_collection` writes a backup (below). `delete_dataset` is a purge with the registry row tombstoned first, so an
interrupted deletion leaves rows nothing routes to rather than a live dataset missing half
its data — and the log distinguishes a dataset that was retired from one whose data was
cleaned out from under it. Every child
is addressed **by name**, never by importing its class: importing drags the pipeline's
module graph through the workflow sandbox's importer, where a re-imported C extension fails
with a bare `SystemError` naming nothing in this repository — and the operations container
has no business loading the pipeline's dependencies anyway, since it schedules that work
rather than running it.

A kind the workflow cannot drive fails honestly: the row errors naming the kind. The table
accepts more kinds than the workflow drives, on purpose, so a row can exist for work another
surface performs.

## Progress and estimates

Progress is whatever that kind can honestly count, and the unit differs by kind: an ingest,
an OCR-language change and a plan execution count **plans**, a retry counts the plans it
re-runs, and a purge or a delete counts **rows still in the stores**, so its bar moves with
the deletion rather than with the number of activities that have returned. A purge excludes
the two task-telemetry tables it writes to while it runs — an operation counting its own
telemetry as work left to do could never reach its total.

**Three kinds have no progress fraction at all, deliberately.** `compute_plans` writes
every plan in one statement, and `ensure_collection` and `drop_collection_database` are one
activity each, so none of them has a unit that finishes repeatedly and none has an honest
denominator. Their counters stay at zero and their result string says what happened. A bar
invented for them would sit empty and then be full, which reports less than no bar.

A plan is the unit the pipeline finishes, and the only one whose total is known before the
work is done, which is why so many kinds count it. The estimate is derived from this
operation's own elapsed time rather than from the global ETA sampler, so it is right for
this run's data even when nothing comparable has been ingested before. `progress_total = 0`
means "not yet known", which is a different statement from "no work".

`detail` is JSON and is merged rather than overwritten, so two writers of different counters
do not erase each other. Per-stage and per-document counters belong there.

## The queues

Four, served from one process in the `hoover4-ops` container. The slot counts are the point
of the split, not the split itself:

| queue | slots | what runs there |
|---|---|---|
| `operations-queue` | 8 | the operation workflows — orchestration only |
| `operations-clickhouse-queue` | 1 | ClickHouse backup and restore driving and polling |
| `operations-manticore-queue` | 2 | Manticore backup, decompress, import |
| `operations-garage-queue` | 2 | object-store enumerate, get, put, volume writing |

ClickHouse gets exactly one because concurrent backups and restores are disabled in its
server config anyway: a second slot would only queue inside ClickHouse, where nothing here
can see it.

Each store queue carries that store's own export work and nothing else, so a long object
copy cannot take the single ClickHouse slot.

## The backup format

`export_collection` writes one directory per backup under the configured root. A caller
names a **subdirectory**, never a path, so a directory that is not mounted into this
container cannot be asked for.

```
<root>/<destination>/
  manifest.json                      what is here, how big it is, and what it checks against
  garage/vol-000.tar ...             the collection's objects, uncompressed
  garage/objects.json.gz             key -> (volume, offset, size, etag)
  clickhouse/clickhouse-<op_id>.tar  BACKUP DATABASE, uncompressed
  manticore/<table>.tar.zst          one artifact per shard table, zstd
```

Every choice in it is measured. The ClickHouse artifact is an **uncompressed tar** because
the only compressed single-file shape ClickHouse offers is a deflate zip, its part files are
already compressed internally, and deflating them again bought 1.38x for twenty percent more
time. The object payload is **not compressed** because the blobs are already-compressed
documents behind a write path that tops out around 27 MB/s, so re-compressing spends
processor time on the wrong side of the bottleneck — its key manifest is compressed, and a
million entries costs 8.3 MB and under a second. Manticore artifacts are compressed because
a text index compresses well, though a collection dominated by vector tables compresses far
less than a text-only one.

**ClickHouse writes its own artifact straight into the backup directory**, because the
backup root is mounted onto its `backups/` path as well as onto this container's. Nothing is
copied afterwards, which matters: this container holds the store volumes read-only and could
neither delete an original nor hard-link one — **a cross-mount hard link is refused even
inside one filesystem, so a backup copies bytes.**

Manticore is taken with `FREEZE`, which flushes the table's RAM chunk, holds it read-only
and answers with the exact file list. Copying a live table's directory without it captures
an unflushed chunk mid-write. Every freeze is released on the way out, including out of a
failure: a table left frozen accepts no more writes.

**Order is object store, then ClickHouse, then Manticore.** No two stores can be snapshotted
together, so the order decides what a backup taken during ingestion leaves behind: an
orphaned blob rather than a row pointing at a blob that was never copied.

**A failed or cancelled export blocks nothing.** Everything is written into
`<destination>.partial-<op_id>/` and renamed onto `<destination>/` only when the manifest is
complete, so an incomplete run leaves a directory that says so in its name and a later
attempt at the same name succeeds. The ClickHouse `.lock` a failed `BACKUP` leaves behind is
inside that directory and carries the operation id, so it can never block a re-run either.

Progress is **bytes, one named phase per store**, and every denominator comes from the store
itself: the object listing, ClickHouse's own byte counter polled out of `system.backups`, and
the sizes of the frozen Manticore files. No store knows another's total, so a single
denominator across all three would only exist once the backup was over; the phase is named
in `detail` and the per-store sizes accumulate there as each one lands.

The manifest carries the collection's own rows — the collection, its group permissions, its
datasets and their settings, the server settings and the schema versions — because they are
small and they are what makes a restored collection *configured* rather than merely present.
Artifacts this container writes carry a sha256 taken as they are written; the ClickHouse
archive carries ClickHouse's own per-file checksums inside it instead, so an outer digest
would cost a second full read of the largest artifact and guarantee nothing the inner ones
do not.

**Original source data is not in a backup.** It is held outside this system.

## Navigation

- [Go Back](../Readme.md)
- [../../database/Readme.md](../../database/Readme.md)
