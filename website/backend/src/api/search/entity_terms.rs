//! The corpus-wide term search behind every "Search X" box in the filter modal.
//!
//! Why this exists at all
//! ----------------------
//! A facet pane holds the buckets one query returned, twenty-one of them by the
//! over-fetch limit. Narrowing that list client-side answers "nothing matches" for a
//! value that is present in the corpus and simply did not make the top twenty-one, which
//! on any real corpus is almost every value. The needle has to be asked of the corpus.
//!
//! It cannot be asked of the search shards. Their facet columns hold
//! `hash_string_to_uint63` term ids and never the text, so there is not even a string
//! there for a needle to match. `<collectionname>_entities` is the table that carries
//! both: `term_text` for the needle, `term_id` for the filter the tick then writes.
//!
//! Uncached, for the same reason the folder tree is uncached: the table changes while
//! ingestion runs, and a stale term list is worse than a slow one. These queries are
//! cheap, one small table per collection, one infix `MATCH`.

use common::{
    current_user::CurrentUser,
    entity_cards::{EntityTermHit, EntityTermHits},
    search_query::SearchQuery,
};
use serde::{Deserialize, Serialize};

use crate::api::search::fanout::{self, FanoutTarget};
use crate::api::search::search_sql::{search_field_name, sql_options_clause};
use crate::auth::permissions;
use crate::db_utils::manticore_match::prepare_match_query;
use crate::db_utils::manticore_utils::manticore_search_sql_uncached;

/// Rows returned per collection, and the `max_matches` the query is given.
///
/// The two are the same number on purpose. Manticore caps a result set at `max_matches`
/// silently, so a `LIMIT` above it returns a truncated list with no indication that it
/// was truncated, which is exactly the failure this endpoint exists to remove.
const TERM_HIT_LIMIT: u64 = 200;

/// Facet fields a needle may be resolved against, and the term field each one is stored
/// under.
///
/// This is a whitelist because the value is interpolated into SQL, and it is a *mapping*
/// because the two names are genuinely different: the search column is `re_email`, the
/// term dictionary's field is `regex_email`, and `ner_per`/`ner_org`/`ner_loc`/`ner_misc`
/// all share the single term field `ner`. The NER dictionary does not distinguish them.
const TERM_FIELD_OF: &[(&str, &str)] = &[
    ("ner_per", "ner"),
    ("ner_org", "ner"),
    ("ner_loc", "ner"),
    ("ner_misc", "ner"),
    ("email_from", "email_address"),
    ("email_to", "email_address"),
    ("re_email", "regex_email"),
    ("re_phone", "regex_phone"),
    ("re_bank_account", "regex_bank_account"),
    ("re_company_id", "regex_company_id"),
    ("re_money", "regex_money"),
    ("re_crypto_wallet", "regex_crypto_wallet"),
];

/// The term-dictionary field one search column's values live under, or an error.
pub fn term_field_for_column(column: &str) -> anyhow::Result<&'static str> {
    // Validate the caller's spelling against the SQL whitelist first, so a name that is
    // not a search field at all is rejected here rather than three layers down.
    let column = search_field_name(column)?;
    TERM_FIELD_OF
        .iter()
        .find(|(search_column, _)| *search_column == column)
        .map(|(_, term_field)| *term_field)
        .ok_or_else(|| anyhow::anyhow!("{column:?} has no searchable term dictionary"))
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
struct TermRow {
    term_field: String,
    term_display: String,
    term_id: i64,
    #[serde(default)]
    highlight: String,
}

/// The `<collectionname>_entities` table name, validated.
fn entities_table(collectionname: &str) -> anyhow::Result<String> {
    if !crate::api::admin::collections::collectionname_valid(collectionname) {
        anyhow::bail!("invalid collection name: {collectionname:?}");
    }
    Ok(format!("{collectionname}_entities"))
}

/// Terms matching `needle` in any of `columns`, across every collection the query reaches.
///
/// The needle is wrapped in stars for infix matching and goes through
/// [`prepare_match_query`], never `QuotedData`: a facet search box is a full-text query
/// against `term_text`, and the shapes the parser rejects (a lone quote, a stray `~`)
/// are shapes people type. Repairing them is what keeps a keystroke from reading as the
/// site falling over.
///
/// The result is capped at [`TERM_HIT_LIMIT`] rows per collection and reports whether it
/// hit the cap.
pub async fn search_entity_terms(
    user: &CurrentUser,
    query: SearchQuery,
    needle: String,
    columns: Vec<String>,
) -> anyhow::Result<EntityTermHits> {
    let needle = needle.trim().to_string();
    if needle.is_empty() || columns.is_empty() {
        return Ok(EntityTermHits::default());
    }
    let perms = permissions::resolve_permissions(user).await?;
    let Some(query) = permissions::sanitize_query(query, &perms) else {
        return Ok(EntityTermHits::default());
    };

    let mut term_fields: Vec<&'static str> = Vec::new();
    for column in &columns {
        let field = term_field_for_column(column)?;
        if !term_fields.contains(&field) {
            term_fields.push(field);
        }
    }
    let field_list = term_fields
        .iter()
        .map(|field| format!("'{field}'"))
        .collect::<Vec<_>>()
        .join(", ");

    let collections = fanout::permitted_search_collections(user, &query).await?;
    if collections.is_empty() {
        return Ok(EntityTermHits::default());
    }
    let match_argument = prepare_match_query(&format!("*{needle}*"))
        .map_err(anyhow::Error::from)?
        .quoted();
    let options_clause = sql_options_clause(TERM_HIT_LIMIT);

    let targets: Vec<FanoutTarget> = collections
        .iter()
        .map(|name| FanoutTarget::collection(name.clone()))
        .collect();
    let outcome = fanout::fan_out(targets, move |target: FanoutTarget| {
        let field_list = field_list.clone();
        let match_argument = match_argument.clone();
        let options_clause = options_clause.clone();
        async move {
            let table = entities_table(target.collectionname())?;
            let sql = format!(
                "
                SELECT term_field, term_display, term_id,
                    HIGHLIGHT({{
                        limit=120,
                        limit_snippets=1,
                        html_strip_mode=strip,
                        before_match='<hoover4_strong>',
                        after_match='</hoover4_strong>',
                        around=20
                    }}, term_text) AS highlight
                FROM {table}
                WHERE MATCH({match_argument})
                  AND term_field IN ({field_list})
                ORDER BY term_display ASC
                LIMIT {TERM_HIT_LIMIT}
                {options_clause}
                ;"
            );
            manticore_search_sql_uncached::<TermRow>(sql).await
        }
    })
    .await?;

    let mut hits: Vec<EntityTermHit> = Vec::new();
    let mut truncated = outcome.is_partial();
    for (_target, response) in outcome.results {
        if response.hits.hits.len() as u64 >= TERM_HIT_LIMIT {
            truncated = true;
        }
        for hit in response.hits.hits {
            let row = hit._source;
            // The dictionary mints ids with `hash_string_to_uint63`, so every one fits
            // in 63 bits and the cast back from Manticore's signed bigint is exact. A
            // negative value would mean the writer changed its hash; drop it rather than
            // wrap it into a filter that matches nothing.
            let Ok(term_id) = u64::try_from(row.term_id) else {
                tracing::warn!(
                    "entity term {:?} has a negative term_id {}; skipping",
                    row.term_display,
                    row.term_id
                );
                continue;
            };
            hits.push(EntityTermHit {
                term_id,
                term_display: row.term_display,
                term_field: row.term_field,
                highlight: crate::db_utils::decompose_spans::decompose_text_into_spans(
                    row.highlight,
                ),
            });
        }
    }

    // One value can exist in more than one collection under the same id: the ids are
    // content-derived, so the same string hashes the same everywhere. One row per
    // `(field, id)` is what the facet pane wants.
    hits.sort_by(|a, b| {
        (&a.term_field, &a.term_display, a.term_id).cmp(&(&b.term_field, &b.term_display, b.term_id))
    });
    hits.dedup_by(|a, b| a.term_field == b.term_field && a.term_id == b.term_id);

    Ok(EntityTermHits { hits, truncated })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_searchable_facet_column_maps_to_a_term_field() {
        for (column, expected) in TERM_FIELD_OF {
            assert_eq!(term_field_for_column(column).unwrap(), *expected);
        }
    }

    /// The four NER columns share one dictionary field. Asking for all four must not
    /// send `'ner'` four times. The `IN` list would be redundant and the intent
    /// unreadable.
    #[test]
    fn the_four_ner_columns_collapse_to_one_term_field() {
        let fields: Vec<&str> = ["ner_per", "ner_org", "ner_loc", "ner_misc"]
            .iter()
            .map(|c| term_field_for_column(c).unwrap())
            .collect();
        assert_eq!(fields, vec!["ner", "ner", "ner", "ner"]);
    }

    /// `re_email` and `email_from` are different questions about the same string: one is
    /// an address the body mentions, the other is the envelope's sender. They must never
    /// resolve to one dictionary field, or ticking a row would apply the wrong filter.
    #[test]
    fn a_mentioned_address_and_an_envelope_address_are_different_fields() {
        assert_eq!(term_field_for_column("re_email").unwrap(), "regex_email");
        assert_eq!(term_field_for_column("email_from").unwrap(), "email_address");
    }

    /// `file_types` has a handful of buckets, all on screen at once, and no rows in the
    /// term table. Offering it a server-side search box would answer nothing for every
    /// needle.
    #[test]
    fn a_column_with_no_term_dictionary_is_rejected() {
        assert!(term_field_for_column("file_types").is_err());
        assert!(term_field_for_column("dates").is_err());
    }

    #[test]
    fn an_unknown_column_is_rejected_before_it_reaches_sql() {
        assert!(term_field_for_column("unknown; DROP TABLE x").is_err());
        assert!(term_field_for_column("no_such_column").is_err());
    }

    #[test]
    fn the_table_name_is_validated() {
        assert_eq!(entities_table("testdata").unwrap(), "testdata_entities");
        assert!(entities_table("bad name").is_err());
        assert!(entities_table("a; DROP TABLE x").is_err());
    }
}
