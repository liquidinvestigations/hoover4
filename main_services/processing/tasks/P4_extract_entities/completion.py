"""Versioned NER completion and exact provider replacement."""

import hashlib
import os

NER_STAGE_VERSION = 2


def target() -> dict:
    """The entity update target. NER runs on the GPU only, so `provider` is always `gpu`.
    The key stays in the target because the update fingerprint hashes the whole dict."""
    from .activities import configured_nlp_model
    return {"enabled": bool((os.getenv("NER_URL") or "").strip()), "provider": "gpu",
            "model": configured_nlp_model(), "coverage_version": 2}


def replace_completed_groups(client, dataset, rows):
    """Replace only successfully inferred provider groups whose source remains current."""
    from tasks.text_sources import fetch_text_batch, plan_text_batches
    wanted = {(row["file_hash"], row["extracted_by"], int(row["page_id"])):
              (int(row["text_version"]), row["text_digest"]) for row in rows}
    actual = {}
    for batch in plan_text_batches([(key, 0) for key in wanted]):
        for row in fetch_text_batch(client, dataset, batch):
            actual[row["file_hash"], row["extracted_by"], int(row["page_id"])] = (
                int(row.get("text_version", 0)), hashlib.sha256(row["text"].encode("utf-8")).hexdigest())
    if actual != wanted:
        raise RuntimeError("NER source text changed before publication")
    keys = [(row["file_hash"], row["extracted_by"], int(row["page_id"]), row["nlp_model"]) for row in rows]
    for start in range(0, len(keys), 100):
        for table in ("entity_hit", "nlp_processed"):
            client.command(f"DELETE FROM {table} WHERE collection_dataset = {{cd:String}} "
                "AND (file_hash, extracted_by, page_id, nlp_model) IN {keys:Array(Tuple(String,String,UInt32,String))} "
                "SETTINGS mutations_sync = 2", parameters={"cd": dataset, "keys": keys[start:start + 100]})
