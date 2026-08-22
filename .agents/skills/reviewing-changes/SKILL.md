---
name: reviewing-changes
description: Reviews a diff against the invariants that this specific repository breaks silently — the ones a compiler, a linter and a passing test suite all miss. Use before committing, when asked to "review my changes", "check this over", "does this look right", "anything wrong with this diff", or after a sub-agent reports work done. Covers the cross-language mirrored constants, the text-page and extractor-key writer contracts, the migration runner's naive statement split, ClickHouse and Temporal wire-format traps that fail as silence rather than as errors, Dioxus hook ordering, the storage-key permission rule, and the specification row that must move in the same patch as the code.
allowed-tools: Bash, Read, Grep, Glob
---

# Reviewing changes in this repository

The defects worth looking for here are the ones that **do not raise**. Everything that raises
is already found by `cargo check`, the unit tests and a page load. Read the diff for the
list below, in this order.

## First, read the diff — all of it

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
The convention is implemented twice on purpose — once in Python, once in Rust — and neither
runtime may depend on the other being right. Call the shared formatter; never build the
string in a component.

**A bucket rebuilt from the environment instead of read from the row.** Blob storage is a
bucket per collection. Readers take the bucket out of `blobs.s3_path`; a reader that
reconstructs it from its own configuration works on one collection and fails on the next.

**A storage id treated as a capability.** A `chat_artifacts` id reaches the backend through a
tool payload written by a model. Every read resolves it to its owner and enforces
owner-or-admin, and someone else's id is a **403, not a 404** — collapsing the two hides a
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
column it is derived from, and an aggregate returns a row even over an empty match — so
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
its first step. Note that `if ! f` does **not** fix this — inverting a return value suppresses
`set -e` inside the body exactly as a `||` list does. The honesty has to live in the function:
every failure path records a failure before returning.

**An aggregate field that claims more than it knows.** A "which queries found this hit" list
repeated the same query, because one query's ranking can carry a page more than once across
shards — so the field asserted corroboration that did not exist, **inverting the meaning of the
only signal it added**. Every unit test and both type checks passed. Check that a derived
signal cannot report the opposite of the truth.

**A comment made false by the change.** The most common real defect in this tree. Fix it in
the same patch — `writing-project-docs`.

**An edit inside an already-applied migration.** The runner records an md5 of the whole file,
comments included, so correcting a stale word in one makes it refuse to start on every
deployment that already ran it. A prose sweep that reaches the migration directories has gone
too far.

## Then the standing checks

- **The specification moved with the code.** A change that adds, removes or re-scopes a
  capability edits its row in `docs/technical-specification/` in the same patch. A capability
  with no row was never agreed; a row with no code is a lie.
- **The `Readme.md` beside the code is true again**, and the patch to it is as small as the
  code patch that prompted it.
- **No private infrastructure detail** anywhere in the diff — no hostname, address, port
  identifying a real host, credential, or description of an authentication boundary. Those
  live only in the gitignored `INFRASTRUCTURE_INVENTORY.md`.
- **No scratch-folder reference, no date, no history of the work** in any added prose. That
  includes a bare tag coined in a plan folder — `D22`, `S13` — in a comment or a `Readme.md`;
  `.agents/check-doc-ids.py` names them, and the fix is to state the fact instead.
- **A new configuration key has a consumer in the same change**, or is written down as
  not-yet-implemented. A key that is rendered and read by nothing is a lie.
- **The commit message is one lowercase line** under about fifty characters, and nothing
  else.

## References

- `reference/checklist.md` — the same list as a run-through, with the command that settles
  each item.
