//! Dictionary counts and spelling candidates share shard resolution and permissions.

use std::collections::{BTreeMap, BTreeSet};
use std::time::Duration;

use common::current_user::CurrentUser;
use common::search_query::SearchQuery;
use common::search_suggestions::{SearchSuggestions, SpellingCandidate, SuggestedQuery, WordCount, WordSuggestions};
use futures::{stream, StreamExt, TryStreamExt};

use super::{fanout, search_sql};
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils;
use crate::db_utils::manticore_match::quoted_manticore_string as quote;
use crate::db_utils::manticore_utils::{manticore_dictionary_sql, ManticoreRawRow};

const OPERATORS: &[&str] = &["AND", "OR", "NOT", "NEAR", "NOTNEAR", "MAYBE", "SENTENCE", "PARAGRAPH", "ZONE", "ZONESPAN", "REGEX"];

#[derive(Debug, Clone, Copy, Default, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TableKind {
    #[default]
    Pages,
    Entities,
    Folders,
}

#[derive(Debug, Clone, Copy)]
pub enum Gate { Agent, Page }

/// Keep positive letter words and their byte positions for query replacement.
fn word_spans(query: &str) -> Vec<(usize, usize)> {
    let mut spans = Vec::new();
    let mut start = None;
    for (i, c) in query.char_indices().chain(std::iter::once((query.len(), ' '))) {
        if c.is_alphanumeric() || "_*?%".contains(c) {
            start.get_or_insert(i);
        } else if let Some(begin) = start.take() {
            let word = &query[begin..i];
            let negated = query[..begin].ends_with(['-', '!']);
            if !negated && word.chars().count() >= 3 && word.chars().all(char::is_alphabetic)
                && !OPERATORS.contains(&word) {
                spans.push((begin, i));
            }
        }
    }
    spans
}

pub fn words_of(query: &str) -> Vec<String> {
    let mut seen = BTreeSet::new();
    word_spans(query).into_iter().map(|(a, b)| query[a..b].to_lowercase())
        .filter(|word| seen.insert(word.clone())).collect()
}

fn number(row: &ManticoreRawRow, key: &str) -> u64 {
    row.get(key).and_then(|v| v.as_u64().or_else(|| v.as_str()?.parse().ok())).unwrap_or(0)
}

/// Match counts by query position, because the index folds case and accents.
fn keyword_counts(words: &[String], rows: &[ManticoreRawRow]) -> Vec<WordCount> {
    let mut counts: Vec<_> = words.iter().map(|w| WordCount { word: w.clone(), folded: w.clone(), documents: 0 }).collect();
    for row in rows {
        let Some(pos) = number(row, "qpos").checked_sub(1) else { continue; };
        let pos = pos as usize;
        if let Some(count) = counts.get_mut(pos) {
            count.folded = row.get("normalized").and_then(|v| v.as_str()).unwrap_or(&count.word).to_string();
            count.documents += number(row, "docs");
        }
    }
    counts
}

/// Sum the counts of each word over every table.
fn merge_counts(words: &[String], rows: Vec<Vec<ManticoreRawRow>>) -> Vec<WordCount> {
    let mut counts: Vec<_> = words.iter().map(|w| WordCount { word: w.clone(), folded: w.clone(), documents: 0 }).collect();
    for table in rows {
        for (count, entry) in counts.iter_mut().zip(keyword_counts(words, &table)) {
            count.documents += entry.documents;
            count.folded = entry.folded;
        }
    }
    counts
}

fn ranked_candidates(original: &WordCount, distances: BTreeMap<String, u32>, checked: &[WordCount], gate: Gate) -> Vec<SpellingCandidate> {
    let best = checked.iter().map(|c| c.documents).max().unwrap_or(0);
    if original.documents > 5 || (original.documents > 0 && best < original.documents.saturating_mul(20)) {
        return vec![];
    }
    let mut candidates: Vec<_> = checked.iter().filter_map(|count| {
        let distance = *distances.get(&count.word)?;
        if !(1..=2).contains(&distance) || count.word == original.folded || count.documents == 0 {
            return None;
        }
        if matches!(gate, Gate::Page) && (count.documents < 10 || distance == 2 && original.word.chars().count() < 7) {
            return None;
        }
        Some(SpellingCandidate { word: count.word.clone(), distance, documents: count.documents })
    }).collect();
    candidates.sort_by(|a, b| a.distance.cmp(&b.distance).then(b.documents.cmp(&a.documents)).then(a.word.cmp(&b.word)));
    candidates.truncate(4);
    candidates
}

/// The dictionary tables of every collection, each with its cache salt. A registry read
/// is retried, and a collection whose tables cannot be listed fails the lookup.
async fn tables_for(collections: &[String], kind: TableKind) -> anyhow::Result<Vec<(String, String)>> {
    let mut tables = Vec::new();
    for collection in collections {
        if !crate::api::admin::collections::collectionname_valid(collection) {
            anyhow::bail!("collection name {collection:?} is not valid");
        }
        let generation = fanout::with_retries("suggestions: shard generation", || clickhouse_utils::shard_generation(collection)).await?;
        let salt = format!("{collection}@{generation}");
        match kind {
            TableKind::Pages => {
                let shards = fanout::with_retries("suggestions: list shards", || clickhouse_utils::list_shards(collection)).await?;
                for shard in shards {
                    tables.push((search_sql::shard_table_name(&shard)?, salt.clone()));
                }
            }
            TableKind::Entities => tables.push((format!("{collection}_entities"), salt)),
            TableKind::Folders => tables.push((format!("{collection}_vfs"), salt)),
        }
    }
    Ok(tables)
}

/// Run one dictionary statement on every table. A table that fails is retried alone, so
/// a table that answered is not called again. A table that still fails fails the call.
async fn call_tables(tables: &[(String, String)], statement: impl Fn(&str) -> String) -> anyhow::Result<Vec<Vec<ManticoreRawRow>>> {
    let calls: Vec<_> = tables.iter().map(|(table, salt)| (table.clone(), statement(table), salt.clone())).collect();
    stream::iter(calls).map(|(table, sql, salt)| async move {
        let label = format!("suggestions: table {table}");
        fanout::with_retries(&label, || manticore_dictionary_sql(sql.clone(), &salt)).await
    }).buffer_unordered(fanout::max_parallelism()).try_collect().await
}

/// Word counts and spelling candidates for the words of `query`.
///
/// A failed word-count lookup returns no counts and no candidates, so that no caller
/// reads a missing count as an absent word. A word whose candidate lookup fails gets no
/// candidates. The other words keep theirs.
pub async fn indexed_suggestions(collections: &[String], query: &str, kind: TableKind, gate: Gate) -> SearchSuggestions {
    tokio::time::timeout(PAGE_SUGGESTION_DEADLINE, indexed_suggestions_inner(collections, query, kind, gate))
        .await.unwrap_or_default()
}

async fn indexed_suggestions_inner(collections: &[String], query: &str, kind: TableKind, gate: Gate) -> SearchSuggestions {
    let words = words_of(query);
    if words.is_empty() { return SearchSuggestions::default(); }
    let tables = match tables_for(collections, kind).await {
        Ok(tables) => tables,
        Err(e) => {
            tracing::warn!("suggestions: cannot list the dictionary tables: {e:#}");
            return SearchSuggestions::default();
        }
    };
    if tables.is_empty() { return SearchSuggestions::default(); }
    let joined = quote(&words.join(" "));
    let counts = match call_tables(&tables, |table| format!("CALL KEYWORDS({joined}, {}, 1 AS stats)", quote(table))).await {
        Ok(rows) => merge_counts(&words, rows),
        Err(e) => {
            tracing::warn!("suggestions: the word-count lookup failed: {e:#}");
            return SearchSuggestions::default();
        }
    };
    let mut suggestions = Vec::new();
    for count in counts.iter().filter(|count| count.documents <= 5) {
        match word_candidates(&tables, count, gate).await {
            Ok(candidates) if !candidates.is_empty() => {
                suggestions.push(WordSuggestions { word: count.word.clone(), candidates });
            }
            Ok(_) => {}
            Err(e) => tracing::warn!("suggestions: skipping the candidates of {:?}: {e:#}", count.word),
        }
    }
    SearchSuggestions { word_counts: counts, suggestions, ..Default::default() }
}

/// The checked spelling candidates of one rare word.
async fn word_candidates(tables: &[(String, String)], count: &WordCount, gate: Gate) -> anyhow::Result<Vec<SpellingCandidate>> {
    let rows = call_tables(tables, |table| format!("CALL QSUGGEST({}, {}, 10 AS limit)", quote(&count.folded), quote(table))).await?;
    let mut distances: BTreeMap<String, u32> = BTreeMap::new();
    for row in rows.into_iter().flatten() {
        let distance = number(&row, "distance") as u32;
        if !(1..=2).contains(&distance) { continue; }
        if let Some(word) = row.get("suggest").and_then(|v| v.as_str()) {
            if word == count.folded { continue; }
            distances.entry(word.to_string()).and_modify(|d| *d = (*d).min(distance)).or_insert(distance);
        }
    }
    if distances.is_empty() { return Ok(vec![]); }
    let candidate_words: Vec<_> = distances.keys().cloned().collect();
    let candidate_text = quote(&candidate_words.join(" "));
    let rows = call_tables(tables, |table| format!("CALL KEYWORDS({candidate_text}, {}, 1 AS stats)", quote(table))).await?;
    let checked = merge_counts(&candidate_words, rows);
    Ok(ranked_candidates(count, distances, &checked, gate))
}

fn replace_word(query: &str, word: &str, replacement: &str) -> String {
    let mut rewritten = String::new();
    let mut end = 0;
    for (a, b) in word_spans(query) {
        if query[a..b].to_lowercase() == word {
            rewritten.push_str(&query[end..a]);
            rewritten.push_str(replacement);
            end = b;
        }
    }
    rewritten.push_str(&query[end..]);
    rewritten
}

/// The time one page suggestion request may take, verified candidates included.
const PAGE_SUGGESTION_DEADLINE: Duration = Duration::from_secs(30);

/// Candidate queries the search page verifies with a hit count.
const MAX_VERIFIED_CANDIDATES: usize = 6;

/// Run page suggestions only after a zero count, preserving every filter.
///
/// Suggestions are optional. A step that fails or passes the deadline gives no
/// suggestion and no error: the page already shows the zero result. A candidate query
/// whose count fails is skipped, and the candidates verified before the deadline remain.
pub async fn search_suggestions(user: &CurrentUser, query: SearchQuery) -> anyhow::Result<SearchSuggestions> {
    let deadline = tokio::time::Instant::now() + PAGE_SUGGESTION_DEADLINE;
    match page_suggestions(user, query, deadline).await {
        Ok(response) => Ok(response),
        Err(e) => {
            tracing::warn!("suggestions: no suggestions for this search: {e:#}");
            Ok(SearchSuggestions::default())
        }
    }
}

async fn page_suggestions(user: &CurrentUser, query: SearchQuery, deadline: tokio::time::Instant) -> anyhow::Result<SearchSuggestions> {
    let perms = tokio::time::timeout_at(deadline, permissions::resolve_permissions(user)).await??;
    let Some(query) = permissions::sanitize_query(query, &perms) else { return Ok(SearchSuggestions::default()); };
    if query.query_string.trim().is_empty() { return Ok(SearchSuggestions::default()); }
    let count = tokio::time::timeout_at(deadline, super::search_for_results_hit_count::search_hit_count(user, query.clone())).await??;
    if count.total != 0 { return Ok(SearchSuggestions::default()); }
    let collections = tokio::time::timeout_at(deadline, fanout::permitted_search_collections(user, &query)).await??;
    let mut response = tokio::time::timeout_at(deadline, indexed_suggestions(&collections, &query.query_string, TableKind::Pages, Gate::Page)).await?;
    let mut replacements = Vec::new();
    for group in &response.suggestions {
        for candidate in &group.candidates {
            let replacement = replace_word(&query.query_string, &group.word, &candidate.word);
            if replacements.len() < MAX_VERIFIED_CANDIDATES && !replacements.contains(&replacement) {
                replacements.push(replacement);
            }
        }
    }
    let checks = replacements.into_iter().map(|replacement| {
        let mut corrected = query.clone();
        corrected.query_string = replacement.clone();
        async move {
            let count = tokio::time::timeout_at(deadline, super::search_for_results_hit_count::search_hit_count(user, corrected)).await;
            (replacement, count)
        }
    });
    for (replacement, count) in futures::future::join_all(checks).await {
        match count {
            Ok(Ok(count)) if count.total > 0 => response.queries.push(SuggestedQuery { query: replacement, count: count.total }),
            Ok(Ok(_)) => {}
            Ok(Err(e)) => tracing::warn!("suggestions: skipping {replacement:?}, its count failed: {e:#}"),
            Err(_) => tracing::warn!("suggestions: skipping {replacement:?}, its count passed the deadline"),
        }
    }
    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn count(word: &str, documents: u64) -> WordCount {
        WordCount { word: word.into(), folded: word.into(), documents }
    }

    #[test]
    fn extraction_preserves_positive_phrase_words() {
        assert_eq!(words_of(r#""Köszönöm példa" NEAR/5 water -draft !deny contract* dasovi?h dasovic% abc123 OR water"#),
                   ["köszönöm", "példa", "water"]);
        assert_eq!(replace_word("Dasovitch -dasovitch \"dasovitch mail\"", "dasovitch", "dasovich"),
                   "dasovich -dasovitch \"dasovich mail\"");
    }

    #[test]
    fn folding_uses_positions_and_sums_tables() {
        let words = vec!["köszönöm".into(), "példa".into()];
        let rows = vec![json!({"qpos":2,"normalized":"pelda","docs":4}),
                        json!({"qpos":"1","normalized":"koszonom","docs":"3"}),
                        json!({"qpos":0,"normalized":"invalid","docs":999})];
        let rows = rows.into_iter().map(|r| serde_json::from_value(r).unwrap()).collect::<Vec<_>>();
        let counts = merge_counts(&words, vec![rows.clone(), rows]);
        assert_eq!(counts[0].folded, "koszonom");
        assert_eq!(counts[0].documents, 6);
        assert_eq!(counts[1].documents, 8);
    }

    #[test]
    fn a_word_in_no_table_counts_zero() {
        let words = vec!["research".into(), "kaminsjy".into()];
        let rows = vec![serde_json::from_value(json!({"qpos":1,"normalized":"research","docs":12})).unwrap()];
        assert_eq!(merge_counts(&words, vec![rows]), vec![count("research", 12), count("kaminsjy", 0)]);
    }

    #[test]
    fn gates_use_checked_counts_and_distance() {
        let distances = BTreeMap::from([("alpha".into(),1), ("beta".into(),2), ("gamma".into(),3)]);
        let checked = vec![count("alpha",3), count("beta",100), count("gamma",200)];
        let original = count("alphx",0);
        let agent = ranked_candidates(&original, distances.clone(), &checked, Gate::Agent);
        assert_eq!(agent.iter().map(|c|c.word.as_str()).collect::<Vec<_>>(), ["alpha","beta"]);
        assert!(ranked_candidates(&original, distances.clone(), &checked, Gate::Page).is_empty());
        assert_eq!(ranked_candidates(&count("alphxxx",0), distances.clone(), &checked, Gate::Page)[0].word, "beta");
        assert!(ranked_candidates(&count("alphx",6), distances.clone(), &checked, Gate::Agent).is_empty());
        assert!(ranked_candidates(&count("alphx",5), BTreeMap::from([("alpha".into(),1)]), &[count("alpha",99)], Gate::Agent).is_empty());
    }
}
