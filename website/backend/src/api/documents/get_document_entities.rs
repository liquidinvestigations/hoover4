//! Per-document entities, from both extractors, grouped with counts.
//!
//! Two sources, one list. `entity_hit` holds what an NER model judged to be a name, an
//! organisation or a place; `regex_entity_hit` holds what a rule's validator accepted as
//! an identifier, an amount or a date. They are unioned here rather than in the viewer
//! because the same query answers the agent's `list_document_entities` tool, and two
//! implementations of "what does this document contain" would drift.
//!
//! The two halves are counted differently, on purpose. A model-found value is re-counted
//! against the document's own text, because the stored count comes from a variant of the
//! text the viewer may not be showing. A rule-found value is NOT: its normalised form is
//! frequently not what the document wrote — `+442075623419` for `+44 (0)20 7562 3419` —
//! so a full-text count of it would be zero and would drop every phone number in the
//! corpus. The scanner already counted occurrences in the text it read, and that count
//! is the one that is true.

use clickhouse::Row;
use common::{
    current_user::CurrentUser,
    document_entities::{DocumentEntitiesResponse, DocumentEntityItem, DocumentEntityType},
    entity_stoplist::is_stopped_entity,
    search_result::DocumentIdentifier,
};
use futures::{StreamExt, stream};
use serde::Deserialize;
use std::collections::HashMap;

use crate::api::search::fanout;
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

#[derive(Debug, Clone, Deserialize, Row)]
struct EntityRow {
    pub entity_type: String,
    pub value: String,
    pub hit_count: u64,
    pub providers: Vec<String>,
}

#[derive(Debug, Clone, Deserialize, Row)]
struct RegexEntityRow {
    pub entity_type: String,
    pub value: String,
    pub rule_id: String,
    pub value_json: String,
    pub surface_text: String,
    pub hit_count: u64,
}

/// Collapse every run of whitespace to a single space and trim.
///
/// A document extracted by more than one extractor carries one `entity_hit` row per
/// extractor, and on mail the two differ only in line endings: `email_parser` stores
/// `Eric \nCc` where `raw_text` stores `Eric \r\nCc`. Grouped by the raw string those are
/// two entries that render identically, so an email carrying both variants lists every one
/// of its values twice. Folding the whitespace is also what lets the stop-list see
/// `Eric Cc` for what it is, and it merges nothing else: two entities that differ only in
/// how much space is between their words are one entity.
fn normalize_entity_whitespace(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

fn normalize_entity_type(s: &str) -> DocumentEntityType {
    let t = s.trim().to_lowercase();
    match t.as_str() {
        // Migration says entity_type is free-form (person, org, email, url, etc.)
        // UI expects PER/ORG/LOC/MISC grouping.
        "per" | "person" | "people" => DocumentEntityType::Per,
        "org" | "organization" | "organisation" => DocumentEntityType::Org,
        "loc" | "location" => DocumentEntityType::Loc,
        "misc" => DocumentEntityType::Misc,
        _ => DocumentEntityType::Unknown,
    }
}

pub async fn get_document_entities(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentEntitiesResponse> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;

    let _ents = _get_document_entities(document_identifier.clone()).await?;
    // A scanner that has never run leaves no rows, and this returns an empty list rather
    // than failing: the panel then shows its NER half and no rule half, which is the
    // honest picture of a stack whose scanner is down.
    let regex_items = get_document_regex_entities(&document_identifier).await?;

    // The stored hit count is per entity_hit row, which does not have to agree with what
    // the text index can find; each entity is re-counted against the document's own pages
    // and dropped when it counts zero. That is one full-text search per entity, up to the
    // 500 the query above returns, so the concurrency is capped exactly as the main
    // search path caps its shard fan-out -- an uncapped version puts 500 simultaneous
    // searches on one shard.
    //
    // A per-entity failure drops that entity instead of the whole panel. Collecting with
    // `?` here means one unsearchable value blanks the entities of an otherwise fine
    // document, which is a far worse answer than a list one entity short.
    let mut v2: Vec<DocumentEntityItem> = stream::iter(_ents.items.into_iter().map(|item| {
        let document_identifier = document_identifier.clone();
        let value = item.value.clone();
        async move {
            match _adjust_hit_item_count(user, document_identifier, item).await {
                Ok(item) => Some(item),
                Err(e) => {
                    tracing::warn!("dropping entity {value:?}: could not count its hits: {e}");
                    None
                }
            }
        }
    }))
    .buffer_unordered(fanout::max_parallelism())
    .filter_map(|item| async move { item.filter(|item| item.hit_count > 0) })
    .collect()
    .await;

    v2.extend(regex_items);

    v2.sort_by_key(|item| {
        (item.entity_type, item.hit_count, item.value.clone())
    });
    v2.reverse();

    Ok(DocumentEntitiesResponse{items:v2})
}

async fn _adjust_hit_item_count(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier, 
    mut item: DocumentEntityItem,
) -> anyhow::Result<DocumentEntityItem> {
    let find_query = format!("\"{}\"", item.value);
    use crate::api::documents::search_document_text::search_document_text_for_hit_count;

    let _counts = search_document_text_for_hit_count(user, document_identifier, find_query).await?;
    let _count_sum = _counts.into_iter().map(|x| x.hit_count).sum::<u64>();
    item.hit_count = _count_sum;
    
    Ok(item)
}

async fn _get_document_entities(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentEntitiesResponse> {
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;

    // Match migration schema:
    // - entity_type: String
    // - entity_values: Array(String)
    // We explode values via ARRAY JOIN and count occurrences.
    let sql = r#"
        SELECT
            entity_type as entity_type,
            entity_value as value,
            count() as hit_count,
            arraySort(groupUniqArray(nlp_model)) as providers
        FROM entity_hit
        ARRAY JOIN entity_values AS entity_value
        WHERE collection_dataset = ? AND file_hash = ?
        GROUP BY entity_type, entity_value
        ORDER BY hit_count DESC
        LIMIT 500
    "#;

    let rows: Vec<EntityRow> = client
        .query(sql)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;

    Ok(DocumentEntitiesResponse {
        items: fold_entity_rows(rows),
    })
}

/// The rule-found half of a document's entities.
///
/// Public because the agent's `list_document_entities` tool reads exactly this: two
/// implementations of "which identifiers does this document contain" would give the
/// model and the reader different answers about the same file.
///
/// Three things the query has to get right, none of them obvious from the schema:
///
/// * **Only the newest rule set.** `regex_entity_hit` keeps every rule set's results side
///   by side, so that bumping the version makes a rescan possible without destroying what
///   the previous version found. Reading them all would list a value once per version.
/// * **Counts are summed across segments and MAXed across text variants.** A document
///   parsed twice — `raw_text` and `email_parser` — carries the same occurrences under
///   both, so adding the variants would double every count.
/// * **The five value arrays are parallel**, and `ARRAY JOIN` over all of them at once is
///   what keeps a value with its own rule, its own canonical object, its own count and
///   its own surface text. Joining them separately would produce the cross product.
pub async fn get_document_regex_entities(
    document_identifier: &DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentEntityItem>> {
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let sql = r#"
        SELECT
            entity_type,
            value,
            any(rule_id) AS rule_id,
            any(value_json) AS value_json,
            any(surface_text) AS surface_text,
            max(variant_count) AS hit_count
        FROM (
            SELECT
                entity_type,
                entity_value AS value,
                extracted_by,
                any(rule_id) AS rule_id,
                any(value_json) AS value_json,
                any(surface_text) AS surface_text,
                sum(occurrences) AS variant_count
            FROM (
                SELECT entity_type, extracted_by, entity_values, entity_rule_ids,
                       entity_value_json, entity_counts, entity_texts
                FROM regex_entity_hit FINAL
                WHERE collection_dataset = ? AND file_hash = ?
                  AND rule_set_version = (
                      SELECT max(rule_set_version) FROM regex_entity_hit
                      WHERE collection_dataset = ? AND file_hash = ?
                  )
            )
            ARRAY JOIN
                entity_values AS entity_value,
                entity_rule_ids AS rule_id,
                entity_value_json AS value_json,
                entity_counts AS occurrences,
                entity_texts AS surface_text
            GROUP BY entity_type, value, extracted_by
        )
        GROUP BY entity_type, value
        ORDER BY hit_count DESC
        LIMIT 1000
    "#;
    let rows: Vec<RegexEntityRow> = client
        .query(sql)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;
    Ok(rows.into_iter().map(regex_item).collect())
}

/// One stored row as a panel item.
fn regex_item(row: RegexEntityRow) -> DocumentEntityItem {
    let entity_type = DocumentEntityType::from_scanner_type(&row.entity_type);
    // The surface form is only worth carrying when it differs: a find-in-page click on a
    // value that IS its own surface form should search the value, and storing the same
    // string twice invites a renderer to show it twice.
    let surface_text = if row.surface_text == row.value {
        String::new()
    } else {
        row.surface_text
    };
    let bucket = if entity_type == DocumentEntityType::Money {
        common::entity_cards::money_bucket_from_value_json(&row.value_json).unwrap_or_default()
    } else {
        String::new()
    };
    DocumentEntityItem {
        entity_type,
        value: row.value,
        hit_count: row.hit_count,
        // The provider is the rule, and it is already carried as `rule_id`. Repeating it
        // here would put the same string in two places on one card.
        providers: Vec::new(),
        rule_id: row.rule_id,
        value_json: row.value_json,
        surface_text,
        bucket,
    }
}

/// Turn the stored rows into one item per `(type, value)`, dropping debris.
///
/// The grouping key is the whitespace-folded value, which is what merges the two rows a
/// pre-existing email carries — see [`normalize_entity_whitespace`]. The hit count is
/// *not* summed: each row already counts the same occurrences in a different variant of
/// the same text, and adding them would double the number. It is replaced outright by a
/// full-text count of the document before it reaches the panel anyway.
fn fold_entity_rows(rows: Vec<EntityRow>) -> Vec<DocumentEntityItem> {
    let mut items: Vec<DocumentEntityItem> = Vec::new();
    let mut seen: HashMap<(DocumentEntityType, String), usize> = HashMap::new();
    for r in rows {
        let value = normalize_entity_whitespace(&r.value);
        if value.is_empty() {
            continue;
        }
        // Header names, encoding fragments and letter-spaced PDF headings. The pipeline
        // stops these before they are stored; this catches what older rows kept. Run
        // after the whitespace fold, so a value the extractor split across a line break
        // is matched by the same rules as its unwrapped twin.
        if is_stopped_entity(&value) {
            continue;
        }
        let entity_type = normalize_entity_type(&r.entity_type);
        // An empty model name is an ingest that predates the column, not a provider.
        let providers = r.providers.into_iter().filter(|p| !p.is_empty());

        match seen.get(&(entity_type, value.clone())) {
            Some(&index) => {
                let item = &mut items[index];
                item.hit_count = item.hit_count.max(r.hit_count);
                for provider in providers {
                    if !item.providers.contains(&provider) {
                        item.providers.push(provider);
                    }
                }
                item.providers.sort();
            }
            None => {
                seen.insert((entity_type, value.clone()), items.len());
                let mut providers: Vec<String> = providers.collect();
                providers.sort();
                items.push(DocumentEntityItem {
                    entity_type,
                    value,
                    hit_count: r.hit_count,
                    providers,
                    // A model-found value has no rule, no canonical object and no card;
                    // its surface form is the value, because a model reads prose rather
                    // than normalising it.
                    rule_id: String::new(),
                    value_json: String::new(),
                    surface_text: String::new(),
                    bucket: String::new(),
                });
            }
        }
    }
    items
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(entity_type: &str, value: &str, hit_count: u64, provider: &str) -> EntityRow {
        EntityRow {
            entity_type: entity_type.to_string(),
            value: value.to_string(),
            hit_count,
            providers: vec![provider.to_string()],
        }
    }

    #[test]
    fn the_two_line_ending_variants_of_one_value_are_one_entry() {
        // What the panel showed: `Eric Cc  6` twice, adjacent, identical. The document has
        // an `email_parser` row and a `raw_text` row that differ only in `\r\n`.
        let items = fold_entity_rows(vec![
            row("PER", "Virginia \nHughes", 2, "email_parser"),
            row("PER", "Virginia \r\nHughes", 2, "raw_text"),
        ]);
        assert_eq!(items.len(), 1);
        assert_eq!(items[0].value, "Virginia Hughes");
        assert_eq!(items[0].hit_count, 2, "the same occurrences seen twice are not twice as many");
        assert_eq!(items[0].providers, vec!["email_parser", "raw_text"]);
    }

    #[test]
    fn two_genuinely_different_values_are_never_merged() {
        let items = fold_entity_rows(vec![
            row("PER", "Virginia Hughes", 2, "raw_text"),
            row("PER", "Virginia Hughes-Smith", 1, "raw_text"),
            row("ORG", "Virginia Hughes", 3, "raw_text"),
        ]);
        assert_eq!(items.len(), 3);
    }

    #[test]
    fn a_value_only_a_line_break_hid_from_the_stop_list_is_now_stopped() {
        // `Eric \nCc` is the reply block's header keyword glued to the name above it. The
        // whole-value rules never saw it while the newline was in the middle.
        assert!(fold_entity_rows(vec![row("PER", "Eric \r\nCc", 6, "raw_text")]).is_empty());
    }
}
