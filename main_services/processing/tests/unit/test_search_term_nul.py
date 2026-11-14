"""Filter terms that hold a NUL byte must match their stored rows.

Manticore 29.9.0 ends a stored string attribute at a NUL byte. A measured `ab\\0cd` reads
back as `ab`. A term value with a NUL byte then never matched its stored row. The
`search_terms` step then failed with "1 filter terms remain absent or incorrect". The
`entities` step failed with "NER searchable terms are incomplete".
"""

import re
from contextlib import contextmanager

import pytest

import database.manticore as manticore
from database.manticore import stored_string
from tasks.P6_index_data.activities import entity_term_row_id
from tasks.P_admin.updates import selectors
from tasks.P_admin.updates.selectors import ScopeContext


def test_a_stored_string_holds_no_nul_byte():
    assert stored_string("ab\0cd") == "ab cd"
    assert stored_string("plain") == "plain"
    assert manticore.indexed_text("ab\0cd") == "ab cd"


class Terms:
    """ClickHouse terms, and a Manticore table that cuts each string at a NUL byte."""

    def __init__(self, terms, stored):
        self.terms = terms
        self.table = {entity_term_row_id("d", field, term_id): (field, term_id, value.partition("\0")[0])
                      for field, term_id, value in stored}

    def query(self, sql, parameters):
        after = (parameters["field"], parameters["id"])
        rows = [row for row in self.terms if (row[0], row[1]) > after][:500]
        return type("R", (), {"result_rows": rows})()

    def cursor(self):
        table = self.table

        class Cursor:
            def execute(self, sql):
                where = sql.split("WHERE", 1)[1].split("LIMIT", 1)[0]
                self.ids = [int(value) for value in re.findall(r"\d+", where)]
                self.with_id = sql.startswith("SELECT id,")

            def fetchall(self):
                return [((row_id,) if self.with_id else ()) + table[row_id]
                        for row_id in self.ids if row_id in table]
        return Cursor()


def run(monkeypatch, terms, stored, examples=None):
    source = Terms(terms, stored)

    @contextmanager
    def connection():
        yield source

    monkeypatch.setattr(manticore, "create_entities_table", lambda name: "c_entities")
    monkeypatch.setattr(manticore, "get_manticore_client", connection)
    return selectors.missing_search_terms(source, ScopeContext("dataset", "d", "c"), examples)


def test_a_term_written_without_its_nul_byte_is_current(monkeypatch):
    terms = [("ner", 7, "Acme\0Corp"), ("ner", 9, "Other")]
    written = [(field, term_id, stored_string(value)) for field, term_id, value in terms]
    assert run(monkeypatch, terms, written) == 0


def test_a_term_cut_at_its_nul_byte_is_named(monkeypatch):
    terms = [("ner", 7, "Acme\0Corp"), ("ner", 9, "Other")]
    examples = []
    assert run(monkeypatch, terms, terms, examples) == 1
    assert examples == ["ner term 7"]


def test_index_entity_terms_writes_the_stored_string(monkeypatch):
    from tasks.P6_index_data import activities
    from tasks.P6_index_data.params import BuildVfsNodesParams

    class Arrow:
        def to_pylist(self):
            return [{"term_field": "ner", "term_id": 7, "term_value": "Acme\0Corp"}]

    class Client:
        def query_arrow(self, sql, parameters):
            return Arrow()

        def cursor(self):
            class Cursor:
                def execute(self, sql, parameters=None):
                    pass

                def fetchall(self):
                    return []
            return Cursor()

        def commit(self):
            pass

    @contextmanager
    def client(*_):
        yield Client()

    written = []
    monkeypatch.setattr(activities, "get_collection_client", client)
    monkeypatch.setattr(manticore, "create_entities_table", lambda name: "c_entities")
    monkeypatch.setattr(manticore, "get_manticore_client", client)
    monkeypatch.setattr(activities, "manticore_execute", lambda cnx, sql, bound=(): written.append(bound))
    activities.index_entity_terms(BuildVfsNodesParams("c", "d"))
    assert written and "Acme Corp" in written[0] and not any("\0" in str(v) for v in written[0])


def test_the_entity_check_names_the_wrong_terms(monkeypatch):
    from tasks.P_admin.updates import entities

    def missing(client, ctx, examples):
        examples.append("ner term 7")
        return 1

    @contextmanager
    def client(_):
        yield None

    import database.clickhouse
    monkeypatch.setattr(database.clickhouse, "get_collection_client", client)
    monkeypatch.setattr(selectors, "missing_search_terms", missing)
    with pytest.raises(RuntimeError, match="1 terms are absent or incorrect, for example ner term 7"):
        entities.verify_terms(entities.EntityUpdateParams("c", "d"))
