"""Execute pinned page plans and publish complete OCR replacements."""

import base64
import dataclasses
import json
import time

from temporalio import activity

from tasks.automatic_ocr import capabilities, digest, make_plan
from tasks.heartbeat import HeartbeatClock, with_heartbeat
from tasks.P3_parse_files.batch_runner import BatchResult, StageBatchParams, run_batch

# The `ocr_skips` reason of an image that the OCR service refuses (422). The normal OCR stage uses it too.
OCR_INPUT_UNDECODABLE = "ocr_skipped_undecodable"


def write_plan(client, plan, state, reason="", presence=0):
    from database.clickhouse import insert_durable
    maximum = client.query("SELECT max(revision) FROM automatic_ocr_plans WHERE collection_dataset = {cd:String} AND hash = {h:String}",
        parameters={"cd": plan["dataset"], "h": plan["file_hash"]}).result_rows[0][0]
    revision = 0 if state == "candidate" else max(time.time_ns() // 1000, int(maximum) + 1)
    insert_durable(client, "automatic_ocr_plans", [[plan["dataset"], plan["file_hash"], plan["plan_digest"],
        plan["source_revision"], plan["capability_digest"], plan["policy_version"], plan["expected_pages"],
        json.dumps(plan, sort_keys=True), state, reason, presence, revision]],
        column_names=["collection_dataset", "hash", "plan_digest", "source_revision", "capability_digest",
                      "policy_version", "expected_pages", "plan_json", "state", "reason", "has_ocr_output", "revision"])


def read_outputs(client, plan):
    return {identity: json.loads(payload) for identity, payload in client.query(
        "SELECT output_id, payload FROM automatic_ocr_output FINAL WHERE collection_dataset = {cd:String} "
        "AND hash = {h:String} AND plan_digest = {p:String} AND output_id != 'publication-metadata'",
        parameters={"cd": plan["dataset"], "h": plan["file_hash"], "p": plan["plan_digest"]}).result_rows}


def save_output(client, plan, identity, value):
    from database.clickhouse import insert_durable
    insert_durable(client, "automatic_ocr_output", [[plan["dataset"], plan["file_hash"], plan["plan_digest"],
        identity, json.dumps(value, sort_keys=True), time.time_ns() // 1000]],
        column_names=["collection_dataset", "hash", "plan_digest", "output_id", "payload", "revision"])


def detection_rows(client, cd, h, kind):
    from tasks.P3_parse_files.ocr_detection import OCR_DETECTION_VERSION
    return [dict(zip(("page_id", "has_text", "script", "language", "detector_version", "model"), row))
            for row in client.query(
                "SELECT page_id, has_text, script, language, detector_version, model FROM ocr_detection FINAL "
                "WHERE collection_dataset = {cd:String} AND hash = {h:String} AND source_kind = {k:String} "
                "AND detector_version = {v:UInt16} ORDER BY page_id",
                parameters={"cd": cd, "h": h, "k": kind, "v": OCR_DETECTION_VERSION}).result_rows]


def expected_outputs(plan, parts):
    """Return deterministic bounded request identities and selected page sets."""
    pairs = sorted({(item["engine"], item["languages"]) for page in plan["pages"] for item in page["passes"]})
    jobs = []
    for engine, languages in pairs:
        selected = {page["page_id"] for page in plan["pages"]
                    if any(item["engine"] == engine and item["languages"] == languages for item in page["passes"])}
        for part in parts:
            pages = sorted(page for page in selected if part["first_page"] <= page <= part["last_page"])
            identity = digest([engine, languages, part["part_index"], pages])
            jobs.append((identity, engine, languages, part, pages))
    return jobs


def expected_identities(plan, parts):
    """The identities of every staged output that a complete publication of the plan needs."""
    from tasks.P3_parse_files.ocr_reconciliation import adoption_jobs
    recognition = expected_outputs(plan, parts)
    return {job[0] for job in recognition} | {job["identity"] for job in adoption_jobs(plan, parts, recognition)}


def plan_sources(plan):
    """The OCR text sources that the plan publishes: new recognition passes and adopted results."""
    from tasks.text_sources import ocr_extracted_by, pdf_ocr_extracted_by
    extractor = ocr_extracted_by if plan["source_kind"] == "image" else pdf_ocr_extracted_by
    return ({extractor(item["engine"], item["languages"]) for page in plan["pages"] for item in page["passes"]}
            | {extractor(item["engine"], item["languages"]) for page in plan["pages"] for item in page.get("adopted", [])})


def pinned_plan(client, dataset, h, op_id):
    """Read the operation's serialized first executable plan claim."""
    receipts = client.query("SELECT output_identity, receipt_version FROM processing_output_receipts FINAL "
        "WHERE collection_dataset = {cd:String} AND file_hash = {h:String} AND fingerprint = {op:String} "
        "AND output_kind = 'automatic_ocr' AND stage = 'planned' LIMIT 1",
        parameters={"cd": dataset, "h": h, "op": op_id}).result_rows
    if not receipts:
        return None
    identity, epoch = receipts[0]
    rows = client.query("SELECT plan_json FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
        "AND hash = {h:String} AND plan_digest = {p:String}",
        parameters={"cd": dataset, "h": h, "p": identity}).result_rows
    if not rows:
        raise RuntimeError("The claimed automatic OCR plan is absent")
    plan = json.loads(rows[0][0])
    plan.update(claim_version=int(epoch), owner_op=op_id)
    return plan


def claim_automatic_plan(client, command):
    """Claim one executable candidate under the single-consumer metadata coordinator."""
    from database.clickhouse import insert_durable
    from temporalio.exceptions import ApplicationError
    values = json.loads(command.manifest)
    current = pinned_plan(client, values["dataset"], command.file_hash, command.owner_op)
    if current is None:
        found = client.query("SELECT plan_json FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
            "AND hash = {h:String} AND plan_digest = {p:String}",
            parameters={"cd": values["dataset"], "h": command.file_hash, "p": values["plan_digest"]}).result_rows
        if not found:
            raise RuntimeError("Automatic OCR candidate is absent")
        candidate = json.loads(found[0][0])
        if any(page["status"] not in ("ready", "no_text") for page in candidate["pages"]):
            raise ApplicationError("Automatic OCR candidate is not executable", non_retryable=True)
        epoch = int(client.query("SELECT max(receipt_version) FROM processing_output_receipts "
            "WHERE collection_dataset = {cd:String} AND file_hash = {h:String} AND output_kind = 'automatic_ocr' "
            "AND stage = 'planned'", parameters={"cd": values["dataset"], "h": command.file_hash}).result_rows[0][0]) + 1
        insert_durable(client, "processing_output_receipts", [[values["dataset"], command.file_hash,
            "automatic_ocr", values["plan_digest"], command.owner_op, "planned", command.owner_op, epoch]],
            column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id", "receipt_version"])
    plan = pinned_plan(client, values["dataset"], command.file_hash, command.owner_op)
    if require_current_claim(client, plan) <= plan["claim_version"]:
        states = client.query("SELECT state FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
            "AND hash = {h:String} AND plan_digest = {p:String}",
            parameters={"cd": values["dataset"], "h": command.file_hash, "p": plan["plan_digest"]}).result_rows
        if states[0][0] not in ("published", "applied"):
            write_plan(client, plan, "planned")
    return 1


def require_current_claim(client, plan):
    """Return the highest durable published epoch and reject older different plans."""
    rows = client.query("SELECT output_identity, receipt_version FROM processing_output_receipts FINAL "
        "WHERE collection_dataset = {cd:String} AND file_hash = {h:String} "
        "AND output_kind = 'automatic_ocr' AND stage = 'published' ORDER BY receipt_version DESC LIMIT 1",
        parameters={"cd": plan["dataset"], "h": plan["file_hash"]}).result_rows
    if not rows:
        return 0
    identity, epoch = rows[0]
    if int(epoch) > plan["claim_version"] and identity != plan["plan_digest"]:
        from temporalio.exceptions import ApplicationError
        raise ApplicationError("A later automatic OCR plan is already published", type="OcrPlanSuperseded", non_retryable=True)
    return int(epoch)


def record_published_claim(client, plan):
    """Keep immutable published epochs independent of replaceable plan metadata."""
    from database.clickhouse import insert_durable
    insert_durable(client, "processing_output_receipts", [[plan["dataset"], plan["file_hash"], "automatic_ocr",
        plan["plan_digest"], plan["owner_op"], "published", plan["owner_op"], plan["claim_version"]]],
        column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id", "receipt_version"])


def _execute_file(params, file):
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files import ocr_detection
    from tasks.P3_parse_files.pdf_parts import source_parts, source_digest, live_hashes
    from tasks.P3_parse_files.table_generations import GenerationCommand, send_command
    from tasks.text_sources import PDF_SEGMENTATION_VERSION
    cd, h = params.collection_dataset, file.item_hash
    kind = "image" if "image" in file.routes else file.source_kind
    with get_collection_client(params.collectionname) as client:
        if h not in live_hashes(client, cd, [h]):
            raise RuntimeError("Automatic OCR source is no longer live")
        plan = pinned_plan(client, cd, h, params.op_id)
        was_pinned = plan is not None
        if plan is None:
            ocr_detection._detect_file(params, file)
            rows = detection_rows(client, cd, h, kind)
        if kind == "image":
            expected = [1]
            parts = [dict(part_index=1, first_page=1, last_page=1, s3_path="", size_bytes=file.file_size_bytes)]
            revision = h
        else:
            expected = ocr_detection.stored_pdf_pages(client, cd, h, kind)
            parts = source_parts(client, cd, h, kind)
            if not parts:
                raise RuntimeError("Automatic OCR requires prepared PDF source parts")
            revision = source_digest(parts, parts[-1]["last_page"], expected)
        if plan is None:
            if [row["page_id"] for row in rows] != sorted(expected):
                raise RuntimeError("Automatic OCR detection does not cover every eligible page")
            plan = make_plan(cd, h, revision, kind, rows, capabilities(), PDF_SEGMENTATION_VERSION)
            from tasks.P3_parse_files.ocr_reconciliation import bounded_ranges, reconcile_plan
            # Earlier output is classified before any recognition request, so a capability
            # failure blocks only the pages without an accepted earlier result.
            plan = reconcile_plan(client, params, file, kind, plan, [(1, 1)] if kind == "image" else bounded_ranges(parts))
            blocked = [page for page in plan["pages"] if page["status"] in ("incomplete", "unsupported", "failed")]
            if blocked:
                write_plan(client, plan, blocked[0]["status"], blocked[0]["reason"])
                if blocked[0]["status"] == "failed":
                    raise RuntimeError("Automatic OCR capability discovery is temporarily unavailable")
                from temporalio.exceptions import ApplicationError
                raise ApplicationError("Automatic OCR has incomplete script coverage", type="OcrCoverageUnavailable", non_retryable=True)
            if kind != "image":
                parts = bounded_source_parts(client, params, file, parts, revision)
            plan["source_parts"] = parts
            stored = client.query("SELECT count() FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
                "AND hash = {h:String} AND plan_digest = {p:String}", parameters={"cd": cd, "h": h, "p": plan["plan_digest"]}).result_rows
            if not stored[0][0]:
                write_plan(client, plan, "candidate")
            send_command(GenerationCommand(params.collectionname, h, "claim_ocr_plan", owner_op=params.op_id,
                manifest=json.dumps(dict(dataset=cd, plan_digest=plan["plan_digest"])).encode()))
            plan = pinned_plan(client, cd, h, params.op_id)
            if plan is None:
                raise RuntimeError("Automatic OCR executable plan claim is absent")
        if plan["source_revision"] != revision or plan["source_kind"] != kind:
            raise RuntimeError("Automatic OCR source changed after its plan was claimed")
        parts = plan["source_parts"]
        if was_pinned:
            send_command(GenerationCommand(params.collectionname, h, "claim_ocr_plan", owner_op=params.op_id,
                manifest=json.dumps(dict(dataset=cd, plan_digest=plan["plan_digest"])).encode()))
        if require_current_claim(client, plan) > plan["claim_version"]:
            return plan["plan_digest"]
        outputs = read_outputs(client, plan)
        jobs = expected_outputs(plan, parts)
        from tasks.P3_parse_files.ocr_reconciliation import adoption_jobs
        adoptions = adoption_jobs(plan, parts, jobs)
        clock = HeartbeatClock()
        for identity, engine, languages, part, pages in jobs:
            clock.beat(f"Automatic OCR {h[:8]} {part['part_index']}")
            if identity in outputs:
                continue
            if kind == "image":
                output = image_output(params, file, engine, languages, plan)
            elif pages:
                output = pdf_output(params, file, engine, languages, part, pages, plan)
            else:
                output = dict(engine=engine, languages=languages, part=part, pages=[], borrowed=False,
                              blob_key=part["s3_path"].split("/", 3)[-1], size_bytes=part["size_bytes"])
            save_output(client, plan, identity, output)
            outputs[identity] = output
        pending = [job for job in adoptions if job["identity"] not in outputs]
        if pending:
            stage_adoptions(client, params, file, plan, pending, outputs, clock)
        if set(outputs) != {job[0] for job in jobs} | {job["identity"] for job in adoptions}:
            raise RuntimeError("Automatic OCR staged output does not cover the pinned plan")
        publish(client, params, file, plan, outputs)
    return plan["plan_digest"]


def stage_adoptions(client, params, file, plan, pending, outputs, clock):
    """Stage adopted earlier results after recognition output. No OCR request runs."""
    import tempfile
    from tasks.P3_parse_files.ocr_reconciliation import adoption_output, load_payloads
    with tempfile.TemporaryDirectory(prefix="hoover4-ocr-adoption-") as folder:
        payloads, candidates = load_payloads(client, params, file, plan, folder)
        for job in pending:
            clock.beat(f"Automatic OCR adoption {file.item_hash[:8]} {job['part']['part_index']}")
            output = adoption_output(client, params, file, plan, job, payloads, candidates, outputs, folder)
            save_output(client, plan, job["identity"], output)
            outputs[job["identity"]] = output


def execute_file(params, file):
    """Retain failure provenance while transport failures remain retryable."""
    try:
        identity = _execute_file(params, file)
        from database.clickhouse import get_collection_client, insert_durable
        with get_collection_client(params.collectionname) as client:
            insert_durable(client, "processing_output_receipts", [[params.collection_dataset, file.item_hash,
                "automatic_ocr", identity, params.op_id, "prepared", params.op_id]],
                column_names=["collection_dataset", "file_hash", "output_kind", "output_identity", "fingerprint", "stage", "op_id"])
        return identity
    except Exception as exc:
        from tasks.P3_parse_files.table_generations import GenerationCommand, send_command
        try:
            send_command(GenerationCommand(params.collectionname, file.item_hash, "fail_ocr_plan", owner_op=params.op_id,
                manifest=json.dumps(dict(dataset=params.collection_dataset, error_type=getattr(exc, "type", None) or type(exc).__name__)).encode()))
        except Exception:
            import logging
            logging.getLogger(__name__).warning("Automatic OCR failure state could not be stored", exc_info=True)
        raise


def bounded_source_parts(client, params, file, stored, revision):
    """Create automatic artifact ranges with at most 32 source pages each."""
    import os
    import tempfile
    from database.s3 import collection_bucket, get_s3_client
    from tasks.automatic_ocr import PAGE_BATCH
    from tasks.P3_parse_files.pdf_parts import source_file, split_pdf
    if all(part["last_page"] - part["first_page"] + 1 <= PAGE_BATCH for part in stored):
        return stored
    bucket = collection_bucket(params.collectionname)
    result = []
    with source_file(client, params, file) as source, tempfile.TemporaryDirectory(prefix="hoover4-automatic-parts-") as folder:
        for index, first in enumerate(range(1, stored[-1]["last_page"] + 1, PAGE_BATCH), 1):
            last = min(stored[-1]["last_page"], first + PAGE_BATCH - 1)
            path = os.path.join(folder, f"{index}.pdf")
            split_pdf(source, path, first, last)
            key = f"derived/automatic-ocr-source/{params.collection_dataset}/{file.item_hash}/{revision}/{first}-{last}.pdf"
            get_s3_client().fput_object(bucket, key, path, content_type="application/pdf")
            result.append(dict(part_index=index, first_page=first, last_page=last,
                               s3_path=f"s3://{bucket}/{key}", size_bytes=os.path.getsize(path)))
    return result


def image_output(params, file, engine, languages, plan):
    from database.clickhouse import get_collection_client
    from tasks.ocr_client import run_ocr
    from tasks.ocr_pdf_client import service_configured, build_ocr_pdf
    from tasks.P3_parse_files.ocr_detection import read_image
    with get_collection_client(params.collectionname) as client:
        image = read_image(client, params.collection_dataset, file.item_hash, file.file_path)
    try:
        outcome = run_ocr(engine, languages, image)
    except Exception as exc:
        import requests
        if isinstance(exc, requests.HTTPError) and getattr(exc.response, "status_code", None) == 422:
            # The OCR service read the bytes and found no image it can process. A retry gets
            # the same 422. Like the normal OCR stage, store a skip and publish an empty page.
            from tasks.ocr_targets import STAGE_IMAGE, record_ocr_skips
            with get_collection_client(params.collectionname) as client:
                record_ocr_skips(client, params.collection_dataset, file.item_hash, STAGE_IMAGE,
                                 engine, [languages], OCR_INPUT_UNDECODABLE, getattr(params, "op_id", ""))
            return dict(engine=engine, languages=languages, pages=[(1, "")], raw_json="",
                        skipped=OCR_INPUT_UNDECODABLE)
        raise
    if outcome.engine != engine or outcome.languages != languages:
        raise RuntimeError("OCR service changed the pinned pass identity")
    result = dict(engine=engine, languages=languages, pages=[(1, outcome.text)], raw_json=outcome.raw_json)
    from tasks.P3_parse_files.image_pdf import qualifying_words
    raw = json.loads(outcome.raw_json)
    if service_configured() and qualifying_words(outcome.text) >= 5:
        if not isinstance(raw.get("words"), list):
            raise RuntimeError("Image PDF requires stored OCR word boxes")
        pdf = build_ocr_pdf(collectionname=params.collectionname, collection_dataset=params.collection_dataset,
            pdf_hash=file.item_hash, engine=engine, languages=languages, mode="image", words=raw["words"],
            source_b64=base64.b64encode(image).decode(),
            dest_key=f"derived/automatic-ocr/{params.collection_dataset}/{file.item_hash}/{plan['plan_digest']}/{engine}+{languages}.pdf")
        result.update(blob_key=pdf.dest_key, size_bytes=pdf.size_bytes, blob_hash=pdf.blob_hash)
    return result


def pdf_output(params, file, engine, languages, part, pages, plan):
    from tasks.ocr_pdf_client import build_ocr_pdf, service_configured
    from tasks.P3_parse_files.pdf_parts import stored_path
    from tasks.P3_parse_files.parse_ocr_pdf import MAX_INLINE_PDF_BYTES
    if not service_configured():
        raise RuntimeError("Automatic PDF OCR requires the searchable PDF service")
    bucket, key = stored_path(part["s3_path"])
    inline = ""
    if not key:
        with open(file.file_path, "rb") as handle:
            data = handle.read(MAX_INLINE_PDF_BYTES + 1)
        if len(data) > MAX_INLINE_PDF_BYTES:
            raise RuntimeError("PDF inline source exceeds its input limit")
        inline = base64.b64encode(data).decode()
    selected = [page - part["first_page"] + 1 for page in pages]
    outcome = build_ocr_pdf(collectionname=params.collectionname, collection_dataset=params.collection_dataset,
        pdf_hash=file.item_hash, engine=engine, languages=languages, source_key=key, source_bucket=bucket,
        source_b64=inline, ocr_pages=selected,
        dest_key=f"derived/automatic-ocr/{params.collection_dataset}/{file.item_hash}/{plan['plan_digest']}/{engine}+{languages}/{part['part_index']}.pdf")
    if outcome.engine != engine or outcome.languages != languages or [int(page["page"]) for page in outcome.pages] != selected:
        raise RuntimeError("PDF OCR returned incomplete pinned page identities")
    return dict(engine=engine, languages=languages, part=part, borrowed=False, blob_key=outcome.dest_key,
                size_bytes=outcome.size_bytes, pages=[(part["first_page"] + int(page["page"]) - 1, page["text"]) for page in outcome.pages])


def publication_sources(plan, outputs):
    from tasks.text_sources import ocr_extracted_by, pdf_ocr_extracted_by
    extractor = ocr_extracted_by if plan["source_kind"] == "image" else pdf_ocr_extracted_by
    sources = {}
    for output in outputs.values():
        sources.setdefault(extractor(output["engine"], output["languages"]), []).extend(output["pages"])
    return {source: sorted((int(page), text) for page, text in pages) for source, pages in sources.items()}


def publish(client, params, file, plan, outputs):
    """Verify artifacts and stage language results before the serialized storage command."""
    from tasks.document_language import source_language
    from tasks.P3_parse_files.table_generations import GenerationCommand, send_command
    verify_artifacts(params.collectionname, outputs.values())
    languages = {source: source_language(pages) for source, pages in publication_sources(plan, outputs).items()}
    output_digest = digest(dict(outputs=outputs, languages=languages))
    save_output(client, plan, "publication-metadata", dict(languages=languages, output_digest=output_digest))
    send_command(GenerationCommand(params.collectionname, file.item_hash, "publish_ocr_plan", owner_op=params.op_id,
        manifest=json.dumps(dict(dataset=params.collection_dataset, plan_digest=plan["plan_digest"], output_digest=output_digest)).encode()))


def apply_automatic_state_command(client, command):
    """Fence publication, failure, and settlement mutations through the metadata coordinator."""
    from tasks.P3_parse_files.batch_runner import BatchFile, StageBatchParams
    values = json.loads(command.manifest)
    plan = pinned_plan(client, values["dataset"], command.file_hash, command.owner_op)
    if plan is None:
        if command.action == "fail_ocr_plan":
            return 0
        raise RuntimeError("The automatic OCR command has no executable plan claim")
    try:
        epoch = require_current_claim(client, plan)
    except Exception as exc:
        from temporalio.exceptions import ApplicationError
        if command.action == "fail_ocr_plan" and isinstance(exc, ApplicationError) and exc.type == "OcrPlanSuperseded":
            return 0
        raise
    if epoch > plan["claim_version"]:
        return 1
    parameters = {"cd": values["dataset"], "h": command.file_hash, "p": plan["plan_digest"]}
    if command.action == "fail_ocr_plan":
        rows = client.query("SELECT state FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
            "AND hash = {h:String} AND plan_digest = {p:String}", parameters=parameters).result_rows
        if rows and rows[0][0] in ("planned", "failed"):
            write_plan(client, plan, "failed", values["error_type"])
        return 1
    if values["plan_digest"] != plan["plan_digest"]:
        raise RuntimeError("The automatic OCR command changed its claimed plan")
    if command.action == "apply_ocr_plan":
        if epoch != int(values["publication_epoch"]):
            raise RuntimeError("Automatic OCR publication changed during verification")
        rows = client.query("SELECT plan_json, has_ocr_output FROM automatic_ocr_plans FINAL "
            "WHERE collection_dataset = {cd:String} AND hash = {h:String} AND plan_digest = {p:String}", parameters=parameters).result_rows
        write_plan(client, json.loads(rows[0][0]), "applied", presence=int(rows[0][1]))
        return 1
    metadata = client.query("SELECT payload FROM automatic_ocr_output FINAL WHERE collection_dataset = {cd:String} "
        "AND hash = {h:String} AND plan_digest = {p:String} AND output_id = 'publication-metadata'", parameters=parameters).result_rows
    if not metadata:
        raise RuntimeError("Automatic OCR publication metadata is absent")
    metadata = json.loads(metadata[0][0])
    outputs = read_outputs(client, plan)
    if set(outputs) != expected_identities(plan, plan["source_parts"]):
        raise RuntimeError("Automatic OCR publication has incomplete staged requests")
    if metadata["output_digest"] != values["output_digest"] or digest(dict(outputs=outputs, languages=metadata["languages"])) != values["output_digest"]:
        raise RuntimeError("Automatic OCR staged output changed before publication")
    params = StageBatchParams(command.collectionname, values["dataset"], "", op_id=command.owner_op)
    _publish_serialized(client, params, BatchFile(command.file_hash, "", source_kind=plan["source_kind"]), plan, outputs, metadata["languages"])
    return 1


def publication_rows(client, dataset, file_hash, source_kind, sources):
    """The `text_content` rows of each OCR source: the pages of an image, or one row for each PDF part."""
    if source_kind == "image":
        return sources
    from tasks.P3_parse_files.parse_common import pdf_text_rows
    from tasks.P3_parse_files.pdf_parts import source_parts, source_ranges
    ranges = [(part["first_page"], part["last_page"]) for part in source_parts(client, dataset, file_hash, source_kind)]
    ranges = ranges or source_ranges(max((int(page) for pages in sources.values() for page, _ in pages), default=0), 1)
    return {source: pdf_text_rows(pages, ranges) for source, pages in sources.items()}


def _publish_serialized(client, params, file, plan, outputs, source_languages):
    """Publish complete text and PDF manifests before retiring obsolete normal variants."""
    from tasks.P3_parse_files.parse_common import insert_text_sources
    from tasks.P3_parse_files.pdf_parts import store_part, write_row
    from tasks.P3_parse_files.insert_batch import current_batch
    from tasks.text_sources import ocr_extracted_by, pdf_ocr_extracted_by
    if require_current_claim(client, plan) > plan["claim_version"]:
        return
    groups = {}
    for output in outputs.values():
        groups.setdefault((output["engine"], output["languages"]), []).append(output)
    sources = {}
    for (engine, languages), values in groups.items():
        extractor = ocr_extracted_by if plan["source_kind"] == "image" else pdf_ocr_extracted_by
        sources[extractor(engine, languages)] = sorted((int(page), text) for value in values for page, text in value["pages"])
    sources = publication_rows(client, params.collection_dataset, file.item_hash, plan["source_kind"], sources)
    states = client.query("SELECT state, has_ocr_output FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
        "AND hash = {h:String} AND plan_digest = {p:String}",
        parameters={"cd": params.collection_dataset, "h": file.item_hash, "p": plan["plan_digest"]}).result_rows
    if states and states[0][0] in ("published", "applied"):
        try:
            verify_text_publication(client, params, file.item_hash, sources)
        except RuntimeError:
            pass
        else:
            record_published_claim(client, plan)
            pdf_pairs = {(item["engine"], item["languages"]) for item in outputs.values() if item.get("blob_key")}
            retire_superseded(client, params, file.item_hash, set(sources), pdf_pairs)
            supersede_prior_plans(client, plan)
            write_plan(client, plan, states[0][0], presence=int(states[0][1]))
            return
    insert_text_sources(params.collectionname, params.collection_dataset, file.item_hash, sources, languages=source_languages)
    if current_batch() is not None:
        batch = current_batch()
        batch.flush()
        if batch.index in batch.errors:
            raise batch.errors[batch.index]
        batch.finish_file(batch.index)
    verify_text_publication(client, params, file.item_hash, sources)
    for (engine, languages), values in groups.items():
        with_engine = dataclasses.replace(params, engine=engine)
        rows = artifact_rows(plan["source_kind"], values)
        if not rows:
            continue
        for value, part, pages in rows:
            part_file = dataclasses.replace(file, source_kind=plan["source_kind"],
                part_index=part["part_index"], first_page=part["first_page"], last_page=part["last_page"])
            store_part(client, with_engine, part_file, languages, key=value.get("blob_key", ""),
                       size=value.get("size_bytes", 0), pages=pages, borrowed=value.get("borrowed", False))
        write_row(client, "pdf_ocr_results", dict(collection_dataset=params.collection_dataset,
            pdf_hash=file.item_hash, engine=engine, languages=languages, source_kind=plan["source_kind"],
            form="overlay", blob_key=rows[0][0].get("blob_key", "") if len(rows) == 1 else "", blob_hash="",
            page_count=max(part["last_page"] for _, part, _ in rows), size_bytes=sum(value.get("size_bytes", 0) for value, _, _ in rows),
            run_time_ms=0, part_count=len(rows), text_complete=1))
    from tasks.P_admin.ocr_languages import EXTRACTED_BY_TABLES
    for table in EXTRACTED_BY_TABLES:
        if table != "text_content":
            client.command(f"DELETE FROM `{table}` WHERE collection_dataset = {{cd:String}} AND file_hash = {{h:String}} "
                "AND extracted_by IN {sources:Array(String)} SETTINGS mutations_sync = 2",
                parameters={"cd": params.collection_dataset, "h": file.item_hash, "sources": sorted(sources)})
    from tasks.P3_parse_files.parse_common import stored_page_bodies
    presence = int(any(bool(list(stored_page_bodies(pages, min_chars=2))) for pages in sources.values()))
    record_published_claim(client, plan)
    write_plan(client, plan, "published", presence=presence)
    pdf_pairs = {(item["engine"], item["languages"]) for item in outputs.values() if item.get("blob_key")}
    retire_superseded(client, params, file.item_hash, set(sources), pdf_pairs)
    supersede_prior_plans(client, plan)


def artifact_rows(source_kind, values):
    """One `(artifact output, part, pages)` row for each part of one `(engine, languages)` pair.

    A part with a recognition output and an adoption output has one artifact: the
    assembled adoption artifact, else the recognition artifact. Its pages join the pages of
    both outputs. An image without a searchable PDF has no row.
    """
    if source_kind == "image":
        value = next((item for item in values if item.get("blob_key")), None)
        if value is None:
            return []
        pages = sorted((int(page), text) for item in values for page, text in item["pages"])
        return [(value, dict(part_index=1, first_page=1, last_page=1), pages)]
    parts = {}
    for value in values:
        parts.setdefault(value["part"]["part_index"], []).append(value)
    rows = []
    for _, members in sorted(parts.items()):
        final = (next((item for item in members if item.get("assembled")), None)
                 or next((item for item in members if item.get("blob_key")), members[0]))
        pages = sorted((int(page), text) for item in members for page, text in item["pages"])
        rows.append((final, final["part"], pages))
    return rows


def supersede_prior_plans(client, plan):
    """Retain old plan provenance after its normal replacement output publishes."""
    rows = client.query("SELECT plan_json, has_ocr_output FROM automatic_ocr_plans FINAL "
        "WHERE collection_dataset = {cd:String} AND hash = {h:String} AND plan_digest != {p:String} "
        "AND state IN ('published', 'applied')",
        parameters={"cd": plan["dataset"], "h": plan["file_hash"], "p": plan["plan_digest"]}).result_rows
    for raw, presence in rows:
        previous = json.loads(raw)
        if int(previous.get("claim_version", 0)) < plan["claim_version"]:
            write_plan(client, previous, "superseded", "replacement_published", int(presence))


def verify_artifacts(collectionname, outputs):
    """Require every staged searchable artifact to exist with its declared size."""
    from database.s3 import collection_bucket, get_s3_client
    bucket = collection_bucket(collectionname)
    for item in outputs:
        if item.get("blob_key"):
            stored = get_s3_client().stat_object(bucket, item["blob_key"])
            if stored.size != item["size_bytes"] or stored.size <= 0:
                raise RuntimeError("Automatic OCR has incomplete stored PDF artifacts")


def verify_text_publication(client, params, h, sources):
    """Require exact current page bodies before publishing the replacement manifest."""
    from tasks.P3_parse_files.parse_common import stored_page_bodies
    for source, pages in sources.items():
        expected = dict(stored_page_bodies(pages, min_chars=2))
        actual = {int(page): text for page, text in client.query(
            "SELECT page_id, argMax(text, version) FROM text_content WHERE collection_dataset = {cd:String} "
            "AND file_hash = {h:String} AND extracted_by = {s:String} GROUP BY page_id",
            parameters={"cd": params.collection_dataset, "h": h, "s": source}).result_rows}
        if actual != expected:
            raise RuntimeError("Automatic OCR has incomplete durable replacement text")


def retire_superseded(client, params, h, keep_sources, keep_pairs):
    """Remove obsolete normal output after replacement publication. Keep diagnostic rows."""
    from tasks.P_admin.ocr_languages import EXTRACTED_BY_TABLES
    values = {"cd": params.collection_dataset, "h": h, "keep": sorted(keep_sources)}
    # Raw OCR payloads and automatic plan/output records retain diagnostic provenance.
    for table in EXTRACTED_BY_TABLES:
        client.command(f"DELETE FROM `{table}` WHERE collection_dataset = {{cd:String}} "
            "AND file_hash = {h:String} AND (startsWith(extracted_by, 'ocr_') OR startsWith(extracted_by, 'pdfocr_')) "
            "AND extracted_by NOT IN {keep:Array(String)}", parameters=values)
    pairs = client.query("SELECT engine, languages FROM pdf_ocr_results FINAL "
        "WHERE collection_dataset = {cd:String} AND pdf_hash = {h:String} AND is_deleted = 0", parameters=values).result_rows
    for engine, languages in pairs:
        if (engine, languages) not in keep_pairs:
            client.command("INSERT INTO pdf_ocr_parts SELECT * REPLACE (1 AS is_deleted, now64(6) AS updated_at) "
                "FROM pdf_ocr_parts FINAL WHERE collection_dataset = {cd:String} AND hash = {h:String} "
                "AND engine = {e:String} AND languages = {l:String}", parameters=values | {"e": engine, "l": languages})
            client.command("INSERT INTO pdf_ocr_results SELECT * REPLACE (1 AS is_deleted, now64(6) AS updated_at) "
                "FROM pdf_ocr_results FINAL WHERE collection_dataset = {cd:String} AND pdf_hash = {h:String} "
                "AND engine = {e:String} AND languages = {l:String}", parameters=values | {"e": engine, "l": languages})


@activity.defn
@with_heartbeat
def automatic_ocr_batch(params: StageBatchParams) -> BatchResult:
    """Run bounded files with durable page decisions and resumable output requests."""
    return run_batch("automatic_ocr_batch", params.files, key=lambda file: file.item_hash,
                     size=lambda file: file.file_size_bytes, step=lambda file: execute_file(params, file),
                     task_name="automatic_ocr")
