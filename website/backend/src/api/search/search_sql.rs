//! SQL builder helpers for search queries.
//!
//! Search data is sharded per collection: logical shard `<collectionname>_<n>` (n is
//! 1-based) consists of two physical Manticore tables, `<shard>_pages` and
//! `<shard>_meta`. There are no global search tables and no distributed tables
//! (Manticore 14.1.0 cannot JOIN over them — see
//! `plans/2-collections/2-spike-manticore-results.md`), so every search query is built
//! once per shard with the table names substituted and fanned out (see `fanout.rs`).
//!
//! Table and field names are interpolated into SQL strings and cannot be bound
//! parameters, so both are validated here: shard names against
//! [`collectionname_valid`] plus a numeric suffix, field names against a whitelist.

use anyhow::Context;
use common::{search_query::SearchQuery, search_result::FacetOriginalValue};

use crate::api::admin::collections::collectionname_valid;

/// Columns that live on the `<shard>_meta` table. Frontend-facing field names are
/// bare (`file_types`, never `<table>.file_types`); they are qualified with the
/// shard's meta table here so the reference is unambiguous inside the JOIN.
const META_TABLE_FIELDS: &[&str] = &[
    "file_types",
    "file_mime_types",
    "file_extensions",
    "file_paths",
    "filenames",
    "metadata_values",
];

/// Columns allowed to appear unqualified: pages-only attributes, plus the two
/// columns present on both tables of the JOIN (`collection_dataset`, `file_hash`).
/// Manticore 14.1.0 resolves the ambiguous ones — the pre-shard queries already
/// relied on that behaviour against the retired global tables.
const UNQUALIFIED_FIELDS: &[&str] = &[
    "collection_dataset",
    "file_hash",
    "extracted_by",
    "page_id",
    "page_text",
    "ner_per",
    "ner_org",
    "ner_loc",
    "ner_misc",
];

/// Validate a logical shard name `<collectionname>_<n>` and return its two physical
/// table names, `(<shard>_pages, <shard>_meta)`.
///
/// Shard names reach this crate from the `manticore_shards` ledger and from the
/// search fan-out — never from user input — but they end up interpolated into SQL,
/// so re-validate anyway.
pub fn shard_table_names(shard_name: &str) -> anyhow::Result<(String, String)> {
    let (collectionname, index) = shard_name
        .rsplit_once('_')
        .with_context(|| format!("invalid shard name: {shard_name:?}"))?;
    if index.is_empty() || !index.chars().all(|c| c.is_ascii_digit()) {
        anyhow::bail!("invalid shard name: {shard_name:?} (suffix must be digits)");
    }
    if !collectionname_valid(collectionname) {
        anyhow::bail!("invalid shard name: {shard_name:?} (bad collectionname)");
    }
    Ok((format!("{shard_name}_pages"), format!("{shard_name}_meta")))
}

/// FROM clause joining one shard's pages and meta tables.
pub fn sql_from_clause(shard_name: &str) -> anyhow::Result<String> {
    let (pages, meta) = shard_table_names(shard_name)?;
    Ok(format!(
        "
    FROM {pages}
    LEFT JOIN {meta}
    ON {pages}.collection_dataset = {meta}.collection_dataset
    AND {pages}.file_hash = {meta}.file_hash
"
    ))
}

/// Qualify a frontend-facing field name for use in a per-shard query.
///
/// Meta-table columns become `<meta>.<field>`; pages/shared columns pass through
/// unqualified. Anything else is rejected — facet field names arrive over the wire
/// and are interpolated into SQL, so a whitelist is the only safe option.
pub fn qualify_field_name(field_name: &str, meta_table: &str) -> anyhow::Result<String> {
    if META_TABLE_FIELDS.contains(&field_name) {
        return Ok(format!("{meta_table}.{field_name}"));
    }
    if UNQUALIFIED_FIELDS.contains(&field_name) {
        return Ok(field_name.to_string());
    }
    anyhow::bail!("invalid search field name: {field_name:?}");
}

/// Timeout options for every search query. `max_matches` must cover the rows the
/// caller wants back: Manticore silently caps result sets at `max_matches`
/// (default 1000), which would corrupt deep pagination and large facet merges.
pub fn sql_options_clause(max_matches: u64) -> String {
    format!("OPTION agent_query_timeout=60000,max_query_time=60000,max_matches={max_matches}")
}

pub fn build_sql_where_clause(
    query: &SearchQuery,
    pages_table: &str,
    meta_table: &str,
) -> anyhow::Result<String> {
    // automatically quote all @ symbols in the query string to avoid problems with FIELD SELECTOR manticore operator
    let query_string = query.query_string.clone().trim().replace("@", "\\@");

    let mut terms = vec![format!(
        "
        WHERE MATCH({}, {pages_table})
    ",
        format_sql_query::QuotedData(&query_string)
    )];

    for (field_name, values) in query.facet_filters.iter() {
        let field_name = qualify_field_name(field_name, meta_table)?;
        let values_str = values
            .iter()
            .map(|value| match value {
                FacetOriginalValue::String(s) => format_sql_query::QuotedData(s).to_string(),
                FacetOriginalValue::Int(i) => i.to_string(),
            })
            .collect::<Vec<String>>()
            .join(", ");
        terms.push(format!("{field_name} IN ({values_str})",));
    }

    Ok(terms.join(
        "
        AND ",
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::search_result::FacetOriginalValue;
    use std::collections::{BTreeMap, BTreeSet};

    fn query(query_string: &str, filters: &[(&str, &[FacetOriginalValue])]) -> SearchQuery {
        let mut facet_filters = BTreeMap::new();
        for (field, values) in filters {
            facet_filters.insert(field.to_string(), values.iter().cloned().collect::<BTreeSet<_>>());
        }
        SearchQuery {
            collection_datasets: vec![],
            query_string: query_string.to_string(),
            facet_filters,
        }
    }

    fn normalize(sql: &str) -> String {
        sql.split_whitespace().collect::<Vec<_>>().join(" ")
    }

    #[test]
    fn shard_table_names_valid() {
        assert_eq!(
            shard_table_names("testdata_1").unwrap(),
            ("testdata_1_pages".to_string(), "testdata_1_meta".to_string())
        );
        assert_eq!(
            shard_table_names("mycollection_12").unwrap(),
            ("mycollection_12_pages".to_string(), "mycollection_12_meta".to_string())
        );
    }

    #[test]
    fn shard_table_names_rejects_invalid() {
        for bad in [
            "testdata",              // no shard index
            "testdata_",             // empty index
            "testdata_x",            // non-digit index
            "bad name_1",            // invalid collectionname
            "a; DROP TABLE x_1",     // injection attempt
            "testdata_1_pages",      // reserved suffix -> invalid collectionname
            "_1",                    // empty collectionname
        ] {
            assert!(shard_table_names(bad).is_err(), "should reject {bad:?}");
        }
    }

    #[test]
    fn sql_from_clause_golden() {
        assert_eq!(
            normalize(&sql_from_clause("testdata_2").unwrap()),
            normalize("
                FROM testdata_2_pages
                LEFT JOIN testdata_2_meta
                ON testdata_2_pages.collection_dataset = testdata_2_meta.collection_dataset
                AND testdata_2_pages.file_hash = testdata_2_meta.file_hash
            ")
        );
    }

    #[test]
    fn qualify_field_name_meta_and_pages() {
        assert_eq!(
            qualify_field_name("file_types", "testdata_1_meta").unwrap(),
            "testdata_1_meta.file_types"
        );
        assert_eq!(qualify_field_name("ner_per", "testdata_1_meta").unwrap(), "ner_per");
        assert_eq!(
            qualify_field_name("collection_dataset", "testdata_1_meta").unwrap(),
            "collection_dataset"
        );
    }

    #[test]
    fn qualify_field_name_rejects_unknown_and_injection() {
        for bad in ["no_such_field", "file_types); DROP TABLE x", "meta.file_types", "FILE_TYPES"] {
            assert!(qualify_field_name(bad, "testdata_1_meta").is_err(), "should reject {bad:?}");
        }
    }

    #[test]
    fn where_clause_plain_query_golden() {
        let q = query("hello world", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages", "testdata_1_meta").unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('hello world', testdata_1_pages)");
    }

    #[test]
    fn where_clause_escapes_at_field_selector() {
        // `@` is the Manticore field-selector operator; it must reach the query escaped.
        // format_sql_query additionally escapes the backslash itself, so the wire
        // string is `user\\@example.com`.
        let q = query("user@example.com", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages", "testdata_1_meta").unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('user\\\\@example.com', testdata_1_pages)");
    }

    #[test]
    fn where_clause_trims_and_quotes() {
        // Single quotes are escaped by doubling, per format_sql_query::QuotedData.
        let q = query("  it's a test  ", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages", "testdata_1_meta").unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('it''s a test', testdata_1_pages)");
    }

    #[test]
    fn where_clause_facet_filters() {
        let q = query(
            "word",
            &[
                ("collection_dataset", &[FacetOriginalValue::String("testdata_testfiles".to_string())]),
                ("file_types", &[FacetOriginalValue::Int(7), FacetOriginalValue::Int(9)]),
            ],
        );
        let sql = build_sql_where_clause(&q, "testdata_1_pages", "testdata_1_meta").unwrap();
        assert_eq!(
            normalize(&sql),
            "WHERE MATCH('word', testdata_1_pages) \
             AND collection_dataset IN ('testdata_testfiles') \
             AND testdata_1_meta.file_types IN (7, 9)"
        );
    }

    #[test]
    fn where_clause_rejects_bad_field_name() {
        let q = query("word", &[("evil_field", &[FacetOriginalValue::Int(1)])]);
        assert!(build_sql_where_clause(&q, "testdata_1_pages", "testdata_1_meta").is_err());
    }

    #[test]
    fn options_clause_includes_max_matches() {
        assert_eq!(
            sql_options_clause(42),
            "OPTION agent_query_timeout=60000,max_query_time=60000,max_matches=42"
        );
    }

    /// Every facet field the frontend can send must be accepted — a whitelist that
    /// drifts from its caller list is a runtime 500. Keep in sync with the facet
    /// list in `frontend/src/components/search_components/search_facets.rs`,
    /// INCLUDING the currently commented-out mime/extension/path facets (they are
    /// one uncomment away from being sent).
    #[test]
    fn qualify_field_name_accepts_every_frontend_facet_field() {
        for field in [
            "collection_dataset",
            "file_types",
            "file_mime_types",
            "file_extensions",
            "file_paths",
            "ner_per",
            "ner_org",
            "ner_loc",
            "ner_misc",
        ] {
            assert!(
                qualify_field_name(field, "testdata_1_meta").is_ok(),
                "frontend facet field {field:?} rejected by the whitelist"
            );
        }
    }
}
