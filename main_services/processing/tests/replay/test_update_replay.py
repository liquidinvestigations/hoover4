"""Replay the processing update workflows of both sets on the current code.

`fixtures/update_histories.json.gz` holds the histories of `generate_update_histories.py`.
The `legacy-` histories come from the code before the update tracks: one coordinator run
and one operation with OCR, NER and vector steps. The `tracks-` histories come from the
current code: one coordinator run and one operation of each GPU or OCR track. A deployment
replays the legacy histories of running workflows on the current code, so each one must
give the recorded commands.
"""

from __future__ import annotations

import asyncio
import copy
import gzip
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

with gzip.open(FIXTURES / "update_histories.json.gz", "rt", encoding="utf-8") as fh:
    HISTORIES = json.load(fh)


def _replay(*entries: dict) -> list:
    from temporalio.client import WorkflowHistory
    from temporalio.worker import Replayer

    from tasks.P_admin.updates.workflows import (
        ProcessingUpdates, RunProcessingUpdate, UpdateDatasetEntities, UpdateDatasetVectors,
    )
    from tasks.P_admin.workflows import OcrRunPlan, RerunOcr
    from tasks.run_worker import sandboxed_runner

    replayer = Replayer(workflows=[ProcessingUpdates, RunProcessingUpdate, UpdateDatasetEntities,
                                   UpdateDatasetVectors, RerunOcr, OcrRunPlan],
                        workflow_runner=sandboxed_runner())

    async def run() -> list:
        out = []
        for entry in entries:
            history = WorkflowHistory.from_json(entry["workflow_id"], entry["history"])
            result = await replayer.replay_workflow(history, raise_on_replay_failure=False)
            out.append(result.replay_failure)
        return out

    return asyncio.run(run())


def _prefixes(entry: dict) -> list[dict]:
    """The history at each point where an activity, a child or a timer runs."""
    out = []
    events = entry["history"]["events"]
    for index, event in enumerate(events[:-1]):
        if event["eventType"] in ("EVENT_TYPE_ACTIVITY_TASK_STARTED", "EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED",
                                  "EVENT_TYPE_TIMER_STARTED"):
            prefix = copy.deepcopy(entry)
            prefix["history"]["events"] = events[:index + 1]
            out.append(prefix)
    return out


def _text(entry: dict) -> str:
    return json.dumps(entry["history"])


def _patches(entry: dict) -> set:
    """The patch ids of the markers of a history. The history stores them base64 encoded."""
    import base64

    found = set()
    for event in entry["history"]["events"]:
        details = (event.get("markerRecordedEventAttributes") or {}).get("details") or {}
        for payload in (details.get("patch-data") or {}).get("payloads", []):
            found.add(json.loads(base64.b64decode(payload["data"]))["id"])
    return found


@pytest.mark.parametrize("key", sorted(HISTORIES))
def test_a_history_and_its_in_flight_prefixes_replay(key):
    entries = [HISTORIES[key], *_prefixes(HISTORIES[key])]
    assert _replay(*entries) == [None] * len(entries)


def test_both_sets_cover_the_changed_workflows():
    kinds = {(key.split("-")[0], entry["workflow_type"]) for key, entry in HISTORIES.items()}
    for kind in ("ProcessingUpdates", "RunProcessingUpdate", "RerunOcr", "UpdateDatasetEntities",
                 "UpdateDatasetVectors"):
        assert ("legacy", kind) in kinds and ("tracks", kind) in kinds, kind


def test_the_legacy_histories_come_from_the_code_before_the_tracks():
    for key, entry in HISTORIES.items():
        if key.startswith("legacy-"):
            assert "processing-update-tracks" not in _patches(entry), key
            assert "update_windows" not in _text(entry), key
    legacy_ocr = [e for k, e in HISTORIES.items() if k.startswith("legacy-") and e["workflow_type"] == "RerunOcr"]
    assert any("ExtractEntitiesForPlan" in _text(e) for e in legacy_ocr)


def test_the_tracks_histories_hold_the_new_commands():
    tracks = {k: e for k, e in HISTORIES.items() if k.startswith("tracks-")}
    coordinator = [e for e in tracks.values() if e["workflow_type"] == "ProcessingUpdates"]
    assert coordinator and all("processing-update-tracks" in _patches(e) for e in coordinator)
    ocr = [e for e in tracks.values() if e["workflow_type"] == "RerunOcr"]
    assert ocr and not any("ExtractEntitiesForPlan" in _text(e) or "ChunkEmbedForPlan" in _text(e) for e in ocr)
    assert any("update_windows" in _text(e) for e in tracks.values() if e["workflow_type"] == "RunProcessingUpdate")



def _signals(entry: dict) -> list:
    """The decoded inputs of the signals of a history."""
    import base64

    found = []
    for event in entry["history"]["events"]:
        attributes = event.get("workflowExecutionSignaledEventAttributes") or {}
        for payload in (attributes.get("input") or {}).get("payloads", []):
            found.append(json.loads(base64.b64decode(payload["data"])))
    return found


def test_a_legacy_coordinator_that_an_older_worker_signalled_keeps_its_loop():
    """An older worker ignored the `upgrade` request, so the replay must not leave the loop."""
    legacy = [e for k, e in HISTORIES.items() if k.startswith("legacy-") and e["workflow_type"] == "ProcessingUpdates"]
    assert legacy and all({"upgrade": True} in _signals(e) for e in legacy)
    assert all("processing-update-upgrade" not in _patches(e) for e in legacy)
    for entry in legacy:
        events = entry["history"]["events"]
        signalled = next(i for i, e in enumerate(events) if "workflowExecutionSignaledEventAttributes" in e)
        assert any("activityTaskScheduledEventAttributes" in e for e in events[signalled:])
