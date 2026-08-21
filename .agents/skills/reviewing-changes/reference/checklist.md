# Review run-through

One pass down the list. Each row names the command or the read that settles it, so a review
is a sequence of answers rather than an impression.

## Mechanical

| check | how |
|---|---|
| the whole diff has been read | `git diff HEAD` — all of it, not a summary |
| what would actually be staged | `git status --short` and `git add -An` |
| comment hygiene on added lines | `.agents/skills/reviewing-changes/scripts/check-diff-comments.sh` |
| the Rust workspace still type-checks, tests included | `.agents/skills/verifying-before-claiming/scripts/cargo-check.sh` |
| no Dioxus hook or `rsx!` defect | `.agents/skills/verifying-before-claiming/scripts/dx-check.sh` |
| the pipeline unit tests pass | `.agents/skills/verifying-before-claiming/scripts/pytest-unit.sh` |
| migrations are well-formed | `.agents/skills/verifying-before-claiming/scripts/pytest-unit.sh tests/unit/test_migrations_parity.py` |
| the specification and the code still agree | `website/tools/check-spec-drift.sh` |

## By eye, because nothing can check them

| check | what you are looking for |
|---|---|
| private infrastructure detail | a hostname, an address, a port that identifies a real host, a credential, a description of an authentication boundary |
| prose that records the work | a date, a commit hash, a scratch-folder reference, "previously", "now that X landed", a `TODO` |
| a comment made false by the change | the diff changed a behaviour and left the sentence above it describing the old one |
| a mirrored constant changed on one side | a `STAGE_*` value, or any type in `website/common/src/` whose Python counterpart did not move |
| a control that renders and does nothing | only a browser walk finds this — `driving-the-browser` |
| a configuration key with no consumer | grep the key across `main_services`, `website` and `deploy.py` |

## Per-area

**Pipeline (`main_services/processing/`)** — text pages written once per `(file,
extracted_by)` with the complete list; `page_id` never 0; `extracted_by` through the shared
formatter; activity parameters annotated with their real type; `requests` timeouts as a
`(connect, read)` two-tuple in **seconds**.

**Migrations** — comments above the statement, never inside it; no `;` inside a `COMMENT`
literal or a `--` comment; nothing after the final terminator.

**Website backend** — every full-text match argument through the shared builder; a storage id
resolved to its owner before it is used, with 403 for a foreign one; the bucket taken from
the row, not from configuration.

**Website frontend** — no hook behind a condition; no emoji, every glyph from the icon crate;
structure queries on the uncached primitive; `rsx!` interpolation of an expression, never a
block.

**Agents and MCP servers** — the vendored shared package means the build context is the
parent directory; one web-search tool, deliberately, because choosing between overlapping
search tools is something a small model does badly.

## Closing

Say which checks you ran in this session and which you did not. A review that lists the
checklist without naming what was run is a claim about a review, not a review.
