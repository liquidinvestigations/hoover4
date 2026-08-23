# Serena calls, with real symbols

## Contents

- What a file contains
- A single symbol's body
- Callers and implementations
- A literal, scoped
- When the index is cold

## What a file contains

`get_symbols_overview` with `relative_path:
main_services/processing/tasks/P3_parse_files/parse_email.py` returns the module's classes
and functions with their line ranges and nothing else. That is the replacement for
`sed -n '1,80p'` on an unfamiliar file: it costs a few hundred tokens and tells you which
line range is worth reading.

## A single symbol's body

`find_symbol` with `name_path: insert_text_pages`, `include_body: true` returns the
function. With `depth: 1` and no body it returns a class's members as a list, which is the
cheap way to decide which method matters.

Anchoring forms:

- `insert_text_pages`, matches anywhere in the project.
- `ClickHouseClient/query`, the `query` member of `ClickHouseClient`.
- `/format_extracted_by`, a top-level symbol only.

## Callers and implementations

`find_referencing_symbols` on `name_path: STAGE_INDEX` answers "what breaks if I change
this" in one call, and answers it with symbol context rather than raw match lines.
`find_implementations` answers the same question for a Rust trait.

## A literal, scoped

`search_for_pattern` takes `relative_path`, so a search for a log string or a config key
can be confined to `main_services/processing` or `website/backend/src` rather than walking
the tree.

## When the index is cold

The first call against a language can be slow while the server indexes. It is still faster
than the reads it replaces. If a call returns nothing for a symbol you can see in the file,
the file is probably not in the indexed project root. Fall back to a scoped grep for that
one lookup and say so, rather than abandoning the tool for the session.
