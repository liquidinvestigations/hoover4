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
from tasks.P3_parse_files.batch_runner import BatchResult, FileResult


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


def test_group_detector_and_parser_ids_follow_file_and_entry_order(monkeypatch):
    """Detector ids are 5 x file index + detector index. Parser ids count every entry."""
    captured = []
    hashes = ["a", "b"]
    detector_names = list(parse_workflows.LOCAL_DETECTORS) + ["tika"]

    def execute_activity(name, params, **_kwargs):
        async def result():
            results = []
            for file in params.files:
                if name == "detect_mime_batch":
                    value = {"detectors": {}, "errors": {n: "failed" for n in detector_names[:-1]}}
                    value["detectors"][detector_names[1]] = {"coarse_types": ["text"]}
                    results.append(FileResult(file.item_hash, "detect_mime_all", "ok", value))
                else:
                    results.append(FileResult(file.item_hash, name, "failed",
                                              error_type="Broken", error_message=name))
            return BatchResult(stage=name, results=results)
        return result()

    async def record(results, **kwargs):
        captured.append((results, kwargs))
        return len(results)

    monkeypatch.setattr(plan_workflows.workflow, "execute_activity", execute_activity)
    monkeypatch.setattr(plan_workflows.workflow, "now", lambda:
                        datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(plan_workflows.workflow, "info", lambda:
                        SimpleNamespace(run_id="group-run"))
    monkeypatch.setattr(plan_workflows, "record_errors_from_results", record)
    params = plan_workflows.ProcessItemsBatchedParams(
        "collection", "dataset", "plan", "/tmp", [{"item_hash": h} for h in hashes], "op")
    assert asyncio.run(plan_workflows.ProcessItemsBatched().run(params)) == "processed 2 items"

    detector_results, detector = captured[0]
    assert len(detector_results) == len(detector_names) * len(hashes)
    assert detector["item_hashes"] == [h for h in hashes for _ in detector_names]
    assert detector["task_ids"] == [f"detector_error_{name}"
                                    for _ in hashes for name in detector_names]
    assert [json.loads(source) for source in detector["source_execution_ids"]] == [
        ["group-run", "P3.group.detector", index]
        for index in range(len(detector_names) * len(hashes))]
    parser_results, parser = captured[1]
    assert parser["task_ids"] == ["extract_plaintext_chunks"] * len(hashes)
    assert parser["item_hashes"] == hashes
    assert all(isinstance(result, Exception) for result in parser_results)
    assert [json.loads(source) for source in parser["source_execution_ids"]] == [
        ["group-run", "P3.group.parser", index] for index in range(len(hashes))]
