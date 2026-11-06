"""A failed automatic OCR file must not prevent later files from completing."""

import asyncio
from types import SimpleNamespace

import pytest
from temporalio.exceptions import ApplicationError
from tasks.P_admin import workflows
from tasks.P_admin.ocr_rerun import RerunOcrParams


def test_unsupported_first_file_keeps_later_supported_file_progress(monkeypatch):
    calls = []
    verified = []
    async def activity(name, scope, **_options):
        if name == "list_automatic_ocr_files":
            return [{"item_hash":"bad"},{"item_hash":"good"}]
        if name == "run_automatic_ocr_files":
            calls.extend(scope.hashes)
            if "bad" in scope.hashes:
                raise ApplicationError("unsupported script", non_retryable=True)
            return {"good":"pinned-plan"}
        if name == "verify_automatic_ocr_files":
            verified.extend(scope.hashes)
    async def text(*_args, **_kwargs):
        return None
    async def errors(*_args, **_kwargs):
        return None
    class Continued(Exception):
        pass
    states = []
    def continued(params):
        states.append(params)
        raise Continued()
    monkeypatch.setattr(workflows.workflow,"execute_activity",activity)
    monkeypatch.setattr(workflows.workflow,"patched",lambda _name: True)
    monkeypatch.setattr(workflows.workflow,"continue_as_new",continued)
    monkeypatch.setattr(workflows.workflow,"now",lambda: None)
    monkeypatch.setattr(workflows.workflow,"info",lambda: SimpleNamespace(run_id="fixture-run"))
    monkeypatch.setattr(workflows.OcrRunPlan,"_text_steps",text)
    from tasks.P3_parse_files import parse_common
    monkeypatch.setattr(parse_common,"record_errors_from_results",errors)
    with pytest.raises(Continued):
        asyncio.run(workflows.RerunOcr()._automatic(RerunOcrParams("collection","dataset","operation",listed=True)))
    assert calls == ["bad","good"]
    assert verified == ["good"]
    assert states[0].automatic_failed_files == 1
    assert states[0].automatic_files == 1


def test_completed_scan_reports_earlier_failed_files(monkeypatch):
    async def listed(*_args,**_kwargs):
        return []
    monkeypatch.setattr(workflows.workflow,"execute_activity",listed)
    monkeypatch.setattr(workflows.workflow,"patched",lambda _name:True)
    with pytest.raises(ApplicationError,match="1 automatic OCR files failed"):
        asyncio.run(workflows.RerunOcr()._automatic(RerunOcrParams("collection","dataset","operation",listed=True,automatic_failed_files=1)))
