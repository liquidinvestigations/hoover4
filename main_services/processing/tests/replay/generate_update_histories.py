"""Generate the processing update histories of the replay suite.

It starts a local Temporal test server, so it never touches the queues of a stack. Fake
activities answer by activity name, and a dynamic workflow answers each child that the
update workflows start by name (`Operation`, `ExtractEntitiesForPlan`, `IndexDatasetPlan`).

Two sets exist, and each one needs the code of its own revision:

- ``legacy``: the update workflows before the tracks. Run the script from a checkout of that
  revision, with ``--set legacy``.
- ``tracks``: the current code, with ``--set tracks``.

    python tests/replay/generate_update_histories.py --set tracks --out fixtures/update_histories.json.gz

The script adds its histories to the output file and keeps the histories of the other set.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import sys
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Sequence

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

from temporalio import activity, workflow  # noqa: E402
from temporalio.common import RawValue  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from tasks.run_worker import sandboxed_runner  # noqa: E402

sys.path.insert(0, str(HERE))
from update_history_children import AnyChild  # noqa: E402

QUEUES = ("processing-common-queue", "operations-queue", "processing-nlp-queue",
          "processing-indexing-queue", "processing-ocr-queue", "processing-clamav-queue",
          "processing-embed-queue")
CALLS: Counter = Counter()


def _first(name: str, workflow_id: str) -> bool:
    """True for the first call of an activity in one workflow id, over every run."""
    CALLS[(name, workflow_id)] += 1
    return CALLS[(name, workflow_id)] == 1


@activity.defn(dynamic=True)
def fake_activity(args: Sequence[RawValue]):
    info = activity.info()
    name = info.activity_type
    arg = activity.payload_converter().from_payload(args[0].payload) if args else None
    first = _first(name, info.workflow_id)
    if name == "check_processing_updates":
        if not first:
            return {"candidates": [], "automatic": True, "capacity": {}, "live": {}}
        tracks = bool((arg or {}).get("tracks"))
        candidates = []
        for dataset in ("c_d1", "c_d2"):
            for track, step in (("ocr", "ocr"), ("main", "folder_counts")):
                candidates.append({"scope_kind": "dataset", "scope_id": dataset, "collectionname": "c",
                                   "collection_dataset": dataset, "steps": [step], "fingerprints": {step: "F"},
                                   **({"track": track} if tracks else {})})
        capacity = {"update_ocr": 2, "update_ner": 2, "update_vectors": 2, "update_main": 2,
                    "update_collection": 2}
        return {"candidates": candidates, "automatic": True, "calculated": 1,
                **({"capacity": capacity, "live": {}} if tracks else {})}
    if name == "update_operation_state":
        return "running" if first else "finished"
    if name == "submit_automatic_update":
        return f"started:{arg['op_id']}"
    if name == "operation_start_params":
        return {}
    if name == "snapshot_processing_update":
        return {"steps": [{"step_id": s, "fingerprint": "F-" + s, "detail": "{}", "pending": 1}
                          for s in arg["steps"]]}
    if name == "update_windows":
        return {"ocr": 3, "ner": 5, "embed": 7}
    if name == "settle_update_step":
        return {"settled": True, "message": ""}
    if name == "obsolete_ocr_variants":
        return {"variants": [], "pairs": []}
    if name in ("list_pending_plans",):
        return []
    if name == "count_new_blobs":
        return 0
    if name == "list_automatic_ocr_files":
        return [{"item_hash": h} for h in ("a1", "a2", "a3", "a4")] if first else []
    if name == "run_automatic_ocr_files":
        return {h: "plan-" + h for h in arg["hashes"]}
    if name == "list_entity_update_hashes":
        return ["e1", "e2"] if first else []
    if name == "list_update_vector_plans":
        return ["p1", "p2"] if first else []
    if name == "verify_update_vector_plan":
        return 1
    if name == "scan_pdf_text_layers":
        return {"unbuilt_parts": 0}
    if name in ("refresh_update_checks",):
        return 0
    return None


def workflows_of(set_name: str) -> list:
    from tasks.P_admin.updates.workflows import (
        ProcessingUpdates, RunProcessingUpdate, UpdateDatasetEntities, UpdateDatasetVectors,
    )
    from tasks.P_admin.workflows import OcrRunPlan, RerunOcr

    return [ProcessingUpdates, RunProcessingUpdate, UpdateDatasetEntities, UpdateDatasetVectors,
            RerunOcr, OcrRunPlan]


def update_params(set_name: str, steps: list, track: str = ""):
    from tasks.P_admin.updates.params import RunUpdateParams

    params = RunUpdateParams("op-" + "-".join(steps), "dataset", "c", "c_d1", steps, automatic=True)
    if track:
        params.track, params.profile = track, "tracks-v1"
    return params


async def runs_of(client, workflow_id: str, run_id: str) -> list:
    """Each run of a workflow id from `run_id`, following continue-as-new."""
    out = []
    while run_id:
        history = await client.get_workflow_handle(workflow_id, run_id=run_id).fetch_history()
        out.append(history)
        last = json.loads(history.to_json())["events"][-1]
        attributes = last.get("workflowExecutionContinuedAsNewEventAttributes") or {}
        run_id = attributes.get("newExecutionRunId", "")
    return out


async def children_of(client, history) -> list:
    """The `(workflow_id, run_id)` of each child that a history started."""
    found = []
    for event in json.loads(history.to_json())["events"]:
        attributes = event.get("childWorkflowExecutionStartedEventAttributes")
        if attributes:
            execution = attributes["workflowExecution"]
            found.append((attributes["workflowType"]["name"], execution["workflowId"], execution["runId"]))
    return found


async def generate(set_name: str) -> dict:
    out = {}
    real = {w.__name__ for w in workflows_of(set_name)}
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = env.client
        from tasks.visibility import ensure_search_attributes

        await ensure_search_attributes(client)
        with ThreadPoolExecutor(max_workers=8) as executor:
            workers = [Worker(client, task_queue=queue, activities=[fake_activity], activity_executor=executor,
                              workflows=[AnyChild, *(workflows_of(set_name) if queue == "processing-common-queue" else [])],
                              workflow_runner=sandboxed_runner())
                       for queue in QUEUES]
            for worker in workers:
                asyncio.ensure_future(worker.run())

            async def record(prefix: str, workflow_id: str, run_id: str) -> None:
                for index, history in enumerate(await runs_of(client, workflow_id, run_id)):
                    events = json.loads(history.to_json())
                    kind = events["events"][0]["workflowExecutionStartedEventAttributes"]["workflowType"]["name"]
                    out[f"{set_name}-{prefix}-{kind}-{index}"] = {
                        "workflow_id": workflow_id, "workflow_type": kind, "history": events}
                    for child_kind, child_id, child_run in await children_of(client, history):
                        if child_kind in real:
                            await record(prefix, child_id, child_run)

            # The coordinator: two passes, an `upgrade` request, then it is stopped. A legacy
            # run ignores the request, as an older worker that takes the signal does.
            from tasks.P_admin.updates.workflows import ProcessingUpdates

            handle = await client.start_workflow(ProcessingUpdates.run, id=f"coordinator-{uuid.uuid4().hex[:6]}",
                                                 task_queue="processing-common-queue")
            await env.sleep(timedelta(minutes=5))
            await handle.signal("request_check", {"upgrade": True})
            await env.sleep(timedelta(minutes=3))
            await handle.terminate("the generator records the passes")
            await record("coordinator", handle.id, handle.result_run_id)

            from tasks.P_admin.updates.workflows import RunProcessingUpdate

            scenarios = ([("update-ocr", ["ocr", "pdf_text"], "ocr"), ("update-ner", ["entities"], "ner"),
                          ("update-vectors", ["vectors"], "vectors")] if set_name == "tracks" else
                         [("update-mixed", ["ocr", "entities", "vectors"], "")])
            for prefix, steps, track in scenarios:
                params = update_params(set_name, steps, track)
                handle = await client.start_workflow(RunProcessingUpdate.run, params, id=f"run-{prefix}-{uuid.uuid4().hex[:6]}",
                                                     task_queue="processing-common-queue")
                await handle.result()
                await record(prefix, handle.id, handle.result_run_id)
            await asyncio.gather(*(worker.shutdown() for worker in workers))
    return out


def main() -> None:
    import logging
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=("legacy", "tracks"), required=True)
    parser.add_argument("--out", type=Path, default=HERE / "fixtures" / "update_histories.json.gz")
    options = parser.parse_args()
    existing = {}
    if options.out.exists():
        with gzip.open(options.out, "rt", encoding="utf-8") as fh:
            existing = {k: v for k, v in json.load(fh).items() if not k.startswith(options.set + "-")}
    histories = asyncio.run(generate(options.set))
    with gzip.open(options.out, "wt", encoding="utf-8") as fh:
        json.dump({**existing, **histories}, fh, sort_keys=True)
    print(f"wrote {len(histories)} {options.set} histories to {options.out}")


if __name__ == "__main__":
    main()
