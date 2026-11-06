"""Seed controlled stored OCR states and recorded date gaps for browser verification.

Run after release_browser.py in disposable datastores with current processing source.
These rows verify readers and interface states. They do not represent model execution.
"""
import hashlib
import json
import time

from database import clickhouse, manticore
from tasks.P_admin.updates.activities import apply_search_schema
from tasks.P_admin.updates.params import StepParams, StepSnapshotParams

COLLECTION = "release_browser"
DATASET = "release_browser_primary"
clickhouse.migrate_collection(COLLECTION)
print(apply_search_schema(StepParams("browser-fixture-schema", "collection", COLLECTION, DATASET, False, StepSnapshotParams("search_schema", "browser-fixture"))))
manifest = {"collection_dataset": DATASET, "documents": {}}
with clickhouse.get_collection_client(COLLECTION) as client:
    def put(table, row):
        clickhouse.insert_durable(client, table, [list(row.values())], column_names=list(row))

    def document(name, text, identifier, dates, presence):
        raw = text.encode()
        digest = hashlib.sha3_256(raw).hexdigest()
        put("blobs", dict(collection_dataset=DATASET, blob_hash=digest, blob_size_bytes=len(raw), stored_in_clickhouse=1))
        put("blob_values", dict(collection_dataset=DATASET, blob_hash=digest, blob_length=len(raw), blob_value=raw))
        put("vfs_files", dict(collection_dataset=DATASET, container_hash="", path="/" + name, hash=digest, file_size_bytes=len(raw)))
        put("file_types", dict(collection_dataset=DATASET, hash=digest, extracted_by="fixture", mime_type=["text/plain"], mime_encoding=["utf-8"], file_type=["text"], extensions=["txt"]))
        put("file_type_canonical", dict(collection_dataset=DATASET, hash=digest, file_type="text"))
        put("text_content", dict(collection_dataset=DATASET, file_hash=digest, extracted_by="raw_text", page_id=1, text=text, text_bytes=len(raw), version=1))
        put("manticore_shard_assignments", dict(collection_dataset=DATASET, file_hash=digest, shard_name=COLLECTION + "_1", text_bytes=len(raw)))
        unknown = -(2**63)
        with manticore.get_manticore_client() as connection:
            date_values = ",".join(map(str, dates or [unknown]))
            connection.cursor().execute(
                "REPLACE INTO release_browser_1_pages (id,page_text,file_hash,collection_dataset,extracted_by,page_id,dates,date_min,date_max,has_ocr_output) "
                f"VALUES (%s,%s,%s,%s,'raw_text',1,({date_values}),%s,%s,%s)",
                (identifier, text, digest, DATASET, min(dates) if dates else unknown, max(dates) if dates else unknown, presence))
        manifest["documents"][name] = {"file_hash": digest, "dates": dates, "published_presence": presence}
        return digest

    for index, (name, dates) in enumerate([
        ("date-gap.txt", [946684800, 1262304000]),
        ("date-inside.txt", [1104537600]),
        ("date-unknown.txt", []),
        ("date-before-epoch.txt", [-315619200]),
    ]):
        document(name, "chronologyfixture " + name, 791000 + index, dates, 0)

    for index, (name, state, page_state, reason, script, language, presence) in enumerate([
        ("ocr-published.txt", "applied", "ready", "detected_language", "Latin", "en", 2),
        ("ocr-absent.txt", "published", "no_text", "detected_no_text", "Latin", "en", 1),
        ("ocr-unsupported.txt", "unsupported", "unsupported", "script_coverage_unavailable", "Greek", "el", 0),
        ("ocr-failed.txt", "failed", "ready", "FixtureTransportFailure", "Cyrillic", "ru", 2),
        ("ocr-incomplete.txt", "incomplete", "incomplete", "unknown_script", "", "und", 0),
        ("ocr-planned.txt", "planned", "ready", "unknown_language_script_coverage", "Latin", "und", 0),
    ]):
        digest = document(name, "automaticfixture " + name, 791010 + index, [], presence)
        passes = [{"engine": "tesseract", "languages": {"und": "Latin", "en": "eng", "ru": "rus"}[language]} ] if page_state == "ready" else []
        plan = {"pages": [{"script": script, "language": language, "status": page_state, "reason": reason, "passes": passes}]}
        put("automatic_ocr_plans", dict(collection_dataset=DATASET, hash=digest, plan_digest="browser-status-" + digest,
            source_revision="browser-fixture", capability_digest="browser-controlled-coverage", policy_version=1,
            expected_pages=1, plan_json=json.dumps(plan), state=state, reason=reason,
            has_ocr_output=presence, revision=time.time_ns() // 1000))
        if presence == 2:
            text = "Retained published OCR fixture text."
            put("text_content", dict(collection_dataset=DATASET, file_hash=digest, extracted_by="ocr_tesseract_eng", page_id=1, text=text, text_bytes=len(text), version=1))
        manifest["documents"][name]["state"] = state

# Latest internal states must suppress earlier visible rows for the same document.
with clickhouse.get_collection_client(COLLECTION) as client:
    for label, states in [("candidate", [("candidate", 0)]), ("superseded", [("applied", 1), ("superseded", 2)])]:
        digest = hashlib.sha3_256(("browser-internal-" + label).encode()).hexdigest()
        for state, revision in states:
            clickhouse.insert_durable(client, "automatic_ocr_plans", [[DATASET, digest, "internal-" + digest,
                "browser-fixture", "browser-internal-" + label, 1, 99,
                json.dumps({"pages": [{"script": "InternalFixtureScript", "language": "und", "status": "ready"}]}),
                state, "internal-fixture", 0, revision]], column_names=["collection_dataset", "hash", "plan_digest",
                "source_revision", "capability_digest", "policy_version", "expected_pages", "plan_json", "state", "reason", "has_ocr_output", "revision"])

# Superseding an old plan can write a later revision than the current publication.
from datetime import datetime, timezone
order_dataset = "release_browser_status_order"
with clickhouse.get_global_client() as client:
    exists = client.query("SELECT count() FROM dataset FINAL WHERE collection_dataset = {dataset:String}",
                          parameters={"dataset": order_dataset}).result_rows[0][0]
    if not exists:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        clickhouse.insert_durable(client, "dataset", [[order_dataset, COLLECTION, "status_order", "Status ordering fixture",
            "s3", "fixtures/", None, "admin", now, now]], column_names=["collection_dataset", "collectionname", "dataset_name",
            "dataset_display_name", "dataset_type", "dataset_path", "dataset_access_json", "user_id", "date_created", "date_modified"])
with clickhouse.get_collection_client(COLLECTION) as client:
    for label, plan_id, state, revision, capability in [
        ("replacement", "old", "applied", 10, "old-status-order"),
        ("replacement", "new", "published", 20, "current-status-order"),
        ("replacement", "old", "superseded", 30, "old-status-order"),
        ("candidate-only", "candidate", "candidate", 0, "candidate-status-order"),
        ("superseded-only", "historical", "applied", 1, "historical-status-order"),
        ("superseded-only", "historical", "superseded", 2, "historical-status-order"),
    ]:
        digest = hashlib.sha3_256(("status-order-" + label).encode()).hexdigest()
        plan = {"pages": [{"script": "Greek", "language": "el", "status": "ready", "reason": "detected_language",
                            "passes": [{"engine": "tesseract", "languages": "ell"}]}]}
        clickhouse.insert_durable(client, "automatic_ocr_plans", [[order_dataset, digest, plan_id + "-" + digest,
            "browser-fixture", capability, 1, 1, json.dumps(plan), state, "", 2, revision]], column_names=["collection_dataset", "hash",
            "plan_digest", "source_revision", "capability_digest", "policy_version", "expected_pages", "plan_json", "state", "reason", "has_ocr_output", "revision"])

# Retained installation values must not become editing controls.
with clickhouse.get_global_client() as client:
    clickhouse.insert_durable(client, "server_settings", [[key, "fixture-retired-value"] for key in [
        "ocr.tesseract.languages", "ocr.easyocr.languages", "ocr.default.tesseract.languages", "ocr.default.easyocr.languages"]],
        column_names=["key", "value"])

print(json.dumps(manifest, indent=2))
