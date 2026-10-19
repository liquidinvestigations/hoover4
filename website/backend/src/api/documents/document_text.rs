//! Stored-page reads and source-scoped match steps for one document text source.
//!
//! The website text viewer and the agent document routes both read through these
//! helpers. Each helper reads page identities or one page body, never every body of a
//! source, so a call costs the same on a source of any length.
//!
//! **The callers verify access.** The website functions in this module call
//! [`permissions::assert_can_read`] before any read. The agent routes resolve the
//! document through their own collection permission check first. The helpers that take a
//! ClickHouse client trust that check.
//!
//! ClickHouse holds the stored text and Manticore holds its index. The two are separate
//! requests and do not form a transactional snapshot. A match step therefore checks its
//! candidate pages against `text_content` before it returns one.

use std::collections::BTreeSet;

use common::{
    current_user::CurrentUser,
    document_text_pages::{MatchDirection, TextMatchStep, TextPageBody, TextPageNavigation, TextPageView, TextSourceUnit},
    search_result::DocumentIdentifier,
};
use serde::Deserialize;

use crate::api::documents::search_document_text::{find_query_match_argument, page_hit_rows, pages_table_for_document};
use crate::api::search::search_sql::{QueryTable, sql_options_clause};
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;
use crate::db_utils::{manticore_match::quoted_manticore_string, manticore_utils::manticore_search_sql};

/// Matching index rows that one match batch reads.
pub const MATCH_BATCH_ROWS: usize = 200;

/// Match batches that one website match step reads before it reports
/// [`TextMatchStep::Incomplete`]. Only obsolete index rows, whose page has no stored text,
/// make a step read more than one batch.
pub const MATCH_STEP_BATCHES: usize = 5;

/// One row of the page-identity aggregate. Page identifiers are never 0, so 0 in a
/// conditional aggregate means "no such page".
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, clickhouse::Row, Deserialize)]
pub struct PageStats {
    pub stored_count: u64,
    pub first_page: u32,
    pub last_page: u32,
    pub previous_page: u32,
    pub next_page: u32,
    pub stored_before: u64,
    pub selected_rows: u64,
    pub max_version: u64,
}

/// Reads the stored-page identity of a source around one identifier. It loads no text.
pub async fn page_stats(
    client: &clickhouse::Client,
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    around: u32,
) -> anyhow::Result<PageStats> {
    let stats = client
        .query(
            "SELECT
                uniqExact(page_id) AS stored_count,
                min(page_id) AS first_page,
                max(page_id) AS last_page,
                maxIf(page_id, page_id < ?) AS previous_page,
                minIf(page_id, page_id > ?) AS next_page,
                uniqExactIf(page_id, page_id < ?) AS stored_before,
                countIf(page_id = ?) AS selected_rows,
                max(version) AS max_version
            FROM text_content
            WHERE collection_dataset = ? AND file_hash = ? AND extracted_by = ?",
        )
        .bind(around)
        .bind(around)
        .bind(around)
        .bind(around)
        .bind(&identifier.collection_dataset)
        .bind(&identifier.file_hash)
        .bind(extracted_by)
        .fetch_one::<PageStats>()
        .await?;
    Ok(stats)
}

/// The navigation of one requested page, from the aggregate around it.
///
/// `requested` `None` selects the first stored page. An identifier without stored text
/// stays requested and gets `page: None`, with the stored neighbours on both sides.
pub fn navigation_from_stats(extracted_by: &str, requested: Option<u32>, stats: &PageStats) -> TextPageNavigation {
    let present = |page: u32| (page != 0).then_some(page);
    let empty = stats.stored_count == 0;
    let page = match requested {
        None => present(stats.first_page).filter(|_| !empty),
        Some(page) => (stats.selected_rows > 0).then_some(page),
    };
    TextPageNavigation {
        extracted_by: extracted_by.to_string(),
        unit: TextSourceUnit::of(extracted_by),
        requested_page: requested,
        page,
        stored_count: stats.stored_count,
        position: page.map(|_| stats.stored_before + 1),
        first_page: present(stats.first_page).filter(|_| !empty),
        last_page: present(stats.last_page).filter(|_| !empty),
        previous_page: present(stats.previous_page),
        next_page: present(stats.next_page),
        revision: source_revision(stats),
    }
}

/// The revision of a source: count, range and highest writer version.
pub fn source_revision(stats: &PageStats) -> String {
    format!("{}:{}-{}:{}", stats.stored_count, stats.first_page, stats.last_page, stats.max_version)
}

/// The navigation of one requested page. Two aggregate reads when `requested` is `None`:
/// the first finds the first stored page, the second its neighbours.
pub async fn page_navigation(
    client: &clickhouse::Client,
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    requested: Option<u32>,
) -> anyhow::Result<TextPageNavigation> {
    let around = match requested {
        Some(page) => page,
        None => {
            let first = page_stats(client, identifier, extracted_by, 0).await?;
            if first.stored_count == 0 {
                return Ok(navigation_from_stats(extracted_by, None, &first));
            }
            first.first_page
        }
    };
    let stats = page_stats(client, identifier, extracted_by, around).await?;
    let mut navigation = navigation_from_stats(extracted_by, Some(around), &stats);
    navigation.requested_page = requested;
    Ok(navigation)
}

/// The latest stored version of one page, or `None` when the identifier has no row.
pub async fn page_body(
    client: &clickhouse::Client,
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    page_id: u32,
) -> anyhow::Result<Option<(String, u64)>> {
    Ok(client
        .query(
            "SELECT text, version FROM text_content
            WHERE collection_dataset = ? AND file_hash = ? AND extracted_by = ? AND page_id = ?
            ORDER BY version DESC LIMIT 1",
        )
        .bind(&identifier.collection_dataset)
        .bind(&identifier.file_hash)
        .bind(extracted_by)
        .bind(page_id)
        .fetch_optional::<(String, u64)>()
        .await?)
}

/// The identifiers among `pages` that have stored text.
pub async fn stored_pages_among(
    client: &clickhouse::Client,
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    pages: &[u32],
) -> anyhow::Result<BTreeSet<u32>> {
    if pages.is_empty() {
        return Ok(BTreeSet::new());
    }
    let rows = client
        .query(
            "SELECT DISTINCT page_id FROM text_content
            WHERE collection_dataset = ? AND file_hash = ? AND extracted_by = ? AND has(?, page_id)",
        )
        .bind(&identifier.collection_dataset)
        .bind(&identifier.file_hash)
        .bind(extracted_by)
        .bind(pages)
        .fetch_all::<u32>()
        .await?;
    Ok(rows.into_iter().collect())
}

/// One batch of matching page identities of one source, in the requested direction.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct MatchBatch {
    /// Distinct matching identifiers, in the requested direction.
    pub pages: Vec<u32>,
    /// The boundary that the next batch continues after, or `None` when the index holds
    /// no further matching row in this direction.
    pub continue_after: Option<u32>,
}

/// Folds the raw index rows of one batch. `rows` hold at most `limit + 1` identifiers in
/// the requested order, duplicates included. The extra row only proves that more rows
/// exist. The boundary is the last identifier within `limit`, and the next batch reads
/// strictly beyond it, so a page whose duplicates cross the batch end is reported once.
pub fn fold_match_rows(rows: &[u32], limit: usize) -> MatchBatch {
    let within = &rows[..rows.len().min(limit)];
    let mut pages: Vec<u32> = Vec::with_capacity(within.len());
    for &page in within {
        if pages.last() != Some(&page) {
            pages.push(page);
        }
    }
    let continue_after = (rows.len() > limit).then(|| within.last().copied()).flatten();
    MatchBatch { pages, continue_after }
}

#[derive(Debug, Deserialize)]
struct MatchRow {
    page_id: u32,
}

/// Reads one batch of matching page identities of one source from the document's index
/// shard. Only this source's rows count against `limit`. `after` is an exclusive
/// boundary in the requested direction. `None` starts at the first or last page.
pub async fn matching_page_batch(
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    find_query: &str,
    after: Option<u32>,
    direction: MatchDirection,
    limit: usize,
) -> anyhow::Result<MatchBatch> {
    let Some(match_argument) = find_query_match_argument(find_query) else {
        return Ok(MatchBatch::default());
    };
    let Some((pages_table, salt)) = pages_table_for_document(identifier).await? else {
        return Ok(MatchBatch::default());
    };
    let (boundary, order) = match (direction, after) {
        (MatchDirection::Forward, Some(page)) => (format!("AND page_id > {page}"), "ASC"),
        (MatchDirection::Forward, None) => (String::new(), "ASC"),
        (MatchDirection::Backward, Some(page)) => (format!("AND page_id < {page}"), "DESC"),
        (MatchDirection::Backward, None) => (String::new(), "DESC"),
    };
    let rows = limit + 1;
    let options = sql_options_clause(QueryTable::Pages, rows as u64);
    let sql = format!(
        "SELECT page_id FROM {pages_table}
        WHERE file_hash = {} AND collection_dataset = {} AND extracted_by = {}
        AND extracted_by != 'filename_index' {boundary}
        AND MATCH({match_argument})
        ORDER BY page_id {order}
        LIMIT {rows}
        {options}",
        quoted_manticore_string(&identifier.file_hash),
        quoted_manticore_string(&identifier.collection_dataset),
        quoted_manticore_string(extracted_by),
    );
    let response = manticore_search_sql::<MatchRow>(sql, &salt).await?;
    let ids: Vec<u32> = response.hits.hits.into_iter().map(|hit| hit._source.page_id).collect();
    Ok(fold_match_rows(&ids, limit))
}

/// Matching pages that also have stored text, read batch by batch.
#[allow(async_fn_in_trait)]
pub trait MatchPages {
    /// One batch of matching identifiers beyond `after`, as [`matching_page_batch`] reads it.
    async fn batch(&self, after: Option<u32>, direction: MatchDirection, limit: usize) -> anyhow::Result<MatchBatch>;
    /// The identifiers among `pages` that have stored text.
    async fn stored(&self, pages: &[u32]) -> anyhow::Result<BTreeSet<u32>>;
}

/// [`MatchPages`] over one source in `text_content` and the document's index shard.
pub struct StoredMatchPages<'a> {
    pub client: &'a clickhouse::Client,
    pub identifier: &'a DocumentIdentifier,
    pub extracted_by: &'a str,
    pub find_query: &'a str,
}

impl MatchPages for StoredMatchPages<'_> {
    async fn batch(&self, after: Option<u32>, direction: MatchDirection, limit: usize) -> anyhow::Result<MatchBatch> {
        matching_page_batch(self.identifier, self.extracted_by, self.find_query, after, direction, limit).await
    }

    async fn stored(&self, pages: &[u32]) -> anyhow::Result<BTreeSet<u32>> {
        stored_pages_among(self.client, self.identifier, self.extracted_by, pages).await
    }
}

/// The nearest stored matching page beyond `from` in `direction`. It reads at most
/// `batches` batches of `limit` rows, and skips index rows whose page has no stored text.
/// The step never wraps at either end of the source.
pub async fn next_matching_page<M: MatchPages>(
    pages: &M,
    from: Option<u32>,
    direction: MatchDirection,
    batches: usize,
    limit: usize,
) -> anyhow::Result<TextMatchStep> {
    let mut after = from;
    for _ in 0..batches {
        let batch = pages.batch(after, direction, limit).await?;
        let stored = pages.stored(&batch.pages).await?;
        if let Some(page_id) = batch.pages.iter().copied().find(|page| stored.contains(page)) {
            return Ok(TextMatchStep::Found { page_id });
        }
        match batch.continue_after {
            Some(boundary) => after = Some(boundary),
            None => return Ok(TextMatchStep::NoMore),
        }
    }
    Ok(after.map_or(TextMatchStep::NoMore, |resume_after| TextMatchStep::Incomplete { resume_after }))
}

/// The highlighted spans of one page, or `None` when the find query does not match it.
async fn page_highlights(
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    find_query: &str,
    page_id: u32,
) -> anyhow::Result<Option<Vec<common::text_highlight::HighlightTextSpan>>> {
    let rows = page_hit_rows(identifier, find_query, extracted_by, page_id).await?;
    Ok(rows.into_iter().next().map(|row| row.highlight_text_spans))
}

/// One plain span holding the raw stored text.
fn plain_spans(text: String) -> Vec<common::text_highlight::HighlightTextSpan> {
    vec![common::text_highlight::HighlightTextSpan { text, is_highlighted: false, index: 0 }]
}

/// One text page for the website viewer: its navigation, its latest stored text, and its
/// find-query highlights.
///
/// An explicit `requested` page stays exact. Without one, a non-empty query opens the
/// first matching stored page in ascending order, and otherwise the first stored page.
/// A failed match search opens the first stored page and reports the error. A failed
/// highlight read shows the raw stored text of the same page and reports the error.
/// `expected_revision` names the revision the caller displayed. A different current
/// revision sets `source_changed`.
pub async fn get_text_page_view(
    user: &CurrentUser,
    identifier: DocumentIdentifier,
    extracted_by: String,
    requested: Option<u32>,
    find_query: String,
    expected_revision: Option<String>,
) -> anyhow::Result<TextPageView> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&identifier.collection_dataset).await?;
    let query = find_query.trim();

    let mut match_error = None;
    let mut wanted = requested;
    if wanted.is_none() && !query.is_empty() {
        let pages = StoredMatchPages { client: &client, identifier: &identifier, extracted_by: &extracted_by, find_query: query };
        match next_matching_page(&pages, None, MatchDirection::Forward, MATCH_STEP_BATCHES, MATCH_BATCH_ROWS).await {
            Ok(TextMatchStep::Found { page_id }) => wanted = Some(page_id),
            Ok(_) => {}
            Err(error) => match_error = Some(error.to_string()),
        }
    }
    let mut navigation = page_navigation(&client, &identifier, &extracted_by, wanted).await?;
    navigation.requested_page = requested;
    let source_changed = expected_revision.is_some_and(|expected| expected != navigation.revision);

    let body = match navigation.page {
        None if navigation.stored_count == 0 => TextPageBody::EmptySource,
        None => TextPageBody::Absent,
        Some(page_id) => match page_body(&client, &identifier, &extracted_by, page_id).await? {
            // The row went away between the two reads.
            None => TextPageBody::Absent,
            Some((text, version)) => {
                let (spans, highlight_error) = if query.is_empty() {
                    (plain_spans(text), None)
                } else {
                    match page_highlights(&identifier, &extracted_by, query, page_id).await {
                        Ok(Some(spans)) => (spans, None),
                        Ok(None) => (plain_spans(text), None),
                        Err(error) => (plain_spans(text), Some(error.to_string())),
                    }
                };
                TextPageBody::Text { page_id, version, spans, highlight_error }
            }
        },
    };
    Ok(TextPageView { navigation, body, match_error, source_changed })
}

/// One source-scoped match step for the website viewer: the nearest stored page beyond
/// `from` whose index row matches `find_query`.
pub async fn find_text_match_page(
    user: &CurrentUser,
    identifier: DocumentIdentifier,
    extracted_by: String,
    find_query: String,
    from: Option<u32>,
    direction: MatchDirection,
) -> anyhow::Result<TextMatchStep> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &identifier.collection_dataset).await?;
    let query = find_query.trim();
    if query.is_empty() {
        return Ok(TextMatchStep::NoMore);
    }
    let client = get_client_for_dataset(&identifier.collection_dataset).await?;
    let pages = StoredMatchPages { client: &client, identifier: &identifier, extracted_by: &extracted_by, find_query: query };
    next_matching_page(&pages, from, direction, MATCH_STEP_BATCHES, MATCH_BATCH_ROWS).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::Cell;

    fn stats(ids: &[u32], around: u32, version: u64) -> PageStats {
        PageStats {
            stored_count: ids.len() as u64,
            first_page: ids.iter().copied().min().unwrap_or(0),
            last_page: ids.iter().copied().max().unwrap_or(0),
            previous_page: ids.iter().copied().filter(|id| *id < around).max().unwrap_or(0),
            next_page: ids.iter().copied().filter(|id| *id > around).min().unwrap_or(0),
            stored_before: ids.iter().filter(|id| **id < around).count() as u64,
            selected_rows: ids.iter().filter(|id| **id == around).count() as u64,
            max_version: version,
        }
    }

    #[test]
    fn sparse_identifiers_count_stored_entries_and_not_the_highest_identifier() {
        let ids = [3, 7, 12];
        let last = navigation_from_stats("pdftotext", Some(12), &stats(&ids, 12, 5));
        assert_eq!((last.page, last.position, last.stored_count), (Some(12), Some(3), 3));
        assert_eq!((last.previous_page, last.next_page), (Some(7), None));
        assert_eq!(last.unit, TextSourceUnit::DocumentPage);
        let first = navigation_from_stats("pdftotext", Some(3), &stats(&ids, 3, 5));
        assert_eq!((first.position, first.previous_page, first.next_page), (Some(1), None, Some(7)));
    }

    #[test]
    fn an_absent_identifier_stays_requested_and_names_both_neighbours() {
        let absent = navigation_from_stats("pdftotext", Some(9), &stats(&[3, 7, 12], 9, 5));
        assert_eq!(absent.page, None);
        assert_eq!(absent.position, None);
        assert_eq!(absent.requested_page, Some(9));
        assert_eq!((absent.previous_page, absent.next_page), (Some(7), Some(12)));
        let below = navigation_from_stats("pdftotext", Some(1), &stats(&[3, 7, 12], 1, 5));
        assert_eq!((below.page, below.previous_page, below.next_page), (None, None, Some(3)));
    }

    #[test]
    fn an_empty_source_has_no_page_and_the_revision_follows_the_writer_version() {
        let empty = navigation_from_stats("raw_text", None, &stats(&[], 0, 0));
        assert_eq!((empty.page, empty.first_page, empty.stored_count), (None, None, 0));
        assert_ne!(source_revision(&stats(&[1, 2], 1, 5)), source_revision(&stats(&[1, 2], 1, 6)));
    }

    #[test]
    fn duplicate_rows_fold_to_one_page_and_the_boundary_crosses_them() {
        let batch = fold_match_rows(&[4, 4, 9, 9, 9], 4);
        assert_eq!(batch.pages, vec![4, 9]);
        assert_eq!(batch.continue_after, Some(9), "the fifth row proves that more rows exist");
        let last = fold_match_rows(&[4, 9, 9], 4);
        assert_eq!(last, MatchBatch { pages: vec![4, 9], continue_after: None });
        assert_eq!(fold_match_rows(&[], 4), MatchBatch::default());
    }

    /// Page identities 1 to 1,500 of one source. Every page except 1,000 to 1,009 matches,
    /// pages 300 and 301 are each indexed three times, and index rows 600 to 899 name pages
    /// with no stored text.
    struct FixtureMatches {
        batches: Cell<usize>,
    }

    impl FixtureMatches {
        fn matches(page: u32) -> bool {
            (1..=1_500).contains(&page) && !(1_000..=1_009).contains(&page)
        }
        fn copies(page: u32) -> usize {
            if page == 300 || page == 301 { 3 } else { 1 }
        }
        fn stored_page(page: u32) -> bool {
            !(600..=899).contains(&page)
        }
    }

    impl MatchPages for FixtureMatches {
        async fn batch(&self, after: Option<u32>, direction: MatchDirection, limit: usize) -> anyhow::Result<MatchBatch> {
            self.batches.set(self.batches.get() + 1);
            let mut rows = Vec::new();
            let ids: Box<dyn Iterator<Item = u32>> = match direction {
                MatchDirection::Forward => Box::new(after.map_or(1, |a| a + 1)..=1_500),
                MatchDirection::Backward => Box::new((1..after.unwrap_or(1_501)).rev()),
            };
            for page in ids.filter(|page| Self::matches(*page)) {
                for _ in 0..Self::copies(page) {
                    rows.push(page);
                }
                if rows.len() > limit {
                    break;
                }
            }
            rows.truncate(limit + 1);
            Ok(fold_match_rows(&rows, limit))
        }

        async fn stored(&self, pages: &[u32]) -> anyhow::Result<BTreeSet<u32>> {
            Ok(pages.iter().copied().filter(|page| Self::stored_page(*page)).collect())
        }
    }

    async fn walk(direction: MatchDirection, start: Option<u32>) -> Vec<u32> {
        let pages = FixtureMatches { batches: Cell::new(0) };
        let mut seen = Vec::new();
        let mut from = start;
        loop {
            match next_matching_page(&pages, from, direction, MATCH_STEP_BATCHES, MATCH_BATCH_ROWS).await.unwrap() {
                TextMatchStep::Found { page_id } => {
                    seen.push(page_id);
                    from = Some(page_id);
                }
                TextMatchStep::NoMore => break,
                TextMatchStep::Incomplete { resume_after } => from = Some(resume_after),
            }
        }
        seen
    }

    fn expected() -> Vec<u32> {
        (1..=1_500).filter(|page| FixtureMatches::matches(*page) && FixtureMatches::stored_page(*page)).collect()
    }

    #[tokio::test]
    async fn forward_steps_pass_the_old_row_limit_and_reach_the_final_match_once_each() {
        let seen = walk(MatchDirection::Forward, None).await;
        assert_eq!(seen, expected());
        assert_eq!(seen.last(), Some(&1_500));
        assert!(seen.len() > 1_000);
    }

    #[tokio::test]
    async fn backward_steps_visit_the_same_pages_in_reverse() {
        let mut seen = walk(MatchDirection::Backward, None).await;
        seen.reverse();
        assert_eq!(seen, expected());
    }

    #[tokio::test]
    async fn a_step_from_a_page_without_matches_finds_the_nearest_match_and_never_wraps() {
        let pages = FixtureMatches { batches: Cell::new(0) };
        let next = next_matching_page(&pages, Some(1_004), MatchDirection::Forward, 5, 200).await.unwrap();
        assert_eq!(next, TextMatchStep::Found { page_id: 1_010 });
        let previous = next_matching_page(&pages, Some(1_004), MatchDirection::Backward, 5, 200).await.unwrap();
        assert_eq!(previous, TextMatchStep::Found { page_id: 999 });
        assert_eq!(next_matching_page(&pages, Some(1_500), MatchDirection::Forward, 5, 200).await.unwrap(), TextMatchStep::NoMore);
        assert_eq!(next_matching_page(&pages, Some(1), MatchDirection::Backward, 5, 200).await.unwrap(), TextMatchStep::NoMore);
    }

    #[tokio::test]
    async fn obsolete_rows_advance_the_boundary_and_an_exhausted_allowance_is_resumable() {
        let pages = FixtureMatches { batches: Cell::new(0) };
        let step = next_matching_page(&pages, Some(599), MatchDirection::Forward, 1, 100).await.unwrap();
        assert_eq!(step, TextMatchStep::Incomplete { resume_after: 699 });
        let step = next_matching_page(&pages, Some(599), MatchDirection::Forward, 5, 100).await.unwrap();
        assert_eq!(step, TextMatchStep::Found { page_id: 900 });
        assert_eq!(pages.batches.get(), 1 + 4, "each batch advances past the obsolete rows it read");
    }
}
