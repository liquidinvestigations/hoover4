# Failures that do not raise

## The migration runner splits on `;` without parsing SQL

Three ways to break it, all failing with an error that names neither the file nor the line:

1. a semicolon inside a `COMMENT '...'` literal,
2. a semicolon inside a `--` comment,
3. prose after the final statement terminator, which has no stray semicolon at all, becomes
   a comment-only fragment, and reaches ClickHouse as `Code: 62, Empty query`.

Put explanatory comments **above** the statement they describe.
`main_services/processing/tests/unit/test_migrations_parity.py` covers all three.

## Two wire-format traps

Temporal deserialises an activity argument into its **annotated** type. An unannotated
`params` arrives as a dict. ClickHouse `Enum8` takes the **name** on insert and returns the
**ordinal** on read.

Both fail silently, in the shape of "the feature quietly does nothing".
`main_services/processing/Readme.md` carries the detail.

## ClickHouse query traps

A `Row` matches by column name, an alias shadows its own column, and an aggregate returns a
row over an empty match, so "there is a result" is not "there is data".
