---
name: finding-code
description: Finds where something is defined, what calls it, and what a file contains, without paging through it. Use whenever you would reach for `sed -n '400,520p'`, `cat` a source file, or `grep -rn` to answer "where is X", "where is X defined", "what calls X", "where is this used", "who implements this trait", "what does this file contain", "find the function that…", "how does X work" — and when looking up a section of a long Readme. Covers serena's symbol tools (get_symbols_overview, find_symbol, find_referencing_symbols, search_for_pattern) for Rust and Python, correctly scoped grep for everything else, and the map of where hoover4 keeps its pipeline, website, agents and configuration.
allowed-tools: mcp__serena__get_symbols_overview, mcp__serena__find_symbol, mcp__serena__find_referencing_symbols, mcp__serena__find_declaration, mcp__serena__find_implementations, mcp__serena__search_for_pattern, mcp__serena__list_dir, mcp__serena__find_file, Read, Grep, Glob, Bash
---

# Finding code

Reading is most of the work in this repo, and paging a file you have no map of is the
slowest way to do it. Locate first, then read only what you located.

## Reach for these, not for a page read

| you want | do this | not this |
|---|---|---|
| what is in this file | `get_symbols_overview` on the path | `sed -n '1,80p'`, `cat` |
| where a function, struct, class or method is defined | `find_symbol` with `name_path`, `include_body: true` | `grep -n "fn foo"` then paging |
| everything that calls it | `find_referencing_symbols` | `grep -rn foo` |
| who implements this trait | `find_implementations` | grep for the trait name |
| the definition behind a use site | `find_declaration` | reading the imports and guessing |
| a literal, a config key, a log string | `search_for_pattern` with a `relative_path`, or scoped `grep` | bare recursive grep |
| a file whose name you half-remember | `find_file` | `find . -name` from the root |

`find_symbol` takes a `name_path`: `insert_text_pages` finds it anywhere,
`ClickHouseClient/query` finds the method on that class, `/format_extracted_by` anchors at
the top level. Ask for `depth: 1` to list a type's members without their bodies, then a
second call with `include_body: true` for the one member you actually need. That two-step
costs a fraction of what reading the file costs, and it does not put two thousand
irrelevant lines in your context.

Serena is configured here and was almost never used, which is why the habit has to be
deliberate: **when you catch yourself about to read line ranges of a `.rs` or `.py` file,
that is the trigger.** Serena indexes both languages in this workspace.

## When grep is still right

Non-code text, generated output, compose files, SQL, `.ini`, logs, and any question whose
answer is a string rather than a symbol. Scope every one of them:

```
grep -rn 'STAGE_INDEX' --include='*.py' --include='*.rs' main_services website/common
grep -rn 'chat_artifacts' --include='*.rs' website/backend/src
```

`grep` on this host is ugrep and it does **not** skip build output. `website/target` alone
is tens of gigabytes; an unscoped search there burns a core for over an hour and reports as
"no output", which is indistinguishable from finding nothing. A hook denies the unscoped
form. **A search that has not returned within seconds is wrong, not slow** — kill it and
re-scope.

## Navigating the documentation

The prose is large enough to need the same treatment. `website/Readme.md` is tens of
kilobytes and each subject directory has its own `Readme.md`.

```
.agents/skills/finding-code/scripts/doc-toc.sh website/Readme.md   # headings with line numbers
```

(In a harness that substitutes it, `${CLAUDE_SKILL_DIR}/scripts/doc-toc.sh` is the same
file. The repo-relative path is written first because only one harness substitutes the
variable and the rest run the literal string.)

Read the table of contents at the top of the file first, then read only the section. The
same applies to `main_services/processing/Readme.md`, `main_services/ops/Readme.md` and the
pages under `docs/`.

## Where things live

- `main_services/processing/` — the Temporal pipeline. Stages are `tasks/P0_scan_disk/`
  … `tasks/P6_*/`; shared helpers are `tasks/remote.py`, `tasks/text_sources.py`,
  `parse_common.py`; schema is `database/db_collection_migrations/*.sql`; tests are
  `tests/unit/`. All of those paths are relative to `main_services/processing/`.
- `main_services/agents/` — MCP servers and the research agent. `agent_common/` is vendored
  into the metasearch and browser images; their build context is `main_services/agents`.
- `main_services/ops/` — operational procedures, the compose files and the per-service
  build contexts, with its own long `Readme.md`.
- `main_services/regex_entity_scanner/` — the pattern-scanning service, self-contained with
  its own `README.md` and sub-documents.
- `main_services/verify-stack.sh` — end-to-end verification.
- `website/backend/src/api/` — HTTP surface; `website/frontend/src/components/` — Dioxus
  components; `website/common/src/` — types shared by both, including the ones that must
  mirror Python constants.
- `ai_services/` — the standalone GPU tier. `main_services/ocr_tesseract/` and
  `main_services/ner_spacy/` are its CPU twins and live on the main side deliberately.
- `deploy.py` and `hoover4.ini` at the root — every port and every generated `.env`.

## References

- `reference/serena-calls.md` — worked examples of each tool call with real hoover4
  symbols, and what to do when the language server has not indexed a file yet.
- `reference/repo-map.md` — which file answers which question.
- `docs/development/Repo_Map.md` — the fuller directory map, for a person reading cold.
