"""Read completed signal versions and replace scored passages after indexing.

    The completion watermark selects its exact hit generation.
    Unfinished writes cannot replace completed signal evidence.
"""

from database.clickhouse import insert_arrow_durable
from tasks.red_flags import compute_clusters, load_calibration, text_digest


LATEST_SIGNALS = """
    SELECT file_hash, extracted_by, page_id, completed.1 AS signal_set_version,
           completed.2 AS text_digest, completed.3 AS text_version, completed_scan_version AS scan_version
    FROM (
        SELECT file_hash, extracted_by, page_id,
               argMax((signal_set_version, text_digest, text_version), scan_version) AS completed,
               max(scan_version) AS completed_scan_version
        FROM signal_scanned
        WHERE collection_dataset = {ds:String} AND file_hash IN {hashes:Array(String)}
        GROUP BY file_hash, extracted_by, page_id
    )
"""


def read_signal_pages(client, dataset, hashes):
    bound = {"ds": dataset, "hashes": hashes}
    marks = {}
    for row in client.query_arrow(LATEST_SIGNALS, bound).to_pylist():
        key = row["file_hash"], row["extracted_by"], row["page_id"]
        marks[key] = row["signal_set_version"], row["text_digest"], row["text_version"]
    rows = client.query_arrow("""
        SELECT h.file_hash, h.extracted_by, h.page_id, h.category,
               h.starts, h.ends, h.terms, h.concepts, h.languages, h.tiers, h.speakers, h.flags, h.texts
        FROM signal_hit AS h FINAL
        INNER JOIN (""" + LATEST_SIGNALS + """) AS s
        ON h.file_hash = s.file_hash AND h.extracted_by = s.extracted_by AND h.page_id = s.page_id
           AND h.scan_version = s.scan_version AND h.signal_set_version = s.signal_set_version
        WHERE h.collection_dataset = {ds:String} AND h.file_hash IN {hashes:Array(String)}
    """, bound).to_pylist()
    hits = {}
    fields = {"start": "starts", "end": "ends", "term": "terms", "concept": "concepts",
              "lang": "languages", "tier": "tiers", "speaker": "speakers", "flags": "flags", "text": "texts"}
    for row in rows:
        key = row["file_hash"], row["extracted_by"], row["page_id"]
        if len({len(row[name]) for name in fields.values()}) != 1:
            raise ValueError("Stored signal arrays have different lengths.")
        hits.setdefault(key, []).extend(dict(category=row["category"], **{
            field: row[column][index] for field, column in fields.items()}) for index in range(len(row["starts"])))
    return marks, hits


def page_clusters(row, cleaned, marks, hits, write_version):
    key = row["file_hash"], row["extracted_by"], row["page_id"]
    digest = text_digest(cleaned)
    mark = marks.get(key)
    if mark is None or mark[1] != digest or int(mark[2]) != int(row["text_version"]):
        raise ValueError("The text needs a current signal scan before indexing.")
    calibration = load_calibration()
    common = {name: row[name] for name in ("collection_dataset", "file_hash", "extracted_by", "page_id")}
    common.update(calibration_hash=calibration["hash"], text_digest=digest, write_version=write_version)
    return [dict(common, **cluster) for cluster in compute_clusters(cleaned, hits.get(key, []), calibration)]


def write_clusters(client, rows):
    if not rows:
        return
    import pyarrow as pa
    types = {"page_id": pa.uint32(), "start": pa.uint32(), "end": pa.uint32(),
             "points": pa.float64(), "write_version": pa.uint64(),
             "hit_starts": pa.list_(pa.uint32()), "hit_ends": pa.list_(pa.uint32())}
    insert_arrow_durable(client, "signal_cluster", pa.table({
        name: pa.array([row[name] for row in rows], type=types.get(name, pa.string()))
        for name in rows[0]}))


def remove_old_clusters(client, dataset, hashes, write_version):
    client.command("DELETE FROM signal_cluster WHERE collection_dataset = {ds:String} "
                   "AND file_hash IN {hashes:Array(String)} AND write_version != {version:UInt64}",
                   parameters={"ds": dataset, "hashes": hashes, "version": write_version},
                   settings={"mutations_sync": 2})
