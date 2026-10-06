"""Verify completed signal versions and scored replacements in ClickHouse."""

import pytest
from .test_text_storage_migration import storage, migrate
from tasks.P4_extract_entities.scan_regex_entities import write_signal_rows, SIGNAL_ARRAYS
from tasks.red_flags import text_digest
from tasks.signal_storage import read_signal_pages, page_clusters, write_clusters, remove_old_clusters

pytestmark = pytest.mark.integration


def rows(version, lexicon, text, terms=True):
    common = dict(collection_dataset="dataset", file_hash="file", extracted_by="raw_text", page_id=1,
                  signal_set_version=lexicon, text_digest=text_digest(text), scan_version=version)
    hits = []
    if terms:
        values = [dict(start=0, end=5, term="alpha", concept="first", lang="en", tier="H", speaker="actor", flags=[], text="alpha"),
                  dict(start=6, end=10, term="beta", concept="second", lang="en", tier="H", speaker="actor", flags=[], text="beta")]
        hits = [dict(common, category="bribery", **{column: [hit[field] for hit in values]
                                                   for column, field in SIGNAL_ARRAYS.items()})]
    return hits, [dict(common, text_version=1)]


def test_latest_completed_scan_selects_its_hits_and_empty_rescan_clears_flags(storage):
    _collection, client, cluster, folder = storage
    migrate(client, cluster, folder)
    text = "alpha beta"
    source = dict(collection_dataset="dataset", file_hash="file", extracted_by="raw_text", page_id=1, text_version=1)
    write_signal_rows(client, *rows(1, "z-old", text))
    marks, hits = read_signal_pages(client, "dataset", ["file"])
    scored = page_clusters(source, text, marks, hits, 10)
    assert len(scored) == 1 and scored[0]["points"] == 12
    write_clusters(client, scored)
    remove_old_clusters(client, "dataset", ["file"], 10)
    assert client.query("SELECT excerpt, hit_starts, hit_ends FROM signal_cluster FINAL").result_rows == [(text, [0, 6], [5, 10])]
    write_signal_rows(client, *rows(2, "a-new", text, terms=False))
    marks, hits = read_signal_pages(client, "dataset", ["file"])
    assert marks[("file", "raw_text", 1)][0] == "a-new" and not hits
    assert page_clusters(source, text, marks, hits, 11) == []
    remove_old_clusters(client, "dataset", ["file"], 11)
    assert client.query("SELECT count() FROM signal_cluster FINAL").result_rows == [(0,)]


def test_unfinished_scan_does_not_replace_completed_evidence(storage, monkeypatch):
    from tasks.P4_extract_entities import scan_regex_entities as activity
    _collection, client, cluster, folder = storage
    migrate(client, cluster, folder)
    text = "alpha beta"
    write_signal_rows(client, *rows(1, "completed", text))
    durable = activity.insert_arrow_durable

    def fail_watermark(client, table, values):
        if table == "signal_scanned":
            raise RuntimeError("The watermark write failed.")
        durable(client, table, values)

    monkeypatch.setattr(activity, "insert_arrow_durable", fail_watermark)
    with pytest.raises(RuntimeError, match="watermark"):
        write_signal_rows(client, *rows(2, "unfinished", text))
    marks, hits = read_signal_pages(client, "dataset", ["file"])
    assert marks[("file", "raw_text", 1)][0] == "completed"
    assert len(hits[("file", "raw_text", 1)]) == 2
    monkeypatch.setattr(activity, "insert_arrow_durable", durable)
    write_signal_rows(client, *rows(3, "unfinished", text))
    assert read_signal_pages(client, "dataset", ["file"])[0][("file", "raw_text", 1)][0] == "unfinished"


def test_activity_reuses_regex_watermark_when_only_signal_scan_is_missing(storage, monkeypatch):
    from tasks.P3_parse_files.parse_common import insert_text_pages
    from tasks.P4_extract_entities import scan_regex_entities as activity
    from tasks.P4_extract_entities.params import ScanRegexEntitiesParams
    name, client, cluster, folder = storage
    migrate(client, cluster, folder)
    monkeypatch.setenv("REGEX_SCANNER_URL", "http://127.0.0.1:19705")
    text = "We will pay a kickback and offer a bribe."
    insert_text_pages(name, "dataset", "file", "raw_text", [(1, text)])
    params = ScanRegexEntitiesParams(name, "dataset", "plan", ["file"])
    assert activity.scan_regex_entities_for_hashes(params).text_segments == 1
    marks, hits = read_signal_pages(client, "dataset", ["file"])
    assert marks and hits
    assert activity.scan_regex_entities_for_hashes(params).text_segments == 0
    client.command("TRUNCATE TABLE signal_scanned")
    routes = []
    scan = activity.scan_batches

    def observe(texts, route, *args, **kwargs):
        if texts:
            routes.append(route)
        return scan(texts, route, *args, **kwargs)

    monkeypatch.setattr(activity, "scan_batches", observe)
    assert activity.scan_regex_entities_for_hashes(params).text_segments == 1
    assert routes == ["/signal_batch"]
    assert read_signal_pages(client, "dataset", ["file"])[0]
