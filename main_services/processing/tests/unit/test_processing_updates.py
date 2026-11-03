"""Processing updates: stage identities, fingerprints, eligibility, state order and the run."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError

from database import processing_updates as state
from tasks.P_admin import rerun_selection
from tasks.P_admin.stage_eligibility import KNOWN_TASK_NAMES
from tasks.P_admin.updates import activities, registry, selectors
from tasks.P_admin.updates import workflows as update_workflows
from tasks.P_admin.updates.params import (
    RunUpdateParams, StepOutcomeResult, StepSnapshotParams, UpdateSnapshotResult,
)
from tasks.stage_versions import STAGE_VERSIONS, canonical_stage


# ---- stage identities ----------------------------------------------------------------------

def test_every_known_error_name_has_a_stage():
    missing = [name for name in KNOWN_TASK_NAMES if canonical_stage(name) is None]
    assert not missing


def test_every_recovery_alias_has_a_stage():
    names = ["detector_error_tika", "parse_error_tika", "tika_text_batch", "pdf_process",
             "P4_ExtractEntities", "P4_ScanRegexEntities", "P5_ChunkEmbed",
             "P6_IndexTextPages", "P6_IndexVectors", "run_ocr_and_store[tesseract]",
             "run_ocr_pdf_and_store[easyocr]", "make_image_pdf[tesseract]"]
    for name in names:
        assert rerun_selection.recovery_activity(name) is not None
        assert canonical_stage(name) in STAGE_VERSIONS


def test_parameterised_names_need_an_engine():
    assert canonical_stage("run_ocr_and_store[]") is None
    assert canonical_stage("run_ocr_and_store[easyocr]") == "ocr_image"
    assert canonical_stage("no_such_task") is None


def test_every_step_stage_has_a_version():
    for step in registry.STEPS:
        for stage in step.stages:
            assert stage in STAGE_VERSIONS


# ---- fingerprints --------------------------------------------------------------------------

def test_a_fingerprint_changes_with_version_target_and_input(monkeypatch):
    ocr = registry.STEPS_BY_ID["ocr"]
    unfinished = registry.STEPS_BY_ID["unfinished"]
    base = registry.fingerprint(ocr, "eng", "op-1")
    assert base == registry.fingerprint(ocr, "eng", "op-1")
    assert base != registry.fingerprint(ocr, "eng+deu", "op-1")
    # OCR does not select unfinished work, so new input does not change its fingerprint.
    assert base == registry.fingerprint(ocr, "eng", "op-2")
    assert registry.fingerprint(unfinished, "", "op-1") != registry.fingerprint(unfinished, "", "op-2")
    monkeypatch.setitem(STAGE_VERSIONS, "ocr_image", STAGE_VERSIONS["ocr_image"] + 1)
    assert base != registry.fingerprint(ocr, "eng", "op-1")


def test_the_steps_of_a_scope_keep_registry_order():
    assert [s.step_id for s in registry.steps_of("dataset")] == [
        "unfinished", "failed_files", "virus_scan", "tables", "ocr", "pdf_text", "vectors", "folder_counts"]
    assert [s.step_id for s in registry.steps_of("collection")] == ["search_schema"]


# ---- failed files and the retry entitlement -------------------------------------------------

def test_the_automatic_retry_selects_only_unclaimed_changed_versions():
    pairs = [("a", "P4_ExtractEntities"), ("b", "parse_table_and_store"),
             ("c", "run_ocr_and_store[tesseract]"), ("d", "unknown_task"), ("e", "P5_ChunkEmbed")]
    classes = selectors.classify_failed(
        pairs, stage_is_off=lambda task: task == "P5_ChunkEmbed",
        entitled={"table": 4, "ocr_image": 2}, claimed={("ocr_image", 2)})
    assert classes["manual_tasks"] == sorted(
        ["P4_ExtractEntities", "parse_table_and_store", "run_ocr_and_store[tesseract]", "unknown_task"])
    assert classes["automatic_tasks"] == ["parse_table_and_store"]
    assert (classes["manual_files"], classes["automatic_files"]) == (4, 1)


# ---- attempts ------------------------------------------------------------------------------

def test_a_terminal_attempt_outranks_a_later_running_write():
    terminal = state.attempt_row_version("succeeded")
    late = state.attempt_row_version("running", terminal)
    assert terminal > late


def test_a_running_attempt_ends_with_its_operation():
    assert state.effective_attempt_state("running", "running") == "running"
    assert state.effective_attempt_state("running", "cancelled") == "cancelled"
    assert state.effective_attempt_state("running", "errored") == "failed"
    assert state.effective_attempt_state("running", "finished") == "failed"
    assert state.effective_attempt_state("succeeded", "cancelled") == "succeeded"


def _ctx():
    return selectors.ScopeContext("dataset", "c_ds", "c", "op-1")


def _wanted(fp="F"):
    return {s.step_id: registry.Desired(s.step_id, fp, "1", "") for s in registry.steps_of("dataset")}


def _check(step_id, fp="F", automatic=3):
    return {"desired_fingerprint": fp, "automatic_files": automatic}


def test_a_step_starts_automatically_once_for_a_fingerprint():
    checks = {("c_ds", "ocr"): _check("ocr"), ("c_ds", "vectors"): _check("vectors", automatic=0),
              ("c_ds", "unfinished"): _check("unfinished", "OLD")}
    assert activities._automatic_steps(_ctx(), _wanted(), checks, {}, {}) == ["ocr"]
    # An earlier attempt at the fingerprint, here a cancelled one, ends the automatic run.
    attempts = {("c_ds", "ocr", "F"): [{"effective_state": "cancelled"}]}
    assert activities._automatic_steps(_ctx(), _wanted(), checks, {}, attempts) == []
    failed = {("c_ds", "ocr", "F"): [{"effective_state": "failed"}]}
    assert activities._automatic_steps(_ctx(), _wanted(), checks, {}, failed) == []
    # A succeeded attempt whose fingerprint is no longer applied runs again: the setting
    # went from F to another value and back.
    returned = {("c_ds", "ocr", "F"): [{"effective_state": "succeeded"}]}
    other = {("c_ds", "ocr"): {"applied_fingerprint": "G"}}
    assert activities._automatic_steps(_ctx(), _wanted(), checks, other, returned) == ["ocr"]
    # An applied fingerprint is up to date.
    applied = {("c_ds", "ocr"): {"applied_fingerprint": "F"}}
    assert activities._automatic_steps(_ctx(), _wanted(), checks, applied, {}) == []
    # A newer desired fingerprint makes it a candidate again after its check.
    newer = {("c_ds", "ocr"): _check("ocr", "G")}
    assert activities._automatic_steps(_ctx(), _wanted("G"), newer, applied, attempts) == ["ocr"]


def test_zero_automatic_work_records_the_fingerprint(monkeypatch):
    written = []
    monkeypatch.setattr(state, "write_applied", lambda *args, **kwargs: written.append(args))
    rows = {"": {"automatic_files": 0},
            "ocr": {"desired_fingerprint": "F", "automatic_files": 0, "detail": "{}"},
            "vectors": {"desired_fingerprint": "V", "automatic_files": 2, "detail": "{}"}}
    applied = {}
    activities._record_zero_work(_ctx(), rows, applied)
    assert [args[3] for args in written] == ["ocr"]
    activities._record_zero_work(_ctx(), rows, applied)
    assert len(written) == 1


# ---- the snapshot of a request --------------------------------------------------------------

@pytest.fixture
def snapshot_env(monkeypatch):
    rows = {s.step_id: {"pending_files": 7, "detail": "{}"} for s in registry.STEPS}
    monkeypatch.setattr(state, "stored_applied", lambda scopes=(): {})
    monkeypatch.setattr(state, "input_revisions", lambda: {"datasets": {}, "collections": {}})
    monkeypatch.setattr(activities, "_desired", lambda ctx: (
        {s.step_id: registry.Desired(s.step_id, "F-" + s.step_id, "1", "")
         for s in registry.steps_of(ctx.scope_kind)}, {}))
    monkeypatch.setattr(activities, "_calculate", lambda ctx, wanted, targets: rows)
    return rows


def _request(**changes):
    params = RunUpdateParams("op", "dataset", "c", "c_ds", ["ocr"], {"ocr": "F-ocr"})
    for key, value in changes.items():
        setattr(params, key, value)
    return params


def test_an_empty_selection_runs_nothing(snapshot_env):
    with pytest.raises(ApplicationError) as raised:
        activities.snapshot_processing_update(_request(steps=[]))
    assert raised.value.type == activities.INVALID_REQUEST


def test_a_stale_preview_starts_no_work(snapshot_env):
    with pytest.raises(ApplicationError) as raised:
        activities.snapshot_processing_update(_request(fingerprints={"ocr": "OLD"}))
    assert raised.value.type == activities.PREVIEW_STALE
    assert "OCR: 7" in str(raised.value)


def test_a_pending_collection_prerequisite_refuses_a_dataset_writer(snapshot_env):
    with pytest.raises(ApplicationError) as raised:
        activities.snapshot_processing_update(_request())
    assert raised.value.type == activities.PREREQUISITE_PENDING


def test_a_current_request_snapshots_its_steps(snapshot_env, monkeypatch):
    monkeypatch.setattr(state, "stored_applied", lambda scopes=(): {
        ("c", "search_schema"): {"applied_fingerprint": "F-search_schema"}})
    snapshot = activities.snapshot_processing_update(_request(steps=["folder_counts", "ocr"]))
    assert [s.step_id for s in snapshot.steps] == ["ocr", "folder_counts"]
    assert snapshot.steps[0].fingerprint == "F-ocr"


# ---- the run of one operation ---------------------------------------------------------------

class Temporal:
    """Answers workflow commands by name and records their order."""

    def __init__(self, monkeypatch, fail_children=(), unsettled=()):
        self.calls = []
        self.fail_children = set(fail_children)
        self.unsettled = set(unsettled)
        w = update_workflows.workflow
        monkeypatch.setattr(w, "execute_activity", self.activity)
        monkeypatch.setattr(w, "execute_child_workflow", self.child)

    async def activity(self, fn, arg=None, **kwargs):
        name = fn if isinstance(fn, str) else fn.__name__
        step = getattr(getattr(arg, "step", None), "step_id", "")
        self.calls.append((name, step))
        if name == "snapshot_processing_update":
            return UpdateSnapshotResult([StepSnapshotParams(s, "F-" + s, "{}", 1) for s in arg.steps])
        if name == "settle_update_step":
            return StepOutcomeResult(step not in self.unsettled, "remaining work")
        if name == "obsolete_ocr_variants":
            return {"variants": [], "pairs": []}
        return {}

    async def child(self, name, arg=None, **kwargs):
        name = name if isinstance(name, str) else name.__qualname__.split(".")[0]
        self.calls.append(("child:" + name, kwargs.get("id", "")))
        if name in self.fail_children:
            raise ApplicationError("child failed")
        return {}


def test_steps_run_in_order_and_settle_before_they_count(monkeypatch):
    temporal = Temporal(monkeypatch)
    params = RunUpdateParams("op", "dataset", "c", "c_ds", ["unfinished", "ocr"])
    result = asyncio.run(update_workflows.RunProcessingUpdate().run(params))
    assert result == {"steps": ["unfinished", "ocr"]}
    names = [c for c in temporal.calls if not c[0].startswith("report_")]
    assert names == [
        ("snapshot_processing_update", ""),
        ("begin_update_step", "unfinished"), ("child:ExecutePlans", "update-unfinished-op"),
        ("settle_update_step", "unfinished"),
        ("begin_update_step", "ocr"), ("child:RerunOcr", "update-ocr-op"),
        ("obsolete_ocr_variants", "ocr"), ("settle_update_step", "ocr"),
        ("refresh_update_checks", ""),
    ]


def test_a_failed_step_is_recorded_and_the_next_step_runs(monkeypatch):
    temporal = Temporal(monkeypatch, fail_children={"ExecutePlans"}, unsettled={"folder_counts"})
    params = RunUpdateParams("op", "dataset", "c", "c_ds", ["unfinished", "folder_counts"])
    with pytest.raises(ApplicationError) as raised:
        asyncio.run(update_workflows.RunProcessingUpdate().run(params))
    assert "unfinished" in str(raised.value) and "folder_counts" in str(raised.value)
    calls = [c for c in temporal.calls if not c[0].startswith("report_")]
    # The failed adapter is never settled, so it cannot record an applied fingerprint.
    assert ("settle_update_step", "unfinished") not in calls
    assert ("finish_update_step", "unfinished") in calls
    assert ("settle_update_step", "folder_counts") in calls


def test_an_operation_without_steps_fails_before_any_work(monkeypatch):
    from tasks.P_ops import workflows as ops_workflows
    from tasks.P_ops.params import OperationParams

    started = []
    monkeypatch.setattr(ops_workflows.workflow, "execute_child_workflow",
                        lambda *a, **k: started.append(a))
    params = OperationParams("op", "update_dataset", "c", "c_ds", detail={"steps": []})
    with pytest.raises(ApplicationError):
        asyncio.run(ops_workflows.Operation()._processing_update(params))
    assert not started


def test_pdf_text_layer_skips_only_windows_1252_language_passes():
    from tasks.P_admin.updates.pdf_text_layer import keeps_every_letter

    assert keeps_every_letter("tesseract", "eng")
    assert keeps_every_letter("tesseract", "eng+deu+fra")
    assert keeps_every_letter("easyocr", "en+fr+de")
    assert not keeps_every_letter("tesseract", "eng+rus")
    assert not keeps_every_letter("easyocr", "en+ru")
    assert not keeps_every_letter("tesseract", "ron")
    # Codes of one engine do not apply to the other.
    assert not keeps_every_letter("easyocr", "eng")


def test_pdf_text_layer_languages_have_windows_1252_letters():
    from tasks.P_admin.updates.pdf_text_layer import WINDOWS_1252_LANGUAGES

    samples = {"deu": "äöüßÄÖÜ„“", "fra": "àâæçéèêëîïôœùûüÿŒŸ«»", "spa": "áéíñóúü¿¡", "por": "ãõâêôç",
               "swe": "åäöÅÄÖ", "isl": "ðþæöÐÞ", "est": "õäöüšž", "gle": "áéíóú"}
    for code, letters in samples.items():
        assert code in WINDOWS_1252_LANGUAGES["tesseract"]
        letters.encode("cp1252")
