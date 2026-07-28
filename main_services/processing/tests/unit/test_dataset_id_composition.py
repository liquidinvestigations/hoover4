"""Tests for ``collection_dataset`` composition and dataset slug validation.

``collection_dataset`` is composed as ``f"{collectionname}_{dataset_name}"`` and is
globally unique by construction. It is NOT a parsing contract: a dataset name may
contain ``_``, so the collection is never recovered by splitting the string -
resolution goes through the ``dataset`` table.
"""

from tasks.P0_scan_disk.submit_job import _slugify_dataset_name, compose_collection_dataset


def test_compose_canonical_example():
    assert compose_collection_dataset("testdata", "testfiles") == "testdata_testfiles"


def test_compose_is_exact_concatenation():
    assert compose_collection_dataset("a", "b") == "a_b"


def test_dataset_name_with_underscores_round_trips():
    """A dataset name containing ``_`` survives slug validation unchanged and is
    preserved verbatim inside the composed id."""
    dataset_name = "my_files_2024"
    assert _slugify_dataset_name(dataset_name) == dataset_name
    composed = compose_collection_dataset("nara", dataset_name)
    assert composed == "nara_my_files_2024"
    assert composed.endswith(dataset_name)


def test_composed_id_is_not_parsed_back():
    """The composition is ambiguous on purpose: different (collection, dataset)
    pairs can produce the same string, which is exactly why the collection is
    never recovered by splitting - it is resolved via the ``dataset`` table."""
    assert compose_collection_dataset("nara", "my_files") == compose_collection_dataset(
        "nara_my", "files"
    )


def test_dataset_slug_rejects_non_slug_names():
    """Names the slugifier would change are rejected by the CLI (it compares the
    slugified form against the input)."""
    assert _slugify_dataset_name("My Files!") != "My Files!"
    assert _slugify_dataset_name("Test-Data") != "Test-Data"


def test_dataset_slug_accepts_lowercase_alnum_underscore():
    assert _slugify_dataset_name("testfiles") == "testfiles"
    assert _slugify_dataset_name("nara2") == "nara2"
