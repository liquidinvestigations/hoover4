#!/usr/bin/env python3
"""Prepare local browser QA datasets through the supported disk-ingest command."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import re
import zipfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses

WORKER_STAGING_ROOT = Path(os.environ.get("MANUAL_QA_STAGING_ROOT", "/tmp/manual-qa-preparation"))
CONTRACT_PATH = WORKER_STAGING_ROOT / "manual_qa_fixtures.json"
PROFILE_PATH = WORKER_STAGING_ROOT / "manual_qa_fixtures.resolved.json"
SOURCE_ROOT = Path("/testdata/hoover-testdata/data")
GENERATED_ROOT = Path("/testdata/generated/manual-qa")
LEAF_ROOT = Path("/testdata/generated/manual-qa-leaf")
WIDE_ROOT = Path("/testdata/generated/wide")
ORIGINAL_PDF_ROOT = Path("/testdata/generated/manual-qa-original-pdf")
EXCELS_ROOT = SOURCE_ROOT / "www.learningcontainer.com/excels"
DISKFILES_ROOT = SOURCE_ROOT / "disk-files"
QA_ERRORED_DATASET = "testdata_qa_errored_confirm"
DISCOVER_DATASETS = (
    "testdata_manualqa", "testdata_excelsc", "testdata_wide", "testdata_leaf",
    "testdata_shapes", "testdata_manualpdf", "testdata_diskfiles",
)
LOCAL_INGEST = (
    ("manualqa", GENERATED_ROOT),
    ("excelsc", EXCELS_ROOT),
    ("wide", WIDE_ROOT),
    ("leaf", LEAF_ROOT),
    ("diskfiles", DISKFILES_ROOT),
)

SOURCES = {
    "entity-fixtures/shipping-manifest.txt": SOURCE_ROOT / "disk-files/entity-fixtures/shipping-manifest.txt",
    "entity-fixtures/invoice-batch.docx": SOURCE_ROOT / "disk-files/entity-fixtures/invoice-batch.docx",
    "entity-fixtures/generate.py": SOURCE_ROOT / "disk-files/entity-fixtures/generate.py",
    "entity-fixtures/security-incident.eml": SOURCE_ROOT / "disk-files/entity-fixtures/security-incident.eml",
    "documents/easychair.docx": SOURCE_ROOT / "disk-files/pdf-doc-txt/easychair.docx",
    "documents/easychair.odt": SOURCE_ROOT / "disk-files/pdf-doc-txt/easychair.odt",
    "documents/easychair.txt": SOURCE_ROOT / "disk-files/pdf-doc-txt/easychair.txt",
    "documents/stanley.ec02.pdf": SOURCE_ROOT / "disk-files/pdf-doc-txt/stanley.ec02.pdf",
    "emails/Urăsc canicula, e nașpa.eml": SOURCE_ROOT / "eml-2-attachment/Urăsc canicula, e nașpa.eml",
    "archives/parent.zip": SOURCE_ROOT / "zip-in-multiple-locations/location-1/parent.zip",
    "archives/the-directory.zip": SOURCE_ROOT / "many-children/the-directory.zip",
    "images/bikes.jpg": SOURCE_ROOT / "disk-files/images/bikes.jpg",
}


def run(command: list[str]) -> str:
    result = subprocess.run(command, check=False, text=True, capture_output=True)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    result.check_returncode()
    return result.stdout


def clickhouse(sql: str) -> list[dict[str, str]]:
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from database.clickhouse import get_collection_client
    with get_collection_client("testdata") as client:
        result = client.query(sql)
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def global_clickhouse(sql: str) -> list[dict[str, str]]:
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from database.clickhouse import get_global_client
    with get_global_client() as client:
        result = client.query(sql)
    return [dict(zip(result.column_names, row, strict=True)) for row in result.result_rows]


def write_generated_sources(root: Path, leaf_root: Path, wide_root: Path) -> None:
    for destination, source in SOURCES.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    tiny_pdf = Path("/app/tests/fixtures/tiny/tiny.pdf")
    if not tiny_pdf.is_file():
        raise FileNotFoundError(tiny_pdf)
    target = root / "documents/born-digital-no-ocr.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(tiny_pdf, target)
    ORIGINAL_PDF_ROOT.mkdir(parents=True, exist_ok=True)
    (ORIGINAL_PDF_ROOT / "original-only.pdf").write_bytes(
        tiny_pdf.read_bytes() + b"\n% hoover4 original-only QA v1\n")
    (root / "substitutes").mkdir(parents=True, exist_ok=True)
    (root / "substitutes/mail-search-substitute.txt").write_text(
        "jeff.hoover@enron.com\n" + "\n".join(
            f"enron separator{number}" for number in range(1, 21)
        ) + "\n", encoding="utf-8")
    with (root / "substitutes/manual-qa-table.csv").open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle, lineterminator="\n").writerows([
            ["Case", "Region", "Amount"], ["A-01", "Bucharest", "10"],
            ["A-02", "Cluj", "20"], ["A-03", "Iași", "30"],
        ])
    leaf_root.mkdir(parents=True, exist_ok=True)
    (leaf_root / "leaf.txt").write_text("manual QA leaf dataset\n", encoding="utf-8")
    wide_root.mkdir(parents=True, exist_ok=True)
    with (wide_root / "wide.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow([f"col{number}" for number in range(1, 351)])
        for row in range(1, 6):
            writer.writerow([f"v{row}_{number}" for number in range(1, 351)])


def source_rows(dataset: str) -> list[dict[str, object]]:
    rows = clickhouse(
        "SELECT f.path, f.hash, toString(f.file_size_bytes) AS file_size_bytes, "
        "arrayStringConcat(groupUniqArray(t.extracted_by), ',') AS extracted_by "
        "FROM Hoover4_Collection_testdata.vfs_files AS f FINAL "
        "LEFT JOIN Hoover4_Collection_testdata.text_content AS t FINAL "
        "ON f.collection_dataset=t.collection_dataset AND f.hash=t.file_hash "
        f"WHERE f.collection_dataset='{dataset}' GROUP BY f.path, f.hash, f.file_size_bytes ORDER BY f.path")
    return [{"path": row["path"], "hash": row["hash"], "file_size_bytes": int(row["file_size_bytes"]),
             "extracted_by": sorted(filter(None, row["extracted_by"].split(",")))} for row in rows]


def pdf_byte_page_count(path: Path) -> int:
    output = run(["pdfinfo", str(path)])
    for line in output.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1])
    raise RuntimeError(f"pdfinfo did not report pages for {path}")


def document(resolved: dict[str, object], dataset: str, path: str) -> dict[str, object] | None:
    return next((row for row in resolved["datasets"].get(dataset, []) if row["path"] == path), None)


def email_expectations(source: bytes) -> dict[str, object]:
    """Read envelope and attachment expectations directly from an email source."""
    message = BytesParser(policy=policy.default).parsebytes(source)
    envelope = {
        field: [{"name": name, "address": address} for name, address in getaddresses(
            [str(value) for value in message.get_all(field, [])])]
        for field in ("from", "to", "cc")
    }
    attachments = []
    for part in message.walk():
        filename = part.get_filename()
        if filename is None:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            raise ValueError(f"Cannot calculate attachment bytes for {filename!r}")
        attachments.append({"filename": filename, "sha256": hashlib.sha256(payload).hexdigest(),
                            "sha3_256": hashlib.sha3_256(payload).hexdigest(),
                            "size_bytes": len(payload), "content_type": part.get_content_type()})
    return {"subject": str(message.get("subject", "")), "envelope": envelope, "attachments": attachments}


def source_expectations(generated_root: Path) -> dict[str, object]:
    """Verify copied source identities and record their independent expectations."""
    files = []
    for destination, source in SOURCES.items():
        content = source.read_bytes()
        copied = (generated_root / destination).read_bytes()
        if copied != content:
            raise ValueError(f"Prepared source differs from fixture source: {destination}")
        files.append({"dataset": "testdata_manualqa", "path": "/" + destination,
                      "source_path": str(source.relative_to(SOURCE_ROOT)),
                      "sha256": hashlib.sha256(content).hexdigest(),
                      "sha3_256": hashlib.sha3_256(content).hexdigest(), "size_bytes": len(content)})
    email_source = SOURCES["emails/Urăsc canicula, e nașpa.eml"].read_bytes()
    with zipfile.ZipFile(generated_root / "documents/easychair.docx") as archive:
        document_xml = ElementTree.fromstring(archive.read("word/document.xml"))
    office_text = "\n".join("".join(paragraph.itertext()) for paragraph in document_xml.iter(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"))
    office_text = re.sub(r"\s+", " ", office_text)
    return {
        "fixture_repository_revision": run(["git", "-C", str(SOURCE_ROOT.parent), "rev-parse", "HEAD"]).strip(),
        "copied_sources": files,
        "romanian_email": email_expectations(email_source),
        "easychair_entities": [{"value": value, "count": len(re.findall(re.escape(value), office_text, re.IGNORECASE)),
                                 "basis": "Occurrences in the original DOCX document XML."}
                                for value in ("University of Manchester", "Microsoft Word")],
    }


def profile(generated_root: Path) -> dict[str, object]:
    datasets = ("testdata_manualqa", "testdata_excelsc", "testdata_wide", "testdata_leaf", "testdata_shapes", "testdata_manualpdf", "testdata_diskfiles")
    result: dict[str, object] = {"schema_version": 2, "datasets": {dataset: source_rows(dataset) for dataset in datasets},
        "pdf_rows": {}, "text_page_counts": {}, "table_documents": {}, "table_cells": {}, "image_ocr_rows": {},
        "source_expectations": source_expectations(generated_root),
        "pdf_byte_page_counts": {"stanley.ec02.pdf": pdf_byte_page_count(generated_root / "documents/stanley.ec02.pdf"),
            "born-digital-no-ocr.pdf": pdf_byte_page_count(ORIGINAL_PDF_ROOT / "original-only.pdf")}}
    original_pdf = (ORIGINAL_PDF_ROOT / "original-only.pdf").read_bytes()
    result["source_expectations"]["generated_sources"] = [{
        "dataset": "testdata_manualpdf", "path": "/original-only.pdf",
        "sha3_256": hashlib.sha3_256(original_pdf).hexdigest(),
        "sha256": hashlib.sha256(original_pdf).hexdigest(), "size_bytes": len(original_pdf),
        "recipe": "The tiny PDF fixture followed by the original-only QA version-one comment.",
    }]
    for dataset in datasets:
        result["pdf_rows"][dataset] = clickhouse(
            "SELECT 'original' AS source_kind, pdf_hash, '' AS engine, '' AS languages, toString(page_count) AS page_count, '' AS blob_hash FROM Hoover4_Collection_testdata.pdfs FINAL "
            f"WHERE collection_dataset='{dataset}' UNION ALL SELECT 'ocr' AS source_kind, pdf_hash, engine, languages, toString(page_count) AS page_count, blob_hash FROM Hoover4_Collection_testdata.pdf_ocr_results FINAL WHERE collection_dataset='{dataset}' AND is_deleted=0 ORDER BY source_kind, pdf_hash, engine, languages")
        result["text_page_counts"][dataset] = clickhouse(
            "SELECT file_hash, extracted_by, toString(count()) AS text_page_count FROM Hoover4_Collection_testdata.text_content FINAL "
            f"WHERE collection_dataset='{dataset}' GROUP BY file_hash, extracted_by ORDER BY file_hash, extracted_by")
        result["table_documents"][dataset] = clickhouse(
            "SELECT hash, status, reader, table_format, toString(sheet_count) AS sheet_count, toString(row_count) AS row_count, toString(column_count) AS column_count, toString(cell_count) AS cell_count, toString(truncated) AS truncated FROM Hoover4_Collection_testdata.table_documents FINAL "
            f"WHERE collection_dataset='{dataset}' ORDER BY hash")
        result["image_ocr_rows"][dataset] = clickhouse(
            "SELECT image_hash, engine, languages, result_hash FROM Hoover4_Collection_testdata.raw_ocr_results FINAL "
            f"WHERE collection_dataset='{dataset}' ORDER BY image_hash, engine, languages")
    result["metadata_oracle"] = metadata_oracle()
    table = document(result, "testdata_manualqa", "/substitutes/manual-qa-table.csv")
    result["table_cells"]["manual-qa-table.csv"] = [] if table is None else clickhouse(
        "SELECT toString(sheet_id) AS sheet_id, toString(row_id) AS row_id, toString(column_id) AS column_id, cell_text FROM Hoover4_Collection_testdata.table_cells FINAL "
        f"WHERE file_hash='{table['hash']}' ORDER BY sheet_id, row_id, column_id")
    return result


def metadata_oracle() -> dict[str, object]:
    """Read source tables independently of browser search and facet endpoints."""
    scope = "collection_dataset='testdata_manualqa'"
    queries = {
        "files": f"SELECT hash, container_hash, path, file_size_bytes FROM vfs_files FINAL WHERE {scope} ORDER BY hash, path",
        "types": f"SELECT hash, file_type FROM file_type_canonical FINAL WHERE {scope} ORDER BY hash",
        "dates": f"SELECT hash, date, source FROM document_dates FINAL WHERE {scope} ORDER BY hash, date",
        "addresses": f"SELECT email_hash, toString(role) AS role, address FROM email_addresses FINAL WHERE {scope} ORDER BY email_hash, role, address",
        "emails": f"SELECT email_hash FROM emails FINAL WHERE {scope} ORDER BY email_hash",
        "entities": f"SELECT file_hash, entity_type, entity_values FROM entity_hit FINAL WHERE {scope} ORDER BY file_hash, entity_type",
    }
    from database.manticore import get_manticore_client, shard_table_name
    relevance = []
    relevance_queries = []
    with get_manticore_client() as client:
        cursor = client.cursor(dictionary=True)
        for shard in clickhouse("SELECT shard_index FROM manticore_shards FINAL ORDER BY shard_index"):
            table = shard_table_name("testdata", int(shard["shard_index"]))
            sql = (f"SELECT file_hash, WEIGHT() AS score FROM {table} WHERE MATCH('child') "
                   "AND collection_dataset='testdata_manualqa' GROUP BY file_hash "
                   "ORDER BY score DESC, file_hash ASC LIMIT 100")
            relevance_queries.append(sql)
            cursor.execute(sql)
            relevance.extend(cursor.fetchall())
        cursor.close()
    relevance.sort(key=lambda row: (-row["score"], row["file_hash"]))
    return {"scope": "testdata_manualqa", "basis": "ClickHouse source metadata, read before browser execution.",
            "queries": queries, "raw_relevance": relevance, "raw_relevance_queries": relevance_queries,
            **{key: clickhouse(sql) for key, sql in queries.items()}}


def fixture_outcomes(contract: dict[str, object], resolved: dict[str, object]) -> list[dict[str, str]]:
    outcomes = []
    for fixture in contract["fixtures"]:
        row = document(resolved, fixture["dataset"], fixture["path"])
        status, reason = ("verified", "indexed source row") if row else ("unmet", "no indexed source row")
        expected = fixture.get("expected", {})
        provenance = resolved.get("source_expectations", {})
        originals = provenance.get("copied_sources", []) + provenance.get("generated_sources", [])
        original = next((item for item in originals
                         if item["dataset"] == fixture["dataset"] and item["path"] == fixture["path"]), None)
        if row and original and row["hash"] != original["sha3_256"]:
            status, reason = "unmet", "indexed identity differs from fixture source bytes"
        if fixture["name"] == "romanian_email":
            email = resolved.get("source_expectations", {}).get("romanian_email")
            if email is None or len(email["attachments"]) != expected["attachment_count"]:
                status, reason = "unmet", "email attachment source expectations are unavailable or differ"
        if fixture["name"] == "screenshot_table_corpus":
            status = "verified" if resolved.get("table_documents", {}).get(fixture["dataset"]) else "unmet"
            reason = "indexed table documents" if status == "verified" else "no indexed table documents"
        if fixture["name"] == "deep_tree":
            status = "verified" if resolved.get("datasets", {}).get(fixture["dataset"]) else "unmet"
            reason = "indexed deep-tree source rows" if status == "verified" else "no indexed deep-tree source rows"
        if fixture["name"] == "diskfiles_dataset":
            status = "verified" if resolved.get("datasets", {}).get(fixture["dataset"]) else "unmet"
            reason = "indexed diskfiles source rows" if status == "verified" else "no indexed diskfiles source rows"
        if row and expected.get("required_extractors"):
            missing = set(expected["required_extractors"]) - set(row["extracted_by"])
            if missing: status, reason = "unmet", "missing extractors: " + ", ".join(sorted(missing))
        if row and expected.get("required_pdf_sources"):
            sources = {item["source_kind"] for item in resolved["pdf_rows"][fixture["dataset"]] if item["pdf_hash"] == row["hash"]}
            if not set(expected["required_pdf_sources"]) <= sources: status, reason = "unmet", "missing required PDF source"
            if set(expected.get("forbidden_pdf_sources", [])) & sources: status, reason = "unmet", "forbidden PDF source exists"
        if fixture["name"] == "manual_table_substitute" and row:
            table = [item for item in resolved["table_documents"][fixture["dataset"]] if item["hash"] == row["hash"] and item["status"] == "ok"]
            cells = [item["cell_text"] for item in resolved["table_cells"]["manual-qa-table.csv"]]
            if not table or cells != expected["cell_values"]: status, reason = "unmet", "table parse or values do not match"
        if fixture["name"] == "image_ocr" and row:
            engines = {item["engine"] for item in resolved["image_ocr_rows"][fixture["dataset"]] if item["image_hash"] == row["hash"]}
            if not {"easyocr", "tesseract"} <= engines: status, reason = "unmet", "missing image OCR engine source"
        outcomes.append({"fixture": fixture["name"], "status": status, "reason": reason})
    return outcomes


def ingest_commands() -> list[list[str]]:
    """Local dataset ingest commands. Discovery never calls these."""
    return [
        ["uv", "run", "python", "main.py", "add-disk-dataset", "testdata", dataset, str(root)]
        for dataset, root in LOCAL_INGEST
    ]


def ingest_local_datasets() -> None:
    if not EXCELS_ROOT.is_dir():
        raise FileNotFoundError(EXCELS_ROOT)
    if not DISKFILES_ROOT.is_dir():
        raise FileNotFoundError(DISKFILES_ROOT)
    for command in ingest_commands():
        run(command)


def discover_operation_states() -> dict[str, object]:
    """Read existing operation rows. This path does not dispatch work."""
    try:
        rows = global_clickhouse(
            "SELECT op_id, kind, collection_dataset, state FROM operations FINAL "
            "WHERE state = 'errored' ORDER BY started_at DESC"
        )
    except Exception as error:  # noqa: BLE001
        return {"available": False, "reason": str(error), "errored_destructive": [],
                "qa_errored_confirm": "absent"}
    destructive = {"purge_dataset", "delete_dataset", "drop_collection_database", "import_collection"}
    errored_destructive = [row for row in rows if row["kind"] in destructive]
    qa = next((row for row in errored_destructive if row["collection_dataset"] == QA_ERRORED_DATASET), None)
    return {
        "available": True,
        "errored_destructive": errored_destructive,
        "qa_errored_confirm": "present" if qa else "absent",
    }


def ensure_errored_operation_fixture() -> dict[str, object]:
    """Create one isolated errored destructive row for local confirmation captures."""
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")
    from database.operations import create_operation, finish_operation, list_operations
    existing = [
        row for row in list_operations(state="errored", kind="delete_dataset", limit=50)
        if row.get("collection_dataset") == QA_ERRORED_DATASET
    ]
    if existing:
        return {"status": "present", "op_id": existing[0]["op_id"]}
    row = create_operation(
        "delete_dataset", "testdata", QA_ERRORED_DATASET,
        detail={"qa_fixture": True, "purpose": "isolated confirmation input"},
        user_id="qa-fixture",
    )
    finish_operation(row["op_id"], "errored", error="isolated QA confirmation fixture")
    return {"status": "created", "op_id": row["op_id"]}


def original_case_status(*, discovered: bool = False) -> list[dict[str, str]]:
    """Record original Enron, Messinai, and Barak coverage as unmet."""
    names = ("original_enron_document", "Messinai-szoros.txt", "original_barak_document")
    if discovered:
        reason = (
            "Independent expected values are not established. "
            "Use the per-target original-case inventory."
        )
        return [{"name": name, "status": "unmet", "reason": reason} for name in names]
    return [
        {"name": "original_enron_document", "status": "unmet",
         "reason": "Local testdata including enron-kaminski-v has no jeff.hoover@enron.com source."},
        {"name": "Messinai-szoros.txt", "status": "unmet",
         "reason": "Local testdata has no Messinai table file by name or content."},
        {"name": "original_barak_document", "status": "unmet",
         "reason": "Local testdata has no Barak PDF. stanley.ec02.pdf is the independent substitute."},
    ]


def discover_profile(contract: dict[str, object]) -> dict[str, object]:
    """Resolve current identities from indexed data without ingest or recovery."""
    result: dict[str, object] = {
        "schema_version": 2, "mode": "discover",
        "datasets": {}, "pdf_rows": {}, "table_documents": {}, "table_cells": {},
        "image_ocr_rows": {}, "source_expectations": {},
    }
    for dataset in DISCOVER_DATASETS:
        try:
            result["datasets"][dataset] = source_rows(dataset)
        except Exception as error:  # noqa: BLE001
            result["datasets"][dataset] = []
            result.setdefault("dataset_errors", {})[dataset] = str(error)
        try:
            result["pdf_rows"][dataset] = clickhouse(
                "SELECT 'original' AS source_kind, pdf_hash, '' AS engine, '' AS languages, "
                "toString(page_count) AS page_count, '' AS blob_hash FROM Hoover4_Collection_testdata.pdfs FINAL "
                f"WHERE collection_dataset='{dataset}' UNION ALL SELECT 'ocr' AS source_kind, pdf_hash, engine, "
                "languages, toString(page_count) AS page_count, blob_hash FROM Hoover4_Collection_testdata.pdf_ocr_results FINAL "
                f"WHERE collection_dataset='{dataset}' AND is_deleted=0 ORDER BY source_kind, pdf_hash, engine, languages")
        except Exception:  # noqa: BLE001
            result["pdf_rows"][dataset] = []
        try:
            result["table_documents"][dataset] = clickhouse(
                "SELECT hash, status, reader, table_format, toString(sheet_count) AS sheet_count, "
                "toString(row_count) AS row_count, toString(column_count) AS column_count, "
                "toString(cell_count) AS cell_count, toString(truncated) AS truncated "
                "FROM Hoover4_Collection_testdata.table_documents FINAL "
                f"WHERE collection_dataset='{dataset}' ORDER BY hash")
        except Exception:  # noqa: BLE001
            result["table_documents"][dataset] = []
        try:
            result["image_ocr_rows"][dataset] = clickhouse(
                "SELECT image_hash, engine, languages, result_hash FROM Hoover4_Collection_testdata.raw_ocr_results FINAL "
                f"WHERE collection_dataset='{dataset}' ORDER BY image_hash, engine, languages")
        except Exception:  # noqa: BLE001
            result["image_ocr_rows"][dataset] = []
    result["outcomes"] = fixture_outcomes(contract, result)
    result["operation_states"] = discover_operation_states()
    result["original_cases"] = original_case_status(discovered=True)
    return result


def write_discovered_profile(contract: dict[str, object]) -> bool:
    resolved = discover_profile(contract)
    resolved["contract_schema_version"] = contract["schema_version"]
    pending_path = PROFILE_PATH.with_suffix(".pending.json")
    pending_path.write_text(json.dumps(resolved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pending_path.replace(PROFILE_PATH)
    print(f"Wrote {PROFILE_PATH}")
    return all(item["status"] == "verified" for item in resolved["outcomes"])


def write_profile(contract: dict[str, object], generated_root: Path) -> bool:
    resolved = profile(generated_root)
    resolved["contract_schema_version"] = contract["schema_version"]
    resolved["outcomes"] = fixture_outcomes(contract, resolved)
    resolved["operation_states"] = discover_operation_states()
    resolved["original_cases"] = original_case_status()
    pending_path = PROFILE_PATH.with_suffix(".pending.json")
    pending_path.write_text(json.dumps(resolved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pending_path.replace(PROFILE_PATH)
    print(f"Wrote {PROFILE_PATH}")
    return all(item["status"] == "verified" for item in resolved["outcomes"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated-root", type=Path, default=GENERATED_ROOT)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--profile-only", action="store_true")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--observe-incomplete", action="store_true")
    args = parser.parse_args()
    if not Path("/app/main.py").is_file():
        raise RuntimeError("Run this script in hoover4-worker through prepare_manual_qa.sh")
    if sum(bool(flag) for flag in (args.prepare_only, args.profile_only, args.discover_only)) > 1:
        parser.error("--prepare-only, --profile-only, and --discover-only cannot be used together")
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if args.discover_only:
        complete = write_discovered_profile(contract)
        return 0 if complete or args.observe_incomplete else 1
    if args.profile_only:
        complete = write_profile(contract, args.generated_root)
        return 0 if complete or args.observe_incomplete else 1
    write_generated_sources(args.generated_root, LEAF_ROOT, WIDE_ROOT)
    if args.prepare_only:
        print("Prepared source files only.")
        return 0
    ingest_local_datasets()
    ensure_errored_operation_fixture()
    complete = write_profile(contract, args.generated_root)
    return 0 if complete or args.observe_incomplete else 1


if __name__ == "__main__":
    raise SystemExit(main())
