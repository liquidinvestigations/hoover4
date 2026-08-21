---
name: editing-code
description: Changes source files with tools that fail loudly instead of silently — the harness's own Edit and Write tools for a single edit, and serena's symbol operations for anything symbol-shaped. Use when about to modify a `.rs`, `.py`, `.sql`, `.sh` or `.toml` file, and whenever the task is "rename this", "refactor", "change every occurrence", "apply this across the files", "update the signature", "move this function", or "replace X with Y everywhere". Covers why `sed -i` is the wrong first reach, which serena operation matches which shape of change, and the multi-file literal substitution that is the most common real case here.
allowed-tools: Edit, Write, Read, mcp__serena__replace_symbol_body, mcp__serena__insert_after_symbol, mcp__serena__insert_before_symbol, mcp__serena__rename_symbol, mcp__serena__replace_in_files, mcp__serena__replace_content, mcp__serena__find_symbol, mcp__serena__find_referencing_symbols, mcp__serena__safe_delete_symbol, Grep, Glob, Bash
---

# Editing code

## Why the first reach matters

`sed -i 's/old/new/'` **cannot fail**. If the pattern does not match — because the file moved,
because the whitespace differs, because an earlier edit already changed it — it exits 0 and
changes nothing, and the next thing you do is report a change that was never made.

`Edit` refuses on a stale match and tells you which one. That is the entire argument, and it
is a property of the tools rather than a matter of taste. Some harness modes carry a built-in
instruction to prefer shell reads and stream edits; where that mode is on, this rule is what
biases the first reach back.

Bash editing stays legitimate where it is genuinely the practical tool — throwaway analysis
that writes nothing into the repo, generating a file from data, a mechanical transform you
are about to read back in full. The point is which one you try first, not a prohibition.

## Match the operation to the shape of the change

| the change is | use |
|---|---|
| one edit in one file | `Edit` with enough context to be unique |
| a new file | `Write` |
| replacing a whole function, method or class body | `replace_symbol_body` |
| adding a function, method or import beside an existing symbol | `insert_after_symbol` / `insert_before_symbol` |
| renaming a symbol and every reference to it | `rename_symbol` |
| the same literal string across many files | `replace_in_files` |
| deleting a symbol that nothing references | `safe_delete_symbol`, after `find_referencing_symbols` |

**Multi-file literal substitution is the common case here** — a renamed configuration key, a
moved path, a container name, a term that appeared in twenty comments. `replace_in_files`
does it in one call with a report of what it touched, which is the part `sed` across a file
list does not give you.

## Before a symbol-shaped change

Ask what breaks first. `find_referencing_symbols` on the symbol answers "what calls this" with
symbol context, in one call. Renaming without it is how a call site in the other language
gets left behind — and the two languages here share constants deliberately, so the compiler
will not catch it.

## After any edit

- **Type-check or run the tests before saying it worked.** `verifying-before-claiming`.
- **Fix the comment your change made false**, in the same patch. `writing-project-docs`.
- **If the change adds, removes or re-scopes a capability**, edit its row in
  `docs/technical-specification/` in the same patch.

## When serena does not answer

If a symbol lookup returns nothing for something you can see in the file, the file is
probably outside the indexed project root, or the language server has not finished indexing.
Fall back to `Edit` with a unique context window for that one change, and say that you did —
do not abandon the tool for the rest of the session, and do not silently drop to `sed`.

## References

- `reference/serena-edits.md` — each operation with a worked call, and the checks to run
  around a rename.
