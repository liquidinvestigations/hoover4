---
name: migrations
description: How the migration runner parses a file, and the three ways to break it.
paths: main_services/processing/database/**/*.sql
---

# Writing a migration

**The runner splits on `;` without parsing SQL.** There are three ways to break it, and all
three fail with an error that names neither the file nor the line:

1. **A semicolon inside a `COMMENT '...'` literal.** The statement is cut in half.
2. **A semicolon inside a `--` comment.** Same.
3. **Prose after the final statement terminator.** It becomes a comment-only fragment and
   reaches the server as an empty query, the one that has no stray semicolon in it at all,
   and therefore the one that is hardest to see.

**Put explanatory comments above the statement they describe**, never inside it and never
after the last one.

The parity test covers all three:

```
.agents/skills/verifying-before-claiming/scripts/pytest-unit.sh tests/unit/test_migrations_parity.py
```

## What a migration header says, and does not say

A header explaining why a table exists is the right shape, and these files are mostly header
by line count on purpose. But it states **what is true now**:

- **No plan number, no phase or part label, no reference to the scratch folder.** Those mean
  nothing to a reader with only the repository, and the folder they name is wiped.
- **No history.** Not "this used to be", not "until this table existed", not "moved here
  when". The migration number already records the order; `git log` records the rest.
- **Keep the lesson.** Write the standing property and the failure it prevents. The reason a
  column is not the expected type, the invariant a sort order depends on, the sentinel that
  must not be confused with zero. Those are exactly what belongs here.

## Column comments

A `COMMENT` on a column earns its place by naming the unit, the invariant or the sentinel.
Restating the column name does not. And mind the semicolon rule inside the literal.

## Enum columns

An `Enum8` takes the **name** on insert and returns the **ordinal** on read. Any consumer
comparing against the name on the read side matches nothing and raises nothing.

## Replacing tables

Where a table is a replacing engine keyed on a version column with a deletion flag, a plain
count includes tombstones and superseded rows. Every consumer either reads the final state
explicitly or is wrong, and the migration's header is the place to say which key and which
version column decide it.
