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

## Progress and estimates

For an ingest, progress is counted in **plans**: the unit the pipeline finishes, and the
only one whose total is known before the work is done. The estimate is derived from this
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

The three store queues currently carry only the row writer. They are declared ahead of the
activities that will use them because a workflow that addresses a queue nothing is polling
waits for ever, with no error anywhere to say why.

## Navigation

- [Go Back](../Readme.md)
- [../../database/Readme.md](../../database/Readme.md)
