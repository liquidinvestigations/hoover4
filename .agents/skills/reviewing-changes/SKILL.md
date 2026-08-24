---
name: reviewing-changes
description: Reviews a diff against the invariants that this specific repository breaks silently, meaning the ones a compiler, a linter and a passing test suite all miss. Use before committing, when asked to "review my changes", "check this over", "does this look right", "anything wrong with this diff", or after a sub-agent reports work done. Covers the cross-language mirrored constants, the text-page and extractor-key writer contracts, the migration runner's naive statement split, ClickHouse and Temporal wire-format traps that fail as silence rather than as errors, Dioxus hook ordering, the storage-key permission rule, and the specification row that must move in the same patch as the code.
allowed-tools: Bash, Read, Grep, Glob
---

# Reviewing changes in this repository

The defects worth looking for here are the ones that **do not raise**. Everything that raises
is already found by `cargo check`, the unit tests and a page load. Read the diff for the
list below, in this order.

## First, read the diff: all of it

```
git diff HEAD              # or the range the work covers
git status --short         # what would actually be staged
.agents/skills/reviewing-changes/scripts/check-diff-comments.sh
```

A report of what changed is not a review. So is a summary written by whoever made the change.

## The silent-failure checklist

**Mirrored constants moved on one side only.** `STAGE_INDEX` and its siblings are stored
values in `processing_eta_samples` *and* Rust constants in
`website/common/src/processing_types.rs`. Both sides move together or the admin processing
page loses a bar with no error anywhere.

**`insert_text_pages` called more than once for one `(file, extracted_by)`.** It trims rows
above the highest page it writes, so a second call for the same variant silently deletes the
first call's pages. It must be called once, with the complete page list.

**`text_content.page_id` written as 0.** It is a real 1-based page number for paged formats
and a 1-based segment ordinal otherwise. Never 0.

**`extracted_by` formatted ad hoc.** It is a storage key and a user-visible label at once.
The convention is implemented twice on purpose (once in Python, once in Rust), and neither
runtime may depend on the other being right. Call the shared formatter; never build the
string in a component.

**A bucket rebuilt from the environment instead of read from the row.** Blob storage is a
bucket per collection. Readers take the bucket out of `blobs.s3_path`; a reader that
reconstructs it from its own configuration works on one collection and fails on the next.

**A storage id treated as a capability.** A `chat_artifacts` id reaches the backend through a
tool payload written by a model. Every read resolves it to its owner and enforces
owner-or-admin, and someone else's id is a **403, not a 404**. Collapsing the two hides a
real permission failure behind an apparent missing row.

**A migration whose statements do not survive the runner's split.** The runner splits on `;`
without parsing SQL. Three ways to break it, none of which name the file or line in the
error: a semicolon inside a `COMMENT '...'` literal, a semicolon inside a `--` comment, and
prose after the final terminator, which reaches the server as an empty query. Put explanatory
comments **above** the statement they describe.

**A Temporal activity argument that lost its annotation.** Temporal deserialises into the
*annotated* type; an unannotated parameter arrives as a dict and the feature quietly does
nothing.

**A ClickHouse `Enum8` written by name and read as a number.** Insert takes the name, read
returns the ordinal. Also: a result row matches by **column name**, an alias shadows the
column it is derived from, and an aggregate returns a row even over an empty match, so
"there is a row" is not "there is data".

**A Dioxus hook behind a condition.** It traps the WebAssembly runtime on the render that
adds it and leaves the page painted and inert. `cargo check` is clean; a release build says
only `unreachable`. `dx check --package frontend` names the site.

**A structure query routed through the search cache.** The collection's tree changes while
ingestion runs, so it is read uncached deliberately. A stale tree is worse than a slow one.

**A field name on a wire that both type checks accept.** A Temporal dispatch shipped here
naming a conflict-policy field the HTTP API rejects outright. `cargo check` and `dx check` were
both green over it; it failed as an error string in a database row, and the feature had never
worked. **A call across a wire is verified by making the call**, never by the build.

**A gate that cannot fail.** A verification function was called in a `|| true` list, which
discarded its return, so the run printed *all checks passed* over a check that had aborted at
its first step. Note that `if ! f` does **not** fix this. Inverting a return value suppresses
`set -e` inside the body exactly as a `||` list does. The accuracy has to live in the function:
every failure path records a failure before returning.

**An aggregate field that claims more than it knows.** A "which queries found this hit" list
repeated the same query, because one query's ranking can carry a page more than once across
shards, so the field asserted corroboration that did not exist, **inverting the meaning of the
only signal it added**. Every unit test and both type checks passed. Check that a derived
signal cannot report the opposite of the truth.

**A comment made false by the change.** The most common real defect in this tree. Fix it in
the same patch: `writing-project-docs`.

**An edit inside an already-applied migration.** The runner records an md5 of the whole file,
comments included, so correcting a stale word in one makes it refuse to start on every
deployment that already ran it. A prose sweep that reaches the migration directories has gone
too far.

## Reviewing against the plan

The checklist above covers whether the code is right. This section covers whether the code is
what the plan asked for, which is a different question and a short one to answer, because the
tree already holds the fixed point. A work package stamps the commit it was written against,
and a plan folder holds the scope it agreed.

Read the scope list against the diff, and report, item by item, what the diff did not do. Keep
this separate from the silent-failure checklist above, which is about defects rather than about
scope.

## The four shape tests

These read the design rather than the defect, so they also apply when a plan is deciding how to
structure something. `planning-work` loads this skill for that.

**1. A file that crossed a size threshold by a large delta.** Ask whether the code should be
decomposed before the change lands, and ask it **only when the growth is large**. Measured over
one fortnight here, nine files crossed 1000 lines in nine commits. Three deserved a yes, and they
were the ones that gained a whole new responsibility: a shared type file whose growth is why one
feature needs mirrored edits in two languages, a worker entry point that absorbed an entire
operations layer, and an indexing module that gained a graph builder. The other six gained 40 to
140 lines and crossed an arbitrary line. **Trigger on the delta, not on the total.** One useful
finding for two false alarms is below the rate at which a reviewer stops reading the output.

**2. A repeated conditional that signals a missing model.** The same branch written three times
over the same value is a type that was never named. Found here as a progress counter that could
never reach its own total, because a purge counted the telemetry rows it wrote about itself. Two
populations, one counter, no type separating them.

**3. An abstraction that adds indirection and buys nothing.** Ask what it removes. Found here as
a compaction step that made the context bigger, evicting a 91-character result to insert a
127-character placeholder. **One adapter is hypothetical and two are real**: a layer with a
single implementation is a guess about a second one.

**4. A module that has to be tested past its interface.** If a test reaches inside to set up a
case the interface cannot express, the interface is the wrong shape. This is the cheapest of the
four to check, because the test file says so directly.

## The demanding pass

Ordinary review reads the diff for the checklist above. **A demanding pass is a second reading
with a different question: what would have to be true for this to be wrong.** Take it when the
change touches a wire format, a permission, a migration, or a counter that someone will trust.

Three rules make it worth the second reading.

- **Open every location before repeating a finding.** A report that a location is wrong is a
  claim, including your own from ten minutes ago. Expect three failure classes: behaviour that is
  by design reported as a fault, a real finding attributed to the wrong file, and the same
  finding counted twice.
- **Say which checks you ran and which you took on trust.** Collapsing the two is how an
  unverified claim reaches the tree.
- **Write down what you considered and rejected**, one line each, in the rejection register at
  the bottom of `plans/TODO.md` and `plans/DEFECTS.md`. Without it the next pass raises the same
  item, which this repository's archive shows happening repeatedly.

## Then the standing checks

- **The specification moved with the code.** A change that adds, removes or re-scopes a
  capability edits its row in `docs/technical-specification/` in the same patch. A capability
  with no row was never agreed; a row with no code is false.
- **The `Readme.md` beside the code is true again**, and the patch to it is as small as the
  code patch that prompted it.
- **No private infrastructure detail** anywhere in the diff, no hostname, address, port
  identifying a real host, credential, or description of an authentication boundary. Those
  live only in the gitignored `INFRASTRUCTURE_INVENTORY.md`.
- **No scratch-folder reference, no date, no history of the work** in any added prose. That
  includes a bare tag coined in a plan folder (`D22`, `S13`) in a comment or a `Readme.md`;
  `.agents/check-doc-ids.py` names them, and the fix is to state the fact instead.
- **A new configuration key has a consumer in the same change**, or is written down as
  not-yet-implemented. A key that is rendered and read by nothing is false.
- **The commit message is one lowercase line** under about fifty characters, and nothing
  else.

## References

- `reference/checklist.md`, the same list as a run-through, with the command that settles
  each item.
