"""Reconcile the stored OCR output of one source before automatic OCR requests recognition.

`reconcile_plan` runs before a new page plan is claimed. It reads the stored evidence of
the file with the reader of the read-only assessment (`tasks.P_admin.ocr_assessment`),
calls `tasks.ocr_recovery.classify_file`, and writes the decision into the page plan.
The claim then pins the decision, so a retry uses the same candidates.

The plan of `ocr_plan` version 2 has these additions.

* A page with accepted earlier text has `passes = []` and an `adopted` list. Each entry
  names the candidate, its form, its engine, its original language set, the published
  language set (`languages`), the text source, the reason and the remaining work.
* Each page has a `recovery` record with the classifier action and reason.
* `reconciliation` records the recovery policy version and the identity of each adopted
  candidate: form, record, engine, languages, source kind, content digest, source plan and
  artifacts.
* `reconciliation_diagnostics` records the decision digest, the rejected candidates, and
  for each page the replaced, duplicate and retired compatible candidates. A retired
  compatible result is reported and not restored. The plan digest excludes this record,
  so the same output decisions give the same plan identity after other history changes.
* `output_contract` records the stage versions of the stored output without the
  installed models. A later stage change makes the output of this plan stale.

Execution reads the evidence with these changes to the assessment.

* The applied plan does not count as proof. Its output is a candidate like the others, so
  each kept page has an accepted entry with its text.
* Output of an earlier plan with another source revision or output contract is retired
  (`source_changed`, `stage_contract_changed`).
* A historical result outside automatic plans is retired when the recognition stages
  differ from `RECOVERY_STAGES`, the versions that recovery policy 1 accepts.
* A preview result with a page after the last page of the current preview is retired.
* Artifact objects of live candidates get a metadata check before classification.

Adoption output is staged as automatic output with its own identity (`adoption_jobs`).
Recognition output and adoption output have separate identities, so a retry of an
artifact build repeats no recognition.
"""

import base64
import json
import os
import tempfile
from dataclasses import replace

from tasks import ocr_recovery as recovery

#: The recognition stage versions under which recovery policy 1 accepts a historical result.
RECOVERY_STAGES = {"ocr_image": 2, "ocr_pdf": 2, "image_pdf": 2}
#: Saved raster PDFs that one file reads at most.
RASTER_READS = 64
#: Retired values that execution adds to the assessment values.
SOURCE_CHANGED = "source_changed"
STAGE_CONTRACT_CHANGED = "stage_contract_changed"


def bounded_ranges(stored: list[dict]) -> list[tuple[int, int]]:
    """The physical page ranges of the automatic artifact parts, as `bounded_source_parts` creates them."""
    from tasks.automatic_ocr import PAGE_BATCH
    if all(part["last_page"] - part["first_page"] + 1 <= PAGE_BATCH for part in stored):
        return [(part["first_page"], part["last_page"]) for part in stored]
    last = stored[-1]["last_page"]
    return [(first, min(last, first + PAGE_BATCH - 1)) for first in range(1, last + 1, PAGE_BATCH)]


def _legacy_stale() -> bool:
    from tasks.stage_versions import STAGE_VERSIONS
    return any(STAGE_VERSIONS[stage] != version for stage, version in RECOVERY_STAGES.items())


def _preview_pages(client, cd: str, h: str) -> int:
    rows = client.query("SELECT page_count FROM pdf_previews FINAL WHERE collection_dataset = {cd:String} "
                        "AND hash = {h:String}", parameters={"cd": cd, "h": h}).result_rows
    return int(rows[0][0]) if rows else 0


def _stale_reason(candidate, plans: dict, revision: str, current_contract: str, legacy_stale: bool,
                  preview_pages: int) -> str:
    from tasks.automatic_ocr import plan_output_contract
    if candidate.form == recovery.FORM_AUTOMATIC:
        plan = plans.get(candidate.plan_digest)
        if plan is None or plan["source_revision"] != revision:
            return SOURCE_CHANGED
        if plan_output_contract(plan["plan"]) != current_contract:
            return STAGE_CONTRACT_CHANGED
        return ""
    if legacy_stale:
        return STAGE_CONTRACT_CHANGED
    if candidate.source_kind == "preview" and any(page.page_id > preview_pages for page in candidate.pages):
        return SOURCE_CHANGED
    return ""


def read_evidence(client, collectionname: str, cd: str, h: str, kind: str, revision: str,
                  eligible: list[int], ranges: list[tuple[int, int]], folder: str) -> tuple:
    """Return `(evidence, described, payloads)` for execution. See the module docstring."""
    from database.s3 import get_s3_client
    from tasks.automatic_ocr import output_contract
    from tasks.P_admin.ocr_assessment import Batch, Schema, raster_reader_for, stat_states, with_states
    objects = get_s3_client()
    batch = Batch(client, Schema(client), collectionname, cd, [(h, kind, 0)])
    payloads = {}
    evidence, described = batch.evidence(h, kind, raster_reader_for(objects, folder, RASTER_READS), payloads,
                                         read_retired=False)
    plans = {plan["plan_digest"]: plan for plan in batch.plans.get(h, [])}
    contract, legacy = output_contract(), _legacy_stale()
    preview = _preview_pages(client, cd, h) if kind == "preview" else 0
    candidates = []
    for candidate in evidence.candidates:
        reason = "" if candidate.retired else _stale_reason(candidate, plans, revision, contract, legacy, preview)
        candidates.append(replace(candidate, retired=reason) if reason else candidate)
        if reason:
            described[candidate.candidate_id]["retired"] = reason
    evidence = replace(evidence, applied=None, source_revision=revision, eligible=tuple(eligible),
                       source_ranges=tuple(ranges), candidates=tuple(candidates))
    artifacts = [artifact for candidate in candidates if not candidate.retired for artifact in candidate.artifacts]
    states, _ = stat_states(objects, artifacts, len(artifacts))
    return with_states(evidence, states), described, payloads


def execution_contract(plan: dict) -> recovery.Contract:
    from tasks.automatic_ocr import POLICY_VERSION
    from tasks.ocr_pdf_client import service_configured
    return recovery.Contract(plan["capabilities"], plan["capability_digest"], POLICY_VERSION, service_configured())


def reconcile_plan(client, params, file, kind: str, plan: dict, ranges: list[tuple[int, int]]) -> dict:
    """Classify the stored evidence of the file and record the decision in the unclaimed plan."""
    eligible = [page["page_id"] for page in plan["pages"]]
    with tempfile.TemporaryDirectory(prefix="hoover4-ocr-reconcile-") as folder:
        evidence, described, _ = read_evidence(client, params.collectionname, params.collection_dataset,
                                               file.item_hash, kind, plan["source_revision"], eligible, ranges, folder)
    decision = recovery.classify_file(evidence, execution_contract(plan))
    return apply_decision(plan, decision, evidence)


def apply_decision(plan: dict, decision: recovery.FileDecision, evidence: recovery.FileEvidence) -> dict:
    """Write page adoptions and recovery records into the plan, then seal it."""
    from temporalio.exceptions import ApplicationError
    from tasks.automatic_ocr import output_contract, seal_plan
    pages = {page["page_id"]: page for page in plan["pages"]}
    candidates = {candidate.candidate_id: candidate for candidate in evidence.candidates}
    used, diagnostics = set(), {}
    for item in decision.pages:
        if item.action == recovery.REQUIRE_DETECTION:
            raise RuntimeError("Automatic OCR detection is not current for every eligible page")
        if item.action == recovery.UNRESOLVED and not item.reason.startswith("planner_"):
            raise ApplicationError(f"Earlier OCR output cannot be recovered without new OCR: {item.reason}",
                                   type="OcrRecoveryUnresolved", non_retryable=True)
        page = pages[item.page_id]
        page["recovery"] = dict(action=item.action, reason=item.reason)
        notes = {name: sorted(getattr(item, name)) for name in ("replaced", "duplicates", "retired_compatible")
                 if getattr(item, name)}
        if notes:
            diagnostics[str(item.page_id)] = notes
        if item.accepted:
            page.update(status="ready", passes=[], adopted=[dict(
                candidate_id=accepted.candidate_id, form=accepted.form, engine=accepted.engine,
                original_languages=accepted.original_languages, languages=accepted.canonical_languages,
                extracted_by=accepted.extracted_by, reason=accepted.reason, work=sorted(accepted.work))
                for accepted in sorted(item.accepted, key=lambda value: (value.engine, value.canonical_languages))])
            used.update(accepted.candidate_id for accepted in item.accepted)
    plan["reconciliation"] = dict(
        policy_version=recovery.RECOVERY_POLICY_VERSION, action=decision.action, reason=decision.reason,
        candidates={candidate_id: _identity(candidates[candidate_id]) for candidate_id in sorted(used)})
    plan["reconciliation_diagnostics"] = dict(decision_digest=decision.decision_digest,
                                              rejected=sorted(decision.rejected), pages=diagnostics)
    plan["output_contract"] = output_contract()
    return seal_plan(plan)


def _identity(candidate: recovery.Candidate) -> dict:
    return dict(form=candidate.form, record=candidate.record, engine=candidate.engine, languages=candidate.languages,
                source_kind=candidate.source_kind, content_digest=candidate.content_digest,
                plan_digest=candidate.plan_digest,
                artifacts=[[item.bucket, item.key, item.first_page, item.last_page, item.size_bytes, item.state,
                            item.text_layer] for item in candidate.artifacts])


def adoption_jobs(plan: dict, parts: list[dict], recognition: list) -> list[dict]:
    """Return one deterministic adoption request for each adopted `(engine, languages)` pair and part.

    A pair without new recognition gets a request for every part, so its downloadable PDF
    covers the file. A pair that also has a recognition request gets a request only for
    the parts with adopted pages. That request merges its pages into the recognition
    artifact of the same part (`merge`).
    """
    from tasks.automatic_ocr import digest
    recognized = {(engine, languages, part["part_index"]): identity
                  for identity, engine, languages, part, _ in recognition}
    groups = {}
    for page in plan["pages"]:
        for entry in page.get("adopted", []):
            groups.setdefault((entry["engine"], entry["languages"]), {})[page["page_id"]] = entry
    jobs = []
    for (engine, languages), entries in sorted(groups.items()):
        for part in parts:
            pages = sorted(page for page in entries if part["first_page"] <= page <= part["last_page"])
            merge = recognized.get((engine, languages, part["part_index"]), "")
            if merge and not pages:
                continue
            sources = [[page, entries[page]["candidate_id"]] for page in pages]
            jobs.append(dict(identity=digest(["adopt", engine, languages, part["part_index"], sources, merge]),
                             engine=engine, languages=languages, part=part, pages=pages,
                             entries={page: entries[page] for page in pages}, merge=merge))
    return jobs


def load_payloads(client, params, file, plan: dict, folder: str) -> tuple[dict, dict]:
    """Read the texts of the pinned candidates again. Return `(payloads, candidates)`."""
    eligible = [page["page_id"] for page in plan["pages"]]
    ranges = [(part["first_page"], part["last_page"]) for part in plan["source_parts"]]
    evidence, _, payloads = read_evidence(client, params.collectionname, params.collection_dataset, file.item_hash,
                                          plan["source_kind"], plan["source_revision"], eligible, ranges, folder)
    return payloads, {candidate.candidate_id: candidate for candidate in evidence.candidates}


def _changed(reason: str):
    from temporalio.exceptions import ApplicationError
    return ApplicationError(f"A pinned earlier OCR result changed after its plan was claimed: {reason}",
                            type="OcrRecoveryChanged", non_retryable=True)


def adoption_output(client, params, file, plan: dict, job: dict, payloads: dict, candidates: dict,
                    outputs: dict, folder: str) -> dict:
    """Stage the text of adopted pages and their searchable PDF without an OCR request."""
    texts, adopted = [], []
    for page in job["pages"]:
        entry = job["entries"][page]
        payload = payloads.get(entry["candidate_id"])
        if payload is None or page not in payload["pages"] or entry["candidate_id"] not in candidates:
            raise _changed(entry["candidate_id"])
        texts.append((page, payload["pages"][page] or ""))
        adopted.append(dict(page=page, candidate_id=entry["candidate_id"], form=entry["form"],
                            original_languages=entry["original_languages"], reason=entry["reason"]))
    output = dict(engine=job["engine"], languages=job["languages"], pages=texts, adopted=adopted,
                  recovery_policy=plan["reconciliation"]["policy_version"])
    if plan["source_kind"] == "image":
        return _image_artifact(client, params, file, plan, job, payloads, candidates, output)
    output.update(part=job["part"], borrowed=False)
    with_text = [page for page, text in texts if "".join(text.split())]
    if not with_text:
        if not job["merge"]:
            output.update(blob_key=job["part"]["s3_path"].split("/", 3)[-1], size_bytes=job["part"]["size_bytes"])
        return output
    reused = _reusable_artifact(job, with_text, candidates)
    if reused is not None:
        output.update(blob_key=reused.key, size_bytes=reused.size_bytes)
        return output
    key, size = assemble_part(client, params, file, plan, job, with_text, candidates,
                              outputs.get(job["merge"]) if job["merge"] else None, folder)
    output.update(blob_key=key, size_bytes=size, assembled=True)
    return output


def _artifact_for(candidate, page: int):
    return next((item for item in candidate.artifacts if item.key and item.first_page <= page <= item.last_page
                 and item.state in (recovery.ARTIFACT_PRESENT, recovery.ARTIFACT_UNCHECKED)), None)


def _reusable_artifact(job: dict, with_text: list[int], candidates: dict):
    """One stored part of one candidate that covers this part exactly and needs no rebuild."""
    if job["merge"]:
        return None
    entries = [job["entries"][page] for page in with_text]
    if len({entry["candidate_id"] for entry in entries}) != 1 or any(recovery.WORK_PDF_PAGES in entry["work"]
                                                                      for entry in entries):
        return None
    candidate = candidates[entries[0]["candidate_id"]]
    found = {_artifact_for(candidate, page) for page in with_text}
    if len(found) != 1 or None in found:
        return None
    artifact = found.pop()
    if (artifact.first_page, artifact.last_page) != (job["part"]["first_page"], job["part"]["last_page"]):
        return None
    return artifact


def _image_artifact(client, params, file, plan, job, payloads, candidates, output):
    from tasks.ocr_pdf_client import build_ocr_pdf, service_configured
    from tasks.P3_parse_files.image_pdf import qualifying_words
    from tasks.P3_parse_files.ocr_detection import read_image
    if not job["pages"]:
        return output
    entry = job["entries"][1]
    text = output["pages"][0][1]
    words = payloads[entry["candidate_id"]].get("words")
    if isinstance(words, list):
        output["raw_json"] = json.dumps(dict(text=text, words=words), sort_keys=True)
    if not service_configured() or qualifying_words(text) < recovery.IMAGE_PDF_MIN_WORDS:
        return output
    if recovery.WORK_PDF_WORDS not in entry["work"]:
        artifact = _artifact_for(candidates[entry["candidate_id"]], 1)
        if artifact is None:
            raise _changed("artifact")
        output.update(blob_key=artifact.key, size_bytes=artifact.size_bytes)
        return output
    if not isinstance(words, list):
        raise _changed("word boxes")
    image = read_image(client, params.collection_dataset, file.item_hash, file.file_path)
    pdf = build_ocr_pdf(collectionname=params.collectionname, collection_dataset=params.collection_dataset,
        pdf_hash=file.item_hash, engine=job["engine"], languages=job["languages"], mode="image", words=words,
        source_b64=base64.b64encode(image).decode(),
        dest_key=f"derived/automatic-ocr/{params.collection_dataset}/{file.item_hash}/{plan['plan_digest']}/"
                 f"{job['engine']}+{job['languages']}.reconciled.pdf")
    output.update(blob_key=pdf.dest_key, size_bytes=pdf.size_bytes, blob_hash=pdf.blob_hash, assembled=True)
    return output


def assemble_part(client, params, file, plan, job, with_text, candidates, merged, folder) -> tuple[str, int]:
    """Build one part PDF from the source or the recognition artifact, with adopted pages from their artifacts.

    No OCR runs. A page without adopted text keeps the base page, so native text and
    pages without OCR stay in the download. Returns the object key and size.
    """
    from database.s3 import collection_bucket, get_s3_client
    from tasks.P3_parse_files.parse_pdf import _qpdf_show_npages, _qpdf_succeeded, _run_qpdf
    from tasks.P3_parse_files.pdf_parts import source_file
    part = job["part"]
    bucket = collection_bucket(params.collectionname)
    objects = get_s3_client()
    downloads = {}

    def fetch(source_bucket, key):
        if (source_bucket, key) not in downloads:
            path = os.path.join(folder, f"artifact-{len(downloads)}.pdf")
            objects.fget_object(source_bucket, key, path)
            downloads[(source_bucket, key)] = path
        return downloads[(source_bucket, key)]

    with source_file(client, params, file) as source:
        if merged is not None:
            if not merged.get("blob_key"):
                raise RuntimeError("Automatic OCR merge requires the recognition artifact")
            base, base_first = fetch(bucket, merged["blob_key"]), part["first_page"]
        else:
            base, base_first = source, 1
        selection = []
        for page in range(part["first_page"], part["last_page"] + 1):
            if page in with_text:
                candidate = candidates[job["entries"][page]["candidate_id"]]
                artifact = _artifact_for(candidate, page)
                if artifact is None:
                    raise _changed("artifact")
                selection.append((fetch(artifact.bucket, artifact.key), page - artifact.first_page + 1))
            else:
                selection.append((base, page - base_first + 1))
        arguments = []
        for path, number in selection:
            if arguments and arguments[-2] == path and arguments[-1].rsplit("-", 1)[-1] == str(number - 1):
                arguments[-1] = f"{arguments[-1].split('-')[0]}-{number}"
            else:
                arguments += [path, str(number)]
        destination = os.path.join(folder, f"part-{part['part_index']}.pdf")
        result = _run_qpdf(["--empty", "--warning-exit-0", "--pages", *arguments, "--", destination])
    if not _qpdf_succeeded(result):
        raise RuntimeError(f"Automatic OCR part assembly failed: {result.stderr[:200]!r}")
    if _qpdf_show_npages(destination, file.item_hash) != part["last_page"] - part["first_page"] + 1:
        raise RuntimeError("Automatic OCR assembled part has incomplete page coverage")
    key = (f"derived/automatic-ocr/{params.collection_dataset}/{file.item_hash}/{plan['plan_digest']}/"
           f"{job['engine']}+{job['languages']}/{part['part_index']}.reconciled.pdf")
    objects.fput_object(bucket, key, destination, content_type="application/pdf")
    return key, os.path.getsize(destination)
