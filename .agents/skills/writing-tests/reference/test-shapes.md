# What a good test is, and the three anti-patterns

## Contents

- [The shape](#the-shape)
- [A Python example](#a-python-example)
- [A Rust example](#a-rust-example)
- [Anti-pattern 1: implementation-coupled](#anti-pattern-1-implementation-coupled)
- [Anti-pattern 2: tautological](#anti-pattern-2-tautological)
- [Anti-pattern 3: side-channel](#anti-pattern-3-side-channel)

## The shape

A good test calls the public interface, asserts on the value or the behaviour a caller
would observe, and mocks only at a system boundary such as a network call or the clock.
Nothing inside the function under test is asserted directly, and nothing the test needs is
reached by a path a real caller could not also take.

Both examples below are read from this tree rather than invented, because the shape reads
clearer against a case with a real reason behind every assertion.

## A Python example

`main_services/processing/tests/unit/test_dataset_id_composition.py` tests
`compose_collection_dataset`, the function that builds a `collection_dataset` id:

```python
def test_composed_id_is_not_parsed_back():
    """The composition is ambiguous on purpose: different (collection, dataset)
    pairs can produce the same string, which is exactly why the collection is
    never recovered by splitting - it is resolved via the ``dataset`` table."""
    assert compose_collection_dataset("nara", "my_files") == compose_collection_dataset(
        "nara_my", "files"
    )
```

This calls the one function a caller calls, and it asserts a property a caller depends on,
that the id is not meant to round-trip, rather than recomputing the concatenation the
function already performs. The docstring says why the case exists, which is what keeps a
later reader from "fixing" the collision.

## A Rust example

`website/backend/tests/stack_integration.rs`, `structure_queries_are_not_cached`, tests a
coupling `reviewing-changes` names directly: a structure query must never be written into
the search cache, because the collection's tree changes while ingestion runs.

```rust
let before = count_vfs_rows().await;
for _ in 0..2 {
    backend::api::vfs::vfs_tree_children(
        &admin_user(),
        SHAPES.to_string(),
        dataset_root_key(SHAPES),
        50,
        0,
        false,
    )
    .await
    .unwrap();
}
assert_eq!(
    count_vfs_rows().await,
    before,
    "a query against a <collection>_vfs table was written to the search cache"
);
```

The call goes through `vfs_tree_children`, the same public function the backend's HTTP
handler calls, twice, the way a real repeated request would. The assertion reads the cache
table directly, which is the one place the coupling can be seen from outside the function,
and the failure message states which invariant broke rather than which value differed.

## Anti-pattern 1: implementation-coupled

A test that asserts on an internal step rather than on what the interface returns. It
reaches into a private field, asserts the order helper functions ran in, or asserts an
intermediate data structure the interface never exposes. It breaks on a refactor that
changes nothing a caller could observe, and a reviewer then has to decide whether the test
or the refactor is wrong. Neither example above does this: both assert only what a caller
of the public function can see.

## Anti-pattern 2: tautological

A test whose expected value is computed the way the code under test computes it, rather
than stated as a known value or a known property. Squaring the input to check a squaring
function, or reimplementing the same string concatenation to check a formatter, passes
whenever the code is wrong in a way both copies share, and it never catches that. Both
examples above avoid it: `test_composed_id_is_not_parsed_back` asserts a property (two
different inputs collide, and that is fine) rather than a recomputed string, and the Rust
test asserts a row count against a cache table, not against a re-derivation of the query
logic.

## Anti-pattern 3: side-channel

A test that confirms a change happened through a channel the interface does not expose,
such as a log line, a debug counter, or a database row nothing downstream reads, instead of
through the interface a caller actually uses. It passes when the feature is broken for
every real caller and the side channel alone still fires. The Rust example above is written
to resist this on purpose: `search_manticore_cache` is asserted because a real caller's
behaviour depends on what is in it (a stale cache row is what a real user would eventually
hit), not because it happens to be convenient to read.
