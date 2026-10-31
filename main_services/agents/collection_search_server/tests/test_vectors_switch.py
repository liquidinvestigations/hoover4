"""Tests for the collection switch `features.vectors` in vector search."""

from collection_search_server import vectors


def _rows(monkeypatch, rows):
    queries = []

    def fake_query(sql, database=None, params=None):
        queries.append((sql, params))
        return rows

    monkeypatch.setattr(vectors, "clickhouse_query", fake_query)
    return queries


def test_only_a_false_row_turns_vectors_off(monkeypatch):
    queries = _rows(monkeypatch, [
        {"c": "off_col", "v": "false", "d": 0},
        {"c": "on_col", "v": "true", "d": 0},
        {"c": "reset_col", "v": "false", "d": 1},
        {"c": "other_col", "v": "false", "d": 0},
    ])
    off = vectors.vectors_off_collections(["off_col", "on_col", "reset_col", "plain_col"])
    assert off == {"off_col"}
    assert queries[0][1] == {"k": "features.vectors"}


def test_no_collections_reads_nothing(monkeypatch):
    queries = _rows(monkeypatch, [])
    assert vectors.vectors_off_collections([]) == set()
    assert queries == []


def test_search_skips_a_switched_off_collection(monkeypatch):
    monkeypatch.setattr(vectors, "_existing_tables", lambda: {"s1_vectors"})
    monkeypatch.setattr(vectors, "vectors_off_collections", lambda cols: {"off_col"})
    asked = []

    def tables(collectionname, existing):
        asked.append(collectionname)
        return []

    monkeypatch.setattr(vectors, "_vector_tables", tables)
    assert vectors.search([0.1, 0.2], ["off_col", "on_col"]) == []
    assert asked == ["on_col"]
