"""Tracked update operations: OCR publication without NER, recorded windows, and the
dependency revision of NER and vectors."""

import asyncio
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from database import processing_updates as state
from tasks.P_admin import workflows as ocr_workflows
from tasks.P_admin.ocr_rerun import OcrRunPlanParams, RerunOcrParams
from tasks.P_admin.updates import activities, registry, selectors
from tasks.P_admin.updates import workflows as update_workflows
from tasks.P_admin.updates.params import (
    RunUpdateParams, StepOutcomeResult, StepSnapshotParams, UpdateSnapshotResult,
)


class Continued(Exception):
    pass


@pytest.fixture
def ocr_run(monkeypatch):
    """Fake the commands of `RerunOcr` and record them."""
    run = SimpleNamespace(ocr=[], children=[], verified=[], errors=[], continued=[],
                          fail_ocr=set(), fail_children=set(), files=[])

    async def activity(name, scope, **_options):
        if name == "list_automatic_ocr_files":
            return [{"item_hash": h} for h in run.files]
        if name == "run_automatic_ocr_files":
            run.ocr.extend(scope.hashes)
            [h] = scope.hashes
            if h in run.fail_ocr:
                raise ApplicationError("unsupported script", non_retryable=True)
            return {h: "plan-" + h}
        if name == "verify_automatic_ocr_files":
            assert scope.separated
            run.verified.append(list(scope.hashes))

    async def child(fn, arg, **kwargs):
        name = fn.__qualname__.split(".")[0]
        run.children.append((name, list(arg.item_hashes)))
        if any(h in run.fail_children for h in arg.item_hashes) and len(arg.item_hashes) > 1:
            raise ApplicationError("page publication failed")
        if arg.item_hashes == ["poison"]:
            raise ApplicationError("file publication failed")

    async def errors(failed, item_hashes, **_kwargs):
        run.errors.extend(item_hashes)

    def continued(params):
        run.continued.append(params)
        raise Continued()

    monkeypatch.setattr(ocr_workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(ocr_workflows.workflow, "execute_child_workflow", child)
    monkeypatch.setattr(ocr_workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(ocr_workflows.workflow, "continue_as_new", continued)
    monkeypatch.setattr(ocr_workflows.workflow, "now", lambda: None)
    monkeypatch.setattr(ocr_workflows.workflow, "info", lambda: SimpleNamespace(run_id="fixture-run"))
    monkeypatch.setattr(ocr_workflows.workflow, "logger", __import__("logging").getLogger("test"))
    from tasks.P3_parse_files import parse_common
    monkeypatch.setattr(parse_common, "record_errors_from_results", errors)
    return run


def _separated(**changes):
    return RerunOcrParams("c", "c_ds", "op", listed=True, automatic_mode=True, separated=True, **changes)


def test_a_separated_page_publishes_once_without_ner_or_embedding(ocr_run):
    ocr_run.files = ["a", "b", "c", "d", "e", "f"]
    ocr_run.fail_ocr = {"c"}
    with pytest.raises(Continued):
        asyncio.run(ocr_workflows.RerunOcr()._automatic(_separated(ocr_window=3)))
    assert sorted(ocr_run.ocr) == ["a", "b", "c", "d", "e", "f"]
    good = ["a", "b", "d", "e", "f"]
    assert ocr_run.children == [("ScanRegexEntitiesForPlan", good), ("IndexDatasetPlan", good)]
    assert ocr_run.verified == [good]
    assert ocr_run.errors == ["c"]
    [after] = ocr_run.continued
    assert (after.after, after.automatic_files, after.automatic_failed_files) == ("f", 5, 1)
    assert after.ocr_window == 3 and after.separated


def test_a_failed_page_publication_falls_back_to_single_files(ocr_run):
    ocr_run.files = ["a", "poison", "b"]
    ocr_run.fail_children = {"poison"}
    with pytest.raises(Continued):
        asyncio.run(ocr_workflows.RerunOcr()._automatic(_separated()))
    # The page failed, then each file was published alone.
    singles = [hashes for name, hashes in ocr_run.children if len(hashes) == 1]
    assert ["a"] in singles and ["b"] in singles and ["poison"] in singles
    assert sorted(h for [h] in ocr_run.verified) == ["a", "b"]
    # Only the file whose own publication failed has a file error.
    assert ocr_run.errors == ["poison"]
    [after] = ocr_run.continued
    assert after.publication_failures == 1 and after.automatic_failed_files == 1


def test_a_separated_phase_one_runs_no_unfinished_plans(monkeypatch):
    calls = []

    async def activity(fn, *args, **kwargs):
        calls.append(fn if isinstance(fn, str) else fn.__name__)

    async def child(*args, **kwargs):
        calls.append("child")

    monkeypatch.setattr(ocr_workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(ocr_workflows.workflow, "execute_child_workflow", child)
    params = RerunOcrParams("c", "c_ds", "op", parts_version=True, separated=True)
    result = asyncio.run(ocr_workflows.RerunOcr()._phase_one(params, automatic=True))
    assert calls == ["ensure_temp_dir_exists", "remove_pdf_members"]
    assert result.listed and result.phase_one_plans == 0


def test_separated_plan_text_steps_scan_signals_and_index_only(monkeypatch):
    names = []

    async def child(fn, arg, **kwargs):
        names.append(fn.__qualname__.split(".")[0])

    monkeypatch.setattr(ocr_workflows.workflow, "execute_child_workflow", child)
    plan = OcrRunPlanParams("c", "c_ds", "op", "plan", separated=True)
    asyncio.run(ocr_workflows.OcrRunPlan()._text_steps(plan, ["a"]))
    assert names == ["ScanRegexEntitiesForPlan", "IndexDatasetPlan"]


class Temporal:
    """Answers the commands of `RunProcessingUpdate` and records children."""

    def __init__(self, monkeypatch):
        self.calls, self.children = [], []
        w = update_workflows.workflow
        monkeypatch.setattr(w, "patched", lambda name: True)
        monkeypatch.setattr(w, "execute_activity", self.activity)
        monkeypatch.setattr(w, "execute_child_workflow", self.child)

    async def activity(self, fn, arg=None, **kwargs):
        name = fn if isinstance(fn, str) else fn.__name__
        self.calls.append(name)
        if name == "snapshot_processing_update":
            return UpdateSnapshotResult([StepSnapshotParams(s, "F-" + s, '{"model": "m"}', 1) for s in arg.steps])
        if name == "update_windows":
            return {"ocr": 24, "ner": 5, "embed": 7}
        if name == "scan_pdf_text_layers":
            return {"unbuilt_parts": 1}
        if name == "settle_update_step":
            return StepOutcomeResult(True, "")
        return {}

    async def child(self, name, arg=None, **kwargs):
        name = name if isinstance(name, str) else name.__qualname__.split(".")[0]
        self.children.append((name, arg))
        return {}


def test_a_tracked_operation_records_windows_and_separates_ocr(monkeypatch):
    temporal = Temporal(monkeypatch)
    params = RunUpdateParams("op", "dataset", "c", "c_ds", ["ocr", "pdf_text"], automatic=True,
                             track="ocr", profile=registry.PROFILE_TRACKS)
    asyncio.run(update_workflows.RunProcessingUpdate().run(params))
    assert temporal.calls.index("update_windows") == 1
    ocr = [arg for name, arg in temporal.children if name == "RerunOcr"]
    assert ocr and all(arg["separated"] and arg["ocr_window"] == 24 for arg in ocr)


def test_tracked_ner_and_vector_children_get_their_windows(monkeypatch):
    temporal = Temporal(monkeypatch)
    for track, step in (("ner", "entities"), ("vectors", "vectors")):
        params = RunUpdateParams("op", "dataset", "c", "c_ds", [step], automatic=True,
                                 track=track, profile=registry.PROFILE_TRACKS)
        asyncio.run(update_workflows.RunProcessingUpdate().run(params))
    windows = {name: arg.window for name, arg in temporal.children}
    assert windows == {"UpdateDatasetEntities": 5, "UpdateDatasetVectors": 7}
    vectors = [arg for name, arg in temporal.children if name == "UpdateDatasetVectors"]
    assert vectors[0].verify


def test_a_legacy_operation_keeps_its_inputs(monkeypatch):
    temporal = Temporal(monkeypatch)
    params = RunUpdateParams("op", "dataset", "c", "c_ds", ["ocr", "entities"], automatic=True)
    asyncio.run(update_workflows.RunProcessingUpdate().run(params))
    assert "update_windows" not in temporal.calls
    ocr = [arg for name, arg in temporal.children if name == "RerunOcr"]
    assert "separated" not in ocr[0] and "ocr_window" not in ocr[0]
    entities = [arg for name, arg in temporal.children if name == "UpdateDatasetEntities"]
    assert entities[0].window == 0


def test_the_dependency_revision_changes_only_ner_and_vector_fingerprints():
    ctx_a = selectors.ScopeContext("dataset", "c_ds", "c", "in-1", dependency_revision="op-ocr-1")
    ctx_b = selectors.ScopeContext("dataset", "c_ds", "c", "in-1", dependency_revision="op-ocr-2")
    changed = []
    for step in registry.steps_of("dataset"):
        a = registry.desired(step, "k", ctx_a.input_revision, dependency_revision=ctx_a.dependency_revision)
        b = registry.desired(step, "k", ctx_b.input_revision, dependency_revision=ctx_b.dependency_revision)
        if a.fingerprint != b.fingerprint:
            changed.append(step.step_id)
    assert changed == ["entities", "vectors"]
    # A step without the revision keeps the fingerprint that it had before the revision existed.
    step = registry.STEPS_BY_ID["ocr"]
    assert registry.fingerprint(step, "k", "in-1") == registry.fingerprint(step, "k", "in-1", "op-ocr-1")


def test_the_context_reads_the_dependency_revision_of_its_dataset():
    revisions = {"datasets": {"c_ds": "op-in"}, "collections": {}, "dependencies": {"c_ds": "op-ocr"}}
    assert activities._context("dataset", "c_ds", "c", revisions, {}).dependency_revision == "op-ocr"
    assert activities._context("collection", "c", "c", revisions, {}).dependency_revision == ""
    # Revisions of an earlier reader without dependencies.
    assert activities._context("dataset", "c_ds", "c", {"datasets": {}, "collections": {}}, {}).dependency_revision == ""


def test_an_automatic_request_runs_against_the_current_fingerprints(monkeypatch):
    rows = {s.step_id: {"pending_files": 7, "detail": "{}"} for s in registry.STEPS}
    monkeypatch.setattr(state, "stored_applied", lambda scopes=(): {
        ("c", "search_schema"): {"applied_fingerprint": "F-search_schema"}})
    monkeypatch.setattr(state, "input_revisions", lambda: {"datasets": {}, "collections": {}})
    monkeypatch.setattr(activities, "_desired", lambda ctx: (
        {s.step_id: registry.Desired(s.step_id, "F-" + s.step_id, "1", "")
         for s in registry.steps_of(ctx.scope_kind)}, {}))
    monkeypatch.setattr(activities, "_calculate", lambda ctx, wanted, targets: rows)
    automatic = RunUpdateParams("op", "dataset", "c", "c_ds", ["entities"], {"entities": "OLD"}, automatic=True)
    snapshot = activities.snapshot_processing_update(automatic)
    assert [s.fingerprint for s in snapshot.steps] == ["F-entities"]
    manual = RunUpdateParams("op", "dataset", "c", "c_ds", ["entities"], {"entities": "OLD"})
    with pytest.raises(ApplicationError) as raised:
        activities.snapshot_processing_update(manual)
    assert raised.value.type == activities.PREVIEW_STALE


def test_text_writers_and_consumers():
    assert set(registry.TEXT_WRITER_STEPS) == {
        "unfinished", "failed_files", "tables", "archive_members", "ocr", "pdf_text", "text_rows"}
    assert not {"entities", "vectors"} & set(registry.TEXT_WRITER_STEPS)
