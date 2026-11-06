"""PDF rows on part boundaries, cuts at white space, and the per-source work limit."""

from types import SimpleNamespace

from tasks.P3_parse_files import parse_common as common
from tasks.P_admin.updates.text_rows import split_again
from tasks import text_sources


def test_a_pdf_row_holds_each_part_and_starts_at_its_first_page():
    pages = [(page, f"text {page}") for page in range(1, 6)]
    rows = common.pdf_text_rows(pages, [(1, 3), (4, 5)])
    assert rows == [(1, "text 1\ftext 2\ftext 3"), (4, "text 4\ftext 5")]


def test_an_empty_page_keeps_its_place_at_the_start_of_a_row():
    rows = common.pdf_text_rows([(3, "third page")], [(1, 4)])
    assert rows == [(1, "\f\fthird page")]
    assert common.stored_page_bodies(rows) == rows


def test_a_part_without_text_has_no_row():
    assert common.pdf_text_rows([(1, "first"), (3, " ")], [(1, 2), (3, 4)]) == [(1, "first")]


def test_a_part_over_the_ceiling_splits_at_a_page_and_keeps_the_page_number():
    pages = [(page, "x" * 60) for page in range(1, 5)]
    rows = common.pdf_text_rows(pages, [(1, 4)], max_bytes=130)
    assert [page for page, _ in rows] == [1, 3]
    assert rows[1][1].count(common.PAGE_BREAK) == 1


def test_a_form_feed_inside_page_text_does_not_shift_page_numbers():
    assert common.pdf_text_rows([(1, "a\fb")], [(1, 2)]) == [(1, "a b")]


def test_segments_cut_at_white_space_and_repeat_the_end_of_the_one_before():
    words = " ".join(f"word{number}" for number in range(4000))
    segments = common.split_text_segments(words, max_bytes=4096)
    assert all(len(segment.encode()) <= 4096 for segment in segments)
    for before, after in zip(segments, segments[1:]):
        assert before.rstrip().rsplit(" ", 1)[-1].startswith("word")
        first = after.split(" ", 1)[0]
        assert f" {first} " in f" {before} "
    assert all(f"word{number}" in " ".join(segments) for number in range(0, 4000, 97))


def test_a_name_on_the_cut_is_whole_in_one_segment():
    text = "a " * 2047 + "john smith " + "b " * 2047
    segments = common.split_text_segments(text, max_bytes=4096)
    assert any("john smith" in segment for segment in segments)


def test_a_cut_does_not_remove_a_multibyte_letter():
    text = "א" * 3000
    segments = common.split_text_segments(text, max_bytes=4096)
    assert "".join(segments).count("א") >= 3000
    assert all("�" not in segment for segment in segments)


def test_text_without_white_space_still_advances():
    assert len(common.split_text_segments("x" * 10000, max_bytes=4096)) >= 3


def test_short_text_is_one_segment():
    assert common.text_chunk_pages("short text") == [(1, "short text")]


def test_unpaged_rows_join_before_the_new_cut():
    rows = [(1, "first "), (2, "second")]
    assert split_again(None, "ds", "h", "raw_text", rows) == [(1, "first second")]


def test_a_pdf_source_without_a_manifest_gets_rows_of_100_pages(monkeypatch):
    from tasks.P3_parse_files import pdf_parts

    monkeypatch.setattr(pdf_parts, "source_parts", lambda *a: [])
    rows = split_again(None, "ds", "h", "pdftotext", [(1, "first"), (150, "second")])
    assert [page for page, _ in rows] == [1, 101]


def test_the_work_limit_asks_for_pages_past_the_limit():
    seen = {}

    def query(sql, parameters):
        seen.update(parameters)
        return SimpleNamespace(result_rows=[("h", "raw_text", 300)])

    keys = text_sources.pages_over_work_limit(SimpleNamespace(query=query), "ds", ["h"])
    assert keys == {("h", "raw_text", 300)}
    assert seen["limit"] == 75_000_000
    assert text_sources.pages_over_work_limit(None, "ds", []) == set()


def test_a_batch_of_an_entity_update_leaves_the_dataset_terms_to_the_end(monkeypatch):
    from contextlib import nullcontext

    import database.clickhouse as clickhouse
    from tasks.P6_index_data import activities as index
    from tasks.P_admin.updates import entities

    deleted, published = [], []
    client = SimpleNamespace(
        command=lambda *a, **k: deleted.append(a),
        query=lambda *a, **k: SimpleNamespace(result_rows=[("h", "shard")]),
    )
    monkeypatch.setattr(clickhouse, "get_collection_client", lambda _name: nullcontext(client))
    monkeypatch.setattr(clickhouse, "insert_durable", lambda *a, **k: None)
    monkeypatch.setattr(entities, "completions", lambda *a: [])
    monkeypatch.setattr(entities, "rewrite_ner_attributes", lambda *a: None)
    monkeypatch.setattr(entities, "verify_index", lambda *a: None)
    monkeypatch.setattr(entities, "contract", lambda: "c")
    monkeypatch.setattr(index, "index_entity_terms", lambda params: published.append(params))
    params = entities.EntityUpdateParams("c", "ds", "op", ["h"], terms_at_end=True)
    entities.finish_entity_update.__wrapped__(params)
    assert deleted == [] and published == []
    entities.finish_entity_terms.__wrapped__(params)
    assert len(deleted) == 2 and len(published) == 1
