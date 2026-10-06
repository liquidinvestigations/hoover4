"""Verify page transactions against both MySQL connector implementations."""

from contextlib import closing
import os

import mysql.connector
import pytest

from database.manticore import bind_manticore_sql, manticore_execute, pages_table_ddl
from tasks.P6_index_data.activities import (
    empty_document_metadata,
    pages_replace_params,
    pages_replace_sql,
    write_page_batches,
)


pytestmark = [pytest.mark.integration, pytest.mark.timeout(300)]
TABLE = "it_page_batches_probe"
SINGLE_TABLE = "it_page_single_probe"
DATASET = "it_page_batches"


def connection(use_pure):
    if not use_pure and not mysql.connector.HAVE_CEXT:
        pytest.skip("Connector C extension is unavailable in this process")
    return mysql.connector.connect(
        host=os.getenv("MANTICORE_HOST", "manticore"), port=9306,
        user="manticore", password="manticore", database="Manticore",
        use_pure=use_pure, connection_timeout=10, read_timeout=180, write_timeout=180,
    )


def query(cnx, sql):
    cursor = cnx.cursor()
    cursor.execute(sql)
    return cursor.fetchall()


def row(page_id, text):
    result = empty_document_metadata()
    result.update(
        collection_dataset=DATASET, file_hash="same-file", extracted_by="tika",
        page_id=page_id, page_text=text, primary_filename="test.txt",
        file_types="(21)", dates="(-3786825600)", language="(22)", red_flags="(23)",
    )
    return result


def status(cnx):
    return dict(query(cnx, f"SHOW TABLE {TABLE} STATUS"))


def command_commits(cnx):
    return int(dict(query(cnx, "SHOW STATUS"))["command_commit"])


@pytest.fixture()
def probe_table():
    with closing(connection(True)) as cnx:
        for table in (TABLE, SINGLE_TABLE):
            query(cnx, f"DROP TABLE IF EXISTS {table}")
            query(cnx, pages_table_ddl(table))
    yield
    with closing(connection(True)) as cnx:
        for table in (TABLE, SINGLE_TABLE):
            query(cnx, f"DROP TABLE IF EXISTS {table}")


@pytest.mark.parametrize("use_pure", [False, True], ids=["c-extension", "pure-python"])
def test_page_batch_visibility_rollback_and_commit(probe_table, use_pure):
    first = row(1, "delimiter ''' with a quote and %s")
    second = row(2, "a second page with a date facet")
    with closing(connection(use_pure)) as writer, closing(connection(use_pure)) as reader:
        before = int(status(writer)["tid"])
        commits_before = command_commits(writer)
        statement = bind_manticore_sql(
            writer, pages_replace_sql(TABLE, first), pages_replace_params(DATASET, first),
        )
        writer.cmd_query(b"BEGIN")
        writer.cmd_query(statement)
        assert query(reader, f"SELECT id FROM {TABLE} LIMIT 10") == []
        writer.cmd_query(b"ROLLBACK")
        assert query(reader, f"SELECT id FROM {TABLE} LIMIT 10") == []
        assert int(status(writer)["tid"]) == before

        write_page_batches(writer, TABLE, DATASET, [first, second])
        stored = query(reader, f"SELECT page_id, page_text, file_types, dates FROM {TABLE} LIMIT 10")
        assert sorted((int(page), text) for page, text, *_ in stored) == [
            (1, first["page_text"]), (2, second["page_text"]),
        ]
        assert all(str(facets) == "21" or facets == (21,) for _, _, facets, _ in stored)
        assert int(status(writer)["tid"]) == before + 1
        assert command_commits(writer) >= commits_before + 1

        write_page_batches(writer, TABLE, DATASET, [first, second])
        assert len(query(reader, f"SELECT id FROM {TABLE} LIMIT 10")) == 2
        assert query(reader, f"SELECT COUNT(DISTINCT file_hash) FROM {TABLE} WHERE ANY(language) IN (22) AND ANY(red_flags) IN (23)") == [(1,)]
        assert int(status(writer)["tid"]) == before + 2
        assert command_commits(writer) >= commits_before + 2


def test_batch_matches_single_row_writer(probe_table):
    rows = [
        row(-1, "test.txt"),
        row(1, "delimiter ''' and literal %s"),
        row(2, "A second page with a quoted ' name"),
    ]
    rows[0]["extracted_by"] = "filename_index"
    with closing(connection(True)) as writer:
        write_page_batches(writer, TABLE, DATASET, rows)
        for item in rows:
            manticore_execute(
                writer, pages_replace_sql(SINGLE_TABLE, item),
                pages_replace_params(DATASET, item),
            )
            writer.commit()
    with closing(connection(True)) as reader:
        columns = "id, page_id, page_text, file_types, dates, primary_filename"
        batched = query(reader, f"SELECT {columns} FROM {TABLE} LIMIT 10")
        single = query(reader, f"SELECT {columns} FROM {SINGLE_TABLE} LIMIT 10")
        assert sorted(batched) == sorted(single)
        assert len(batched) == len(rows)
        assert int(status(reader)["tid"]) == 1
        assert int(dict(query(reader, f"SHOW TABLE {SINGLE_TABLE} STATUS"))["tid"]) == len(rows)


def test_short_language_codes_use_attribute_lookup_without_infix_matching():
    from database.manticore import entities_table_ddl
    table = "it_signal_terms_probe"
    with closing(connection(True)) as client:
        query(client, f"DROP TABLE IF EXISTS {table}")
        try:
            query(client, entities_table_ddl(table))
            cursor = client.cursor()
            cursor.execute(f"INSERT INTO {table} (id, term_field, term_text, term_display, term_id, collection_dataset) "
                           "VALUES (1, %s, %s, %s, 22, 'dataset')", ("language", "hu", "hu"))
            rows = query(client, f"SELECT term_display, term_id, HIGHLIGHT({{limit=120}}, term_text) AS highlight "
                                 f"FROM {table} WHERE term_display IN ('hu') AND term_field IN ('language') LIMIT 200")
            assert len(rows) == 1 and rows[0][0] == "hu" and rows[0][1] == 22
        finally:
            query(client, f"DROP TABLE IF EXISTS {table}")
