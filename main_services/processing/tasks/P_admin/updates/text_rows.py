"""Split stored text again under the current rule, for the `text_rows` update step."""

from typing import Dict, List, Tuple

from temporalio import activity

from tasks.heartbeat import with_heartbeat
from tasks.P_admin.updates.params import TablePlanParams


def _is_pdf_source(extracted_by: str) -> bool:
    return extracted_by == "pdftotext" or extracted_by.startswith("pdfocr_")


def _pdf_ranges(client, collection_dataset: str, file_hash: str, last_page: int) -> List[Tuple[int, int]]:
    """The stored parts of a PDF, or parts of the longest width for a PDF without a manifest."""
    from tasks.P3_parse_files.pdf_parts import source_parts, source_ranges

    for kind in ("original", "preview"):
        parts = source_parts(client, collection_dataset, file_hash, kind)
        if parts and parts[-1]["last_page"] >= last_page:
            return [(part["first_page"], part["last_page"]) for part in parts]
    return source_ranges(last_page, 1)


def split_again(client, collection_dataset: str, file_hash: str, extracted_by: str,
                rows: List[Tuple[int, str]]) -> List[Tuple[int, str]]:
    """The rows of one source under the current rule, from its rows under the earlier rule."""
    from tasks.P3_parse_files.parse_common import pdf_text_rows, text_chunk_pages

    if _is_pdf_source(extracted_by):
        ranges = _pdf_ranges(client, collection_dataset, file_hash, max(page for page, _ in rows))
        return pdf_text_rows(rows, ranges)
    return text_chunk_pages("".join(text for _, text in sorted(rows)))


@activity.defn
@with_heartbeat
def rewrite_text_rows(params: TablePlanParams) -> int:
    """Replace the old text rows of a plan, and remove the output that read them.

    Derived rows go first. A retry then still selects the source, because its text keeps
    the earlier `segment_version` until the new rows replace it. Old rows beside rows of
    the current split are deleted and not split again, because the current rows already
    hold the complete source.
    """
    from database.clickhouse import get_collection_client
    from tasks.P3_parse_files.parse_common import _delete_obsolete_pages, insert_text_sources
    from tasks.P_admin.ocr_languages import EXTRACTED_BY_TABLES
    from tasks.P_admin.updates.selectors import text_rows_hash_sql

    hash_sql, extra = text_rows_hash_sql()
    values = {"cd": params.collection_dataset, "plan": params.plan_hash, **extra}
    with get_collection_client(params.collectionname) as client:
        selected = [row[0] for row in client.query(
            f"SELECT DISTINCT item_hash FROM processing_plan_hits WHERE collection_dataset = {{cd:String}} "
            f"AND plan_hash = {{plan:String}} AND item_hash IN ({hash_sql})", parameters=values).result_rows]
        if not selected:
            return 0
        grouped: Dict[Tuple[str, str], List[Tuple[int, str]]] = {}
        languages: Dict[Tuple[str, str], str] = {}
        current = set()
        for file_hash, source, page_id, text, language, written in client.query(
                "SELECT file_hash, extracted_by, page_id, argMax(text, version), argMax(language, version), "
                "argMax(segment_version, version) FROM text_content WHERE collection_dataset = {cd:String} "
                "AND file_hash IN {h:Array(String)} AND extracted_by != 'table_text' "
                "GROUP BY file_hash, extracted_by, page_id ORDER BY file_hash, extracted_by, page_id",
                parameters={"cd": params.collection_dataset, "h": selected}).result_rows:
            if int(written) < int(extra["tr_version"]):
                grouped.setdefault((file_hash, source), []).append((int(page_id), text))
                languages[file_hash, source] = language
            else:
                current.add((file_hash, source))
            activity.heartbeat()
        # Rows of the current split hold the complete source, so old rows beside them are leftovers.
        leftovers = {pair: [page for page, _ in rows] for pair, rows in grouped.items() if pair in current}
        pairs = [pair for pair, rows in grouped.items() if pair not in leftovers
                 and (len(rows) > 1 or (_is_pdf_source(pair[1]) and rows[0][0] > 1))]
        pairs += list(leftovers)
        for table in EXTRACTED_BY_TABLES:
            if table != "text_content" and pairs:
                client.command(
                    f"DELETE FROM `{table}` WHERE collection_dataset = {{cd:String}} "
                    "AND (file_hash, extracted_by) IN {pairs:Array(Tuple(String, String))} "
                    "SETTINGS mutations_sync = 2",
                    parameters={"cd": params.collection_dataset, "pairs": pairs})
                activity.heartbeat()
        for (file_hash, source), pages in leftovers.items():
            _delete_obsolete_pages(client, params.collection_dataset, file_hash, source, set(pages))
            activity.heartbeat()
        for file_hash, source in pairs:
            if (file_hash, source) in leftovers:
                continue
            rows = split_again(client, params.collection_dataset, file_hash, source, grouped[file_hash, source])
            insert_text_sources(params.collectionname, params.collection_dataset, file_hash, {source: rows},
                                languages={source: languages[file_hash, source]})
            activity.heartbeat()
    return len(pairs)
