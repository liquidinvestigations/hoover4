# Serena's edit operations, with worked calls

Every one of these takes a `name_path` in the same form `find_symbol` uses:
`insert_text_pages` matches anywhere, `ClickHouseClient/query` matches that member of that
class, `/format_extracted_by` anchors at the top level.

## Replace a body

`replace_symbol_body` with `name_path` and the new body. The signature line stays; the body
is replaced whole. This is the right tool when a function's implementation changes and its
contract does not. The diff then shows exactly the body, with no accidental re-indentation
of the lines around it.

## Insert beside a symbol

`insert_after_symbol` / `insert_before_symbol` place new code relative to an existing symbol
rather than at a line number. A line number is stale the moment anything above it moves;
a symbol name is not.

Typical use: adding an activity beside its siblings, adding a route handler beside the ones
it belongs with, adding an import at the top of a module by anchoring before the first
symbol.

## Rename

`rename_symbol` renames the definition and every reference the language server can see.

**Run `find_referencing_symbols` first and read the list.** Two things it will not cover, and
both exist in this tree:

- **A constant mirrored in the other language.** The stage identifiers are Rust constants and
  Python constants naming the same stored strings. Renaming one side compiles cleanly and
  breaks the join at runtime.
- **A name that also appears as a string**, in SQL, in a compose file, in a generated
  environment file, in a log message that something greps. Search for the literal separately.

After a rename, type-check the workspace *including test targets*: a signature change updated
everywhere in `src/` leaves a plain type check clean while the test binaries no longer
compile.

## The same literal in many files

`replace_in_files` takes a pattern and a replacement across a scoped set of paths and reports
what it touched. Prefer it over a loop of `sed -i` for exactly that reason: the report is the
evidence that the change landed where you expected.

Scope it. An unscoped run over the repository walks build output.

## Delete

`safe_delete_symbol` after `find_referencing_symbols` returns empty. Dead code that is deleted
is recoverable from git; dead code that is left behind is read by the next person as
something that runs.
