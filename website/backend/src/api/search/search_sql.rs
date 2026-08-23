//! SQL builder helpers for search queries.
//!
//! Search data is sharded per collection: logical shard `<collectionname>_<n>` (n is
//! 1-based) is ONE physical Manticore table, `<shard>_pages`. There are no global
//! search tables and no distributed tables (Manticore 14.1.0 cannot run this query
//! shape over them), so every search query is built once per shard with the table name
//! substituted and fanned out (see `fanout.rs`).
//!
//! **The document's metadata is denormalized onto every one of its pages rows, and
//! there is no JOIN here. Do not reintroduce one.** A `LEFT JOIN` over a second
//! per-document table is a nested-loop lookup per left row (~9 µs) evaluated before any
//! predicate, so it costs the same whether the query matches everything or nothing: it
//! made an unfiltered entity facet on the largest shard take 13 s on its own and 100 s
//! under the four-pane concurrency of the Entities tab, which is an HTTP 504. It is
//! also silently WRONG. Manticore's `LEFT JOIN` drops left rows with no match, 0.28 %
//! of documents on the corpus it was measured against, so every facet count served
//! through it was short by that margin. The duplicated metadata costs ~15 % on disk
//! because the columnar engine picks a storage scheme per block and a block of pages
//! belonging to one document holds identical values.
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
use crate::db_utils::manticore_utils::search_timeout_ms;

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

/// Every column a query may name. One whitelist, because one shard is one table:
/// per-document metadata is denormalized onto the pages rows, so no name needs
/// qualifying and none is ambiguous.
///
/// Facet field names arrive over the wire and are interpolated into SQL, so the
/// whitelist is the only thing between a request and the query text, hence the
/// `&'static str` return: what reaches the SQL is this constant, never the caller's
/// string.
const SEARCH_FIELDS: &[&str] = &[
    "collection_dataset",
    "file_hash",
    "extracted_by",
    "page_id",
    "page_text",
    "ner_per",
    "ner_org",
    "ner_loc",
    "ner_misc",
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
    "re_email",
    "re_phone",
    "re_bank_account",
    "re_company_id",
    "re_money",
    "re_crypto_wallet",
    "mentioned_dates",
    "mentioned_date_min",
    "mentioned_date_max",
];

/// Validate a logical shard name `<collectionname>_<n>` and return its physical
/// table name, `<shard>_pages`.
///
/// Shard names reach this crate from the `manticore_shards` ledger and from the
/// search fan-out (never from user input), but they end up interpolated into SQL,
/// so re-validate anyway.
pub fn shard_table_name(shard_name: &str) -> anyhow::Result<String> {
    let (collectionname, index) = shard_name
        .rsplit_once('_')
        .with_context(|| format!("invalid shard name: {shard_name:?}"))?;
    if index.is_empty() || !index.chars().all(|c| c.is_ascii_digit()) {
        anyhow::bail!("invalid shard name: {shard_name:?} (suffix must be digits)");
    }
    if !collectionname_valid(collectionname) {
        anyhow::bail!("invalid shard name: {shard_name:?} (bad collectionname)");
    }
    Ok(format!("{shard_name}_pages"))
}

/// FROM clause for one shard. One table, no join, see the module doc.
pub fn sql_from_clause(shard_name: &str) -> anyhow::Result<String> {
    let pages = shard_table_name(shard_name)?;
    Ok(format!(
        "
    FROM {pages}
"
    ))
}

/// Check a frontend-facing field name against [`SEARCH_FIELDS`] and return the
/// whitelisted spelling. Anything else is rejected.
pub fn search_field_name(field_name: &str) -> anyhow::Result<&'static str> {
    SEARCH_FIELDS
        .iter()
        .find(|known| **known == field_name)
        .copied()
        .with_context(|| format!("invalid search field name: {field_name:?}"))
}

/// Timeout options for every search query, on every path.
///
/// `max_matches` must cover the rows the caller wants back: Manticore silently caps
/// result sets at `max_matches` (default 1000), which would corrupt deep pagination and
/// large facet merges.
///
/// The budget is [`search_timeout_ms`] and is uniform. The MVA facet path once emitted
/// no `OPTION` clause at all, which is how a query the proxy had already given up on
/// went on burning daemon CPU. `max_query_time` is Manticore's own best-effort limit and
/// does not cover a connect or read stall, so the client applies the same budget again
/// (`manticore_search_sql`); this half is what stops the server working on an abandoned
/// query.
pub fn sql_options_clause(max_matches: u64) -> String {
    let budget = search_timeout_ms();
    format!("OPTION agent_query_timeout={budget},max_query_time={budget},max_matches={max_matches}")
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
pub fn sort_column(sort: &SortSpec) -> &'static str {
    match sort.key {
        SortKey::Relevance => "weight()",
        SortKey::Date => {
            if sort.desc {
                "date_max"
            } else {
                "date_min"
            }
        }
        SortKey::FileSize => "file_size_bytes",
        SortKey::Name => "primary_filename",
    }
}

/// The full `ORDER BY` for a per-shard query.
///
/// The tie-break on `(collection_dataset, file_hash)` decides the order and must match
/// `fanout::merge_hits` exactly: Manticore's order among equal keys is not stable across
/// queries with different `LIMIT`, and `fetch_limit` grows with the requested page, so
/// without a total order a document tied at the truncation boundary appears on two pages
/// or on none.
pub fn sort_order_by(sort: &SortSpec) -> String {
    let column = sort_column(sort);
    let direction = if sort.desc { "DESC" } else { "ASC" };
    format!("ORDER BY {column} {direction}, collection_dataset ASC, file_hash ASC")
}

/// A range predicate over one indexed field.
///
/// **Dates are an interval-overlap test, not `ANY(dates) BETWEEN`.** The predicate is
/// the same shape the scalar bounds are stored for, and it is what every sort and every
/// histogram bin already reads, so the filter and the picture of it agree by
/// construction.
///
/// The predicate is `date_min <= hi AND date_max >= lo`: the document's date SPAN
/// overlaps the requested range. For the ordinary document (one date, or several within
/// a few days) this is exactly "any date in range". It differs only for a document whose
/// dates STRADDLE the range with none inside it: a file created in 2007 and modified in
/// 2020 matches a 2013–2016 filter. The error is one-sided (a superset, never a subset),
/// which is the right direction for a search filter: a user can see and dismiss an extra
/// result, and cannot see one that was silently withheld. The viewer's Dates section
/// shows every date with its provenance, so the extra result explains itself.
///
/// The unknown sentinel is tested on `date_min` alone: an undated document has
/// `date_min = date_max = DATE_UNKNOWN`, which is below every real bound, so the overlap
/// test excludes it automatically.
fn range_predicate(field_name: &str, filter: &RangeFilter) -> anyhow::Result<Option<String>> {
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
    // Every bound is an i64. See `RangeFilter`. Nothing here is user-supplied text.
    let (lo, hi) = (filter.min.unwrap_or(i64::MIN + 1), filter.max.unwrap_or(i64::MAX));
    let ranged = match field_name {
        // Interval overlap; see the doc comment for why this is not `ANY(dates)`.
        // The DATE_UNKNOWN sentinel is i64::MIN, so an undated document fails
        // `date_max >= lo` for every real `lo` and drops out here rather than needing
        // an extra clause.
        "dates" => Some(format!("date_min <= {hi} AND date_max >= {lo}")),
        // NOT the `dates` arm, and copying it here is the single most likely way to get
        // this feature wrong.
        //
        // A document's own dates are an interval it occupies: created in 1990, modified
        // in 2020, and every year between is a year the file existed in. The dates it
        // *mentions* are points. A document that names 1936 and 2020 occupies neither
        // 2005 nor anything between them, and interval overlap would match it for every
        // year in that span. `mentioned_dates` is an MVA, so `ANY(...)` asks the right
        // question: is any single mention inside the range.
        "mentioned_dates" => Some(format!("ANY(mentioned_dates) BETWEEN {lo} AND {hi}")),
        "file_size_bytes" => {
            // A document with no vfs_files row carries SIZE_UNKNOWN (-1), which would
            // otherwise land inside any range whose lower bound is unset.
            let lo = lo.max(0);
            Some(format!("file_size_bytes BETWEEN {lo} AND {hi}"))
        }
        other => anyhow::bail!("invalid range filter field: {other:?}"),
    };
    let unknown = match field_name {
        "dates" => format!("date_min = {DATE_UNKNOWN}"),
        "mentioned_dates" => format!("mentioned_date_min = {DATE_UNKNOWN}"),
        "file_size_bytes" => "file_size_bytes < 0".to_string(),
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
/// returns an error for the two it cannot, never a string that 500s at Manticore.
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

pub fn build_sql_where_clause(query: &SearchQuery, pages_table: &str) -> anyhow::Result<String> {
    let mut terms = vec![format!(
        "
        WHERE MATCH({}, {pages_table})
    ",
        match_argument(&query.query_string)?
    )];

    for (field_name, values) in query.facet_filters.iter() {
        let field_name = search_field_name(field_name)?;
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
        if let Some(predicate) = range_predicate(field_name, filter)? {
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
    fn shard_table_name_valid() {
        assert_eq!(shard_table_name("testdata_1").unwrap(), "testdata_1_pages");
        assert_eq!(shard_table_name("mycollection_12").unwrap(), "mycollection_12_pages");
    }

    #[test]
    fn shard_table_name_rejects_invalid() {
        for bad in [
            "testdata",              // no shard index
            "testdata_",             // empty index
            "testdata_x",            // non-digit index
            "bad name_1",            // invalid collectionname
            "a; DROP TABLE x_1",     // injection attempt
            "testdata_1_pages",      // reserved suffix -> invalid collectionname
            "_1",                    // empty collectionname
        ] {
            assert!(shard_table_name(bad).is_err(), "should reject {bad:?}");
        }
    }

    /// One table, no JOIN. The JOIN this replaced cost ~9 µs per left row before any
    /// predicate ran and dropped 0.28 % of documents; see the module doc.
    #[test]
    fn sql_from_clause_golden() {
        let from = sql_from_clause("testdata_2").unwrap();
        assert_eq!(normalize(&from), "FROM testdata_2_pages");
        assert!(!from.to_uppercase().contains("JOIN"), "{from}");
    }

    #[test]
    fn search_field_name_accepts_pages_and_document_columns() {
        assert_eq!(search_field_name("file_types").unwrap(), "file_types");
        assert_eq!(search_field_name("ner_per").unwrap(), "ner_per");
        assert_eq!(search_field_name("collection_dataset").unwrap(), "collection_dataset");
    }

    #[test]
    fn search_field_name_rejects_unknown_and_injection() {
        for bad in ["no_such_field", "file_types); DROP TABLE x", "meta.file_types", "FILE_TYPES"] {
            assert!(search_field_name(bad).is_err(), "should reject {bad:?}");
        }
    }

    #[test]
    fn where_clause_plain_query_golden() {
        let q = query("hello world", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages").unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('hello world', testdata_1_pages)");
    }

    #[test]
    fn where_clause_escapes_at_field_selector() {
        // `@` is the Manticore field-selector operator; it must reach the query escaped.
        // The escape pass then escapes the backslash itself, so the wire string is
        // `user\\@example.com`.
        let q = query("user@example.com", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages").unwrap();
        assert_eq!(normalize(&sql), "WHERE MATCH('user\\\\@example.com', testdata_1_pages)");
    }

    #[test]
    fn where_clause_trims_and_quotes() {
        // A single quote is escaped with a BACKSLASH. Manticore's parser rejects the
        // SQL-standard doubling outright (`P01: syntax error`), so an assertion on the
        // doubled form passes in the test suite while every such search 500s in
        // production, which is exactly how this reached a live site.
        let q = query("  it's a test  ", &[]);
        let sql = build_sql_where_clause(&q, "testdata_1_pages").unwrap();
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
                build_sql_where_clause(&query(input, &[]), "testdata_1_pages")
                    .unwrap();
            assert_eq!(normalize(&sql), expected, "for {input:?}");
        }
    }

    /// A query made only of negations is `non-computable (single NOT operator)` at
    /// Manticore. Failing here turns that into a message in the search bar.
    #[test]
    fn where_clause_rejects_a_query_with_nothing_to_match() {
        assert!(
            build_sql_where_clause(&query("!a", &[]), "testdata_1_pages")
                .is_err()
        );
    }

    /// The empty query is how the site browses without a search term, and it must stay
    /// `MATCH('')` (every row), rather than becoming an error.
    #[test]
    fn where_clause_keeps_the_empty_query_matching_everything() {
        let sql =
            build_sql_where_clause(&query("   ", &[]), "testdata_1_pages")
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
        let sql = build_sql_where_clause(&q, "testdata_1_pages").unwrap();
        assert_eq!(
            normalize(&sql),
            "WHERE MATCH('word', testdata_1_pages) \
             AND collection_dataset IN ('testdata_testfiles') \
             AND file_types IN (7, 9)"
        );
    }

    #[test]
    fn where_clause_rejects_bad_field_name() {
        let q = query("word", &[("evil_field", &[FacetOriginalValue::Int(1)])]);
        assert!(build_sql_where_clause(&q, "testdata_1_pages").is_err());
    }

    /// One budget on every path, and it is the one the client backstop is derived from.
    #[test]
    fn options_clause_carries_the_search_budget_and_max_matches() {
        assert_eq!(
            sql_options_clause(42),
            format!(
                "OPTION agent_query_timeout={ms},max_query_time={ms},max_matches=42",
                ms = search_timeout_ms()
            )
        );
    }

    /// Every facet field the frontend can send must be accepted, a whitelist that
    /// drifts from its caller list is a runtime 500. Keep in sync with the facet
    /// list in `frontend/src/components/search_components/search_facets.rs`.
    #[test]
    fn search_field_name_accepts_every_frontend_facet_field() {
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
                search_field_name(field).is_ok(),
                "frontend facet field {field:?} rejected by the whitelist"
            );
        }
    }

    /// The dropped text columns must NOT come back through the whitelist: they do not
    /// exist on the table, so a filter naming one is a Manticore error on every shard
    /// rather than an empty result.
    #[test]
    fn search_field_name_rejects_the_columns_that_are_not_there() {
        for gone in ["filenames", "metadata_values"] {
            assert!(search_field_name(gone).is_err(), "{gone} is not a column");
        }
    }

    fn ranged(field: &str, filter: RangeFilter) -> String {
        let mut query = SearchQuery { query_string: "word".to_string(), ..Default::default() };
        query.range_filters.insert(field.to_string(), filter);
        normalize(&build_sql_where_clause(&query, "testdata_1_pages").unwrap())
    }

    /// The predicate is an interval-overlap test rather than `ANY(dates) BETWEEN`. See
    /// `range_predicate`'s doc comment; the substitution is deliberate and one-sided
    /// (a superset), and this pins the shape so it is not "fixed" into something that
    /// disagrees with the histogram drawn over the same bounds.
    #[test]
    fn a_date_range_is_an_interval_overlap_over_the_scalar_bounds() {
        let sql = ranged("dates", RangeFilter { min: Some(1356998400), max: Some(1483228799), include_unknown: false });
        assert!(
            sql.contains(
                "AND date_min <= 1483228799 AND date_max >= 1356998400"
            ),
            "{sql}"
        );
        assert!(!sql.contains("ANY("), "the bounds are scalars, not an MVA test: {sql}");
    }

    /// Mentioned dates are POINTS, and a filter over them must not become an interval.
    ///
    /// Three documents, verified against a live Manticore table: doc 1 mentions 1936 and
    /// 2020, doc 2 mentions 2005, doc 3 mentions 1900 and 1936. Filtering for calendar
    /// 2005, interval overlap matches docs 1 and 2; `ANY(...) BETWEEN` matches only doc 2,
    /// which is the right answer. Doc 1 says nothing about 2005. Copying the `dates` arm
    /// here is the single most likely way to get this feature wrong, so the shape is
    /// pinned.
    #[test]
    fn a_mentioned_date_range_is_an_any_test_over_the_mva() {
        // 2005-01-01 .. 2005-12-31, the calendar year the three-document case turns on.
        let sql = ranged(
            "mentioned_dates",
            RangeFilter { min: Some(1104537600), max: Some(1136073599), include_unknown: false },
        );
        assert!(
            sql.contains("ANY(mentioned_dates) BETWEEN 1104537600 AND 1136073599"),
            "{sql}"
        );
        assert!(
            !sql.contains("mentioned_date_min <="),
            "the min/max pair measures the histogram's domain and must never filter: {sql}"
        );
    }

    /// The bounds are signed, so a range entirely before the epoch is expressible at all.
    /// Manticore's own `timestamp` type is 32-bit unsigned and cannot hold 1936.
    #[test]
    fn a_mentioned_date_range_crosses_the_epoch() {
        let sql = ranged(
            "mentioned_dates",
            RangeFilter { min: Some(-1200000000), max: Some(-1000000000), include_unknown: false },
        );
        assert!(sql.contains("ANY(mentioned_dates) BETWEEN -1200000000 AND -1000000000"), "{sql}");
    }

    #[test]
    fn a_segment_mentioning_no_date_is_unknown_on_its_own_scalar() {
        let sql = ranged(
            "mentioned_dates",
            RangeFilter { min: None, max: None, include_unknown: true },
        );
        assert!(sql.contains(&format!("AND mentioned_date_min = {DATE_UNKNOWN}")), "{sql}");
        // The document-date sentinel is a different column, and `mentioned_date_min`
        // contains its name as a substring, hence the leading `AND `.
        assert!(!sql.contains("AND date_min = "), "it must not read the document-date sentinel: {sql}");
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
        assert!(sql.contains(&format!("AND date_min = {DATE_UNKNOWN}")), "{sql}");
        assert!(!sql.contains("ANY("), "unknown-only must not emit an MVA predicate: {sql}");
    }

    #[test]
    fn a_range_plus_unknown_is_a_disjunction() {
        let sql = ranged("dates", RangeFilter { min: Some(0), max: Some(100), include_unknown: true });
        assert!(
            sql.contains(&format!(
                "AND (date_min <= 100 AND date_max >= 0                  OR date_min = {DATE_UNKNOWN})"
            ).replace("                 ", "")),
            "{sql}"
        );
    }

    #[test]
    fn an_open_ended_size_range_still_excludes_the_unknown_sentinel() {
        // SIZE_UNKNOWN is -1. Without the clamp, "under 1 MB" would sweep up every
        // document that has no vfs_files row.
        let sql = ranged("file_size_bytes", RangeFilter { min: None, max: Some(1048575), include_unknown: false });
        assert!(sql.contains("AND file_size_bytes BETWEEN 0 AND 1048575"), "{sql}");
    }

    #[test]
    fn an_inverted_range_is_an_error_not_an_empty_filter() {
        let mut query = SearchQuery { query_string: "word".to_string(), ..Default::default() };
        query.range_filters.insert(
            "dates".to_string(),
            RangeFilter { min: Some(100), max: Some(1), include_unknown: false },
        );
        assert!(build_sql_where_clause(&query, "testdata_1_pages").is_err());
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
        assert!(build_sql_where_clause(&query, "testdata_1_pages").is_err());
    }

    #[test]
    fn sort_columns_are_whitelisted_and_direction_aware() {
        let cases = [
            (SortKey::Relevance, true, "weight()"),
            (SortKey::Relevance, false, "weight()"),
            (SortKey::Date, true, "date_max"),
            (SortKey::Date, false, "date_min"),
            (SortKey::FileSize, true, "file_size_bytes"),
            (SortKey::Name, false, "primary_filename"),
        ];
        for (key, desc, expected) in cases {
            assert_eq!(sort_column(&SortSpec { key, desc }), expected);
        }
    }

    #[test]
    fn sort_order_by_keeps_the_stable_tie_break() {
        assert_eq!(
            sort_order_by(&SortSpec { key: SortKey::Name, desc: false }),
            "ORDER BY primary_filename ASC, collection_dataset ASC, file_hash ASC"
        );
        assert_eq!(
            sort_order_by(&SortSpec { key: SortKey::FileSize, desc: true }),
            "ORDER BY file_size_bytes DESC, collection_dataset ASC, file_hash ASC"
        );
    }

    /// A query the parser cannot be given is the CALLER's mistake, and the classification
    /// has to survive the trip out of the SQL builder for the endpoint to say so.
    ///
    /// It is carried by the error's TYPE. Restating it as `anyhow!("{e}")` anywhere along
    /// the way leaves a bare string, every such query is reported as a 500, and a rejected
    /// keystroke reads as the site falling over, while the telemetry counts it as
    /// breakage.
    #[test]
    fn a_query_with_only_negations_is_a_bad_request_all_the_way_out() {
        let query = SearchQuery { query_string: "!a".to_string(), ..Default::default() };
        let error = build_sql_where_clause(&query, "testdata_1_pages")
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
