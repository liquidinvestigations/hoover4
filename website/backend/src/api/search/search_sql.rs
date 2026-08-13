//! SQL builder helpers for search queries.
//!
//! Search data is sharded per collection: logical shard `<collectionname>_<n>` (n is
//! 1-based) consists of two physical Manticore tables, `<shard>_pages` and
//! `<shard>_meta`. There are no global search tables and no distributed tables
//! (Manticore 14.1.0 cannot JOIN over them), so every search query is built
//! once per shard with the table names substituted and fanned out (see `fanout.rs`).
//!
//! Table and field names are interpolated into SQL strings and cannot be bound
//! parameters, so both are validated here: shard names against
//! [`collectionname_valid`] plus a numeric suffix, field names against a whitelist.

use anyhow::Context;
use common::{
    search_query::{DATE_UNKNOWN, RangeFilter, SearchQuery, SortKey, SortSpec},
    search_result::FacetOriginalValue,
};

use crate::api::admin::collections::collectionname_valid;
use crate::db_utils::manticore_match::prepare_match_query;

/// `extracted_by` of the synthetic pages row that carries a document's filenames.
///
/// It exists so a query for a filename finds the document, and it is a row in the pages
/// table with `page_id = -1`. That makes it a landmine for every consumer that treats a
/// pages row as a real page: `page_id` is deserialised as `u32` in the document
/// endpoints, and a "N other matches" count that includes it is off by one on every
/// filename hit. Every such query excludes it with [`EXCLUDE_FILENAME_ROW`], and
/// `test_filename_row_excluded.py` enumerates the readers.
pub const FILENAME_INDEX_EXTRACTED_BY: &str = "filename_index";

/// Drop-in `AND` predicate excluding the filename row. See
/// [`FILENAME_INDEX_EXTRACTED_BY`].
pub const EXCLUDE_FILENAME_ROW: &str = "extracted_by != 'filename_index'";

/// Columns that live on the `<shard>_meta` table. Frontend-facing field names are
/// bare (`file_types`, never `<table>.file_types`); they are qualified with the
/// shard's meta table here so the reference is unambiguous inside the JOIN.
///
/// `filenames` and `metadata_values` are gone with the meta table's text fields (see
/// `database/manticore.py::meta_table_ddl`).
const META_TABLE_FIELDS: &[&str] = &[
    "file_types",
    "file_mime_types",
    "file_extensions",
    "file_paths",
    "dates",
    "date_min",
    "date_max",
    "file_size_bytes",
    "struct_flags",
    "primary_filename",
    "email_from",
    "email_to",
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

/// The `ORDER BY` column for one sort key, already qualified.
///
/// `Date` picks a different column per direction on purpose: a document has a SET of
/// dates, so "oldest first" is `min(dates)` ascending and "newest first" is
/// `max(dates)` descending. Sorting both directions on one end would put a document
/// spanning 1990..2020 in the wrong place for one of them.
///
/// `Relevance` is `weight()` and never a column, which is why this returns the whole
/// key expression rather than a name.
pub fn sort_column(sort: &SortSpec, meta_table: &str) -> String {
    match sort.key {
        SortKey::Relevance => "weight()".to_string(),
        SortKey::Date => {
            if sort.desc {
                format!("{meta_table}.date_max")
            } else {
                format!("{meta_table}.date_min")
            }
        }
        SortKey::FileSize => format!("{meta_table}.file_size_bytes"),
        SortKey::Name => format!("{meta_table}.primary_filename"),
    }
}

/// The full `ORDER BY` for a per-shard query.
///
/// The tie-break on `(collection_dataset, file_hash)` is load-bearing and must match
/// `fanout::merge_hits` exactly: Manticore's order among equal keys is not stable across
/// queries with different `LIMIT`, and `fetch_limit` grows with the requested page, so
/// without a total order a document tied at the truncation boundary appears on two pages
/// or on none.
pub fn sort_order_by(sort: &SortSpec, meta_table: &str) -> String {
    let column = sort_column(sort, meta_table);
    let direction = if sort.desc { "DESC" } else { "ASC" };
    format!("ORDER BY {column} {direction}, collection_dataset ASC, file_hash ASC")
}

/// A range predicate over one indexed field.
///
/// **Dates are an interval-overlap test, not `ANY(dates) BETWEEN`, and that is a
/// platform limit rather than a choice.** Manticore 14.1.0 cannot evaluate `ANY(mva)`
/// inside this query shape at all: qualified (`ANY(m.dates)`) is a parse error
/// (`unexpected SUBKEY`), unqualified resolves against the pages table and errors as an
/// unknown column, and table aliases are not accepted in the JOIN either. `ANY(dates)`
/// works only against `<shard>_meta` on its own — and the query cannot drop the JOIN,
/// because `MATCH` lives on the pages side. (The JOIN itself is forced by the same
/// version's inability to run this shape over distributed tables.)
///
/// So the predicate is `date_min <= hi AND date_max >= lo`: the document's date SPAN
/// overlaps the requested range. For the ordinary document — one date, or several within
/// a few days — this is exactly "any date in range". It differs only for a document whose
/// dates STRADDLE the range with none inside it: a file created in 2007 and modified in
/// 2020 matches a 2013–2016 filter. The error is one-sided (a superset, never a subset),
/// which is the right direction for a search filter: a user can see and dismiss an extra
/// result, and cannot see one that was silently withheld. The viewer's Dates section
/// shows every date with its provenance, so the extra result explains itself.
///
/// The unknown sentinel is tested on `date_min` alone: an undated document has
/// `date_min = date_max = DATE_UNKNOWN`, which is below every real bound, so the overlap
/// test excludes it automatically.
fn range_predicate(
    field_name: &str,
    filter: &RangeFilter,
    meta_table: &str,
) -> anyhow::Result<Option<String>> {
    if !filter.is_active() {
        return Ok(None);
    }
    if filter.is_inverted() {
        anyhow::bail!(
            "range filter on {field_name:?} has min > max ({:?} > {:?})",
            filter.min,
            filter.max
        );
    }
    // Every bound is an i64 — see `RangeFilter`. Nothing here is user-supplied text.
    let (lo, hi) = (filter.min.unwrap_or(i64::MIN + 1), filter.max.unwrap_or(i64::MAX));
    let ranged = match field_name {
        // Interval overlap; see the doc comment for why this is not `ANY(dates)`.
        // The DATE_UNKNOWN sentinel is i64::MIN, so an undated document fails
        // `date_max >= lo` for every real `lo` and drops out here rather than needing
        // an extra clause.
        "dates" => Some(format!(
            "{meta_table}.date_min <= {hi} AND {meta_table}.date_max >= {lo}"
        )),
        "file_size_bytes" => {
            // A document with no vfs_files row carries SIZE_UNKNOWN (-1), which would
            // otherwise land inside any range whose lower bound is unset.
            let lo = lo.max(0);
            Some(format!("{meta_table}.file_size_bytes BETWEEN {lo} AND {hi}"))
        }
        other => anyhow::bail!("invalid range filter field: {other:?}"),
    };
    let unknown = match field_name {
        "dates" => format!("{meta_table}.date_min = {DATE_UNKNOWN}"),
        "file_size_bytes" => format!("{meta_table}.file_size_bytes < 0"),
        _ => unreachable!("field validated above"),
    };

    Ok(Some(match (filter.min.is_some() || filter.max.is_some(), filter.include_unknown) {
        (true, true) => format!("({} OR {unknown})", ranged.unwrap()),
        (true, false) => ranged.unwrap(),
        (false, true) => unknown,
        (false, false) => unreachable!("is_active() ruled this out"),
    }))
}

/// The `MATCH()` argument for one search, quoted and ready to interpolate.
///
/// An EMPTY query is `MATCH('')` on purpose: that is how the site browses a collection
/// with no search term, and Manticore reads it as "every row". Every non-empty query
/// goes through [`prepare_match_query`], which repairs the shapes the parser rejects and
/// returns an error for the two it cannot — never a string that 500s at Manticore.
fn match_argument(query_string: &str) -> anyhow::Result<String> {
    // automatically quote all @ symbols in the query string to avoid problems with FIELD SELECTOR manticore operator
    let query_string = query_string.trim().replace("@", "\\@");
    if query_string.is_empty() {
        return Ok("''".to_string());
    }
    // `Error::from`, not `anyhow!("{e}")`: the concrete `MatchQueryError` is what tells
    // the HTTP layer this is a malformed *request* rather than a failing server, and
    // re-wrapping it as a string throws that away and leaves only a 500.
    Ok(prepare_match_query(&query_string)
        .map_err(anyhow::Error::from)?
        .quoted())
}

pub fn build_sql_where_clause(
    query: &SearchQuery,
    pages_table: &str,
    meta_table: &str,
) -> anyhow::Result<String> {
    let mut terms = vec![format!(
        "
        WHERE MATCH({}, {pages_table})
    ",
        match_argument(&query.query_string)?
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

    for (field_name, filter) in query.active_range_filters() {
        if let Some(predicate) = range_predicate(field_name, filter, meta_table)? {
            terms.push(predicate);
        }
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
            query_string: query_string.to_string(),
            facet_filters,
            ..Default::default()
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
        // The escape pass then escapes the backslash itself, so the wire string is
        // `user\\@example.com`.
        let q = query("user@example.com", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages", "testdata_1_meta").unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('user\\\\@example.com', testdata_1_pages)");
    }

    #[test]
    fn where_clause_trims_and_quotes() {
        // A single quote is escaped with a BACKSLASH. Manticore's parser rejects the
        // SQL-standard doubling outright (`P01: syntax error`), so an assertion on the
        // doubled form passes in the test suite while every such search 500s in
        // production — which is exactly how this reached a live site.
        let q = query("  it's a test  ", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages", "testdata_1_meta").unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('it\\'s a test', testdata_1_pages)");
    }

    /// Every character measured against a live Manticore as breaking the query parser.
    /// These are searches a person types, not exotic input: `3/4`, `it's`, a quote left
    /// open mid-word.
    #[test]
    fn where_clause_repairs_the_query_syntax_manticore_rejects() {
        for (input, expected) in [
            ("3/4", "WHERE MATCH('3 4', testdata_1_pages)"),
            ("say\"hi", "WHERE MATCH('sayhi', testdata_1_pages)"),
            ("a~2", "WHERE MATCH('a 2', testdata_1_pages)"),
            ("(a | b", "WHERE MATCH('(a | b)', testdata_1_pages)"),
            ("computer", "WHERE MATCH('computer', testdata_1_pages)"),
        ] {
            let sql =
                build_sql_where_clause(&query(input, &[]), "testdata_1_pages", "testdata_1_meta")
                    .unwrap();
            assert_eq!(normalize(&sql), expected, "for {input:?}");
        }
    }

    /// A query made only of negations is `non-computable (single NOT operator)` at
    /// Manticore. Failing here turns that into a message in the search bar.
    #[test]
    fn where_clause_rejects_a_query_with_nothing_to_match() {
        assert!(
            build_sql_where_clause(&query("!a", &[]), "testdata_1_pages", "testdata_1_meta")
                .is_err()
        );
    }

    /// The empty query is how the site browses without a search term, and it must stay
    /// `MATCH('')` — every row — rather than becoming an error.
    #[test]
    fn where_clause_keeps_the_empty_query_matching_everything() {
        let sql =
            build_sql_where_clause(&query("   ", &[]), "testdata_1_pages", "testdata_1_meta")
                .unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('', testdata_1_pages)");
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
    /// list in `frontend/src/components/search_components/search_facets.rs`.
    #[test]
    fn qualify_field_name_accepts_every_frontend_facet_field() {
        for field in [
            "collection_dataset",
            "file_types",
            "file_mime_types",
            "file_extensions",
            "file_paths",
            "dates",
            "date_min",
            "date_max",
            "file_size_bytes",
            "struct_flags",
            "primary_filename",
            "email_from",
            "email_to",
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

    /// The dropped meta text columns must NOT come back through the whitelist: they no
    /// longer exist on the table, so a filter naming one is a Manticore error on every
    /// shard rather than an empty result.
    #[test]
    fn qualify_field_name_rejects_the_dropped_text_columns() {
        for gone in ["filenames", "metadata_values"] {
            assert!(qualify_field_name(gone, "testdata_1_meta").is_err(), "{gone} is gone");
        }
    }

    fn ranged(field: &str, filter: RangeFilter) -> String {
        let mut query = SearchQuery { query_string: "word".to_string(), ..Default::default() };
        query.range_filters.insert(field.to_string(), filter);
        normalize(&build_sql_where_clause(&query, "testdata_1_pages", "testdata_1_meta").unwrap())
    }

    /// The predicate is an interval-overlap test rather than `ANY(dates) BETWEEN`,
    /// because Manticore 14.1.0 cannot evaluate `ANY(mva)` across this JOIN in any
    /// spelling. See `range_predicate`'s doc comment; the substitution is deliberate and
    /// one-sided (a superset), and this pins the shape so it is not "fixed" back into
    /// something that 400s on every query.
    #[test]
    fn a_date_range_is_an_interval_overlap_over_the_scalar_bounds() {
        let sql = ranged("dates", RangeFilter { min: Some(1356998400), max: Some(1483228799), include_unknown: false });
        assert!(
            sql.contains(
                "AND testdata_1_meta.date_min <= 1483228799 AND testdata_1_meta.date_max >= 1356998400"
            ),
            "{sql}"
        );
        assert!(!sql.contains("ANY("), "ANY(mva) does not parse across the JOIN: {sql}");
    }

    #[test]
    fn an_undated_document_falls_out_of_every_range_without_an_extra_clause() {
        // DATE_UNKNOWN is i64::MIN, so `date_max >= lo` is false for every real lo.
        assert!(DATE_UNKNOWN < 0);
        let sql = ranged("dates", RangeFilter { min: Some(0), max: Some(i64::MAX), include_unknown: false });
        assert!(sql.contains("date_max >= 0"), "{sql}");
    }

    #[test]
    fn date_unknown_is_tested_on_the_scalar_not_the_mva() {
        // An undated document's `dates` is EMPTY, so no MVA predicate can reach it.
        let sql = ranged("dates", RangeFilter { min: None, max: None, include_unknown: true });
        assert!(sql.contains(&format!("AND testdata_1_meta.date_min = {DATE_UNKNOWN}")), "{sql}");
        assert!(!sql.contains("ANY("), "unknown-only must not emit an MVA predicate: {sql}");
    }

    #[test]
    fn a_range_plus_unknown_is_a_disjunction() {
        let sql = ranged("dates", RangeFilter { min: Some(0), max: Some(100), include_unknown: true });
        assert!(
            sql.contains(&format!(
                "AND (testdata_1_meta.date_min <= 100 AND testdata_1_meta.date_max >= 0                  OR testdata_1_meta.date_min = {DATE_UNKNOWN})"
            ).replace("                 ", "")),
            "{sql}"
        );
    }

    #[test]
    fn an_open_ended_size_range_still_excludes_the_unknown_sentinel() {
        // SIZE_UNKNOWN is -1. Without the clamp, "under 1 MB" would sweep up every
        // document that has no vfs_files row.
        let sql = ranged("file_size_bytes", RangeFilter { min: None, max: Some(1048575), include_unknown: false });
        assert!(sql.contains("AND testdata_1_meta.file_size_bytes BETWEEN 0 AND 1048575"), "{sql}");
    }

    #[test]
    fn an_inverted_range_is_an_error_not_an_empty_filter() {
        let mut query = SearchQuery { query_string: "word".to_string(), ..Default::default() };
        query.range_filters.insert(
            "dates".to_string(),
            RangeFilter { min: Some(100), max: Some(1), include_unknown: false },
        );
        assert!(build_sql_where_clause(&query, "testdata_1_pages", "testdata_1_meta").is_err());
    }

    #[test]
    fn an_inactive_range_filter_adds_no_predicate() {
        let sql = ranged("dates", RangeFilter::default());
        assert_eq!(sql, "WHERE MATCH('word', testdata_1_pages)");
    }

    #[test]
    fn an_unknown_range_field_is_rejected() {
        let mut query = SearchQuery { query_string: "word".to_string(), ..Default::default() };
        query.range_filters.insert(
            "page_text".to_string(),
            RangeFilter { min: Some(1), ..Default::default() },
        );
        assert!(build_sql_where_clause(&query, "testdata_1_pages", "testdata_1_meta").is_err());
    }

    #[test]
    fn sort_columns_are_whitelisted_and_direction_aware() {
        let cases = [
            (SortKey::Relevance, true, "weight()"),
            (SortKey::Relevance, false, "weight()"),
            (SortKey::Date, true, "testdata_1_meta.date_max"),
            (SortKey::Date, false, "testdata_1_meta.date_min"),
            (SortKey::FileSize, true, "testdata_1_meta.file_size_bytes"),
            (SortKey::Name, false, "testdata_1_meta.primary_filename"),
        ];
        for (key, desc, expected) in cases {
            assert_eq!(sort_column(&SortSpec { key, desc }, "testdata_1_meta"), expected);
        }
    }

    #[test]
    fn sort_order_by_keeps_the_stable_tie_break() {
        assert_eq!(
            sort_order_by(&SortSpec { key: SortKey::Name, desc: false }, "testdata_1_meta"),
            "ORDER BY testdata_1_meta.primary_filename ASC, collection_dataset ASC, file_hash ASC"
        );
        assert_eq!(
            sort_order_by(&SortSpec { key: SortKey::FileSize, desc: true }, "testdata_1_meta"),
            "ORDER BY testdata_1_meta.file_size_bytes DESC, collection_dataset ASC, file_hash ASC"
        );
    }

    /// A query the parser cannot be given is the CALLER's mistake, and the classification
    /// has to survive the trip out of the SQL builder for the endpoint to say so.
    ///
    /// It is carried by the error's TYPE. Restating it as `anyhow!("{e}")` anywhere along
    /// the way leaves a bare string, every such query is reported as a 500, and a rejected
    /// keystroke reads as the site falling over — while the telemetry counts it as
    /// breakage.
    #[test]
    fn a_query_with_only_negations_is_a_bad_request_all_the_way_out() {
        let query = SearchQuery { query_string: "!a".to_string(), ..Default::default() };
        let error = build_sql_where_clause(&query, "testdata_1_pages", "testdata_1_meta")
            .expect_err("a negation-only query has no MATCH() argument");
        assert!(
            crate::auth::guard::is_bad_request(&error),
            "classified as a server failure instead: {error:#}"
        );
        assert!(
            error.to_string().contains("Add at least one word to search for"),
            "and the advice the reader sees must survive too: {error}"
        );
    }
}
