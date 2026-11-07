"""An entity update runs several NER batches at once and continues after the listed files."""

import asyncio

import pytest
from temporalio.exceptions import ApplicationError
from tasks.P_admin.updates import workflows
from tasks.P_admin.updates.entities import EntityUpdateParams


class Continued(Exception):
    pass


def run(monkeypatch, listed, fail=None):
    calls, running, peak, states = [], [0], [0], []

    async def activity(fn, params, **options):
        name = fn if isinstance(fn, str) else fn.__name__
        if name == "list_entity_update_hashes":
            calls.append(("list", params.limit))
            return listed
        if name == "extract_entities_for_hashes":
            running[0] += 1
            peak[0] = max(peak[0], running[0])
            await asyncio.sleep(0.01)
            running[0] -= 1
            if fail and fail in params["hashes"]:
                raise ApplicationError("NER failed", non_retryable=True)
            calls.append(("extract", len(params["hashes"])))
            return None
        calls.append((name, getattr(params, "terms_at_end", None), len(getattr(params, "hashes", []))))

    def continued(params):
        states.append(params)
        raise Continued()

    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "continue_as_new", continued)
    try:
        result = asyncio.run(workflows.UpdateDatasetEntities().run(EntityUpdateParams("c", "d", "op", done=7)))
    except Continued:
        result = None
    return result, calls, peak[0], states


def test_batches_run_four_at_once_and_the_next_run_starts_after_the_last_file(monkeypatch):
    listed = [f"h{index:04d}" for index in range(530)]
    result, calls, peak, states = run(monkeypatch, listed)
    assert result is None and calls[0] == ("list", 1600)
    assert sorted(c[1] for c in calls if c[0] == "extract") == [30, 100, 100, 100, 100, 100]
    assert [c for c in calls if c[0] == "finish_entity_update"] == [("finish_entity_update", True, n) for n in (100,) * 5 + (30,)]
    assert peak == 4
    assert states[0].after == "h0529" and states[0].done == 537


def test_an_empty_listing_writes_the_dataset_terms_once(monkeypatch):
    result, calls, _, states = run(monkeypatch, [])
    assert result == 7 and states == []
    assert calls == [("list", 1600), ("finish_entity_terms", False, 0)]


def test_a_failed_batch_fails_the_run_after_the_other_batches(monkeypatch):
    listed = [f"h{index:04d}" for index in range(300)]
    with pytest.raises(ApplicationError, match="NER failed"):
        run(monkeypatch, listed, fail="h0000")
