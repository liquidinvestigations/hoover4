"""The `pdf_text` update step: searchable PDF parts with the Helvetica text layer.

Text layer version 1 wrote each character outside Windows-1252 as a black square
(U+25A0, a ZapfDingbats glyph), so copied text lost every letter of those scripts. The
step reads each live part of version 1 of a current `(engine, languages)` pair.

* A part of a variant whose languages all have a Windows-1252 alphabet, a part that
  borrows its source, and a part whose text has no black square get version 2. Nothing
  else changes.
* A part whose text has a black square gets a tombstone with `text_layer = 0`, and its
  variant gets `text_complete = 0` and the `overlay` form. `RerunOcr` then builds only
  the missing parts: an image PDF from the stored word boxes, and a PDF part with a new
  OCR request. A new OCR text adds an index target, so search follows the new text.

Settlement: no live part of a current pair has version 1, and no tombstone of this step
is without a new part.
"""

import json
import logging
import os
import subprocess

from tasks import sandbox
import tempfile
from typing import Dict, List

from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P_admin.updates.params import StepParams

log = logging.getLogger(__name__)

#: The black square that text layer version 1 wrote for a character it could not encode.
BLACK_SQUARE = "■"
#: The tombstone value of `text_layer` that marks a part for a new build.
REBUILD_TOMBSTONE = 0
#: Hashes of one page of the scan.
SCAN_PAGE = 100

#: Language codes whose CLDR alphabet Windows-1252 encodes. A variant of these languages
#: only kept every letter in text layer version 1, so the step does not read its blobs.
#: Dutch and Frisian are included: their only other letter is an accented `ij` in emphasis.
WINDOWS_1252_LANGUAGES: Dict[str, frozenset] = {
    "tesseract": frozenset(
        "afr cat ceb dan deu eng est eus fao fil fin fra fry gla gle glg ind isl ita jav ltz "
        "msa nld nor oci por spa sqi sun swa swe".split()),
    "easyocr": frozenset("af da de en es et fr ga id is it ms nl no oc pt sq sv sw tl".split()),
}

_PART_COLUMNS = ("hash", "source_kind", "engine", "languages", "segmentation", "part_index",
                 "first_page", "last_page", "blob_key", "size_bytes", "page_numbers", "page_texts",
                 "borrows_source")


def keeps_every_letter(engine: str, languages: str) -> bool:
    """Whether every language of a pass has a Windows-1252 alphabet."""
    codes = WINDOWS_1252_LANGUAGES.get(engine, frozenset())
    return all(code in codes for code in languages.split("+"))


def layer_target(collection_dataset: str, collectionname: str) -> dict:
    """The `engine|languages` pairs that the PDF builder can build again, by source kind."""
    from tasks.ocr_pdf_client import service_configured
    from tasks.ocr_targets import engine_passes
    from tasks.P_admin.updates.selectors import ocr_target

    target = ocr_target(collection_dataset, collectionname)

    if "languages" not in target:
        from database.clickhouse import get_collection_client
        with get_collection_client(collectionname) as client:
            rows = client.query("SELECT DISTINCT engine, languages, source_kind FROM pdf_ocr_results FINAL "
                "WHERE collection_dataset = {cd:String} AND is_deleted = 0", parameters={"cd": collection_dataset}).result_rows
        return {"image_pairs": sorted({f"{engine}|{languages}" for engine, languages, kind in rows if kind == "image"}),
                "pdf_pairs": sorted({f"{engine}|{languages}" for engine, languages, kind in rows if kind != "image"})}

    def pairs(engines: List[str]) -> List[str]:
        return sorted(f"{e}|{p}" for e in engines for p in engine_passes(e, target["languages"].get(e, "")))

    return {"image_pairs": pairs(target["image_engines"]) if service_configured() else [],
            "pdf_pairs": pairs(target["pdf_engines"])}


def _pair_condition() -> str:
    return ("((source_kind = 'image' AND concat(engine, '|', languages) IN {tl_image:Array(String)}) "
            "OR (source_kind != 'image' AND concat(engine, '|', languages) IN {tl_pdf:Array(String)}))")


def old_layer_sql() -> str:
    """The hashes with a live part of text layer version 1 of a current pair."""
    from tasks.P_admin.updates.selectors import _LIVE

    return ("SELECT hash FROM pdf_ocr_parts FINAL WHERE collection_dataset = {cd:String} "
            "AND is_deleted = 0 AND text_layer < {tl_version:UInt8} AND " + _pair_condition()
            + " AND hash IN (" + _LIVE + ")")


def sql_parameters(target: dict) -> dict:
    from tasks.text_sources import PDF_TEXT_LAYER_VERSION

    return {"tl_version": PDF_TEXT_LAYER_VERSION, "tl_image": target["image_pairs"],
            "tl_pdf": target["pdf_pairs"]}


def unbuilt_tombstones(client, collection_dataset: str, target: dict) -> int:
    """Parts of live files whose latest row is a tombstone of this step."""
    from tasks.P_admin.updates.selectors import _LIVE
    from tasks.text_sources import PDF_SEGMENTATION_VERSION

    return int(client.query(
        "SELECT count() FROM (SELECT argMax(is_deleted, updated_at) AS deleted, "
        "argMax(text_layer, updated_at) AS layer FROM pdf_ocr_parts "
        "WHERE collection_dataset = {cd:String} AND segmentation = {tl_segmentation:UInt16} AND "
        + _pair_condition() + " AND hash IN (" + _LIVE + ") "
        "GROUP BY hash, source_kind, engine, languages, part_index) "
        "WHERE deleted = 1 AND layer = {tl_tombstone:UInt8}",
        parameters={"cd": collection_dataset, "tl_segmentation": PDF_SEGMENTATION_VERSION,
                    "tl_tombstone": REBUILD_TOMBSTONE, **sql_parameters(target)}).result_rows[0][0])


def has_black_square(bucket: str, blob_key: str) -> bool:
    """Whether the text of a stored part has a black square."""
    from database.s3 import get_s3_client

    with tempfile.TemporaryDirectory(prefix="hoover4-pdf-text-layer-") as folder:
        path = os.path.join(folder, "part.pdf")
        get_s3_client().fget_object(bucket, blob_key, path)
        text = sandbox.run(["pdftotext", "-q", "-enc", "UTF-8", path, "-"], capture_output=True,
                              timeout=300, check=True).stdout.decode("utf-8", "replace")
    return BLACK_SQUARE in text


def scan_parts(client, collectionname: str, collection_dataset: str, target: dict) -> dict:
    """Mark or reopen every selected part. See the module docstring."""
    from database.s3 import collection_bucket
    from tasks.P3_parse_files.pdf_parts import variant_result, write_rows
    from tasks.text_sources import PDF_TEXT_LAYER_VERSION

    bucket = collection_bucket(collectionname)
    parameters = {"cd": collection_dataset, **sql_parameters(target)}
    counts = {"files": 0, "kept_parts": 0, "rebuilt_parts": 0, "rebuilt_variants": 0}
    after = ""
    while True:
        hashes = [row[0] for row in client.query(
            f"SELECT DISTINCT hash FROM ({old_layer_sql()}) WHERE hash > {{tl_after:String}} "
            f"ORDER BY hash LIMIT {SCAN_PAGE}", parameters={**parameters, "tl_after": after}).result_rows]
        if not hashes:
            return counts
        after = hashes[-1]
        rows = client.query(
            "SELECT " + ", ".join(_PART_COLUMNS) + " FROM pdf_ocr_parts FINAL "
            "WHERE collection_dataset = {cd:String} AND is_deleted = 0 AND hash IN {tl_hashes:Array(String)} "
            "AND text_layer < {tl_version:UInt8} AND " + _pair_condition()
            + " ORDER BY hash, source_kind, engine, languages, part_index",
            parameters={**parameters, "tl_hashes": hashes}).result_rows
        opened, written = set(), []
        for row in rows:
            part = dict(zip(_PART_COLUMNS, row), collection_dataset=collection_dataset)
            if (part["borrows_source"] or not part["blob_key"]
                    or keeps_every_letter(part["engine"], part["languages"])
                    or not has_black_square(bucket, part["blob_key"])):
                written.append({**part, "is_deleted": 0, "text_layer": PDF_TEXT_LAYER_VERSION})
                counts["kept_parts"] += 1
            else:
                written.append({**part, "is_deleted": 1, "text_layer": REBUILD_TOMBSTONE})
                opened.add((part["hash"], part["engine"], part["languages"]))
                counts["rebuilt_parts"] += 1
        # The variants reopen before their parts get tombstones, so a retried page finds
        # the same parts again. An `overlay` variant builds its missing parts, a `raster`
        # variant does not. A part without a variant row belongs to a build in progress.
        for file_hash, engine, languages in sorted(opened):
            result = variant_result(client, collection_dataset, file_hash, engine, languages)
            if result is not None:
                write_rows(client, "pdf_ocr_results", [{
                    **result, "collection_dataset": collection_dataset, "pdf_hash": file_hash,
                    "engine": engine, "languages": languages, "form": "overlay", "text_complete": 0}])
        if written:
            write_rows(client, "pdf_ocr_parts", written)
        counts["files"] += len(hashes)
        counts["rebuilt_variants"] += len(opened)


@activity.defn
@with_heartbeat
def scan_pdf_text_layers(params: StepParams) -> dict:
    """Mark the parts that keep every letter, and reopen the parts with black squares."""
    from database.clickhouse import get_collection_client

    target = layer_target(params.collection_dataset, params.collectionname)
    with get_collection_client(params.collectionname) as client:
        counts = scan_parts(client, params.collectionname, params.collection_dataset, target)
        # Tombstones of an earlier attempt of this activity count too.
        counts["unbuilt_parts"] = unbuilt_tombstones(client, params.collection_dataset, target)
    log.info("[pdf_text] %s: %s", params.collection_dataset, json.dumps(counts, sort_keys=True))
    return counts
