"""Replay recorded workflow histories against the current workflow code.

A change to a workflow keeps the histories of running executions valid only behind a
`workflow.patched` gate. Mocked `patched` calls do not prove that, so this test replays
real histories with the Temporal SDK's `Replayer`, which fails on a command that the
history does not hold.

The histories are not in the repository: they hold the data of the deployment that
recorded them. Set `HOOVER4_REPLAY_HISTORIES` to a folder of JSON files to run the test.
Each file maps a key to an object with `workflow_id`, `workflow_type` and `history`, the
JSON of `WorkflowHistory.to_json()`. Without the folder the test is skipped.
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
        for key, entry in json.loads(path.read_text()).items():
            found.append(pytest.param(entry, id=f"{path.stem}:{entry['workflow_type']}:{key[-8:]}"))
    return found


@pytest.mark.skipif(not HISTORIES, reason="set HOOVER4_REPLAY_HISTORIES to a folder of histories")
@pytest.mark.parametrize("entry", _histories())
def test_a_recorded_history_replays_on_the_current_code(entry):
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tasks.P_admin.workflows import OcrRunPlan, RerunOcr
    from tasks.P2_execute_plan.workflows import ExecutePlans, ExecuteSinglePlan, ProcessItemsBatched
    from tasks.P4_extract_entities.workflows import ExtractEntitiesForPlan, ScanRegexEntitiesForPlan
    from tasks.P5_chunk_embed.workflows import ChunkEmbedForPlan
    from tasks.P6_index_data.workflows import IndexDatasetPlan
    from tasks.run_worker import sandboxed_runner

    replayer = Replayer(
        workflows=[RerunOcr, OcrRunPlan, ExecutePlans, ExecuteSinglePlan, ProcessItemsBatched,
                   ExtractEntitiesForPlan, ScanRegexEntitiesForPlan, ChunkEmbedForPlan,
                   IndexDatasetPlan],
        workflow_runner=sandboxed_runner(),
    )
    history = WorkflowHistory.from_json(entry["workflow_id"], entry["history"])
    result = asyncio.run(replayer.replay_workflow(history, raise_on_replay_failure=False))
    assert result.replay_failure is None, (
        f"{entry['workflow_type']} {entry['workflow_id']}: {result.replay_failure!r}")
