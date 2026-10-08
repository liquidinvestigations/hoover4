"""Processing state of a dataset from the live operations of its collection."""

from database.dataset_stats import DONE, PROCESSING, dataset_state


def op(kind, target_kind, collection_dataset=""):
    return {"kind": kind, "target_kind": target_kind, "collection_dataset": collection_dataset}


def test_no_live_operation_is_done():
    assert dataset_state("c_a", []) == DONE


def test_a_dataset_operation_holds_only_its_dataset():
    live = [op("add_dataset", "dataset", "c_a")]
    assert dataset_state("c_a", live) == PROCESSING
    assert dataset_state("c_b", live) == DONE


def test_a_collection_operation_holds_every_dataset():
    live = [op("reindex_collection", "collection")]
    assert dataset_state("c_a", live) == PROCESSING
    assert dataset_state("c_b", live) == PROCESSING


def test_an_export_does_not_count_as_processing():
    assert dataset_state("c_a", [op("export_collection", "collection")]) == DONE
