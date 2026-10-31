"""Verify error-selection order across several batches and workflow continuation."""

import asyncio
from types import SimpleNamespace

import pytest
from tasks.P_admin.rerun_params import SelectionResult
from tasks.P_upload import workflows
from tasks.P_upload.params import IngestUploadBatchesParams, UploadBatchLimitsResult


@pytest.mark.parametrize("patched, expected", [(True, ["b1", "b2"]), (False, ["b1"])])
def test_selection_sees_all_hashes_on_new_runs_and_preserves_old_order(monkeypatch, patched, expected):
    ingested, selected, calls = [], [], []

    async def activity(fn, arg, **_kwargs):
        name = fn if isinstance(fn, str) else fn.__name__
        calls.append(name)
        if name == "upload_batch_limits":
            return UploadBatchLimitsResult(ingest_seconds=60)
        if name == "ingest_upload_paths":
            ingested.append(arg.batch_id)
            return {}
        if name == "select_historical_errors":
            selected.extend(ingested)
            return SelectionResult()
        if name == "finish_upload_batches":
            return {"completed": 1}
        return {}

    async def child(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: patched)
    monkeypatch.setattr(workflows.workflow, "info", lambda: SimpleNamespace(
        get_current_history_length=lambda: 1, is_continue_as_new_suggested=lambda: False))
    params = IngestUploadBatchesParams("c", "c_d", "op", ["b1", "b2"])
    result = asyncio.run(workflows.IngestUploadBatches().run(params))
    assert selected == expected
    assert ingested == ["b1", "b2"]
    assert calls.count("select_historical_errors") == 1
    assert result["batch_states"] == {"completed": 2}
    assert params.paths_prepared == patched
