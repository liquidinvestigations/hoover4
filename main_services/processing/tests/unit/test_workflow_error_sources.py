"""Workflow Error rows keep the source schedule of each failed shard writer."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tasks.P4_extract_entities import workflows as entity_workflows
from tasks.P4_extract_entities.params import (
    ExtractEntitiesForPlanParams, ScanRegexEntitiesForPlanParams,
)
from tasks.P5_chunk_embed import workflows as embed_workflows
from tasks.P5_chunk_embed.params import ChunkEmbedForPlanParams
from tasks.P6_index_data import workflows as index_workflows
from tasks.P6_index_data.params import IndexDatasetPlanParams
from tasks.P2_execute_plan import workflows as plan_workflows
from tasks.P3_parse_files import workflows as parse_workflows
from tasks.P3_parse_files import parse_pdf
from tasks.P3_parse_files import parse_common


def test_p6_failed_writers_keep_one_source_id_for_each_chunk_member(monkeypatch):
    hashes = [f"hash-{index}" for index in range(100)] + ["hash-0"]
    captured = []

    def execute_activity(fn, _params, **_kwargs):
        async def result():
            if fn is index_workflows.fetch_plan_hashes:
                return hashes
            if fn is index_workflows.plan_shards:
                return [SimpleNamespace(shard_name="shard", hashes=hashes)]
            if fn in (index_workflows.index_text_pages,
                      index_workflows.index_vectors):
                raise RuntimeError("writer failed")
            return None
        return result()

    async def record_errors(results, **kwargs):
        captured.append((results, kwargs))
        return len(results)

    monkeypatch.setattr(index_workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(index_workflows.workflow, "now", lambda:
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(index_workflows.workflow, "info", lambda:
                        SimpleNamespace(run_id="run"))
    monkeypatch.setattr(index_workflows, "record_errors_from_results", record_errors)

    params = IndexDatasetPlanParams("collection", "dataset", "plan", "op")
    asyncio.run(index_workflows.IndexDatasetPlan().run(params))
    asyncio.run(index_workflows.IndexDatasetPlan().run(params))

    results, passed = captured[0]
    assert len(results) == len(passed["source_execution_ids"]) == 202
    assert len(passed["item_hashes"]) == 202
    assert captured[1][1]["source_execution_ids"] == passed["source_execution_ids"]
    ids_by_hash = {}
    for item_hash, task, source in zip(
        passed["item_hashes"], passed["task_ids"],
        passed["source_execution_ids"]
    ):
        assert source
        ids_by_hash[(item_hash, task)] = json.loads(source)
    assert ids_by_hash[("hash-0", "P6_IndexTextPages")] == ["run", "P6.text", 1]
    assert ids_by_hash[("hash-0", "P6_IndexVectors")] == ["run", "P6.vectors", 1]
    assert json.loads(passed["source_execution_ids"][0]) == ["run", "P6.text", 0]
    assert json.loads(passed["source_execution_ids"][100]) == ["run", "P6.vectors", 0]


@pytest.mark.parametrize("stage,workflow_type,params_type,activity_name,label,task_name", [
    (entity_workflows, entity_workflows.ExtractEntitiesForPlan,
     ExtractEntitiesForPlanParams, "extract_entities_for_hashes", "P4.entities",
     "P4_ExtractEntities"),
    (entity_workflows, entity_workflows.ScanRegexEntitiesForPlan,
     ScanRegexEntitiesForPlanParams, "scan_regex_entities_for_hashes", "P4.regex",
     "P4_ScanRegexEntities"),
    (embed_workflows, embed_workflows.ChunkEmbedForPlan,
     ChunkEmbedForPlanParams, "chunk_embed_for_hashes", "P5.embed",
     "P5_ChunkEmbed"),
])
def test_failed_chunks_keep_their_source_id_for_each_hash(
    monkeypatch, stage, workflow_type, params_type, activity_name, label, task_name
):
    hashes = [f"hash-{index}" for index in range(100)] + ["hash-0"]
    captured = []

    def execute_activity(fn, _params, **_kwargs):
        async def result():
            if fn is stage.fetch_plan_hashes:
                return hashes
            if fn.__name__ == activity_name:
                raise RuntimeError("chunk failed")
            raise AssertionError(fn.__name__)
        return result()

    async def record_errors(results, **kwargs):
        captured.append((results, kwargs))
        return len(results)

    monkeypatch.setattr(stage.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(stage.workflow, "now", lambda:
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(stage.workflow, "info", lambda:
                        SimpleNamespace(run_id="run"))
    monkeypatch.setattr(stage, "record_errors_from_results", record_errors)

    params = params_type("collection", "dataset", "plan", "op")
    asyncio.run(workflow_type().run(params))
    asyncio.run(workflow_type().run(params))

    results, passed = captured[0]
    assert len(results) == len(passed["source_execution_ids"]) == 101
    assert captured[1][1]["source_execution_ids"] == passed["source_execution_ids"]
    assert passed["task_ids"] == [task_name] * 101
    assert all(source for source in passed["source_execution_ids"])
    assert all(json.loads(source) == ["run", label, 0]
               for source in passed["source_execution_ids"][:100])
    assert json.loads(passed["source_execution_ids"][100]) == ["run", label, 1]


def test_p2_continuation_uses_new_run_id_for_aligned_children(monkeypatch):
    captured = []
    next_runs = []
    run_id = ["first"]
    monkeypatch.setattr(plan_workflows, "MAX_ITEMS_PER_RUN", 2)
    monkeypatch.setattr(plan_workflows.workflow, "now", lambda:
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(plan_workflows.workflow, "info", lambda:
                        SimpleNamespace(run_id=run_id[0]))
    monkeypatch.setattr(plan_workflows.workflow, "continue_as_new", next_runs.append)

    def execute_child(_run, child, **_kwargs):
        async def result():
            raise RuntimeError(child.item_hash)
        return result()

    async def run_window(factories, _limit):
        return await asyncio.gather(*(factory() for factory in factories),
                                    return_exceptions=True)

    async def record(results, **kwargs):
        captured.append((results, kwargs))
        return len(results)

    monkeypatch.setattr(plan_workflows, "run_with_window", run_window)
    monkeypatch.setattr(plan_workflows.workflow, "execute_child_workflow", execute_child)
    monkeypatch.setattr(plan_workflows, "record_errors_from_results", record)
    items = [{"item_hash": value} for value in ("a", "b", "c")]
    params = plan_workflows.ProcessItemsBatchedParams(
        "collection", "dataset", "plan", "/tmp", items, "op")
    asyncio.run(plan_workflows.ProcessItemsBatched().run(params))
    assert len(next_runs) == 1
    run_id[0] = "second"
    asyncio.run(plan_workflows.ProcessItemsBatched().run(next_runs[0]))

    assert [call[1]["item_hashes"] for call in captured] == [["a", "b"], ["c"]]
    assert [[str(result) for result in results] for results, _ in captured] == [
        ["a", "b"], ["c"]]
    assert [[json.loads(source) for source in call[1]["source_execution_ids"]]
            for call in captured] == [
                [["first", "P2.parse_file", 0], ["first", "P2.parse_file", 1]],
                [["second", "P2.parse_file", 0]],
            ]
    assert all(len(results) == len(kwargs["source_execution_ids"])
               for results, kwargs in captured)


@pytest.mark.parametrize("parser_present", [False, True])
def test_p3_detector_and_parser_ids_follow_scheduled_results(monkeypatch, parser_present):
    captured = []
    detector_names = list(parse_workflows.LOCAL_DETECTORS)
    assert len(detector_names) == 4
    local = {"detectors": {name: {"coarse_types": [], "mime_types": []}
                           for name in detector_names[1:]},
             "errors": {detector_names[0]: "local detector failed"}}
    if parser_present:
        local["detectors"][detector_names[1]]["coarse_types"] = ["text"]

    def execute_activity(fn, _params, **_kwargs):
        async def result():
            if fn is parse_workflows.detect_mime_all:
                return local
            if fn is parse_workflows.run_tika_and_store:
                raise RuntimeError("tika failed")
            if fn is parse_workflows.extract_plaintext_chunks:
                raise RuntimeError("parser failed")
            raise AssertionError(fn.__name__)
        return result()

    async def record(results, **kwargs):
        captured.append((results, kwargs))
        return len(results)

    monkeypatch.setattr(parse_workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(parse_workflows.workflow, "now", lambda:
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(parse_workflows.workflow, "info", lambda:
                        SimpleNamespace(run_id="parse-run"))
    monkeypatch.setattr(parse_workflows, "record_errors_from_results", record)
    params = parse_workflows.ParseSingleFileParams(
        "collection", "dataset", "plan", "hash", "/tmp/file", 0, "op")
    asyncio.run(parse_workflows.ParseSingleFile().run(params))

    detector_results, detector = captured[0]
    assert len(detector_results) == len(detector_names) + 1
    assert isinstance(detector_results[0], Exception)
    assert isinstance(detector_results[-1], Exception)
    assert detector["task_ids"] == [f"detector_error_{name}"
                                     for name in detector_names + ["tika"]]
    assert [json.loads(source) for source in detector["source_execution_ids"]] == [
        ["parse-run", "P3.detector", index]
        for index in range(len(detector_names) + 1)
    ]
    parser_results, parser = captured[1]
    assert len(parser_results) == int(parser_present)
    assert parser["task_ids"] == (["extract_plaintext_chunks"] if parser_present else [])
    assert [json.loads(source) for source in parser["source_execution_ids"]] == (
        [["parse-run", "P3.parser", 0]] if parser_present else [])


def test_pdf_ocr_ids_follow_engine_results_when_one_fails(monkeypatch):
    captured = []
    assert len(parse_pdf.OCR_ENGINES) >= 2
    failing_engine = parse_pdf.OCR_ENGINES[1]

    def execute_activity(fn, params, **_kwargs):
        async def result():
            if fn is parse_pdf.pdf_get_metadata_and_store:
                return {"page_count": 1, "size_bytes": 1}
            if fn is parse_pdf.pdf_small_extract_text_and_images:
                return {"out_dir": None}
            if fn is parse_pdf.run_ocr_pdf_and_store:
                if params.engine == failing_engine:
                    raise RuntimeError("ocr failed")
                return "ok"
            raise AssertionError(fn.__name__)
        return result()

    async def record(results, **kwargs):
        captured.append((results, kwargs))
        return len(results)

    monkeypatch.setattr(parse_pdf.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(parse_pdf.workflow, "now", lambda:
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(parse_pdf.workflow, "info", lambda:
                        SimpleNamespace(run_id="pdf-run"))
    monkeypatch.setattr(parse_common, "record_errors_from_results", record)
    params = parse_pdf.PdfProcessingWorkflowParams(
        "collection", "dataset", "pdf-hash", "/tmp/file.pdf", 60, "op")
    asyncio.run(parse_pdf.PdfProcessingAndScan().run(params))

    results, passed = captured[0]
    assert len(results) == len(parse_pdf.OCR_ENGINES)
    assert isinstance(results[1], Exception)
    assert passed["task_ids"] == [f"run_ocr_pdf_and_store[{engine}]"
                                  for engine in parse_pdf.OCR_ENGINES]
    assert passed["item_hashes"] == ["pdf-hash"] * len(results)
    assert [json.loads(source) for source in passed["source_execution_ids"]] == [
        ["pdf-run", "P3.pdf_ocr", index]
        for index in range(len(results))
    ]
