"""Count the historical OCR recovery work of a collection without changing anything.

`main.py assess-ocr-recovery` calls `assess`. The command reads ClickHouse rows, object
metadata and, when asked, a bounded number of saved raster PDFs in a temporary folder. It
gives the evidence of each file to `tasks.ocr_recovery.classify_file`, the classifier that
the OCR processing update uses, and adds up the decisions.

The command writes no row, object, schema, operation or capability cache, and it sends no
OCR or detection request. `ReadOnlyClient` refuses each statement that is not a `SELECT`,
and `ReadOnlyObjects` gives only `stat_object` and a download into the temporary folder.

The command accepts two contracts.

* `upgrade` (the default) does not accept an applied automatic plan only because its
  marker matches. A page stays current when its applied pass is the pass the planner
  chooses now for the same detection and source revision. This is the workload after a
  stage version change.
* `current` accepts an applied plan whose policy and capability identity equal the current
  ones, as the `ocr` update step does now.

Historical schemas: the command reads `system.columns` first. A missing table gives no
evidence of its kind. A missing column takes the default of the migration that added it.
"""

import json
import logging
import os
import tempfile
from collections import Counter, defaultdict
from dataclasses import replace

from tasks import ocr_recovery as recovery

log = logging.getLogger(__name__)

#: The tables that the command reads, with the columns that later migrations added and
#: the value that an earlier row has for each.
COLUMN_DEFAULTS = {
    "ocr_detection": {"model": "''"},
    "pdf_ocr_parts": {"text_layer": "toUInt8(1)"},
    "pdf_ocr_results": {"source_kind": "'original'", "form": "'raster'", "part_count": "toUInt16(1)",
                        "text_complete": "toUInt8(0)"},
    "pdf_metadata": {"defect": "NULL"},
}
TABLES = ("vfs_files", "blobs", "image", "pdf_metadata", "pdf_previews", "pdf_parts", "ocr_page_needs",
          "ocr_detection", "processing_errors", "raw_ocr_results", "pdf_ocr_results", "pdf_ocr_parts",
          "automatic_ocr_plans", "automatic_ocr_output", "text_content")
DETECTION_ERROR_TASK = "detect_ocr_text"
#: Plan states whose output was published by a plan that is still current.
CURRENT_PLAN_STATES = ("published", "applied")


class ReadOnlyClient:
    """A ClickHouse client that runs only `SELECT` statements."""

    def __init__(self, client):
        self._client = client

    def query(self, sql: str, parameters: dict | None = None):
        body = sql.lstrip()
        if body.startswith("/*"):
            body = body.split("*/", 1)[1].lstrip()
        if not body.upper().startswith(("SELECT", "WITH")):
            raise PermissionError("The OCR assessment runs only SELECT statements")
        return self._client.query(sql, parameters=parameters or {})


class ReadOnlyObjects:
    """Object metadata reads and downloads into one temporary folder."""

    def __init__(self, objects, folder: str):
        self._objects = objects
        self._folder = os.path.realpath(folder)

    def stat_object(self, bucket: str, key: str):
        return self._objects.stat_object(bucket, key)

    def fget_object(self, bucket: str, key: str, path: str):
        if not os.path.realpath(path).startswith(self._folder + os.sep):
            raise PermissionError("The OCR assessment downloads only into its temporary folder")
        return self._objects.fget_object(bucket, key, path)


class Schema:
    """The tables and columns of one collection database."""

    def __init__(self, client):
        self.columns = defaultdict(set)
        for table, name in client.query(
                "/* schema */ SELECT table, name FROM system.columns WHERE database = currentDatabase() "
                "AND table IN {tables:Array(String)}", {"tables": list(TABLES)}).result_rows:
            self.columns[table].add(name)

    def has(self, table: str) -> bool:
        return table in self.columns

    def column(self, table: str, name: str) -> str:
        """The column, or its earlier default under the same name."""
        if name in self.columns.get(table, ()):
            return name
        return f"{COLUMN_DEFAULTS[table][name]} AS {name}"

    def report(self) -> dict:
        return {table: ("present" if self.has(table) else "missing") if not COLUMN_DEFAULTS.get(table) else
                ("missing" if not self.has(table) else
                 sorted(name for name in COLUMN_DEFAULTS[table] if name not in self.columns[table]) or "present")
                for table in TABLES}


def _rows(client, sql, parameters):
    return client.query(sql, parameters).result_rows


def list_datasets(client, schema: Schema) -> list[str]:
    if not schema.has("vfs_files"):
        return []
    return [row[0] for row in _rows(client, "/* datasets */ SELECT DISTINCT collection_dataset FROM vfs_files "
                                    "ORDER BY collection_dataset", {})]


def list_files(client, schema: Schema, cd: str, after: str, limit: int) -> list[tuple]:
    """Live images, PDFs and Office previews after `after`, as `(hash, source_kind, bytes)`."""
    if not schema.has("vfs_files"):
        return []
    sources = []
    if schema.has("image"):
        sources.append("hash IN (SELECT image_hash FROM image WHERE collection_dataset = {cd:String})")
    if schema.has("pdf_metadata"):
        defect = "" if "defect" not in schema.columns["pdf_metadata"] else " AND ifNull(defect, '') = ''"
        sources.append(f"hash IN (SELECT hash FROM pdf_metadata WHERE collection_dataset = {{cd:String}}{defect})")
    if schema.has("pdf_previews"):
        sources.append("hash IN (SELECT hash FROM pdf_previews WHERE collection_dataset = {cd:String})")
    if not sources:
        return []
    hashes = [row[0] for row in _rows(client,
        "/* files */ SELECT DISTINCT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} "
        f"AND is_deleted = 0 AND hash > {{after:String}} AND ({' OR '.join(sources)}) ORDER BY hash LIMIT {{n:UInt32}}",
        {"cd": cd, "after": after, "n": limit})]
    if not hashes:
        return []
    p = {"cd": cd, "h": hashes}
    images = {row[0] for row in _rows(client, "/* images */ SELECT DISTINCT image_hash FROM image "
              "WHERE collection_dataset = {cd:String} AND image_hash IN {h:Array(String)}", p)} if schema.has("image") else set()
    previews = {row[0] for row in _rows(client, "/* previews */ SELECT DISTINCT hash FROM pdf_previews "
                "WHERE collection_dataset = {cd:String} AND hash IN {h:Array(String)}", p)} if schema.has("pdf_previews") else set()
    sizes = dict(_rows(client, "/* sizes */ SELECT blob_hash, any(blob_size_bytes) FROM blobs "
                 "WHERE collection_dataset = {cd:String} AND blob_hash IN {h:Array(String)} GROUP BY blob_hash", p)) \
        if schema.has("blobs") else {}
    return [(h, "image" if h in images else "preview" if h in previews else "original", int(sizes.get(h) or 0))
            for h in hashes]


def _owned(cd: str, file_hash: str, key: str) -> bool:
    return key.startswith("derived/") and f"/{cd}/{file_hash}/" in key


def _artifact(bucket, cd, h, key, first, last, size, text_layer=0) -> recovery.Artifact:
    state = recovery.ARTIFACT_UNCHECKED if _owned(cd, h, key) else recovery.ARTIFACT_WRONG_OWNER
    return recovery.Artifact(bucket, key, int(first), int(last), int(size or 0), state, int(text_layer or 0))


class Batch:
    """The stored evidence of one page of files, read with one query for each table."""

    def __init__(self, client, schema: Schema, collectionname: str, cd: str, files: list[tuple]):
        from database.s3 import collection_bucket
        from tasks.P3_parse_files.ocr_detection import OCR_DETECTION_VERSION
        from tasks.text_sources import PDF_SEGMENTATION_VERSION
        self.cd, self.files = cd, files
        self.bucket = collection_bucket(collectionname)
        self.detector_version = OCR_DETECTION_VERSION
        hashes = [h for h, _, _ in files]
        p = {"cd": cd, "h": hashes}
        has = schema.has
        self.needs = {(h, k): (int(c), list(pages)) for h, k, c, pages in _rows(client,
            "/* needs */ SELECT hash, source_kind, page_count, ocr_pages FROM ocr_page_needs FINAL "
            "WHERE collection_dataset = {cd:String} AND hash IN {h:Array(String)}", p)} if has("ocr_page_needs") else {}
        self.parts = defaultdict(list)
        if has("pdf_parts"):
            for h, k, index, first, last, path, size in _rows(client,
                    "/* parts */ SELECT hash, source_kind, part_index, first_page, last_page, s3_path, size_bytes "
                    "FROM pdf_parts FINAL WHERE collection_dataset = {cd:String} AND hash IN {h:Array(String)} "
                    "AND segmentation = {s:UInt16} ORDER BY hash, source_kind, part_index", {**p, "s": PDF_SEGMENTATION_VERSION}):
                self.parts[(h, k)].append(dict(part_index=int(index), first_page=int(first), last_page=int(last),
                                               s3_path=path, size_bytes=int(size)))
        self.detection = defaultdict(dict)
        if has("ocr_detection"):
            for h, k, page, version, text, script, language, model in _rows(client,
                    "/* detection */ SELECT hash, source_kind, page_id, detector_version, has_text, script, language, "
                    f"{schema.column('ocr_detection', 'model')} FROM ocr_detection FINAL "
                    "WHERE collection_dataset = {cd:String} AND hash IN {h:Array(String)}", p):
                self.detection[(h, k)][int(page)] = (int(version), bool(text), script, language, model)
        self.detection_errors = {row[0] for row in _rows(client,
            "/* errors */ SELECT DISTINCT hash FROM processing_errors FINAL WHERE collection_dataset = {cd:String} "
            "AND hash IN {h:Array(String)} AND task_name = {t:String}", {**p, "t": DETECTION_ERROR_TASK})} \
            if has("processing_errors") else set()
        self.raw = defaultdict(list)
        if has("raw_ocr_results"):
            for h, engine, languages, payload in _rows(client,
                    "/* raw */ SELECT image_hash, engine, languages, raw_json FROM raw_ocr_results FINAL "
                    "WHERE collection_dataset = {cd:String} AND image_hash IN {h:Array(String)}", p):
                self.raw[h].append((engine, languages, payload))
        self.results = defaultdict(list)
        if has("pdf_ocr_results"):
            c = schema.column
            for h, engine, languages, latest in _rows(client,
                    "/* results */ SELECT pdf_hash, engine, languages, argMax(tuple(blob_key, size_bytes, page_count, "
                    f"source_kind, form, part_count, text_complete, is_deleted), updated_at) FROM (SELECT pdf_hash, engine, "
                    f"languages, blob_key, size_bytes, page_count, {c('pdf_ocr_results', 'source_kind')}, "
                    f"{c('pdf_ocr_results', 'form')}, {c('pdf_ocr_results', 'part_count')}, "
                    f"{c('pdf_ocr_results', 'text_complete')}, is_deleted, updated_at FROM pdf_ocr_results "
                    "WHERE collection_dataset = {cd:String} AND pdf_hash IN {h:Array(String)}) "
                    "GROUP BY pdf_hash, engine, languages", p):
                self.results[h].append(dict(engine=engine, languages=languages, **dict(zip(
                    ("blob_key", "size_bytes", "page_count", "source_kind", "form", "part_count", "text_complete",
                     "is_deleted"), latest))))
        self.ocr_parts = defaultdict(list)
        if has("pdf_ocr_parts"):
            layer = schema.column("pdf_ocr_parts", "text_layer")
            for h, k, engine, languages, segmentation, index, latest in _rows(client,
                    "/* ocr_parts */ SELECT hash, source_kind, engine, languages, segmentation, part_index, "
                    "argMax(tuple(first_page, last_page, blob_key, size_bytes, page_numbers, page_texts, borrows_source, "
                    "text_layer, is_deleted), updated_at) FROM (SELECT hash, source_kind, engine, languages, segmentation, "
                    f"part_index, first_page, last_page, blob_key, size_bytes, page_numbers, page_texts, borrows_source, "
                    f"{layer}, is_deleted, updated_at FROM pdf_ocr_parts WHERE collection_dataset = {{cd:String}} "
                    "AND hash IN {h:Array(String)}) GROUP BY hash, source_kind, engine, languages, segmentation, part_index", p):
                self.ocr_parts[h].append(dict(source_kind=k, engine=engine, languages=languages,
                    segmentation=int(segmentation), part_index=int(index), **dict(zip(
                        ("first_page", "last_page", "blob_key", "size_bytes", "page_numbers", "page_texts",
                         "borrows_source", "text_layer", "is_deleted"), latest))))
        self.plans = defaultdict(list)
        if has("automatic_ocr_plans"):
            for h, plan_digest, state, policy, capability, revision, plan_json, order in _rows(client,
                    "/* plans */ SELECT hash, plan_digest, state, policy_version, capability_digest, source_revision, "
                    "plan_json, revision FROM automatic_ocr_plans FINAL WHERE collection_dataset = {cd:String} "
                    "AND hash IN {h:Array(String)}", p):
                self.plans[h].append(dict(plan_digest=plan_digest, state=state, policy_version=int(policy),
                                          capability_digest=capability, source_revision=revision,
                                          plan=json.loads(plan_json), revision=int(order)))
        self.outputs = defaultdict(list)
        if has("automatic_ocr_output"):
            for h, plan_digest, output_id, payload in _rows(client,
                    "/* outputs */ SELECT hash, plan_digest, output_id, payload FROM automatic_ocr_output FINAL "
                    "WHERE collection_dataset = {cd:String} AND hash IN {h:Array(String)} "
                    "AND output_id != 'publication-metadata'", p):
                self.outputs[(h, plan_digest)].append((output_id, json.loads(payload)))
        self.published = defaultdict(set)
        if has("text_content"):
            for h, sources in _rows(client,
                    "/* published */ SELECT file_hash, groupUniqArray(extracted_by) FROM text_content "
                    "WHERE collection_dataset = {cd:String} AND file_hash IN {h:Array(String)} "
                    "AND (startsWith(extracted_by, 'ocr_') OR startsWith(extracted_by, 'pdfocr_')) GROUP BY file_hash", p):
                self.published[h] = set(sources)

    # ---- evidence -------------------------------------------------------------------------

    def current_plan(self, h):
        plans = [plan for plan in self.plans[h] if plan["state"] in CURRENT_PLAN_STATES]
        return max(plans, key=lambda plan: plan["revision"]) if plans else None

    def evidence(self, h: str, kind: str, raster_reader=None) -> tuple:
        """Return the file evidence and a description of each candidate for the report."""
        from tasks.P3_parse_files.pdf_parts import source_digest
        detection_kind = kind
        parts = self.parts.get((h, kind), [])
        if kind == "image":
            eligible, revision, ranges = (1,), h, ((1, 1),)
        else:
            need = self.needs.get((h, kind))
            if need is None or not parts:
                eligible, revision = None, ""
            else:
                eligible = tuple(need[1])
                revision = source_digest(parts, parts[-1]["last_page"], need[1])
            ranges = tuple((part["first_page"], part["last_page"]) for part in parts)
        detections = []
        for page in (eligible or ()):
            stored = self.detection[(h, detection_kind)].get(page)
            if stored is None:
                state = recovery.DETECTION_FAILED if h in self.detection_errors else recovery.DETECTION_MISSING
                detections.append(recovery.Detection(page, state))
                continue
            version, text, script, language, model = stored
            state = recovery.DETECTION_CURRENT if version == self.detector_version else recovery.DETECTION_OUTDATED
            detections.append(recovery.Detection(page, state, text, script or "", model or "", language or "und", version))
        current = self.current_plan(h)
        applied = None
        if current is not None:
            plan = current["plan"]
            applied = recovery.AppliedPlan(current["plan_digest"], current["state"], current["policy_version"],
                current["capability_digest"], current["source_revision"],
                {int(page["page_id"]): (page.get("detector_digest", ""), page.get("status", ""),
                                        tuple((item["engine"], item["languages"]) for item in page.get("passes", [])))
                 for page in plan.get("pages", [])})
        candidates, described = [], {}

        def add(candidate, **extra):
            candidates.append(candidate)
            described[candidate.candidate_id] = dict(form=candidate.form, record=candidate.record,
                engine=candidate.engine, languages=candidate.languages, retired=candidate.retired,
                recovery=candidate.recovery, **extra)

        superseded_by_automatic = "superseded_by_automatic" if current is not None else ""
        image_artifacts = defaultdict(list)
        for row in self.results.get(h, []):
            if row["source_kind"] == "image" and row["blob_key"]:
                layer = next((part["text_layer"] for part in self.ocr_parts.get(h, [])
                              if part["blob_key"] == row["blob_key"]), 0)
                image_artifacts[(row["engine"], row["languages"])].append(
                    _artifact(self.bucket, self.cd, h, row["blob_key"], 1, 1, row["size_bytes"], layer))
        for engine, languages, payload in sorted(self.raw.get(h, [])) if kind == "image" else ():
            try:
                raw = json.loads(payload)
            except ValueError:
                raw = None
            problem = ""
            if not isinstance(raw, dict):
                problem, raw = "raw_json_unreadable", {}
            elif (raw.get("engine") or engine) != engine or (raw.get("languages") or languages) != languages:
                problem = "engine_identity_mismatch"
            add(recovery.make_candidate(form=recovery.FORM_RAW_IMAGE, record=f"raw_ocr_results|{engine}|{languages}",
                engine=engine, languages=languages, source_kind="image",
                pages=[] if problem else [recovery.PageText.of(1, raw.get("text") or "")],
                retired=superseded_by_automatic, word_boxes=isinstance(raw.get("words"), list) and bool(raw.get("words")),
                artifacts=tuple(image_artifacts.get((engine, languages), ())), recovery=problem))
        variants = defaultdict(list)
        for part in self.ocr_parts.get(h, []):
            variants[(part["source_kind"], part["engine"], part["languages"], part["segmentation"],
                      int(part["is_deleted"]))].append(part)
        part_identities = set()
        for (source_kind, engine, languages, segmentation, deleted), members in sorted(variants.items()):
            part_identities.add((source_kind, engine, languages))
            pages, artifacts = {}, []
            for part in sorted(members, key=lambda item: item["part_index"]):
                for number, text in zip(part["page_numbers"], part["page_texts"]):
                    pages[int(number)] = recovery.PageText.of(int(number), text)
                if part["blob_key"]:
                    artifacts.append(_artifact(self.bucket, self.cd, h, part["blob_key"], part["first_page"],
                                               part["last_page"], part["size_bytes"], part["text_layer"]))
            if source_kind == "image":
                continue
            add(recovery.make_candidate(form=recovery.FORM_PDF_PARTS,
                record=f"pdf_ocr_parts|{segmentation}|{'tombstone' if deleted else 'live'}",
                engine=engine, languages=languages, source_kind=source_kind, pages=list(pages.values()),
                retired="tombstone" if deleted else "", artifacts=tuple(artifacts)))
        for row in self.results.get(h, []):
            if row["source_kind"] == "image" or row["form"] != "raster" and \
                    (row["source_kind"], row["engine"], row["languages"]) in part_identities:
                continue
            retired = "tombstone" if row["is_deleted"] else ""
            artifact = _artifact(self.bucket, self.cd, h, row["blob_key"], 1, max(1, int(row["page_count"] or 1)),
                                 row["size_bytes"]) if row["blob_key"] else None
            if row["form"] == "raster":
                pages, problem = [], "raster_not_read"
                if artifact is not None and raster_reader is not None:
                    texts, problem = raster_reader(self.bucket, row["blob_key"], self.needs.get((h, row["source_kind"])))
                    pages = [recovery.PageText.of(index, text) for index, text in enumerate(texts or [], 1)]
                    if texts is not None and artifact is not None:
                        artifact = replace(artifact, last_page=max(1, len(texts)), state=recovery.ARTIFACT_PRESENT)
                elif artifact is None:
                    problem = "raster_without_object"
                add(recovery.make_candidate(form=recovery.FORM_RASTER_PDF, record="pdf_ocr_results|raster",
                    engine=row["engine"], languages=row["languages"], source_kind=row["source_kind"], pages=pages,
                    retired=retired, artifacts=(artifact,) if artifact else (), recovery=problem))
            else:
                add(recovery.make_candidate(form=recovery.FORM_OVERLAY_PDF, record="pdf_ocr_results|overlay",
                    engine=row["engine"], languages=row["languages"], source_kind=row["source_kind"],
                    retired=retired, artifacts=(artifact,) if artifact else (), recovery="overlay_without_page_text"))
        for plan in self.plans.get(h, []):
            if plan["state"] in CURRENT_PLAN_STATES:
                retired = "" if current is not None and plan["plan_digest"] == current["plan_digest"] else "superseded"
            else:
                retired = "superseded" if plan["state"] == "superseded" else ""
            by_identity = defaultdict(lambda: dict(pages={}, artifacts=[], words=False))
            for _, output in sorted(self.outputs.get((h, plan["plan_digest"]), []), key=lambda item: item[0]):
                if "engine" not in output or "languages" not in output:
                    continue
                entry = by_identity[(output["engine"], output["languages"])]
                for number, text in output.get("pages") or []:
                    entry["pages"][int(number)] = recovery.PageText.of(int(number), text)
                part = output.get("part") or dict(first_page=1, last_page=1)
                if output.get("blob_key"):
                    layer = next((item["text_layer"] for item in self.ocr_parts.get(h, [])
                                  if item["blob_key"] == output["blob_key"]), 0)
                    entry["artifacts"].append(_artifact(self.bucket, self.cd, h, output["blob_key"], part["first_page"],
                                                        part["last_page"], output.get("size_bytes"), layer))
                if output.get("raw_json"):
                    try:
                        entry["words"] = isinstance(json.loads(output["raw_json"]).get("words"), list)
                    except (ValueError, AttributeError):
                        pass
            source_kind = plan["plan"].get("source_kind", kind)
            for (engine, languages), entry in sorted(by_identity.items()):
                add(recovery.make_candidate(form=recovery.FORM_AUTOMATIC,
                    record=f"automatic_ocr_output|{plan['plan_digest']}|{plan['state']}", engine=engine,
                    languages=languages, source_kind=source_kind, pages=list(entry["pages"].values()),
                    retired=retired, word_boxes=entry["words"], artifacts=tuple(entry["artifacts"]),
                    plan_digest=plan["plan_digest"]), plan_state=plan["state"])
        evidence = recovery.FileEvidence(self.cd, h, kind, revision, eligible, tuple(detections), tuple(candidates),
                                         applied, tuple(sorted(self.published.get(h, ()))), ranges)
        return evidence, described


def stat_states(objects, artifacts, limit: int) -> tuple[dict, int]:
    """Object states by `(bucket, key)` for at most `limit` artifacts, and the unchecked count."""
    states, unchecked = {}, 0
    for artifact in artifacts:
        name = (artifact.bucket, artifact.key)
        if name in states or artifact.state != recovery.ARTIFACT_UNCHECKED:
            continue
        if len(states) >= limit:
            unchecked += 1
            continue
        try:
            stored = objects.stat_object(artifact.bucket, artifact.key)
        except Exception as exc:  # noqa: BLE001 -- the code names the missing object
            states[name] = (recovery.ARTIFACT_MISSING if getattr(exc, "code", "") in ("NoSuchKey", "NoSuchBucket")
                            else recovery.ARTIFACT_UNCHECKED)
            continue
        size = int(getattr(stored, "size", 0) or 0)
        states[name] = recovery.ARTIFACT_PRESENT if size > 0 and (not artifact.size_bytes or size == artifact.size_bytes) \
            else recovery.ARTIFACT_TRUNCATED
    return states, unchecked


def with_states(evidence, states: dict):
    def update(artifact):
        state = states.get((artifact.bucket, artifact.key))
        return replace(artifact, state=state) if state else artifact
    return replace(evidence, candidates=tuple(
        replace(item, artifacts=tuple(update(artifact) for artifact in item.artifacts)) for item in evidence.candidates))


def raster_reader_for(objects, folder: str, limit: int):
    """Read the page texts of at most `limit` saved raster PDFs. Return `(texts, problem)`."""
    used = [0]

    def read(bucket, key, need):
        from tasks.P3_parse_files.parse_pdf import _pdftotext_pages, _qpdf_show_npages
        if used[0] >= limit:
            return None, "raster_not_read"
        used[0] += 1
        path = os.path.join(folder, f"raster-{used[0]}.pdf")
        try:
            objects.fget_object(bucket, key, path)
        except Exception as exc:  # noqa: BLE001 -- a missing object is evidence, not a failure
            return None, "raster_missing" if getattr(exc, "code", "") == "NoSuchKey" else "raster_unreadable"
        try:
            count = _qpdf_show_npages(path, key)
            texts = _pdftotext_pages(path)
        except Exception:  # noqa: BLE001 -- an unreadable saved PDF is evidence
            return None, "raster_unreadable"
        finally:
            os.remove(path)
        if len(texts) < count:
            texts = texts + [""] * (count - len(texts))
        if len(texts) != count or (need is not None and need[0] != count):
            return None, "raster_page_count_mismatch"
        return texts, ""
    return read


class Totals:
    """The aggregate report. Primary actions do not overlap. Work and evidence counts can."""

    def __init__(self, samples: int):
        self.samples_limit = samples
        self.files = Counter()
        self.file_bytes = Counter()
        self.file_reasons = Counter()
        self.pages = Counter()
        self.page_reasons = Counter()
        self.overlap = Counter()
        self.groups = Counter()
        self.candidates = Counter()
        self.rejected = Counter()
        self.missing = Counter()
        self.unknown = Counter()
        #: Pages with a retired compatible result, by source kind, form and engine.
        self.retired = Counter()
        self.samples = defaultdict(list)

    def add(self, decision, described: dict, size: int):
        self.files[decision.action] += 1
        self.file_bytes[decision.action] += size
        self.file_reasons[f"{decision.action}:{decision.reason}"] += 1
        if decision.reason == "source_not_prepared":
            self.unknown["files_without_page_identity"] += 1
            self.unknown["bytes_without_page_identity"] += size
        for candidate_id, problem in decision.rejected:
            self.rejected[problem] += 1
        for item in described.values():
            self.candidates["|".join([decision.source_kind, item["form"], item["engine"], item["languages"],
                                      item["retired"] or "live", item["recovery"] or "recoverable"])] += 1
        outside = Counter()
        for candidate_id, count in decision.outside_eligible.items():
            outside["retired" if described[candidate_id]["retired"] else "live"] += count
        for state, count in outside.items():
            self.overlap[f"files_with_{state}_history_outside_eligible_pages"] += 1
            self.overlap[f"{state}_history_pages_outside_eligible_pages"] += count
        for page in decision.pages:
            self.pages[page.action] += 1
            self.page_reasons[f"{page.action}:{page.reason}"] += 1
            for work in page.work:
                self.overlap["pages_" + work] += 1
            for missing in page.missing:
                self.missing[missing] += 1
            if page.duplicates:
                self.overlap["pages_with_duplicate_candidates"] += 1
            if page.retired_compatible:
                self.overlap["pages_with_retired_compatible_history"] += 1
                for name in sorted({"|".join([described[cid]["form"], described[cid]["engine"]])
                                    for cid in page.retired_compatible}):
                    self.retired["|".join([decision.source_kind, name])] += 1
            if page.replaced:
                self.overlap["pages_replacing_historical_text"] += 1
            if len({item.engine for item in page.accepted}) > 1:
                self.overlap["pages_with_several_engines_accepted"] += 1
            if any(item.empty for item in page.accepted):
                self.overlap["pages_reusing_empty_text"] += 1
            if page.accepted:
                engine, form = page.accepted[0].engine, page.accepted[0].form
            elif page.planned:
                engine, form = page.planned[0]["engine"], "new"
            else:
                engine, form = "-", "-"
            self.groups["|".join([decision.source_kind, engine, form, page.detection, page.action])] += 1
            key = f"{page.action}:{page.reason}"
            if len(self.samples[key]) < self.samples_limit:
                self.samples[key].append(dict(
                    dataset=decision.collection_dataset, hash=decision.file_hash, source_kind=decision.source_kind,
                    page_id=page.page_id, detection=page.detection,
                    accepted=[dict(form=item.form, engine=item.engine, original=item.original_languages,
                                   canonical=item.canonical_languages, reason=item.reason, work=item.work,
                                   missing=item.missing) for item in page.accepted],
                    planned=page.planned, duplicates=len(page.duplicates), replaced=len(page.replaced),
                    retired_compatible=[dict(described.get(cid, {}), id=cid) for cid in page.retired_compatible[:3]]))

    def report(self) -> dict:
        def table(counter, keys):
            return [dict(zip(keys, name.split("|")), count=count) for name, count in sorted(counter.items())]
        return dict(
            files=dict(total=sum(self.files.values()), by_action=dict(sorted(self.files.items())),
                       bytes_by_action=dict(sorted(self.file_bytes.items())),
                       by_reason=dict(sorted(self.file_reasons.items()))),
            pages=dict(eligible=sum(self.pages.values()), by_action=dict(sorted(self.pages.items())),
                       by_reason=dict(sorted(self.page_reasons.items()))),
            overlapping=dict(sorted(self.overlap.items())),
            missing_evidence=dict(sorted(self.missing.items())),
            unknown=dict(sorted(self.unknown.items())),
            groups=table(self.groups, ("source_kind", "engine", "form", "detection", "action")),
            candidates=table(self.candidates, ("source_kind", "form", "engine", "languages", "retired", "recovery")),
            rejected=dict(sorted(self.rejected.items())),
            retired_compatible=table(self.retired, ("source_kind", "form", "engine")),
            samples={key: value for key, value in sorted(self.samples.items())})


def assess(collectionname: str, datasets: list[str] | None = None, *, after: str = "", page_size: int = 100,
           max_files: int | None = None, contract: str = "upgrade", capabilities: dict | None = None,
           check_objects: int = 0, read_raster: int = 0, samples: int = 5, client=None, objects=None) -> dict:
    """Classify the live OCR sources of a collection and return the aggregate report."""
    from tasks.automatic_ocr import POLICY_VERSION, capability_digest, read_installed
    from tasks.ocr_pdf_client import service_configured
    if contract not in ("upgrade", "current"):
        raise ValueError("contract is upgrade or current")
    if capabilities is None:
        capabilities = {}
        for engine in ("tesseract", "easyocr"):
            try:
                capabilities[engine] = read_installed(engine)
            except Exception:  # noqa: BLE001 -- the report names the unavailable engine
                capabilities[engine], capabilities[engine + "_unavailable"] = [], True
    requested = recovery.Contract(capabilities, capability_digest(capabilities) if contract == "current" else "",
                                  POLICY_VERSION, service_configured())
    if client is None:
        from database.clickhouse import get_collection_client
        with get_collection_client(collectionname) as pooled:
            return assess(collectionname, datasets, after=after, page_size=page_size, max_files=max_files,
                          contract=contract, capabilities=capabilities, check_objects=check_objects,
                          read_raster=read_raster, samples=samples, client=pooled, objects=objects)
    if objects is None and (check_objects or read_raster):
        from database.s3 import get_s3_client
        objects = get_s3_client()
    client = ReadOnlyClient(client)
    schema = Schema(client)
    totals = Totals(samples)
    scopes, examined, unchecked, complete = [], 0, 0, True
    with tempfile.TemporaryDirectory(prefix="hoover4-ocr-assessment-") as folder:
        guarded = ReadOnlyObjects(objects, folder) if objects is not None else None
        reader = raster_reader_for(guarded, folder, read_raster) if guarded is not None and read_raster else None
        checks_left = check_objects
        for cd in (datasets or list_datasets(client, schema)):
            cursor, files_in_scope = after, 0
            while True:
                limit = page_size if max_files is None else min(page_size, max_files - examined)
                if limit <= 0:
                    complete = False
                    break
                files = list_files(client, schema, cd, cursor, limit)
                if not files:
                    break
                batch = Batch(client, schema, collectionname, cd, files)
                for h, kind, size in files:
                    evidence, described = batch.evidence(h, kind, reader)
                    decision = recovery.classify_file(evidence, requested)
                    if guarded is not None and checks_left > 0:
                        accepted = {item.candidate_id for page in decision.pages for item in page.accepted}
                        artifacts = [artifact for candidate in evidence.candidates for artifact in candidate.artifacts
                                     if candidate.candidate_id in accepted
                                     or (evidence.applied and candidate.plan_digest == evidence.applied.plan_digest)]
                        states, skipped = stat_states(guarded, artifacts, checks_left)
                        checks_left -= len(states)
                        unchecked += skipped
                        if states:
                            evidence = with_states(evidence, states)
                            decision = recovery.classify_file(evidence, requested)
                            for candidate in evidence.candidates:
                                if evidence.applied and candidate.plan_digest == evidence.applied.plan_digest:
                                    for artifact in candidate.artifacts:
                                        totals.overlap["current_artifacts_" + artifact.state] += 1
                    totals.add(decision, described, size)
                examined += len(files)
                files_in_scope += len(files)
                cursor = files[-1][0]
                if len(files) < limit:
                    break
            scopes.append(dict(dataset=cd, files=files_in_scope, next_after=cursor if not complete else ""))
            if not complete:
                break
    report = dict(tool="assess-ocr-recovery", recovery_policy_version=recovery.RECOVERY_POLICY_VERSION,
                  contract=contract, ocr_policy_version=POLICY_VERSION, capabilities=capabilities,
                  capability_digest=capability_digest(capabilities), searchable_pdf=requested.searchable_pdf,
                  collection=collectionname, schema=schema.report(), scopes=scopes, complete=complete,
                  files_examined=examined, object_checks=dict(limit=check_objects, unchecked=unchecked),
                  raster_reads=read_raster)
    report.update(totals.report())
    return report
