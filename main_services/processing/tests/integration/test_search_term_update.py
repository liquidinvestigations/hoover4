"""Verify filter-term publication and recovery across both datastores."""

import json

import pytest

from database import clickhouse, manticore
from tasks.P6_index_data.activities import entity_term_row_id, index_entity_terms
from tasks.P6_index_data.params import BuildVfsNodesParams
from tasks.P_admin.updates import registry, selectors
from .test_archive_and_index_publication import search_collection
from .test_table_publication_receipts import collection

pytestmark = pytest.mark.integration


def test_historical_terms_publish_verify_and_repair(search_collection):
    name = search_collection
    ctx = selectors.ScopeContext("dataset", "dataset", name)
    fields = ("language", "ocr_language", "ocr_script", "red_flags")
    rows = [["dataset", fields[index % 4], index + 1, f"value-{index}"] for index in range(507)]
    with clickhouse.get_collection_client(name) as client:
        clickhouse.insert_durable(client, "string_term_id_to_text", rows,
            column_names=["collection_dataset", "term_field", "term_id", "term_value"])
        assert selectors.select_search_terms(ctx).count == 1
        assert selectors.missing_search_terms(client, ctx) == 507
        assert index_entity_terms(BuildVfsNodesParams(name, "dataset")) == "507 terms"
        assert selectors.missing_search_terms(client, ctx) == 0
        with manticore.get_manticore_client() as connection:
            connection.cursor().execute(
                f"DELETE FROM {name}_entities WHERE id = {entity_term_row_id('language', 1)}")
            connection.commit()
        assert selectors.missing_search_terms(client, ctx) == 1
        index_entity_terms(BuildVfsNodesParams(name, "dataset"))
        assert selectors.missing_search_terms(client, ctx) == 0
    ctx.applied = {"search_terms": {"detail": json.dumps({
        "version": registry.step_version(registry.STEPS_BY_ID["search_terms"])})}}
    assert selectors.select_search_terms(ctx).count == 0
    ctx.applied["search_terms"]["detail"] = '{"version":"older"}'
    assert selectors.select_search_terms(ctx).count == 1
