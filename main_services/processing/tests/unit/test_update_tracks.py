"""Processing update tracks: identity, candidates, capacity, submission and the coordinator."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from database import operations as ops
from database import processing_updates as state
from tasks.P_admin.updates import activities, registry
from tasks.P_admin.updates import workflows as update_workflows
from tasks.P_admin.updates.params import (
    CheckUpdatesResult, RunUpdateParams, SubmitUpdateParams, UpdateCandidateParams,
)


def test_every_dataset_step_has_one_track_and_collection_steps_have_none():
    for step in registry.STEPS:
        if step.scope == registry.SCOPE_DATASET:
            assert step.track in registry.TRACKS, step.step_id
        else:
            assert step.track == ""
    assert {s.step_id for s in registry.STEPS if s.track == "ocr"} == {"ocr_detection", "ocr", "pdf_text"}
    assert {s.step_id for s in registry.STEPS if s.track == "ner"} == {"entities"}
    assert {s.step_id for s in registry.STEPS if s.track == "vectors"} == {"vectors"}


def test_track_requests_are_validated():
    valid = registry.valid_track_request
    assert valid("dataset", ["ocr", "pdf_text"], "", "") == ""
    assert valid("dataset", ["ocr", "pdf_text"], "ocr", registry.PROFILE_TRACKS) == ""
    assert "not all steps" in valid("dataset", ["ocr", "entities"], "ocr", registry.PROFILE_TRACKS)
    assert "Unknown update track" in valid("dataset", ["ocr"], "gpu", registry.PROFILE_TRACKS)
    assert "Unknown update profile" in valid("dataset", ["ocr"], "ocr", "")
    assert "collection" in valid("collection", ["search_schema"], "main", registry.PROFILE_TRACKS)


def test_a_snapshot_refuses_inconsistent_track_metadata_before_it_writes(monkeypatch):
    calculated = []
    monkeypatch.setattr(activities, "_calculate", lambda *a: calculated.append(a))
    params = RunUpdateParams("op", "dataset", "c", "c_ds", ["ocr", "entities"],
                             track="ocr", profile=registry.PROFILE_TRACKS)
    with pytest.raises(ApplicationError) as raised:
        activities.snapshot_processing_update(params)
    assert raised.value.type == activities.INVALID_REQUEST
    assert not calculated


def test_a_dataset_candidate_splits_into_one_candidate_for_each_track():
    steps = ["failed_files", "ocr", "pdf_text", "entities", "search_terms"]
    candidate = UpdateCandidateParams("dataset", "c_ds", "c", "c_ds", steps, {s: "F-" + s for s in steps})
    split = activities._track_candidates(candidate)
    assert [(c.track, c.steps) for c in split] == [
        ("main", ["failed_files", "search_terms"]), ("ocr", ["ocr", "pdf_text"]), ("ner", ["entities"])]
    assert split[1].fingerprints == {"ocr": "F-ocr", "pdf_text": "F-pdf_text"}
    collection = UpdateCandidateParams("collection", "c", "c", "", ["search_schema"], {})
    assert activities._track_candidates(collection) == [collection]


def _live(op_id, track="", kind="update_dataset", state_name="running", user="processing-updates"):
    detail = json.dumps({"track": track} if track else {})
    return {"op_id": op_id, "kind": kind, "detail": detail, "state": state_name, "user_id": user,
            "collectionname": "c", "collection_dataset": "c_" + op_id, "target_kind": "dataset"}


def test_capacity_counts_every_live_row_of_a_class(monkeypatch):
    monkeypatch.setenv("HOOVER4_OPERATION_CAPS", "update_ocr=2,update_ner=3")
    live = [_live("a", "ocr"), _live("b", "ocr", state_name="queued", user="admin"),
            _live("c", "ner"), _live("d"), _live("e", kind="add_dataset")]
    capacity = activities.update_capacity(live)
    assert capacity == {"update_ocr": 0, "update_ner": 2, "update_vectors": 2,
                        "update_main": 2, "update_collection": 2}


def test_gpu_tracks_wait_for_a_ready_service(monkeypatch):
    from tasks import service_readiness

    states = {"ner": service_readiness.UNAVAILABLE, "embeddings": service_readiness.READY}
    monkeypatch.setattr(service_readiness, "capability_readiness", lambda name: states[name])
    candidates = [UpdateCandidateParams("dataset", "d", "c", "d", ["entities"], {}, "ner"),
                  UpdateCandidateParams("dataset", "d", "c", "d", ["vectors"], {}, "vectors")]
    assert activities._ready_tracks(candidates) == {"ocr", "main", "vectors"}
    states["ner"] = service_readiness.DISABLED
    assert "ner" not in activities._ready_tracks(candidates)


@pytest.fixture
def submit_env(monkeypatch):
    env = SimpleNamespace(existing=None, live=[], created=[], locked=False)
    monkeypatch.setattr(ops, "get_operation", lambda op_id: env.existing)
    monkeypatch.setattr(state, "live_update_operations", lambda: env.live)

    def create(kind, collectionname, collection_dataset, detail=None, user_id="", op_id=None, **kw):
        if env.locked:
            raise ops.OperationLocked(kind, collection_dataset, [])
        env.created.append((kind, collection_dataset, detail, op_id))
        return {}

    monkeypatch.setattr(ops, "create_operation", create)
    return env


def _candidate(dataset="c_d1", track="ocr", steps=("ocr",)):
    return UpdateCandidateParams("dataset", dataset, "c", dataset, list(steps), {s: "F" for s in steps}, track)


def test_submission_writes_a_tracked_row(submit_env):
    assert activities.submit_automatic_update(SubmitUpdateParams("op-1", _candidate())) == "started:op-1"
    [(kind, dataset, detail, op_id)] = submit_env.created
    assert (kind, dataset, op_id) == ("update_dataset", "c_d1", "op-1")
    assert detail["track"] == "ocr" and detail["profile"] == registry.PROFILE_TRACKS


def test_a_submission_retry_after_its_insert_returns_the_same_operation(submit_env):
    submit_env.existing = {"op_id": "op-1"}
    assert activities.submit_automatic_update(SubmitUpdateParams("op-1", _candidate())) == "started:op-1"
    assert submit_env.created == []


def test_a_tracked_submission_matches_only_its_own_scope_and_track(submit_env):
    other = dict(_live("x", "ocr"), collection_dataset="c_d2")
    same_dataset_other_track = dict(_live("y", "main"), collection_dataset="c_d1")
    submit_env.live = [other, same_dataset_other_track]
    # Neither row matches, and the dispatch lock then refuses the held dataset.
    submit_env.locked = True
    assert activities.submit_automatic_update(SubmitUpdateParams("op-1", _candidate())) == "held:"
    submit_env.live.append(dict(_live("z", "ocr"), collection_dataset="c_d1"))
    assert activities.submit_automatic_update(SubmitUpdateParams("op-1", _candidate())) == "running:z"


def test_a_legacy_submission_keeps_one_automatic_operation(submit_env):
    submit_env.live = [_live("x", "ocr")]
    legacy = UpdateCandidateParams("dataset", "c_d1", "c", "c_d1", ["ocr"], {"ocr": "F"})
    assert activities.submit_automatic_update(SubmitUpdateParams("op-1", legacy)) == "running:x"


class Coordinator:
    """Answers the commands of the coordinator by name and records them."""

    def __init__(self, monkeypatch, submit=None, start_params=None):
        self.calls = []
        self.submit = submit or (lambda params: f"started:{params.op_id}")
        self.start_params = start_params or {}
        w = update_workflows.workflow
        monkeypatch.setattr(w, "execute_activity", self.activity)
        monkeypatch.setattr(w, "start_child_workflow", self.start)
        monkeypatch.setattr(w, "now", lambda: datetime(2026, 11, 19, tzinfo=timezone.utc))
        counter = iter(range(10_000))
        monkeypatch.setattr(w, "uuid4", lambda: SimpleNamespace(hex=f"{next(counter):032x}"))

    async def activity(self, fn, arg=None, **kwargs):
        name = fn if isinstance(fn, str) else fn.__name__
        self.calls.append((name, arg))
        if name == "submit_automatic_update":
            return self.submit(arg)
        if name == "operation_start_params":
            return self.start_params.get(arg, {})
        return None

    async def start(self, name, params, **kwargs):
        self.calls.append(("start", params))


def _result(candidates, capacity=None, live=None):
    return CheckUpdatesResult(candidates, capacity=capacity if capacity is not None else {
        "update_ocr": 2, "update_ner": 2, "update_vectors": 2, "update_main": 2,
        "update_collection": 2}, live=live or {})


def test_each_track_starts_two_operations_and_one_operation_for_each_dataset(monkeypatch):
    coordinator = Coordinator(monkeypatch)
    candidates = []
    for n in range(1, 5):
        dataset = f"c_d{n}"
        candidates += [_candidate(dataset, "ocr", ["ocr"]), _candidate(dataset, "ner", ["entities"]),
                       _candidate(dataset, "main", ["search_terms"])]
    state_ = update_workflows.CoordinatorState()
    asyncio.run(update_workflows.ProcessingUpdates()._submit(state_, _result(candidates)))
    started = [params["detail"]["track"] for name, params in coordinator.calls if name == "start"]
    datasets = [params["collection_dataset"] for name, params in coordinator.calls if name == "start"]
    # Four datasets, one live operation each, and no track above its two slots.
    assert len(started) == 4 and len(set(datasets)) == 4
    assert all(started.count(track) <= 2 for track in ("ocr", "ner", "main"))
    assert len(state_.active_ops) == 4


def test_a_full_ocr_track_does_not_take_the_slots_of_other_tracks(monkeypatch):
    coordinator = Coordinator(monkeypatch)
    candidates = [_candidate("c_d1", "ocr", ["ocr"]), _candidate("c_d2", "ner", ["entities"]),
                  _candidate("c_d3", "main", ["folder_counts"])]
    capacity = {"update_ocr": 0, "update_ner": 2, "update_vectors": 2, "update_main": 2,
                "update_collection": 2}
    state_ = update_workflows.CoordinatorState()
    asyncio.run(update_workflows.ProcessingUpdates()._submit(state_, _result(candidates, capacity)))
    started = sorted(params["detail"]["track"] for name, params in coordinator.calls if name == "start")
    assert started == ["main", "ner"]


def test_classes_take_turns_by_dataset(monkeypatch):
    coordinator = Coordinator(monkeypatch)
    candidates = [_candidate(f"c_d{n}", "main", ["folder_counts"]) for n in range(1, 5)]
    capacity = {"update_main": 1}
    state_ = update_workflows.CoordinatorState()
    for _ in range(4):
        asyncio.run(update_workflows.ProcessingUpdates()._submit(state_, _result(candidates, capacity)))
    order = [params["collection_dataset"] for name, params in coordinator.calls if name == "start"]
    assert order == ["c_d1", "c_d2", "c_d3", "c_d4"]


def test_a_held_candidate_is_skipped_and_a_running_one_is_tracked(monkeypatch):
    answers = {"c_d1": "held:", "c_d2": "running:op-old"}
    coordinator = Coordinator(monkeypatch, submit=lambda p: answers.get(
        p.candidate.scope_id, f"started:{p.op_id}"))
    candidates = [_candidate("c_d1"), _candidate("c_d2"), _candidate("c_d3")]
    state_ = update_workflows.CoordinatorState()
    asyncio.run(update_workflows.ProcessingUpdates()._submit(state_, _result(candidates)))
    starts = [params["collection_dataset"] for name, params in coordinator.calls if name == "start"]
    assert starts == ["c_d3"]
    assert "op-old" in state_.active_ops


def test_reconciliation_starts_a_pending_row_once_and_drops_ended_rows(monkeypatch):
    params = {"op_id": "op-p", "kind": "update_dataset", "collectionname": "c",
              "collection_dataset": "c_d1", "detail": {"steps": ["ocr"], "track": "ocr"}}
    coordinator = Coordinator(monkeypatch, start_params={"op-p": params})
    state_ = update_workflows.CoordinatorState(active_ops=["op-done", "op-run"])
    coordinator_wf = update_workflows.ProcessingUpdates()
    live = {"op-run": "running", "op-p": "pending", "op-q": "queued"}
    asyncio.run(coordinator_wf._reconcile(state_, live))
    assert state_.active_ops == ["op-run", "op-p", "op-q"]
    assert [c for c in coordinator.calls if c[0] == "start"] == [("start", params)]
    # The next pass of the same run does not start the row again.
    state_.active_ops = []
    asyncio.run(coordinator_wf._reconcile(state_, live))
    assert len([c for c in coordinator.calls if c[0] == "start"]) == 1


def test_a_legacy_active_operation_moves_into_the_tracks_state(monkeypatch):
    coordinator = Coordinator(monkeypatch)
    monkeypatch.setattr(update_workflows, "PASSES_PER_RUN", 0)
    continued = []
    monkeypatch.setattr(update_workflows.workflow, "continue_as_new", lambda s: continued.append(s))
    state_ = update_workflows.CoordinatorState(active_op="op-legacy")
    asyncio.run(update_workflows.ProcessingUpdates()._tracks(state_))
    assert continued[0].active_ops == ["op-legacy"] and continued[0].active_op == ""


def test_an_operation_forwards_its_track_to_the_update_workflow(monkeypatch):
    from tasks.P_ops import workflows as ops_workflows
    from tasks.P_ops.params import OperationParams

    inputs = []

    async def child(name, arg, **kwargs):
        inputs.append(arg)
        return {"steps": arg["steps"]}

    monkeypatch.setattr(ops_workflows.workflow, "execute_child_workflow", child)
    tracked = OperationParams("op", "update_dataset", "c", "c_ds", detail={
        "steps": ["ocr"], "track": "ocr", "profile": registry.PROFILE_TRACKS})
    asyncio.run(ops_workflows.Operation()._processing_update(tracked))
    legacy = OperationParams("op", "update_dataset", "c", "c_ds", detail={"steps": ["ocr"]})
    asyncio.run(ops_workflows.Operation()._processing_update(legacy))
    assert inputs[0]["track"] == "ocr" and inputs[0]["profile"] == registry.PROFILE_TRACKS
    assert "track" not in inputs[1] and "profile" not in inputs[1]
