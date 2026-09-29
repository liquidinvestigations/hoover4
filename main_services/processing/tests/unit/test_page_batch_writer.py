"""The page writer retains only one batch of cleaned text."""

from contextlib import contextmanager

from database import manticore
from tasks.P6_index_data import activities as pages
from tasks.P6_index_data.params import IndexShardParams
from tasks.text_sources import plan_text_batches


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def to_pylist(self):
        return self.rows


def test_page_rows_flush_before_the_next_text_batch(monkeypatch):
    texts = {
        ("a", "tika", 0): "aaaa",
        ("a", "tika", 1): "bbbb",
        ("b", "tika", 0): "cccc",
        ("c", "tika", 0): "dddd",
    }
    segments = [dict(file_hash=file_hash, extracted_by=source, page_id=page_id,
                     text_bytes=len(value))
                for (file_hash, source, page_id), value in reversed(list(texts.items()))]
    written = []
    retained_text = []
    commits = []

    class _Collection:
        def query_arrow(self, sql, _parameters):
            if "FROM text_content FINAL" in sql:
                return _Rows(segments)
            return _Rows([])

    class _Search:
        def commit(self):
            commits.append(len(written))

    @contextmanager
    def collection(_name):
        yield _Collection()

    @contextmanager
    def search():
        yield _Search()

    def fetch(_client, dataset, batch):
        return [dict(collection_dataset=dataset, file_hash=key[0],
                     extracted_by=key[1], page_id=key[2], text=texts[key])
                for key in reversed(batch)]

    original_chunks = pages.chunks

    def measured_chunks(rows, limit):
        retained_text.append(sum(len(row["page_text"].encode()) for row in rows))
        yield from original_chunks(rows, limit)

    monkeypatch.setattr(pages, "get_collection_client", collection)
    monkeypatch.setattr(manticore, "get_manticore_client", search)
    monkeypatch.setattr(pages, "document_metadata", lambda _params: {
        file_hash: {**pages.empty_document_metadata(), "basenames": [f"{file_hash}.txt"]}
        for file_hash in ("a", "b", "c", "empty")})
    monkeypatch.setattr(pages, "get_string_term_ids", lambda *_args: {})
    monkeypatch.setattr(pages, "fetch_text_batch", fetch)
    monkeypatch.setattr(pages, "plan_text_batches",
                        lambda keys: plan_text_batches(keys, max_bytes=5))
    monkeypatch.setattr(pages, "pages_replace_sql", lambda _table, row: row)
    monkeypatch.setattr(pages, "pages_replace_params", lambda _dataset, row: row)
    monkeypatch.setattr(pages, "manticore_execute",
                        lambda _client, row, _params: written.append(dict(row)))
    monkeypatch.setattr(pages, "chunks", measured_chunks)

    result = pages.index_text_pages(IndexShardParams(
        "sample", "sample_data", "plan", "sample_1", ["a", "b", "c", "empty"]))

    assert result == ["a", "b", "c", "empty"]
    assert [(row["file_hash"], row["page_id"]) for row in written] == [
        ("a", -1), ("a", 0), ("a", 1), ("b", -1), ("b", 0),
        ("c", -1), ("c", 0), ("empty", -1)]
    assert len(commits) == 5
    assert max(retained_text) <= 4 + len("empty.txt")
