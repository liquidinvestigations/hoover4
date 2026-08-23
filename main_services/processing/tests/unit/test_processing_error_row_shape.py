"""`record_processing_errors` takes rows, not strings, and the converter is the only judge.

Temporal decodes the activity argument into `RecordProcessingErrorsParams` on the worker
side. A caller that passes the legacy shape (`errors: List[str]` plus loose
`collection_dataset`/`item_hashes`/`task_ids` keys) does not fail at the call site: it
fails inside the converter, and a `try/except: pass` around the call turns "this detector
crashed" into silence. Both directions are asserted here so a future shape drift is a red
test rather than an empty `processing_errors` table.
"""

import pytest
from temporalio.converter import default as default_converter
from temporalio.converter import value_to_type

from tasks.P2_execute_plan.activities import RecordProcessingErrorsParams

ROW_KEYS = ("collection_dataset", "hash", "task_name", "run_time_ms", "error_logs")


def _round_trip(value):
    """Encode as an activity argument and decode into the params dataclass."""
    converter = default_converter().payload_converter
    payloads = converter.to_payloads([value])
    return value_to_type(RecordProcessingErrorsParams, converter.from_payloads(payloads)[0])


def test_error_row_round_trips():
    row = {
        "collection_dataset": "testdata__disk-files",
        "hash": "a" * 40,
        "task_name": "detector_error_tika",
        "run_time_ms": 12,
        "error_logs": "ActivityError: tika said no",
    }
    params = _round_trip(RecordProcessingErrorsParams(collectionname="testdata", errors=[row]))
    assert params.errors == [row]
    assert set(row) == set(ROW_KEYS)


def test_legacy_flat_shape_is_rejected_by_the_converter():
    legacy = {
        "collectionname": "testdata",
        "collection_dataset": "testdata__disk-files",
        "item_hashes": ["a" * 40],
        "task_ids": ["detector_error_tika"],
        "errors": ["ActivityError: tika said no"],
    }
    with pytest.raises(TypeError):
        _round_trip(legacy)
