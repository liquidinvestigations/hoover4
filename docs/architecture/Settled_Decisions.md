# Settled decisions

Decisions that look like defects to a reader who does not know the reason, and that keep being
re-opened because of it. Each entry states what is true and why, so the next reader can stop
rather than re-argue.

A decision belongs here when three things hold. A person decided it. It has been questioned at
least once, or it reads like a fault to someone who does not know the reason. Nothing scheduled
will change it. A decision nobody questions needs no defence, and a decision waiting on work is a
plan.

**A decision that already has a home stays there.** The denormalised search index is explained in
[`Search_Architecture.md`](Search_Architecture.md) and [`Storage_Model.md`](Storage_Model.md), and
the one-way configuration flow in
[`../operations/Configuration_Reference.md`](../operations/Configuration_Reference.md). This page
holds what those pages have no room for.

## An applied migration is never edited

The migration runner records an md5 of the whole file, comments included. Correcting a stale word
in a migration that has already run therefore makes the runner refuse to start on every
deployment that applied it.

The consequence reaches ordinary work: `db_global_migrations/` and `db_collection_migrations/`
are not touched, including to fix a comment that a change has made false. The correction goes
into a new numbered file, or beside the code that reads the table. Editing an applied migration
is a decision the repository owner takes, and it comes with resetting every deployment that ran
it.
