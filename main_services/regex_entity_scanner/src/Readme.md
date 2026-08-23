# `src/`

The scanner and the service around it.

| Module | What it holds |
|---|---|
| `model.rs` | The output contract: `Entity`, `Value`, `EntityType`, `Flag`, and the cross-type precedence order. |
| `data.rs` | Loading of the vendored reference data the validators consult, once at startup. |
| `rules/` | One candidate pattern and one validator per entity type. |
| `scan/` | The pipeline: prefilter, then validate and normalise inside the rules, then resolve. |
| `explain/` | Explainer cards: the static per-rule catalogue and the shapers that turn one match into a card. |
| `service.rs` | The HTTP surface. |
| `main.rs` | The service shell: load, compile, serve. |

## Why the work is split this way

Matching is the cheap half of this problem. A pattern that finds every date in a corpus is a
morning's work; a pattern that finds every date and nothing that merely looks like one does not
exist. So the scanner is two-stage, and the two stages are held to different rules:

- The **prefilter** runs over raw document text and must stay in a linear-time engine. No
  lookaround, no backreferences, no catastrophic backtracking on a document somebody else wrote.
  It is allowed (expected) to over-match.
- The **validator** sees one candidate at a time and may be as expensive as it likes. It re-imposes
  the guards that had to be stripped out of the pattern, applies the checks that decide truth
  (calendar validity, check digits, list membership, plausibility windows), and produces the
  canonical value.

Everything that leaves this crate has been through both. A span with no canonical value is a substring
rather than an extraction, and a facet built out of substrings goes unused.

## Byte offsets

Matching is on bytes and offsets are byte offsets, absolute in the source document. A caller
scanning a large document splits it into overlapping windows (the overlap at least as long as the
longest matchable entity) passes each window's own offset as `base_offset`, and deduplicates on
`(type, start, end)`. Never split a window mid-codepoint.

## A missing table is a startup failure, not a quiet one

Every vendored table is read once at startup, and each one has a minimum number of entries it has
to hold to be the file it was transformed from. This is easy to underestimate: a validator whose
table is empty compiles, runs and answers no, so the process starts, the requests succeed, and one
entity type is silently absent for as long as it runs. `VendoredData::load` refuses to build in that
state, and `/health` answers 503 with the offending tables named for the case where one was built
anyway.
