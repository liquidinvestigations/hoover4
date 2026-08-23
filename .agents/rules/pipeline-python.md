---
name: pipeline-python
description: Invariants that hold while editing the Temporal pipeline's Python.
paths: main_services/processing/**/*.py
---

# Editing the pipeline

**The stages are P0–P4, P5 (chunk and embed, reserved) and P6 (index).** Indexing is P6, not
P5: the embedding stage owns the number that runs before it.

**Stage identifiers are mirrored across the language boundary.** `STAGE_INDEX` and its
siblings are stored values in `processing_eta_samples` and constants in
`website/common/src/processing_types.rs`. Both sides move in the same patch, or the admin
processing view silently loses a bar.

**`text_content.page_id` is never 0.** It is a real 1-based page number for paged formats and
a 1-based segment ordinal otherwise.

**`insert_text_pages` is called once per `(file, extracted_by)`, with the complete page
list.** It trims rows above the highest page it writes, so a second call for the same variant
deletes the first call's pages. Every writer goes through it.

**`extracted_by` is a storage key and a user-visible label at once.** OCR variants carry an
engine-and-language prefix; native extractors carry none. The convention is implemented twice
on purpose (once here, once in the shared Rust types), and neither runtime may depend on the
other being right. Call the shared formatter; never assemble or parse the string in place.

**A bucket comes out of the row, not out of the environment.** Blob storage is a bucket per
collection; readers split the stored path. Reconstructing the bucket from configuration works
on one collection and fails on the next.

## Two wire formats that fail as silence

**Temporal deserialises an activity argument into its annotated type.** An unannotated
parameter arrives as a dict and the feature quietly does nothing. Annotate every one.

**A ClickHouse `Enum8` takes the name on insert and returns the ordinal on read.** A read-side
comparison against the name matches nothing and raises nothing.

## Timeouts

`requests`' `timeout=` is in **seconds**. Use a `(connect, read)` two-tuple so a dead host is
detected in seconds while real work still gets minutes. Detection latency must never be tied
to how long the slowest legitimate run takes.

## Shelled-out binaries

A binary that is not in the image fails silently when the wrapper catches the missing-file
error, and the caller reads the empty result as a property of the corpus. When a parser
produces suspiciously little, check that the binary is present in the image before reading
any of its code.

## Before you report it done

Run the unit tests, and re-run the comment check over your diff:

```
.agents/skills/verifying-before-claiming/scripts/pytest-unit.sh
.agents/skills/reviewing-changes/scripts/check-diff-comments.sh
```
