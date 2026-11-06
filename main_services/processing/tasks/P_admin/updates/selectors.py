"""Target keys and live selectors of the update steps.

`target_key` returns the versioned target of a step.
Automatic OCR includes installed capabilities and policy identities.
Searchable PDF targets include current published engine and language pairs.
`select` counts work through bounded collection queries and returns its hash subquery.

Selector contracts, one for each step:

* `unfinished` selects the files of plans without a `processing_plan_finished` row and
  the blobs without a plan. Settlement: both counts are zero.
* `failed_files` selects the files with a current `processing_errors` row of an enabled
  stage and a plan. The automatic count keeps only the stage versions that are not a
  baseline and have no retry claim for the dataset. Settlement: the selected pairs were
  reconciled.
* `ocr` selects live image and PDF sources without a matching applied automatic plan.
  Policy, detector, capability, stage, and input changes make prior output selectable.
  Settlement verifies exact publication identities and durable dependent output.
* `entities` selects earlier provider completion, changed source identities, or missing verified search publication.
  Settlement verifies current completion, text attributes, and searchable terms.
* `vectors` selects files with text and no vector of the served model, when the
  collection uses vectors. A file whose text has no passage worth a vector stays in the
  count after the run, so the count is an upper bound. Settlement: every selected plan
  ran embedding and indexing.
* `virus_scan` selects, when the scan is on, live files up to the size limit whose hash
  has no completed attempt in the collection and whose latest attempt is not
  `skipped_size` or `incomplete`. A failed or disabled attempt is selected again.
  Settlement: the count is zero and every infected hash of the dataset has `virus_hit`
  set on its search rows.
* `ocr_detection` selects, when the Tesseract service is configured, live images and live
  PDF sources with eligible page identities missing from current-version detection.
  Settlement: the count is zero.
* `tables` selects earlier or failed table readings and missing JSON or delimited readings.
  A current publication remains selected until every matching downstream receipt exists.
  Settlement requires zero selected files.
* `pdf_text` selects live files with a searchable PDF part of text layer version 1 of a
  current pair that the PDF builder can build. See `pdf_text_layer.py`. Settlement: the
  count is zero and no part that the step removed is without a new part.
* `folder_counts` selects folder nodes without counts, or every node after a version
  change of the counts. Settlement: no node lacks its counts.
* `search_schema` selects the shard tables that miss a required column or have another
  type. Settlement: every shard table has the required definitions.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from tasks.P_admin.updates.registry import STEPS_BY_ID, UpdateStep, step_version

log = logging.getLogger(__name__)


@dataclass
class ScopeContext:
    """What the selectors of one scope read."""

    scope_kind: str
    scope_id: str
    collectionname: str
    input_revision: str = ""
    #: The applied rows of the scope, by step id.
    applied: Dict[str, dict] = field(default_factory=dict)


@dataclass
class Selection:
    count: int = 0
    bytes: int = 0
    automatic: int = 0
    #: A subquery over the collection database with one column `hash`, or empty.
    hash_sql: str = ""
    parameters: Dict[str, object] = field(default_factory=dict)
    detail: Dict[str, object] = field(default_factory=dict)


# ---- target keys ---------------------------------------------------------------------------


def ocr_target(collection_dataset: str, collectionname: str) -> dict:
    """Return the automatic policy, detector, and installed-capability identity."""
    from tasks.P_admin.automatic_ocr import target
    return target()


def vectors_target(collectionname: str) -> dict:
    from database.clickhouse import get_server_setting
    from tasks.dataset_config import collection_vectors_enabled

    if not collection_vectors_enabled(collectionname):
        return {"vectors": "off"}
    return {"vectors": "on", "model": get_server_setting("embeddings_serving_model") or ""}


def virus_target() -> dict:
    from tasks.P3_parse_files.scan_virus import clamav_enabled

    return {"virus_scan": "on" if clamav_enabled() else "off"}


def detection_target() -> dict:
    from tasks.ocr_client import engine_configured
    from tasks.text_sources import ENGINE_TESSERACT

    return {"ocr_detection": "on" if engine_configured(ENGINE_TESSERACT) else "off"}


def schema_target() -> dict:
    return {"columns": required_page_columns()}


def target_key(step: UpdateStep, ctx: ScopeContext) -> Tuple[str, dict]:
    """The target key of a step for a scope, and the settings it names."""
    if step.step_id == "ocr":
        target = ocr_target(ctx.scope_id, ctx.collectionname)
        key = target
        return json.dumps(key, sort_keys=True), target
    if step.step_id == "entities":
        from tasks.P4_extract_entities.completion import target as entity_target
        target = entity_target()
        return json.dumps(target, sort_keys=True), target
    if step.step_id == "vectors":
        target = vectors_target(ctx.collectionname)
        return json.dumps(target, sort_keys=True), target
    if step.step_id == "virus_scan":
        target = virus_target()
        return json.dumps(target, sort_keys=True), target
    if step.step_id == "ocr_detection":
        target = detection_target()
        return json.dumps(target, sort_keys=True), target
    if step.step_id == "search_schema":
        target = schema_target()
        return json.dumps(target, sort_keys=True), {}
    if step.step_id == "pdf_text":
        from tasks.P_admin.updates.pdf_text_layer import layer_target

        target = layer_target(ctx.scope_id, ctx.collectionname)
        return json.dumps(target, sort_keys=True), target
    return "", {}


# ---- selectors -----------------------------------------------------------------------------


def _count(client, hash_sql: str, parameters: dict, collection_dataset: str) -> Tuple[int, int]:
    """Distinct files of a hash subquery and their bytes, one size for each blob."""
    if not hash_sql:
        return 0, 0
    rows = client.query(
        f"SELECT uniqExact(h.hash), sum(b.size) FROM (SELECT DISTINCT hash FROM ({hash_sql})) AS h "
        "LEFT JOIN (SELECT blob_hash, any(blob_size_bytes) AS size FROM blobs "
        "WHERE collection_dataset = {cd:String} GROUP BY blob_hash) AS b ON b.blob_hash = h.hash",
        parameters={**parameters, "cd": collection_dataset}).result_rows
    return int(rows[0][0] or 0), int(rows[0][1] or 0)


_LIVE = ("SELECT hash FROM vfs_files FINAL WHERE collection_dataset = {cd:String} "
         "AND is_deleted = 0")


def select_unfinished(client, ctx: ScopeContext) -> Selection:
    open_plans = ("SELECT plan_hash FROM processing_plans WHERE collection_dataset = {cd:String} "
                  "AND plan_hash NOT IN (SELECT plan_hash FROM processing_plan_finished "
                  "WHERE collection_dataset = {cd:String})")
    hash_sql = (
        "SELECT item_hash AS hash FROM processing_plan_hits WHERE collection_dataset = {cd:String} "
        f"AND plan_hash IN ({open_plans}) "
        "UNION ALL SELECT blob_hash AS hash FROM blobs WHERE collection_dataset = {cd:String} "
        "AND blob_hash NOT IN (SELECT item_hash FROM processing_plan_hits "
        "WHERE collection_dataset = {cd:String})")
    parameters = {"cd": ctx.scope_id}
    plans = int(client.query(f"SELECT count() FROM ({open_plans})", parameters=parameters).result_rows[0][0])
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, files, hash_sql if files else "", parameters,
                     {"plans": plans})


def failed_pairs(client, collection_dataset: str) -> List[Tuple[str, str]]:
    """Current error pairs of the dataset with a file and a plan."""
    return [(str(h), str(t)) for h, t in client.query(
        "SELECT DISTINCT hash, task_name FROM processing_errors FINAL "
        "WHERE collection_dataset = {cd:String} AND hash != '' "
        "AND hash IN (SELECT item_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String})",
        parameters={"cd": collection_dataset}).result_rows]


def classify_failed(pairs: Sequence[Tuple[str, str]], stage_is_off, entitled: Dict[str, int],
                    claimed: set) -> dict:
    """The task names that a manual and an automatic retry select, and their stages.

    A name of a disabled stage is left out. An unknown name is retryable by hand only.
    The automatic names belong to entitled stage versions without a claim.
    """
    from tasks.stage_versions import canonical_stage

    manual, automatic, stages = set(), set(), {}
    manual_files, automatic_files = set(), set()
    for file_hash, task_name in pairs:
        if stage_is_off(task_name):
            continue
        manual.add(task_name)
        manual_files.add(file_hash)
        stage = canonical_stage(task_name)
        if stage is None:
            continue
        stages[task_name] = stage
        version = entitled.get(stage)
        if version is not None and (stage, version) not in claimed:
            automatic.add(task_name)
            automatic_files.add(file_hash)
    return {"manual_tasks": sorted(manual), "automatic_tasks": sorted(automatic),
            "stages": stages, "manual_files": len(manual_files),
            "automatic_files": len(automatic_files)}


def select_failed(client, ctx: ScopeContext) -> Selection:
    from database.processing_updates import claimed_stage_versions, entitled_stage_versions
    from tasks.P_admin.stage_eligibility import stage_is_off

    classes = classify_failed(
        failed_pairs(client, ctx.scope_id),
        lambda task: stage_is_off(task, ctx.scope_id),
        entitled_stage_versions(), claimed_stage_versions(ctx.scope_id))
    if not classes["manual_tasks"]:
        return Selection(detail={"manual_tasks": [], "automatic_tasks": []})
    hash_sql = ("SELECT hash FROM processing_errors FINAL WHERE collection_dataset = {cd:String} "
                "AND hash != '' AND task_name IN {ff_tasks:Array(String)} "
                "AND hash IN (SELECT item_hash FROM processing_plan_hits WHERE collection_dataset = {cd:String})")
    parameters = {"cd": ctx.scope_id, "ff_tasks": classes["manual_tasks"]}
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, classes["automatic_files"], hash_sql, parameters, {
        "manual_tasks": classes["manual_tasks"], "automatic_tasks": classes["automatic_tasks"]})


def desired_ocr_variants(languages: Dict[str, str]) -> Tuple[set, set]:
    """The text variants and the PDF `(engine, languages)` pairs of effective languages.

    Engine configuration is not read here: a stopped service must not make its stored
    variants obsolete.
    """
    from tasks.ocr_targets import engine_passes
    from tasks.text_sources import ocr_extracted_by, pdf_ocr_extracted_by

    variants, pairs = set(), set()
    for engine, value in languages.items():
        for languages_pass in engine_passes(engine, value):
            variants.add(ocr_extracted_by(engine, languages_pass))
            variants.add(pdf_ocr_extracted_by(engine, languages_pass))
            pairs.add((engine, languages_pass))
    return variants, pairs


def obsolete_ocr_outputs(client, collection_dataset: str, keep_languages: Sequence[Dict[str, str]]):
    """The stored OCR text variants and PDF pairs outside every settings value in `keep_languages`."""
    keep_variants, keep_pairs = set(), set()
    for languages in keep_languages:
        variants, pairs = desired_ocr_variants(languages)
        keep_variants |= variants
        keep_pairs |= pairs
    stored_variants = {row[0] for row in client.query(
        "SELECT DISTINCT extracted_by FROM text_content WHERE collection_dataset = {cd:String} "
        "AND (startsWith(extracted_by, 'ocr_') OR startsWith(extracted_by, 'pdfocr_'))",
        parameters={"cd": collection_dataset}).result_rows}
    stored_pairs = {(e, l) for e, l in client.query(
        "SELECT engine, languages FROM pdf_ocr_results FINAL WHERE collection_dataset = {cd:String} "
        "AND is_deleted = 0 GROUP BY engine, languages",
        parameters={"cd": collection_dataset}).result_rows}
    return sorted(stored_variants - keep_variants), sorted(stored_pairs - keep_pairs)


def select_ocr(client, ctx: ScopeContext, target: Optional[dict] = None) -> Selection:
    from tasks.P_admin.automatic_ocr import hash_sql, target as automatic_target
    selected = target or automatic_target()
    if "languages" in selected:
        return legacy_select_ocr(client, ctx, selected)
    parameters = {"cd": ctx.scope_id, **selected}
    sql = hash_sql()
    files, size = _count(client, sql, parameters, ctx.scope_id)
    return Selection(files, size, files, sql if files else "", parameters, selected)


def legacy_select_ocr(client, ctx: ScopeContext, target: Optional[dict] = None) -> Selection:
    from tasks.ocr_targets import engine_passes

    target = target or ocr_target(ctx.scope_id, ctx.collectionname)
    image_pairs = [(e, p) for e in target["image_engines"]
                   for p in engine_passes(e, target["languages"].get(e, ""))]
    pdf_pairs = [(e, p) for e in target["pdf_engines"]
                 for p in engine_passes(e, target["languages"].get(e, ""))]
    parameters: Dict[str, object] = {"cd": ctx.scope_id}
    parts = []
    if image_pairs:
        population = ("SELECT image_hash AS hash FROM raw_ocr_results WHERE collection_dataset = {cd:String} "
                      "UNION ALL SELECT file_hash AS hash FROM ocr_skips WHERE collection_dataset = {cd:String} "
                      "AND stage = 'image' "
                      "UNION ALL SELECT hash FROM processing_errors WHERE collection_dataset = {cd:String} "
                      "AND startsWith(task_name, 'run_ocr_and_store[')")
        missing = []
        for index, (engine, languages) in enumerate(image_pairs):
            parameters[f"ie{index}"], parameters[f"il{index}"] = engine, languages
            missing.append(
                f"hash NOT IN (SELECT image_hash FROM raw_ocr_results WHERE collection_dataset = {{cd:String}} "
                f"AND engine = {{ie{index}:String}} AND languages = {{il{index}:String}} "
                f"UNION ALL SELECT file_hash FROM ocr_skips WHERE collection_dataset = {{cd:String}} "
                f"AND stage = 'image' AND engine = {{ie{index}:String}} AND languages = {{il{index}:String}} "
                f"UNION ALL SELECT hash FROM processing_errors WHERE collection_dataset = {{cd:String}} "
                f"AND task_name = concat('run_ocr_and_store[', {{ie{index}:String}}, ']'))")
        parts.append(f"SELECT hash FROM ({population}) WHERE hash IN ({_LIVE}) AND ({' OR '.join(missing)})")
    if pdf_pairs:
        population = ("SELECT pdf_hash AS hash FROM pdf_ocr_results WHERE collection_dataset = {cd:String} "
                      "AND source_kind != 'image' "
                      "UNION ALL SELECT file_hash AS hash FROM ocr_skips WHERE collection_dataset = {cd:String} "
                      "AND stage = 'pdf' "
                      "UNION ALL SELECT hash FROM processing_errors WHERE collection_dataset = {cd:String} "
                      "AND startsWith(task_name, 'run_ocr_pdf_and_store[')")
        missing = []
        for index, (engine, languages) in enumerate(pdf_pairs):
            parameters[f"pe{index}"], parameters[f"pl{index}"] = engine, languages
            missing.append(
                f"hash NOT IN (SELECT pdf_hash FROM pdf_ocr_results FINAL WHERE collection_dataset = {{cd:String}} "
                f"AND engine = {{pe{index}:String}} AND languages = {{pl{index}:String}} AND is_deleted = 0 "
                f"UNION ALL SELECT file_hash FROM ocr_skips WHERE collection_dataset = {{cd:String}} "
                f"AND stage = 'pdf' AND engine = {{pe{index}:String}} AND languages = {{pl{index}:String}} "
                f"UNION ALL SELECT hash FROM processing_errors WHERE collection_dataset = {{cd:String}} "
                f"AND task_name = concat('run_ocr_pdf_and_store[', {{pe{index}:String}}, ']'))")
        parts.append(f"SELECT hash FROM ({population}) WHERE hash IN ({_LIVE}) AND ({' OR '.join(missing)})")
    variants, pairs = obsolete_ocr_outputs(client, ctx.scope_id, [target["languages"]])
    if variants:
        parameters["ov"] = variants
        parts.append("SELECT file_hash AS hash FROM text_content WHERE collection_dataset = {cd:String} "
                     "AND extracted_by IN {ov:Array(String)}")
    for index, (engine, languages) in enumerate(pairs):
        parameters[f"oe{index}"], parameters[f"ol{index}"] = engine, languages
        parts.append(f"SELECT pdf_hash AS hash FROM pdf_ocr_results FINAL WHERE collection_dataset = {{cd:String}} "
                     f"AND engine = {{oe{index}:String}} AND languages = {{ol{index}:String}} AND is_deleted = 0")
    hash_sql = " UNION ALL ".join(parts)
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, files, hash_sql if files else "", parameters, {
        "languages": target["languages"], "sources": target["sources"],
        "obsolete_variants": variants, "obsolete_pairs": [list(p) for p in pairs]})


def select_vectors(client, ctx: ScopeContext, target: Optional[dict] = None) -> Selection:
    target = target or vectors_target(ctx.collectionname)
    if target.get("vectors") != "on":
        return Selection(detail={"vectors": "off"})
    parameters = {"cd": ctx.scope_id, "model": target.get("model", "")}
    hash_sql = ("SELECT DISTINCT file_hash AS hash FROM text_content WHERE collection_dataset = {cd:String} "
                "AND file_hash IN (" + _LIVE + ") AND file_hash NOT IN (SELECT file_hash FROM text_chunk_vectors "
                "WHERE collection_dataset = {cd:String} AND embedding_model = {model:String})")
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, files, hash_sql if files else "", parameters,
                     {"vectors": "on", "model": target.get("model", "")})


def virus_hash_sql() -> Tuple[str, dict]:
    """The files that the `virus_scan` step scans, as a subquery with parameters."""
    from tasks.P3_parse_files.scan_virus import CLAMAV_MAX_FILE_BYTES

    sql = (
        f"SELECT hash FROM ({_LIVE}) WHERE hash IN (SELECT blob_hash FROM blobs "
        "WHERE collection_dataset = {cd:String} AND blob_size_bytes <= {vs_max:UInt64}) "
        "AND hash NOT IN (SELECT hash FROM virus_scan_results WHERE attempt_status = 'completed') "
        "AND hash NOT IN (SELECT hash FROM virus_scan_results GROUP BY hash "
        "HAVING argMax(attempt_status, result_seq) IN ('skipped_size', 'incomplete'))")
    return sql, {"vs_max": CLAMAV_MAX_FILE_BYTES}


def select_virus_scan(client, ctx: ScopeContext) -> Selection:
    if virus_target()["virus_scan"] != "on":
        return Selection(detail={"virus_scan": "off"})
    hash_sql, extra = virus_hash_sql()
    parameters = {"cd": ctx.scope_id, **extra}
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, files, hash_sql if files else "", parameters, {"virus_scan": "on"})


def tables_hash_sql() -> Tuple[str, dict]:
    """The files that the `tables` step reads again, as a subquery with parameters."""
    from tasks.P3_parse_files.table_formats import (
        DELIMITED_EXTENSIONS, JSON_EXTENSIONS,
        LIMIT_COLUMNS_PER_SHEET, READER_VERSION, TABLE_MIMES)

    table_candidates = ("SELECT hash FROM file_types WHERE collection_dataset = {cd:String} "
                       "AND (hasAny(mime_type, {tj_mimes:Array(String)}) "
                       "OR hasAny(extensions, {tj_exts:Array(String)}))")
    from tasks.P_admin.updates.table_receipts import STAGES, accepted_contracts
    sql = (
        "SELECT hash FROM ("
        "SELECT hash FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
        "AND status IN ('ok', 'empty') AND (hash, toString(generation)) NOT IN ("
        "SELECT file_hash, output_identity FROM processing_output_receipts "
        "WHERE collection_dataset = {cd:String} AND output_kind = 'table' "
        "AND fingerprint IN {tr_contracts:Array(String)} AND stage IN {tr_stages:Array(String)} "
        "GROUP BY file_hash, output_identity HAVING uniqExact(stage) = {tr_count:UInt8}) "
        "UNION ALL SELECT hash FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
        "AND (reader_version < {tj_version:UInt16} OR status = 'failed') "
        f"UNION ALL SELECT hash FROM ({table_candidates}) WHERE hash NOT IN ("
        "SELECT hash FROM table_documents FINAL WHERE collection_dataset = {cd:String} "
        "AND reader_version >= {tj_version:UInt16} AND status != 'failed')"
        f") WHERE hash IN ({_LIVE})")
    return sql, {"tj_mimes": sorted(TABLE_MIMES),
                 "tj_exts": sorted(JSON_EXTENSIONS | DELIMITED_EXTENSIONS),
                 "tj_version": READER_VERSION, "tj_limit": LIMIT_COLUMNS_PER_SHEET,
                 "tr_contracts": accepted_contracts(), "tr_stages": list(STAGES), "tr_count": len(STAGES)}


def select_tables(client, ctx: ScopeContext) -> Selection:
    hash_sql, extra = tables_hash_sql()
    parameters = {"cd": ctx.scope_id, **extra}
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, files, hash_sql if files else "", parameters, {})


def select_pdf_text(client, ctx: ScopeContext, target: Optional[dict] = None) -> Selection:
    from tasks.P_admin.updates.pdf_text_layer import layer_target, old_layer_sql, sql_parameters

    target = target or layer_target(ctx.scope_id, ctx.collectionname)
    hash_sql = old_layer_sql()
    parameters = {"cd": ctx.scope_id, **sql_parameters(target)}
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, files, hash_sql if files else "", parameters, {})


def select_search_terms(ctx: ScopeContext) -> Selection:
    """Select the dataset's term table until its current version is applied."""
    step = STEPS_BY_ID["search_terms"]
    applied = ctx.applied.get(step.step_id, {})
    try:
        version = json.loads(applied.get("detail") or "{}").get("version", "")
    except ValueError:
        version = ""
    count = int(version != step_version(step))
    return Selection(count=count, automatic=count)


def missing_search_terms(client, ctx: ScopeContext) -> int:
    """Count missing or changed terms with bounded reads from both datastores."""
    from database.manticore import create_entities_table, get_manticore_client
    from tasks.P6_index_data.activities import SEARCHABLE_TERM_FIELDS, entity_term_row_id

    table = create_entities_table(ctx.collectionname)
    after = ("", -1)
    missing = 0
    with get_manticore_client() as connection:
        cursor = connection.cursor()
        while True:
            rows = client.query(
                "SELECT term_field, term_id, term_value FROM string_term_id_to_text FINAL "
                "WHERE collection_dataset = {cd:String} AND term_field IN {fields:Array(String)} "
                "AND (term_field, term_id) > ({field:String}, {id:Int64}) "
                "ORDER BY term_field, term_id LIMIT 500",
                parameters={"cd": ctx.scope_id, "fields": list(SEARCHABLE_TERM_FIELDS),
                            "field": after[0], "id": after[1]}).result_rows
            if not rows:
                return missing
            expected = {entity_term_row_id(ctx.scope_id, field, int(term_id)): (field, int(term_id), value)
                        for field, term_id, value in rows}
            ids = ",".join(str(row_id) for row_id in expected)
            cursor.execute(f"SELECT id, term_field, term_id, term_display FROM {table} "
                           f"WHERE id IN ({ids}) LIMIT 500 OPTION max_matches=500")
            actual = {int(row[0]): (row[1], int(row[2]), row[3]) for row in cursor.fetchall()}
            for row_id, value in expected.items():
                if row_id not in actual:
                    missing += 1
                elif actual[row_id] != value:
                    # Manticore 29.9.0 returned another term's text for a correct row in a
                    # wide `id IN` read. A read of the one row decides the comparison.
                    cursor.execute(f"SELECT term_field, term_id, term_display FROM {table} "
                                   f"WHERE id = {row_id}")
                    single = [(row[0], int(row[1]), row[2]) for row in cursor.fetchall()]
                    missing += single != [value]
            after = (rows[-1][0], int(rows[-1][1]))


def select_folder_counts(client, ctx: ScopeContext) -> Selection:
    """Nodes without counts, or every node when the applied version is older.

    A dataset without an applied row is compared by its `-1` values only. Its stored
    values were written by the current code or by none.
    """
    step = STEPS_BY_ID["folder_counts"]
    applied = ctx.applied.get(step.step_id)
    applied_version = ""
    if applied:
        try:
            applied_version = json.loads(applied.get("detail") or "{}").get("version", "")
        except ValueError:
            applied_version = ""
    every_node = bool(applied_version) and applied_version != step_version(step)
    condition = "" if every_node else "AND (subtree_file_count < 0 OR subtree_size_bytes < 0) "
    nodes = int(client.query(
        "SELECT count() FROM vfs_nodes FINAL WHERE collection_dataset = {cd:String} "
        "AND kind IN ('dir', 'container') " + condition,
        parameters={"cd": ctx.scope_id}).result_rows[0][0])
    return Selection(nodes, 0, nodes, "", {}, {"every_node": every_node})


# ---- the search index schema ---------------------------------------------------------------

#: Manticore `DESCRIBE` type names of the DDL types.
_DESCRIBE_TYPES = {"string": "string", "text": "text", "int": "uint", "bigint": "bigint",
                   "multi64": "mva64", "multi": "mva", "float": "float", "bool": "bool"}


def detection_hash_sql() -> Tuple[str, dict]:
    """The files that the `ocr_detection` step examines, as a subquery with parameters."""
    from tasks.stage_versions import STAGE_VERSIONS

    sql = (
        "SELECT DISTINCT hash FROM (SELECT image_hash AS hash, 'image' AS kind, toUInt32(1) AS page "
        "FROM image WHERE collection_dataset = {cd:String} UNION ALL "
        "SELECT hash, source_kind AS kind, arrayJoin(ocr_pages) AS page FROM ocr_page_needs FINAL "
        "WHERE collection_dataset = {cd:String}) WHERE hash IN (" + _LIVE + ") "
        "AND (hash, kind, page) NOT IN (SELECT hash, source_kind, page_id FROM ocr_detection FINAL "
        "WHERE collection_dataset = {cd:String} AND detector_version = {od_version:UInt16})")
    return sql, {"od_version": STAGE_VERSIONS["ocr_detection"]}


def select_ocr_detection(client, ctx: ScopeContext) -> Selection:
    if detection_target()["ocr_detection"] != "on":
        return Selection(detail={"ocr_detection": "off"})
    hash_sql, extra = detection_hash_sql()
    parameters = {"cd": ctx.scope_id, **extra}
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    from tasks.P_admin.updates.registry import fingerprint
    from tasks.P6_index_data.location_refresh import PATHS_SCAN_PAGE
    step = STEPS_BY_ID["ocr_detection"]
    target, _ = target_key(step, ctx)
    applied = ctx.applied.get("ocr_detection", {}).get("applied_fingerprint")
    if applied != fingerprint(step, target):
        from tasks.P6_index_data.location_refresh import list_stale_location_hashes
        stale, _, _ = list_stale_location_hashes(ctx.collectionname, ctx.scope_id)
        # Stale hashes need a location refresh and no detection, so they join the count
        # only. One query parameter holds about 1,795 hashes after URL encoding.
        extra_sql = f"SELECT hash FROM (SELECT arrayJoin({{d_stale:Array(String)}}) AS hash) WHERE hash NOT IN ({hash_sql})"
        for start in range(0, len(stale), PATHS_SCAN_PAGE):
            extra = _count(client, extra_sql, {**parameters, "d_stale": stale[start:start + PATHS_SCAN_PAGE]}, ctx.scope_id)
            files, size = files + extra[0], size + extra[1]
    return Selection(files, size, files, hash_sql if files else "", parameters, {"ocr_detection": "on"})


def required_page_columns() -> List[List[str]]:
    """The `[name, type]` columns of a shard pages table, from its DDL."""
    from database.manticore import pages_table_ddl

    body = pages_table_ddl("t")
    inner = body[body.index("(") + 1:body.rindex(")")]
    columns = []
    for line in inner.split(","):
        match = re.match(r"\s*([a-z_0-9]+)\s+([a-z0-9]+)", line)
        if match:
            columns.append([match.group(1), match.group(2)])
    return columns


def schema_differences(collectionname: str) -> Dict[str, dict]:
    """Each shard pages table that differs from the DDL: its missing and retyped columns."""
    from database.manticore import client_for_table, list_shard_tables

    required = required_page_columns()
    differences = {}
    for table in [t for t in list_shard_tables(collectionname) if t.endswith("_pages")]:
        with client_for_table(table) as cnx:
            cursor = cnx.cursor()
            cursor.execute(f"DESCRIBE {table}")
            actual = {row[0]: row[1] for row in cursor.fetchall()}
        missing = [[name, kind] for name, kind in required if name not in actual]
        retyped = [[name, kind] for name, kind in required
                   if name in actual and actual[name] != _DESCRIBE_TYPES.get(kind, kind)]
        if missing or retyped:
            differences[table] = {"missing": missing, "retyped": retyped}
    return differences


def select_search_schema(ctx: ScopeContext) -> Selection:
    differences = schema_differences(ctx.collectionname)
    return Selection(len(differences), 0, len(differences), "", {},
                     {"tables": differences,
                      "rebuild": any(d["retyped"] for d in differences.values())})


def select(step: UpdateStep, ctx: ScopeContext, client=None, target: Optional[dict] = None) -> Selection:
    """Run the live selector of one step."""
    if step.step_id == "search_schema":
        return select_search_schema(ctx)
    if step.step_id == "unfinished":
        return select_unfinished(client, ctx)
    if step.step_id == "failed_files":
        return select_failed(client, ctx)
    if step.step_id == "archive_members":
        return select_archive_members(client, ctx)
    if step.step_id == "image_previews":
        return select_image_previews(client, ctx)
    if step.step_id == "ocr":
        return select_ocr(client, ctx, target)
    if step.step_id == "entities":
        from tasks.P4_extract_entities.completion import target as entity_target
        from .entities import pending_sql
        wanted = target or entity_target()
        if not wanted["enabled"]:
            return Selection(detail=wanted)
        sql, values = pending_sql(wanted)
        parameters = {"cd": ctx.scope_id, **values}
        count, size = _count(client, sql, parameters, ctx.scope_id)
        return Selection(count, size, count, sql if count else "", parameters, wanted)
    if step.step_id == "vectors":
        return select_vectors(client, ctx, target)
    if step.step_id == "virus_scan":
        return select_virus_scan(client, ctx)
    if step.step_id == "ocr_detection":
        return select_ocr_detection(client, ctx)
    if step.step_id == "tables":
        return select_tables(client, ctx)
    if step.step_id == "pdf_text":
        return select_pdf_text(client, ctx, target)
    if step.step_id == "search_terms":
        return select_search_terms(ctx)
    if step.step_id == "folder_counts":
        return select_folder_counts(client, ctx)
    raise ValueError(f"unknown update step {step.step_id!r}")


def unique_files(client, selections: Sequence[Selection], collection_dataset: str) -> Tuple[int, int]:
    """Files and bytes of the union of the selections, each file once."""
    parts, parameters = [], {}
    for index, selection in enumerate(selections):
        if not selection.hash_sql:
            continue
        sql = selection.hash_sql
        for name, value in selection.parameters.items():
            if name == "cd":
                continue
            unique = f"u{index}_{name}"
            sql = sql.replace("{" + name + ":", "{" + unique + ":")
            parameters[unique] = value
        parts.append(sql)
    if not parts:
        return 0, 0
    return _count(client, " UNION ALL ".join(parts), parameters, collection_dataset)


def image_preview_hash_sql() -> Tuple[str, dict]:
    """Select live uncommon images without a published preview, including earlier skips."""
    sql = (
        "SELECT DISTINCT hash FROM file_types WHERE collection_dataset = {cd:String} "
        "AND arrayExists(mime -> startsWith(mime, 'image/'), mime_type) "
        "AND hash NOT IN (SELECT hash FROM file_types WHERE collection_dataset = {cd:String} "
        "AND hasAny(mime_type, {preview_direct:Array(String)})) "
        "AND hash NOT IN (SELECT hash FROM image_previews WHERE collection_dataset = {cd:String}) "
        f"AND hash IN ({_LIVE})")
    return sql, {"preview_direct": ["image/jpeg", "image/png", "image/bmp", "image/webp", "image/x-ms-bmp"]}


def select_image_previews(client, ctx: ScopeContext) -> Selection:
    hash_sql, extra = image_preview_hash_sql()
    parameters = {"cd": ctx.scope_id, **extra}
    files, size = _count(client, hash_sql, parameters, ctx.scope_id)
    return Selection(files, size, files, hash_sql if files else "", parameters, {})


def select_archive_members(client, ctx: ScopeContext) -> Selection:
    from tasks.P_admin.updates.archive_members import pending_archives
    pending = pending_archives(client, ctx.scope_id)
    if not pending:
        return Selection()
    sql = "SELECT arrayJoin({archive_hashes:Array(String)}) AS hash"
    parameters = {"cd": ctx.scope_id, "archive_hashes": sorted(pending)}
    files, size = _count(client, sql, parameters, ctx.scope_id)
    return Selection(files, size, files, sql, parameters, {})
