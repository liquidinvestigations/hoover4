# Meeting a documentation lint without gaming it

A missing-documentation lint (`missing_docs` for the Rust workspace, the pydocstyle family
for Python) measures **presence**, not content. That is the whole problem with it.

## Do not bulk-fill it

A file full of `/// Document public struct member` or `/// The foo field.` is worse than no
documentation at all:

- it defeats the lint, which now reports zero while the code is still undocumented;
- it defeats grep, because the distinctive words are gone and every item reads the same;
- it costs every future reader the context to skim past it.

## The bar

A doc comment must add something the identifier and its type do not already say:

- the **unit** (`bytes`, `milliseconds`, `1-based`);
- the **invariant** (`never 0`, `sorted ascending`, `the caller holds the lock`);
- the **failure it guards** (`a second call for the same variant deletes the first call's
  rows`);
- the **reason the value is not the expected one**.

If there is nothing to add, leave the item undocumented.

## What to do instead of filling

Report that the lint cannot be satisfied without filler for those items, and name them. That is a
real answer. Turning a lint on and generating filler to make it pass is a way of hiding the
question, and the hiding survives long after anyone remembers doing it.

## The one lint worth turning on

`ERA001` ("found commented-out code") targets the one thing that is unambiguously rot and
that a tool can actually judge. This tree already carries almost none of it, so enabling it
is nearly free.

Everything in the `missing_docs` / `D` families measures presence, which is the metric that
produces filler. **No linter can judge whether a comment says something the code cannot, and
none can detect a comment that has gone stale.** Say that plainly rather than shopping for a
tool that claims otherwise.
