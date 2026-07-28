"""Shared helpers for the integration tests (live docker stack required)."""

import json
import os
import time
import urllib.request

PLAN_POLL_INTERVAL_S = 5


def ner_service_reachable() -> bool:
    """Whether the remote NER service answers on its real endpoint.

    Probes ``{NER_URL}/extract-entities`` with a one-text request — the same
    endpoint the P4 stage posts to (NOT ``/docs``: a healthy service that does
    not serve docs would otherwise be reported unreachable, silently downgrading
    every test that branches on this probe).

    When it does not answer, P4 records its failures in ``processing_errors`` and
    the pipeline continues with empty entity MVAs — but ``nlp_processed`` stays
    empty, so tests asserting on it must branch on this probe.
    """
    ner_url = os.environ.get("NER_URL", "")
    if not ner_url:
        return False
    try:
        req = urllib.request.Request(
            f"{ner_url}/extract-entities",
            data=json.dumps({
                "input": ["ping"],
                "include_confidence": False,
                "entity_types": None,
            }).encode(),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=5)
        return True
    except Exception:
        return False


def wait_for_plans_finished(collectionname: str, timeout_s: int = 1800) -> None:
    """Poll until every plan of the collection is finished (P0..P5 chain done).

    ``processing_plan_finished`` is written at the very end of the per-plan
    workflow chain (parse -> NLP -> index), so equality means ingestion,
    entity extraction and indexing have all completed.
    """
    from database.clickhouse import get_collection_client

    deadline = time.monotonic() + timeout_s
    while True:
        with get_collection_client(collectionname) as client:
            plans = client.query(
                "SELECT count() FROM processing_plans FINAL"
            ).result_rows[0][0]
            finished = client.query(
                "SELECT count() FROM processing_plan_finished FINAL"
            ).result_rows[0][0]
        if plans > 0 and plans == finished:
            return
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"plans of {collectionname} not finished after {timeout_s}s: "
                f"{finished}/{plans}"
            )
        time.sleep(PLAN_POLL_INTERVAL_S)


def ingest_dataset(collectionname: str, dataset_name: str, path: str) -> str:
    """Register a disk dataset and submit its plans (same calls as
    ``main.py add-disk-dataset``). Returns the ``collection_dataset`` id.
    Does NOT wait for the plans to finish — see :func:`wait_for_plans_finished`.
    """
    import asyncio

    from tasks.P0_scan_disk.submit_job import add_disk_dataset, compose_collection_dataset
    from tasks.P1_compute_plans.submit_job import submit_compute_plans
    from tasks.P2_execute_plan.submit_job import submit_execute_plans

    add_disk_dataset(collectionname, dataset_name, path)
    collection_dataset = compose_collection_dataset(collectionname, dataset_name)
    asyncio.run(submit_compute_plans(collectionname, collection_dataset))
    asyncio.run(submit_execute_plans(collectionname, collection_dataset))
    return collection_dataset
