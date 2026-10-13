"""Replay recorded workflow histories against the current workflow code.

A change to a workflow keeps the histories of running executions valid only behind a
`workflow.patched` gate. Mocked `patched` calls do not prove that, so this test replays
real histories with the Temporal SDK's `Replayer`, which fails on a command that the
history does not hold.

Tracked sanitized histories verify activity contracts. Deployment captures remain local.
Set `HOOVER4_REPLAY_HISTORIES` to a folder of JSON files to replay deployment captures.
Each file maps a key to an object with `workflow_id`, `workflow_type` and `history`, the
JSON of `WorkflowHistory.to_json()`. Without the folder only deployment capture tests skip.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

HISTORIES = os.environ.get("HOOVER4_REPLAY_HISTORIES", "")


def _histories():
    if not HISTORIES:
        return []
    found = []
    for path in sorted(Path(HISTORIES).glob("*.json")):
        entries = json.loads(path.read_text())
        entries = enumerate(entries) if isinstance(entries, list) else entries.items()
        for key, captured in entries:
            entry = dict(captured)
            entry.setdefault("workflow_type", entry.get("type"))
            key = str(key)
            found.append(pytest.param(entry, id=f"{path.stem}:{entry['workflow_type']}:{key[-8:]}"))
    return found


@pytest.mark.skipif(not HISTORIES, reason="set HOOVER4_REPLAY_HISTORIES to a folder of histories")
@pytest.mark.parametrize("entry", _histories())
def test_a_recorded_history_replays_on_the_current_code(entry):
    _replay_history(entry)


_INDEX_FIXTURES = json.loads((Path(__file__).parent / "fixtures" /
                             "index_activity_contract_histories.json").read_text())
_CURSOR_FIXTURES = json.loads((Path(__file__).parent / "fixtures" /
                              "pdf_cursor_contract_histories.json").read_text())


@pytest.mark.parametrize("entry", [pytest.param(entry, id=name)
                                  for name, entry in _INDEX_FIXTURES.items()])
def test_index_activity_contract_generations_replay(entry):
    _replay_history(entry)


@pytest.mark.parametrize("entry", [pytest.param(entry, id=name)
                                  for name, entry in _CURSOR_FIXTURES.items()])
def test_cursor_continuation_and_interrupted_histories_replay(entry):
    _replay_history(entry)


def _replay_history(entry):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tasks.P_admin.workflows import OcrRunPlan, RerunOcr, ChangeOcrLanguages
    from tasks.P_ops.workflows import Operation
    from tasks.P0_scan_disk.workflows import IngestAndProcessDataset, IngestDiskDataset
    from tasks.P1_compute_plans.workflows import ComputePlans
    from tasks.P2_execute_plan.workflows import ExecutePlans, ExecuteSinglePlan, ProcessItemsBatched
    from tasks.P4_extract_entities.workflows import ExtractEntitiesForPlan, ScanRegexEntitiesForPlan
    from tasks.P5_chunk_embed.workflows import ChunkEmbedForPlan
    from tasks.P6_index_data.workflows import IndexDatasetPlan
    from tasks.P3_parse_files.pdf_cursor import PdfPartGroup
    from tasks.run_worker import sandboxed_runner

    replayer = Replayer(
        workflows=[RerunOcr, OcrRunPlan, ChangeOcrLanguages, Operation, IngestAndProcessDataset, IngestDiskDataset, ComputePlans, ExecutePlans, ExecuteSinglePlan, ProcessItemsBatched,
                   ExtractEntitiesForPlan, ScanRegexEntitiesForPlan, ChunkEmbedForPlan,
                   IndexDatasetPlan, PdfPartGroup],
        workflow_runner=sandboxed_runner(),
    )
    history = WorkflowHistory.from_json(entry["workflow_id"], entry["history"])
    result = asyncio.run(replayer.replay_workflow(history, raise_on_replay_failure=False))
    assert result.replay_failure is None, (
        f"{entry['workflow_type']} {entry['workflow_id']}: {result.replay_failure!r}")
