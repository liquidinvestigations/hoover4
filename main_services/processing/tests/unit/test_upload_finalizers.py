"""The settle of an ended upload operation and a late finish of its child."""

import database.uploads as uploads
from tasks.P_upload import activities


def _stored(rows, batch_id):
    """The row that `FINAL` returns: the highest version, the last insert among equals."""
    best = None
    for row in rows:
        if row["batch_id"] == batch_id and (best is None or row["row_version"] >= best["row_version"]):
            best = row
    return best


def test_a_late_child_finish_does_not_replace_the_settled_state(monkeypatch):
    inserted = [{"batch_id": "b1", "upload_dataset": "ds", "state": "processing",
                 "op_id": "op", "error": "", "row_version": 7}]

    def read_batch(_collection, _dataset, batch_id):
        return dict(_stored(inserted, batch_id))

    monkeypatch.setattr(uploads, "read_batch", read_batch)
    monkeypatch.setattr(uploads, "_insert_batch", lambda _c, row: inserted.append(dict(row)))
    monkeypatch.setattr(uploads, "BATCH_COLUMNS",
                        ["batch_id", "upload_dataset", "state", "op_id", "error",
                         "finished_at", "row_version"])
    monkeypatch.setattr(uploads, "_now", lambda: "now")

    calls = []

    def outcome(_collection, _dataset, _batch_id, operation_state):
        calls.append(operation_state)
        if operation_state == "running":
            # The operation is cancelled while the child computes its outcome. The queue
            # settles the batch before the child writes.
            activities._finish("c", "ds", "op", ["b1"], "cancelled", settles=True)
            return {"state": "completed", "succeeded": 1, "files": 1}
        return {"state": "failed", "succeeded": 0, "files": 1}

    monkeypatch.setattr(uploads, "batch_outcome", outcome)
    monkeypatch.setattr(uploads, "outcome_error", lambda _o: "")

    activities._finish("c", "ds", "op", ["b1"], "running")
    assert calls == ["running", "cancelled"]
    # Both writers read version 7. The child row was inserted last.
    assert [r["state"] for r in inserted[1:]] == ["failed", "completed"]
    assert inserted[-1]["row_version"] == 8
    final = _stored(inserted, "b1")
    assert final["row_version"] == 7 + uploads.SETTLE_VERSION_STEP
    assert final["state"] == "failed"
    assert final["error"] == activities.ENDED_EARLY["cancelled"]
