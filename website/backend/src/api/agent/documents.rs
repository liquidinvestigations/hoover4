//! The document routes: `documents/read`, `documents/search_text`, `documents/sources`,
//! `documents/metadata`, `documents/email`, `documents/diff_sources` and `documents/pdf_search`.

use super::*;
use common::document_sources::DocumentArchiveSourceItem;
use crate::api::documents::search_document_itemcount::SourceCount;
use crate::api::documents::document_text::{self, MATCH_BATCH_ROWS, MatchBatch, MatchPages as _, PageHighlights};
use common::document_text_pages::MatchDirection;

#[cfg(test)]
#[path = "document_pages_tests.rs"]
mod document_pages_tests;

// ===================================================================================
// documents: the shared reads
// ===================================================================================

/// Resolves one document of a collection that the caller may read, in a dataset that
/// holds `row` when one does.
pub(super) async fn document_identifier(
    user: &CurrentUser,
    headers: &HeaderMap,
    collectionname: &str,
    file_hash: &str,
    row: DatasetRow,
) -> Result<DocumentIdentifier, AgentError> {
    validate_plain_text(file_hash)?;
    let header = requested_collections_header(headers);
    let permitted = permitted_collectionnames(user, &header).await?;
    let collection_dataset = resolve_document_dataset(user, &permitted, collectionname, file_hash, row).await?;
    Ok(DocumentIdentifier { collection_dataset, file_hash: file_hash.to_string() })
}

/// The text sources of one document, each with its lowest and highest page id.
async fn text_sources_of(
    user: &CurrentUser,
    identifier: &DocumentIdentifier,
) -> Result<Vec<common::document_sources::DocumentTextSourceItem>, AgentError> {
    get_document_sources::get_text_sources(user, identifier.clone()).await.map_err(AgentError::from_anyhow)
}

/// The revision of one text source: its stored page count, and the revision string of the
/// website text viewer ([`document_text::source_revision`]).
#[derive(Debug, Clone, PartialEq, Eq)]
struct SourceRevision {
    stored_count: u64,
    revision: String,
}

/// The stored text pages of one document, as the document routes read them. Each
/// method reads at most one page, so a call costs the same on a document of any length.
trait TextPages {
    /// Gives the revision of a source: the stored page count, the page range and the
    /// highest writer version. It loads no page text.
    async fn revision(&self, extracted_by: &str) -> Result<SourceRevision, AgentError>;
    /// Reads one page, or `None` when the page id has no stored row.
    async fn page_text(&self, extracted_by: &str, page_id: u32) -> Result<Option<String>, AgentError>;
    /// Gives the lowest stored page id above `page_id`.
    async fn page_after(&self, extracted_by: &str, page_id: u32) -> Result<Option<u32>, AgentError>;
    /// Reads the query hit spans of one page against its stored body, with the rule of
    /// the website text viewer ([`document_text::highlights_for_body`]). An index row
    /// that holds another text of the page gives [`PageHighlights::IndexDiffers`].
    async fn page_hits(&self, extracted_by: &str, page_id: u32, query: &str) -> Result<PageHighlights, AgentError>;
    /// Reads one batch of the stored pages of one source that match `query`, ascending
    /// after `after`. Only this source's index rows count against the batch, and a row
    /// whose page has no stored text is dropped.
    async fn matching_pages(&self, extracted_by: &str, query: &str, after: Option<u32>) -> Result<MatchBatch, AgentError>;
}

/// [`TextPages`] over `text_content` and the document's Manticore shard. The route has
/// checked the caller's access to the document.
struct StoredTextPages<'a> {
    identifier: &'a DocumentIdentifier,
    collectionname: &'a str,
    deadline: Deadline,
}

impl TextPages for StoredTextPages<'_> {
    async fn revision(&self, extracted_by: &str) -> Result<SourceRevision, AgentError> {
        let client = self.deadline.collection_client(self.collectionname);
        let stats = document_text::page_stats(&client, self.identifier, extracted_by, 0)
            .await
            .map_err(AgentError::from_anyhow)?;
        Ok(SourceRevision { stored_count: stats.stored_count, revision: document_text::source_revision(&stats) })
    }

    async fn page_text(&self, extracted_by: &str, page_id: u32) -> Result<Option<String>, AgentError> {
        let client = self.deadline.collection_client(self.collectionname);
        document_text::page_body(&client, self.identifier, extracted_by, page_id)
            .await
            .map(|body| body.map(|(text, _version)| text))
            .map_err(AgentError::from_anyhow)
    }

    async fn page_after(&self, extracted_by: &str, page_id: u32) -> Result<Option<u32>, AgentError> {
        self.deadline
            .collection_client(self.collectionname)
            .query("SELECT page_id FROM text_content WHERE collection_dataset = ? AND file_hash = ? AND extracted_by = ? AND page_id > ? ORDER BY page_id LIMIT 1")
            .bind(&self.identifier.collection_dataset)
            .bind(&self.identifier.file_hash)
            .bind(extracted_by)
            .bind(page_id)
            .fetch_optional()
            .await
            .map_err(AgentError::from_clickhouse)
    }

    async fn page_hits(&self, extracted_by: &str, page_id: u32, query: &str) -> Result<PageHighlights, AgentError> {
        let Some(stored) = self.page_text(extracted_by, page_id).await? else {
            return Ok(PageHighlights::NoMatch);
        };
        let rows = search_document_text::page_highlight_texts(self.identifier, query, extracted_by, page_id)
            .await
            .map_err(AgentError::from_anyhow)?;
        Ok(document_text::highlights_for_body(&rows, &stored))
    }

    async fn matching_pages(&self, extracted_by: &str, query: &str, after: Option<u32>) -> Result<MatchBatch, AgentError> {
        let client = self.deadline.collection_client(self.collectionname);
        let pages = document_text::StoredMatchPages { client: &client, identifier: self.identifier, extracted_by, find_query: query };
        let mut batch = pages.batch(after, MatchDirection::Forward, MATCH_BATCH_ROWS).await.map_err(AgentError::from_anyhow)?;
        let stored = pages.stored(&batch.pages).await.map_err(AgentError::from_anyhow)?;
        batch.pages.retain(|page| stored.contains(page));
        Ok(batch)
    }
}

/// The `source` of one document text source: the revision of the website text viewer,
/// which changes when a page is added or removed and when a writer stores a newer body of a
/// page. A source string of the older form, with the page count and the highest page id
/// only, never equals it, so an older continuation gets the `source_changed` answer.
fn text_source_fingerprint(file_hash: &str, extracted_by: &str, revision: &SourceRevision) -> String {
    format!("{file_hash}:{extracted_by}:{}", revision.revision)
}

/// Reads the one page `page_id`, and the id of the stored page after it.
async fn read_text_page<P: TextPages>(
    pages: &P,
    extracted_by: &str,
    page_id: u32,
) -> Result<(String, Option<u32>), AgentError> {
    let Some(text) = pages.page_text(extracted_by, page_id).await? else {
        return Err(AgentError::not_found(format!(
            "the source {extracted_by:?} has no stored page {page_id}; page ids can have gaps, and doc_sources gives the range"
        )));
    };
    let next = pages.page_after(extracted_by, page_id).await?;
    Ok((text, next))
}

/// The checked query hits of one text source, page by page in page order.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
struct SourceHitCounts {
    /// `(page_id, hits)` of each page whose index row holds its stored text.
    pages: Vec<(u32, u64)>,
    /// True when the index read stayed under [`search_document_text::DOCUMENT_HIT_ROW_LIMIT`] and every matching
    /// index row of the source holds the stored text of its page.
    exact: bool,
}

impl SourceHitCounts {
    fn hits(&self) -> u64 {
        self.pages.iter().map(|(_, count)| count).sum()
    }

    /// `exact` or `lower_bound`, the `count_state` of a counted read.
    fn state(&self) -> &'static str {
        if self.exact { COUNT_EXACT } else { COUNT_LOWER_BOUND }
    }
}

/// Every matching index row was checked against the stored text.
const COUNT_EXACT: &str = "exact";
/// The count holds the checked hits only.
const COUNT_LOWER_BOUND: &str = "lower_bound";

/// The query hits of one text source, checked against the stored text with the count of
/// the website source selector ([`search_document_itemcount::validated_text_counts`]). Each
/// page counts once, from its first index row that holds its stored text. The count is
/// exact when the index read stayed under [`search_document_text::DOCUMENT_HIT_ROW_LIMIT`] rows and no matching
/// index row of the source holds another text. A query that the index refuses is an
/// error, which is not an empty count.
async fn source_hit_counts(
    user: &CurrentUser,
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    query: &str,
) -> Result<SourceHitCounts, AgentError> {
    permissions::assert_can_read(user, &identifier.collection_dataset).await.map_err(AgentError::from_anyhow)?;
    let counts = search_document_itemcount::validated_text_counts(identifier, query)
        .await
        .map_err(AgentError::from_anyhow)?;
    Ok(source_counts_of(&counts, extracted_by))
}

/// The hits of one source among the checked hits of a document.
fn source_counts_of(counts: &search_document_itemcount::TextCounts, extracted_by: &str) -> SourceHitCounts {
    let mut pages: Vec<(u32, u64)> = counts
        .hits
        .iter()
        .filter(|row| row.extracted_by == extracted_by && row.hit_count > 0)
        .map(|row| (row.page_id, row.hit_count))
        .collect();
    pages.sort_unstable();
    SourceHitCounts { pages, exact: !counts.stopped_at_limit && !counts.differs.contains(extracted_by) }
}

/// The page that a `page` argument asks for. No page and page 0 ask for no page: an
/// older tool description used 0 for "the first page", and page ids can start above 1. A
/// positive page stays exact.
fn requested_page(page: Option<u32>) -> Option<u32> {
    page.filter(|page| *page != 0)
}

/// The page that one read opens: the requested page, else the page with the most query
/// hits, else the first stored page of the source (`min_page`, from the stored rows).
fn chosen_page(wanted_page: Option<u32>, counts: &[(u32, u64)], min_page: u32) -> u32 {
    wanted_page.or_else(|| most_hits_page(counts)).unwrap_or(min_page)
}

/// The page with the most hits, the lowest page id on a tie, as the website's viewer
/// opens it.
fn most_hits_page(pages: &[(u32, u64)]) -> Option<u32> {
    pages.iter().max_by(|a, b| a.1.cmp(&b.1).then(b.0.cmp(&a.0))).map(|(page, _)| *page)
}

/// Characters of page text on each side of a hit in its snippet.
const HIT_SNIPPET_CONTEXT_CHARS: usize = 80;

/// The hits of one page, from its highlight spans, with character offsets in the page.
fn hits_from_spans(page: u32, spans: &[HighlightTextSpan]) -> Vec<AgentTextHit> {
    let text: Vec<char> = spans.iter().flat_map(|span| span.text.chars()).collect();
    let mut hits = Vec::new();
    let mut offset = 0usize;
    for span in spans {
        let length = span.text.chars().count();
        if span.is_highlighted {
            let from = offset.saturating_sub(HIT_SNIPPET_CONTEXT_CHARS);
            let to = (offset + length + HIT_SNIPPET_CONTEXT_CHARS).min(text.len());
            hits.push(AgentTextHit {
                page,
                ordinal: hits.len() as u32,
                start: offset as u32,
                end: (offset + length) as u32,
                snippet: text[from..to].iter().collect(),
            });
        }
        offset += length;
    }
    hits
}

/// One page of the hits of a source, its next position, and whether a page it read had
/// an index row with another text than its stored body.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
struct TextHitsPage {
    hits: Vec<AgentTextHit>,
    next_position: Option<AgentPosition>,
    /// A page whose index rows all hold another text gave no hit, so the hits that the
    /// source has are not all known.
    unverified: bool,
}

/// The checked spans of one page, and whether its index rows hold another text.
async fn checked_spans<P: TextPages>(
    pages: &P,
    extracted_by: &str,
    page_id: u32,
    query: &str,
) -> Result<(Vec<HighlightTextSpan>, bool), AgentError> {
    Ok(match pages.page_hits(extracted_by, page_id, query).await? {
        PageHighlights::Spans(spans) => (spans, false),
        PageHighlights::NoMatch => (Vec::new(), false),
        PageHighlights::IndexDiffers => (Vec::new(), true),
    })
}

/// One page of at most `limit` hits after `after`, in page order.
///
/// It walks the matching stored pages of this one source in batches of
/// [`MATCH_BATCH_ROWS`], so a source with more than [`search_document_text::DOCUMENT_HIT_ROW_LIMIT`] matching
/// pages continues to its last hit and other sources take no part of the allowance. It
/// reads the hits of the pages it returns, plus the page of `after` to find the hits left
/// on it. A hit comes only from an index row that holds the stored body of its page. The
/// position is absent when no hit remains.
async fn text_hits_page<P: TextPages>(
    pages: &P,
    extracted_by: &str,
    query: &str,
    after: Option<(u32, u32)>,
    limit: usize,
) -> Result<TextHitsPage, AgentError> {
    let mut hits: Vec<AgentTextHit> = Vec::new();
    let mut unverified = false;
    let position = |hits: &[AgentTextHit]| {
        let last = hits.last().map(|hit| (hit.page, hit.ordinal)).unwrap_or_default();
        Some(AgentPosition::HitKey { page_id: last.0, ordinal: last.1 })
    };
    if let Some((after_page, ordinal)) = after {
        let (spans, differs) = checked_spans(pages, extracted_by, after_page, query).await?;
        unverified |= differs;
        let page_hits = hits_from_spans(after_page, &spans);
        let available = page_hits.len();
        for hit in page_hits.into_iter().skip(ordinal as usize + 1) {
            hits.push(hit);
            if hits.len() == limit {
                let more_here = hits.last().is_some_and(|hit| (hit.ordinal as usize) + 1 < available);
                if more_here {
                    let next_position = position(&hits);
                    return Ok(TextHitsPage { hits, next_position, unverified });
                }
                let later = pages.matching_pages(extracted_by, query, Some(after_page)).await?;
                let more_later = !later.pages.is_empty() || later.continue_after.is_some();
                let next_position = if more_later { position(&hits) } else { None };
                return Ok(TextHitsPage { hits, next_position, unverified });
            }
        }
    }
    let mut boundary = after.map(|(page, _)| page);
    loop {
        let batch = pages.matching_pages(extracted_by, query, boundary).await?;
        for (index, &page_id) in batch.pages.iter().enumerate() {
            let (spans, differs) = checked_spans(pages, extracted_by, page_id, query).await?;
            unverified |= differs;
            let page_hits = hits_from_spans(page_id, &spans);
            let available = page_hits.len();
            for hit in page_hits {
                hits.push(hit);
                if hits.len() == limit {
                    let more_here = hits.last().is_some_and(|hit| (hit.ordinal as usize) + 1 < available);
                    let more_later = index + 1 < batch.pages.len() || batch.continue_after.is_some();
                    let next_position = if more_here || more_later { position(&hits) } else { None };
                    return Ok(TextHitsPage { hits, next_position, unverified });
                }
            }
        }
        match batch.continue_after {
            Some(next) => boundary = Some(next),
            None => return Ok(TextHitsPage { hits, next_position: None, unverified }),
        }
    }
}

// ===================================================================================
// documents/read
// ===================================================================================

pub async fn documents_read(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentsReadRequest>,
) -> AgentResult<DocumentsReadResponse> {
    let deadline = Deadline::start();
    deadline.run(documents_read_body(&user, &headers, body, deadline)).await.map(Json)
}

/// One requested document, resolved before any page is read.
struct PlannedRead {
    file_hash: String,
    identifier: DocumentIdentifier,
    chosen: Option<common::document_sources::DocumentTextSourceItem>,
    revision: SourceRevision,
    /// The archive facts of a document without a text source that is an archive.
    archive: Option<DocumentArchiveSourceItem>,
    /// The image of an image or a video document.
    image: Option<AgentDocumentImage>,
}

async fn documents_read_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: DocumentsReadRequest,
    deadline: Deadline,
) -> Result<DocumentsReadResponse, AgentError> {
    if body.file_hash.is_empty() || body.file_hash.len() > MAX_READ_DOCUMENTS {
        return Err(AgentError::invalid_argument(format!(
            "file_hash takes 1 to {MAX_READ_DOCUMENTS} hashes"
        )));
    }
    if body.length == Some(0) {
        return Err(AgentError::invalid_argument("length must be a positive character count"));
    }
    let length = body.length.unwrap_or(6_000);
    let (wanted_source, wanted_page, wanted_offset) = match body.position.clone() {
        None => (body.source.clone(), requested_page(body.page), body.offset),
        Some(AgentPosition::TextPage { source, page_id, offset }) => (Some(source), Some(page_id), offset),
        Some(other) => return Err(wrong_position_kind("documents/read", &other, "TextPage")),
    };
    let query = body.query.clone().filter(|query| !query.is_empty());

    let mut planned = Vec::with_capacity(body.file_hash.len());
    for file_hash in &body.file_hash {
        let identifier = document_identifier(user, headers, &body.collectionname, file_hash, DatasetRow::Any).await?;
        let sources = text_sources_of(user, &identifier).await?;
        let chosen = match (&body.position, &wanted_source) {
            (Some(_), Some(wanted)) => Some(
                sources
                    .iter()
                    .find(|source| &source.extracted_by == wanted)
                    .cloned()
                    .ok_or_else(|| AgentError::not_found(format!("no text source {wanted:?}")))?,
            ),
            (_, wanted) => wanted
                .as_ref()
                .and_then(|wanted| sources.iter().find(|source| &source.extracted_by == wanted))
                .or_else(|| sources.first())
                .cloned(),
        };
        let pages = StoredTextPages { identifier: &identifier, collectionname: &body.collectionname, deadline };
        let revision = match &chosen {
            Some(source) => pages.revision(&source.extracted_by).await?,
            None => SourceRevision { stored_count: 0, revision: String::new() },
        };
        let archive = match &chosen {
            Some(_) => None,
            None => get_document_sources::archive_info_for(user, &identifier).await,
        };
        let image = get_document_sources::image_info_for(user, &identifier).await;
        planned.push(PlannedRead { file_hash: file_hash.clone(), identifier, chosen, revision, archive, image });
    }
    let source = planned
        .iter()
        .map(|plan| match &plan.chosen {
            Some(chosen) => text_source_fingerprint(&plan.file_hash, &chosen.extracted_by, &plan.revision),
            None => format!("{}:no_text", plan.file_hash),
        })
        .collect::<Vec<_>>()
        .join("|");
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let mut documents = Vec::with_capacity(planned.len());
    let mut partial = false;
    for plan in &planned {
        let read = read_one_document(user, &body.collectionname, plan, query.as_deref(), wanted_page, wanted_offset, length, deadline);
        match tokio::time::timeout_at(deadline.0, read).await {
            Ok(result) => {
                let (document, stopped) = result?;
                partial |= stopped;
                documents.push(document);
            }
            Err(_) => {
                partial = true;
                documents.push(AgentDocumentText {
                    collectionname: body.collectionname.clone(),
                    collection_dataset: plan.identifier.collection_dataset.clone(),
                    file_hash: plan.file_hash.clone(),
                    path: String::new(),
                    title: String::new(),
                    source_used: plan.chosen.as_ref().map(|c| c.extracted_by.clone()).unwrap_or_default(),
                    page: None,
                    min_page: plan.chosen.as_ref().map(|c| c.min_page),
                    max_page: plan.chosen.as_ref().map(|c| c.max_page),
                    text: String::new(),
                    text_start: 0, text_end: 0, text_length: 0, source_version: String::new(),
                    hit_count: 0,
                    hit_pages: Vec::new(),
                    count_state: "timed_out".to_string(),
                    next_position: None,
                    archive: None,
                    image: None,
                });
            }
        }
    }
    let (next_position, total) = match (documents.as_slice(), planned.as_slice()) {
        ([document], [plan]) => (document.next_position.clone(), Some(plan.revision.stored_count)),
        _ => (None, None),
    };
    Ok(DocumentsReadResponse { documents, page_info: AgentPageInfo { source, next_position, total, partial } })
}

/// Reads one page of one document. The second value is true when the hit count is a lower
/// bound.
async fn read_one_document(
    user: &CurrentUser,
    collectionname: &str,
    plan: &PlannedRead,
    query: Option<&str>,
    wanted_page: Option<u32>,
    wanted_offset: Option<u32>,
    length: u32,
    deadline: Deadline,
) -> Result<(AgentDocumentText, bool), AgentError> {
    let path = get_file_path::get_file_path(user, plan.identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .unwrap_or_default();
    let title = path.rsplit('/').next().unwrap_or(&path).to_string();
    let Some(chosen) = &plan.chosen else {
        return Ok((
            AgentDocumentText {
                collectionname: collectionname.to_string(),
                collection_dataset: plan.identifier.collection_dataset.clone(),
                file_hash: plan.file_hash.clone(),
                path,
                title,
                source_used: String::new(),
                page: None,
                min_page: None,
                max_page: None,
                text: String::new(),
                text_start: 0, text_end: 0, text_length: 0, source_version: String::new(),
                hit_count: 0,
                hit_pages: Vec::new(),
                count_state: "no_text".to_string(),
                next_position: None,
                archive: plan.archive.clone(),
                image: plan.image.clone(),
            },
            false,
        ));
    };
    let counts = match query {
        Some(query) => Some(source_hit_counts(user, &plan.identifier, &chosen.extracted_by, query).await?),
        None => None,
    };
    let stopped = counts.as_ref().is_some_and(|counts| !counts.exact);
    let count_pages = counts.as_ref().map(|counts| counts.pages.as_slice()).unwrap_or_default();
    let page_id = chosen_page(wanted_page, count_pages, chosen.min_page);
    let pages = StoredTextPages { identifier: &plan.identifier, collectionname, deadline };
    let (text, text_start, text_end, text_length, next_position) =
        read_text_range(&pages, &chosen.extracted_by, page_id, query, wanted_offset, length).await?;
    Ok((
        AgentDocumentText {
            collectionname: collectionname.to_string(),
            collection_dataset: plan.identifier.collection_dataset.clone(),
            file_hash: plan.file_hash.clone(),
            path,
            title,
            source_used: chosen.extracted_by.clone(),
            page: Some(page_id),
            min_page: Some(chosen.min_page),
            max_page: Some(chosen.max_page),
            text, text_start, text_end, text_length,
            source_version: text_source_fingerprint(&plan.file_hash, &chosen.extracted_by, &plan.revision),
            hit_count: counts.as_ref().map_or(0, SourceHitCounts::hits),
            hit_pages: count_pages.iter().take(MAX_HIT_PAGES).map(|(page, _)| *page).collect(),
            count_state: counts.as_ref().map_or("read", SourceHitCounts::state).to_string(),
            next_position,
            archive: None,
            image: plan.image.clone(),
        },
        stopped,
    ))
}

/// Opens a matching passage or explicit character range within one stored page.
async fn read_text_range<P: TextPages>(
    pages: &P,
    extracted_by: &str,
    page_id: u32,
    query: Option<&str>,
    wanted_offset: Option<u32>,
    length: u32,
) -> Result<(String, u32, u32, u32, Option<AgentPosition>), AgentError> {
    let (whole, next) = read_text_page(pages, extracted_by, page_id).await?;
    let offset = match (wanted_offset, query) {
        (Some(offset), _) => offset,
        (None, Some(query)) => {
            let (spans, _) = checked_spans(pages, extracted_by, page_id, query).await?;
            matching_passage(&spans, length).map(|(start, end)| {
                let before = 1_000.min(length.saturating_sub(end - start));
                start.saturating_sub(before)
            }).unwrap_or(0)
        }
        _ => 0,
    };
    let (text, text_start, text_end, text_length) = text_range(&whole, offset, length)?;
    let next_position = if text_end < text_length {
        Some(AgentPosition::TextPage { source: extracted_by.to_string(), page_id, offset: Some(text_end) })
    } else {
        next.map(|page_id| AgentPosition::TextPage { source: extracted_by.to_string(), page_id, offset: Some(0) })
    };
    Ok((text, text_start, text_end, text_length, next_position))
}

/// Selects nearby distinct highlighted values before an isolated word match.
fn matching_passage(spans: &[HighlightTextSpan], length: u32) -> Option<(u32, u32)> {
    let mut hits = Vec::new();
    let mut offset = 0;
    for span in spans {
        let end = offset + span.text.chars().count() as u32;
        if span.is_highlighted {
            hits.push((offset, end, span.text.to_lowercase()));
        }
        offset = end;
    }
    let mut best = None;
    let mut distinct = 0;
    for (index, (start, _, _)) in hits.iter().enumerate() {
        let mut values = std::collections::BTreeSet::new();
        for (_, end, text) in &hits[index..] {
            if end - start > length.min(1_000) && !values.is_empty() { break; }
            values.insert(text);
            let narrower = best.is_some_and(|(a, b)| end - start < b - a);
            if values.len() > distinct || (values.len() == distinct && distinct > 1 && narrower) {
                best = Some((*start, *end));
                distinct = values.len();
            }
        }
    }
    best
}

/// Reads a repeatable range with Unicode character offsets and an exclusive end.
fn text_range(text: &str, offset: u32, length: u32) -> Result<(String, u32, u32, u32), AgentError> {
    let chars: Vec<char> = text.chars().collect();
    let total = chars.len() as u32;
    if offset > total {
        return Err(AgentError::invalid_argument(format!("offset {offset} exceeds the page length {total}")));
    }
    let end = offset.saturating_add(length).min(total);
    Ok((chars[offset as usize..end as usize].iter().collect(), offset, end, total))
}

// ===================================================================================
// documents/search_text
// ===================================================================================

pub async fn documents_search_text(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentsSearchTextRequest>,
) -> AgentResult<DocumentsSearchTextResponse> {
    let deadline = Deadline::start();
    deadline.run(documents_search_text_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn documents_search_text_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: DocumentsSearchTextRequest,
    deadline: Deadline,
) -> Result<DocumentsSearchTextResponse, AgentError> {
    if body.query.trim().is_empty() {
        return Err(AgentError::invalid_argument("query must not be empty"));
    }
    let after = match &body.position {
        None => None,
        Some(AgentPosition::HitKey { page_id, ordinal }) => Some((*page_id, *ordinal)),
        Some(other) => return Err(wrong_position_kind("documents/search_text", other, "HitKey")),
    };
    let identifier = document_identifier(user, headers, &body.collectionname, &body.file_hash, DatasetRow::Any).await?;
    let sources = text_sources_of(user, &identifier).await?;
    let chosen = match &body.source {
        Some(wanted) => sources
            .iter()
            .find(|source| &source.extracted_by == wanted)
            .ok_or_else(|| AgentError::not_found(format!("no text source {wanted:?}")))?,
        None => match sources.first() {
            Some(first) => first,
            None => {
                // An archive has no text of its own. Its facts tell the caller how to reach
                // the extracted files.
                let Some(archive) = get_document_sources::archive_info_for(user, &identifier).await else {
                    return Err(AgentError::not_found("the document has no text source"));
                };
                let source = format!("{}:archive", body.file_hash);
                verify_expected_source(body.expected_source.as_deref(), &source)?;
                return Ok(DocumentsSearchTextResponse {
                    source_used: String::new(),
                    hit_count: 0,
                    count_state: COUNT_EXACT.to_string(),
                    hits: Vec::new(),
                    archive: Some(archive),
                    page_info: AgentPageInfo { source, next_position: None, total: Some(0), partial: false },
                });
            }
        },
    };
    let pages = StoredTextPages { identifier: &identifier, collectionname: &body.collectionname, deadline };
    let revision = pages.revision(&chosen.extracted_by).await?;
    let source = text_source_fingerprint(&body.file_hash, &chosen.extracted_by, &revision);
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let mut counts = source_hit_counts(user, &identifier, &chosen.extracted_by, &body.query).await?;
    let page = text_hits_page(&pages, &chosen.extracted_by, &body.query, after, TEXT_HITS_PAGE_SIZE).await?;
    // A page of hits that met an index row with another text makes the count a lower
    // bound too, so the count and the hits agree.
    counts.exact &= !page.unverified;
    Ok(search_text_response(chosen.extracted_by.clone(), &counts, page, source))
}

/// The `documents/search_text` response of one page of checked hits. `total` is the hit
/// count only when the count is exact. A lower bound is `partial`.
fn search_text_response(source_used: String, counts: &SourceHitCounts, page: TextHitsPage, source: String) -> DocumentsSearchTextResponse {
    let hit_count = counts.hits();
    DocumentsSearchTextResponse {
        source_used,
        hit_count,
        count_state: counts.state().to_string(),
        hits: page.hits,
        archive: None,
        page_info: AgentPageInfo {
            source,
            next_position: page.next_position,
            total: counts.exact.then_some(hit_count),
            partial: !counts.exact,
        },
    }
}

// ===================================================================================
// documents/sources
// ===================================================================================

pub async fn documents_sources(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentsSourcesRequest>,
) -> AgentResult<DocumentsSourcesResponse> {
    let deadline = Deadline::start();
    deadline.run(documents_sources_body(&user, &headers, body, deadline)).await.map(Json)
}

/// Time the PDF counts leave to the rest of the route, so that a PDF count that does not
/// finish returns `timed_out` for its source and not a 504 for the whole route.
const PDF_COUNT_MARGIN: std::time::Duration = std::time::Duration::from_secs(2);

/// One listed source, with no count yet.
fn describe_source(source: &DocumentSourceItem) -> Option<AgentDocumentSource> {
    let described = match source {
        DocumentSourceItem::Text(text) => AgentDocumentSource {
            kind: "text".into(),
            source: text.extracted_by.clone(),
            label: common::document_sources::text_source_label(&text.extracted_by),
            min_page: Some(text.min_page),
            max_page: Some(text.max_page),
            ..Default::default()
        },
        DocumentSourceItem::Pdf(pdf) => AgentDocumentSource {
            kind: "pdf".into(),
            source: pdf.source_name(),
            label: pdf.label(),
            page_count: Some(pdf.page_count),
            parts: pdf.parts.clone(),
            ..Default::default()
        },
        DocumentSourceItem::Email(email) => AgentDocumentSource {
            kind: "email".into(),
            source: "email_parser".into(),
            label: "Email".into(),
            min_page: email.has_body.then_some(email.min_page),
            max_page: email.has_body.then_some(email.max_page),
            ..Default::default()
        },
        DocumentSourceItem::Table(table) => AgentDocumentSource {
            kind: "table".into(),
            label: table.label(),
            sheet_count: Some(table.sheet_count),
            row_count: Some(table.row_count),
            column_count: Some(table.column_count),
            ..Default::default()
        },
        DocumentSourceItem::Image(_) => AgentDocumentSource { kind: "image".into(), label: "Image".into(), ..Default::default() },
        DocumentSourceItem::Video(_) => AgentDocumentSource { kind: "video".into(), label: "Video".into(), ..Default::default() },
        DocumentSourceItem::Audio(_) => AgentDocumentSource { kind: "audio".into(), label: "Audio".into(), ..Default::default() },
        DocumentSourceItem::FileLocations | DocumentSourceItem::Metadata | DocumentSourceItem::Archive(_) => return None,
    };
    Some(AgentDocumentSource { count_state: "no_query".into(), ..described })
}

/// The `hit_count` and `count_state` of one counted source. A count that stopped at the
/// text read's row limit is `partial`, and a count that did not finish has no number.
fn source_count_state(count: SourceCount) -> (Option<u64>, &'static str) {
    match count {
        SourceCount::Counted { hits, stopped_at_limit: false } => (Some(hits), "counted"),
        SourceCount::Counted { hits, stopped_at_limit: true } => (Some(hits), "partial"),
        SourceCount::TimedOut => (None, "timed_out"),
        SourceCount::Failed => (None, "failed"),
        SourceCount::Unavailable => (None, "unavailable"),
    }
}

async fn documents_sources_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: DocumentsSourcesRequest,
    deadline: Deadline,
) -> Result<DocumentsSourcesResponse, AgentError> {
    let identifier = document_identifier(user, headers, &body.collectionname, &body.file_hash, DatasetRow::Any).await?;
    let mut archive = None;
    let items: Vec<DocumentSourceItem> = get_document_sources::get_document_sources(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .into_iter()
        .filter_map(|item| match item {
            // The archive facts go to `archive`, so `sources` and the hit counts stay aligned.
            DocumentSourceItem::Archive(found) => {
                archive = Some(found);
                None
            }
            DocumentSourceItem::FileLocations | DocumentSourceItem::Metadata => None,
            other => Some(other),
        })
        .collect();
    let mut sources: Vec<AgentDocumentSource> = items.iter().filter_map(describe_source).collect();
    let source = format!(
        "{}:sources:{}",
        body.file_hash,
        sources
            .iter()
            .map(|s| format!("{}/{}/{}/{}", s.kind, s.source, s.max_page.unwrap_or(0), s.row_count.unwrap_or(0)))
            .collect::<Vec<_>>()
            .join(",")
    );
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let mut partial = false;
    if let Some(query) = body.query.clone().filter(|query| !query.is_empty()) {
        let pdf_timeout = deadline.remaining().saturating_sub(PDF_COUNT_MARGIN).max(std::time::Duration::from_secs(1));
        let counts = search_document_itemcount::search_document_item_count_with_timeout(
            user,
            identifier,
            query,
            items,
            pdf_timeout,
        )
        .await
        .map_err(AgentError::from_anyhow)?;
        // A query the index refuses fails the same way on every source, so the route
        // answers 400 as `documents/search_text` does.
        if let Some(error) = counts.text_error
            && crate::db_utils::manticore_utils::is_manticore_refusal(&error)
        {
            return Err(AgentError::from_anyhow(error));
        }
        for (described, (_, count)) in sources.iter_mut().zip(counts.counts) {
            let (hit_count, count_state) = source_count_state(count);
            described.hit_count = hit_count;
            described.count_state = count_state.into();
            partial |= count_state != "counted";
        }
    }
    let total = Some(sources.len() as u64);
    Ok(DocumentsSourcesResponse { sources, archive, page_info: AgentPageInfo { source, next_position: None, total, partial } })
}

// ===================================================================================
// documents/metadata
// ===================================================================================

/// The exact table list `RawMetadataCollector` asks for, copied here because the
/// metadata route composes the same reads the metadata tab renders.
fn raw_metadata_table_list() -> Vec<DocumentMetadataTableInfo> {
    vec![
        DocumentMetadataTableInfo::new("blobs", "blob_hash"),
        DocumentMetadataTableInfo::new("file_types", "hash"),
        DocumentMetadataTableInfo::new("file_type_canonical", "hash"),
        DocumentMetadataTableInfo::new3("tika_metadata", "hash", vec!["tika_metadata_json"]),
        DocumentMetadataTableInfo::new("archives", "archive_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "container_hash"),
        DocumentMetadataTableInfo::new("vfs_files", "hash"),
        DocumentMetadataTableInfo::new3("audio_metadata", "hash", vec!["audio_metadata_json"]),
        DocumentMetadataTableInfo::new3("email_headers", "email_hash", vec!["raw_headers_json"]),
        DocumentMetadataTableInfo::new3("image", "image_hash", vec!["image_metadata"]),
        DocumentMetadataTableInfo::new3("pdf_metadata", "hash", vec!["pdf_metadata_json"]),
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
        DocumentMetadataTableInfo::new3("video_metadata", "hash", vec!["video_metadata_json"]),
        DocumentMetadataTableInfo::new3("raw_ocr_results", "image_hash", vec!["raw_json"]),
        DocumentMetadataTableInfo::new("table_documents", "hash"),
        DocumentMetadataTableInfo::new("table_sheets", "hash"),
        DocumentMetadataTableInfo::new("table_columns", "hash"),
        DocumentMetadataTableInfo::new("processing_errors", "hash"),
    ]
}

/// Cuts every string inside `value` that is longer than [`MAX_METADATA_VALUE_CHARS`]
/// characters. The cut string becomes `{"text": <first part>, "cut": AgentCut}`, and
/// `field` names it by its JSON pointer from `pointer`.
fn cut_long_strings(value: &mut serde_json::Value, pointer: &str) {
    match value {
        serde_json::Value::String(text) if text.chars().count() > MAX_METADATA_VALUE_CHARS => {
            let kept: String = text.chars().take(MAX_METADATA_VALUE_CHARS).collect();
            let cut = AgentCut {
                field: pointer.to_string(),
                returned_bytes: kept.len() as u64,
                total_bytes: text.len() as u64,
            };
            *value = serde_json::json!({ "text": kept, "cut": cut });
        }
        serde_json::Value::Array(items) => {
            for (index, item) in items.iter_mut().enumerate() {
                cut_long_strings(item, &format!("{pointer}/{index}"));
            }
        }
        serde_json::Value::Object(map) => {
            for (key, item) in map.iter_mut() {
                let key = key.replace('~', "~0").replace('/', "~1");
                cut_long_strings(item, &format!("{pointer}/{key}"));
            }
        }
        _ => {}
    }
}

/// Replaces the `stored_in_clickhouse` flag of a `blobs` row with `bytes_stored_in`:
/// `clickhouse` or `object_storage`. A model read the raw `0` as "not stored".
fn name_blob_storage(row: &mut serde_json::Value) {
    let Some(map) = row.as_object_mut() else { return };
    let Some(flag) = map.remove("stored_in_clickhouse") else { return };
    let in_clickhouse = flag.as_u64().map(|n| n != 0).or_else(|| flag.as_bool())
        .or_else(|| flag.as_str().map(|s| s != "0" && !s.is_empty())).unwrap_or(false);
    map.insert("bytes_stored_in".into(),
               if in_clickhouse { "clickhouse".into() } else { "object_storage".into() });
}

pub async fn documents_metadata(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentsMetadataRequest>,
) -> AgentResult<DocumentsMetadataResponse> {
    Deadline::start().run(documents_metadata_body(&user, &headers, body)).await.map(Json)
}

async fn documents_metadata_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: DocumentsMetadataRequest,
) -> Result<DocumentsMetadataResponse, AgentError> {
    let identifier = document_identifier(user, headers, &body.collectionname, &body.file_hash, DatasetRow::Any).await?;
    let source = format!("{}:metadata", body.file_hash);
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let table_list = raw_metadata_table_list();
    let rows = get_raw_metadata::get_raw_metadata_tables(user, identifier.clone(), table_list.clone())
        .await
        .map_err(AgentError::from_anyhow)?;
    let mut raw_metadata = BTreeMap::new();
    for (info, values) in table_list.into_iter().zip(rows) {
        if !values.is_empty() {
            raw_metadata.entry(info.table_name).or_insert_with(Vec::new).extend(values);
        }
    }
    for (table, values) in raw_metadata.iter_mut() {
        for (index, value) in values.iter_mut().enumerate() {
            cut_long_strings(value, &format!("/{table}/{index}"));
        }
    }
    if let Some(blobs) = raw_metadata.get_mut("blobs") {
        blobs.iter_mut().for_each(name_blob_storage);
    }

    let dates = get_document_provenance::get_document_dates(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .dates
        .into_iter()
        .map(|d| AgentDate { value: d.epoch_seconds, kind: d.source_provider().to_string(), provenance: d.source })
        .collect();

    let locations = get_file_path::get_file_locations(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;
    let file_locations_total = locations.total;
    let file_locations = locations
        .locations
        .into_iter()
        .map(|location| AgentFileLocation {
            path: location.path,
            container_hash: location.container_hash,
            container_chain: location.chain.into_iter().map(|node| node.path).collect(),
        })
        .collect();

    let path = get_file_path::get_file_path(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .unwrap_or_default();
    let canonical_file_type = get_file_path::get_canonical_file_type(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;

    let pdf_sources = get_document_sources::get_pdf_sources(user, identifier.clone()).await.unwrap_or_default();
    let ocr_pdf = pdf_sources
        .iter()
        .find(|s| s.is_ocr())
        .map(|s| s.url(&identifier.collection_dataset, &identifier.file_hash));
    let download_links = AgentDownloadLinks { original: identifier.get_absolute_url_path(), ocr_pdf,
        pdf_sources: pdf_sources.iter().map(|source|common::agent_api::AgentPdfDownloadLink {
            source:source.source_name(),label:source.label(),url:source.url(&identifier.collection_dataset,&identifier.file_hash)
        }).collect() };

    let archive = get_document_sources::archive_info_for(user, &identifier).await;
    Ok(DocumentsMetadataResponse {
        archive,
        raw_metadata,
        dates,
        file_locations,
        file_locations_total,
        path,
        canonical_file_type,
        download_links,
        source,
    })
}

// ===================================================================================
// documents/email
// ===================================================================================

pub async fn documents_email(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentsEmailRequest>,
) -> AgentResult<DocumentsEmailResponse> {
    Deadline::start().run(documents_email_body(&user, &headers, body)).await.map(Json)
}

async fn documents_email_body(
    user: &CurrentUser,
    request_headers: &HeaderMap,
    body: DocumentsEmailRequest,
) -> Result<DocumentsEmailResponse, AgentError> {
    let offset = match &body.position {
        None => 0,
        Some(AgentPosition::Offset { offset }) => *offset,
        Some(other) => return Err(wrong_position_kind("documents/email", other, "Offset")),
    };
    let identifier = document_identifier(user, request_headers, &body.collectionname, &body.file_hash, DatasetRow::Email).await?;
    let centre = match &body.node {
        Some(node) if node != &body.file_hash => {
            document_identifier(user, request_headers, &body.collectionname, node, DatasetRow::Email).await?
        }
        _ => identifier.clone(),
    };

    let envelope = get_email_graph::get_email_envelope(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?;
    let attachment_total = envelope.as_ref().map_or(0, |envelope| envelope.attachments.len() as u64);
    let source = format!("{}:email:{attachment_total}", body.file_hash);
    verify_expected_source(body.expected_source.as_deref(), &source)?;
    if offset > attachment_total {
        return Err(AgentError::invalid_argument(format!(
            "the attachment offset {offset} is past the {attachment_total} attachments"
        )));
    }

    let headers_rows = get_raw_metadata::get_raw_metadata(
        user,
        identifier.clone(),
        DocumentMetadataTableInfo::new3("email_headers", "email_hash", vec!["raw_headers_json"]),
    )
    .await
    .unwrap_or_default();
    let headers = headers_rows
        .into_iter()
        .next()
        .and_then(|row| row.get("raw_headers_json").cloned())
        .unwrap_or(serde_json::Value::Object(Default::default()));

    // The website's graph page always asks for these two budgets. A person changes only
    // the centre.
    let graph = get_email_graph::get_email_graph(user, centre, MAX_GRAPH_NODES, MAX_GRAPH_DEPTH)
        .await
        .map_err(AgentError::from_anyhow)?;
    let graph = AgentEmailGraph {
        nodes: graph
            .nodes
            .iter()
            .map(|n| AgentEmailGraphNode {
                file_hash: n.document_identifier.file_hash.clone(),
                subject: n.subject.clone(),
                from: n.from_display.clone(),
                date: n.date_sent_known.then_some(n.date_sent),
                truncated: n.truncated,
                is_centre: n.is_centre,
            })
            .collect(),
        edges: graph
            .edges
            .iter()
            .map(|e| AgentEmailGraphEdge {
                src_file_hash: e.src.file_hash.clone(),
                dst_file_hash: e.dst.file_hash.clone(),
                kind: e.kind.clone(),
                confidence: e.confidence,
                evidence: e.evidence.clone(),
            })
            .collect(),
        cluster_size: graph.cluster_size,
        truncated: graph.truncated,
    };

    let end = (offset as usize + EMAIL_ATTACHMENTS_PAGE_SIZE).min(attachment_total as usize);
    let next_position = (end < attachment_total as usize).then_some(AgentPosition::Offset { offset: end as u64 });
    let page_info = AgentPageInfo { source, next_position, total: Some(attachment_total), partial: false };
    let response = match envelope {
        Some(envelope) => DocumentsEmailResponse {
            attachments: envelope.attachments[offset as usize..end]
                .iter()
                .map(|a| AgentEmailAttachment {
                    file_hash: a.document_identifier.file_hash.clone(),
                    name: a.file_name.clone(),
                    size: a.size_bytes,
                    coarse_type: a.coarse_type.clone(),
                })
                .collect(),
            parent: envelope.parent.map(|parent| AgentEmailRelation {
                file_hash: parent.document_identifier.file_hash,
                subject: parent.subject,
                from: parent.from_display,
                date: parent.date_sent,
                kind: parent.kind,
                confidence: parent.confidence,
            }),
            cluster_size: envelope.cluster_size,
            envelope: Some(AgentEmailEnvelope {
                subject: envelope.subject,
                date: envelope.date_sent,
                from: envelope.from.iter().map(|p| p.full()).collect(),
                to: envelope.to.iter().map(|p| p.full()).collect(),
                cc: envelope.cc.iter().map(|p| p.full()).collect(),
                bcc: envelope.bcc.iter().map(|p| p.full()).collect(),
            }),
            headers,
            graph,
            page_info,
        },
        None => DocumentsEmailResponse {
            envelope: None,
            parent: None,
            cluster_size: 0,
            headers,
            attachments: Vec::new(),
            graph,
            page_info,
        },
    };
    Ok(response)
}

// ===================================================================================
// documents/diff_sources
// ===================================================================================

pub async fn documents_diff_sources(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentsDiffSourcesRequest>,
) -> AgentResult<DocumentsDiffSourcesResponse> {
    let deadline = Deadline::start();
    deadline.run(documents_diff_sources_body(&user, &headers, body, deadline)).await.map(Json)
}

async fn documents_diff_sources_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: DocumentsDiffSourcesRequest,
    deadline: Deadline,
) -> Result<DocumentsDiffSourcesResponse, AgentError> {
    let identifier = document_identifier(user, headers, &body.collectionname, &body.file_hash, DatasetRow::Any).await?;
    let sources = text_sources_of(user, &identifier).await?;
    let pages = StoredTextPages { identifier: &identifier, collectionname: &body.collectionname, deadline };
    let mut fingerprints = Vec::with_capacity(2);
    let mut chosen_pages = Vec::with_capacity(2);
    for (wanted, page) in [(&body.source_a, body.page_a), (&body.source_b, body.page_b)] {
        let Some(found) = sources.iter().find(|source| &source.extracted_by == wanted) else {
            return Err(AgentError::not_found(format!("no text source {wanted:?}")));
        };
        fingerprints.push(text_source_fingerprint(&body.file_hash, wanted, &pages.revision(wanted).await?));
        chosen_pages.push(page.unwrap_or(found.min_page));
    }
    let source = format!("{}:diff", fingerprints.join("|"));
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let (text_a, _) = read_text_page(&pages, &body.source_a, chosen_pages[0]).await?;
    let (text_b, _) = read_text_page(&pages, &body.source_b, chosen_pages[1]).await?;
    let unified_diff = diff::unified_diff(&text_a, &text_b, &body.source_a, &body.source_b);

    Ok(DocumentsDiffSourcesResponse {
        source_a: body.source_a,
        source_b: body.source_b,
        page_a: chosen_pages[0],
        page_b: chosen_pages[1],
        unified_diff,
        source,
    })
}

// ===================================================================================
// documents/pdf_search
// ===================================================================================

/// The sidecar results the agent route keeps, keyed by collection dataset, file hash,
/// source and query. The sidecar searches the whole PDF and takes no page range, so a
/// continuation or another page range reads the kept result.
const PDF_CACHE_ENTRIES: usize = 16;
const PDF_CACHE_TTL: std::time::Duration = std::time::Duration::from_secs(600);

type PdfCacheKey = (String, String, String, String);

/// A least-recently-used list of [`PDF_CACHE_ENTRIES`] sidecar results, each kept for
/// [`PDF_CACHE_TTL`].
#[derive(Default)]
struct PdfSearchCache {
    entries: std::collections::VecDeque<(PdfCacheKey, std::time::Instant, std::sync::Arc<PdfSearchResults>)>,
}

impl PdfSearchCache {
    fn get(&mut self, key: &PdfCacheKey, now: std::time::Instant) -> Option<std::sync::Arc<PdfSearchResults>> {
        self.entries.retain(|(_, stored, _)| now.duration_since(*stored) < PDF_CACHE_TTL);
        let index = self.entries.iter().position(|(stored_key, _, _)| stored_key == key)?;
        let entry = self.entries.remove(index)?;
        let value = entry.2.clone();
        self.entries.push_back(entry);
        Some(value)
    }

    fn put(&mut self, key: PdfCacheKey, value: std::sync::Arc<PdfSearchResults>, now: std::time::Instant) {
        self.entries.retain(|(stored_key, _, _)| stored_key != &key);
        self.entries.push_back((key, now, value));
        while self.entries.len() > PDF_CACHE_ENTRIES {
            self.entries.pop_front();
        }
    }
}

static PDF_SEARCH_CACHE: std::sync::LazyLock<std::sync::Mutex<PdfSearchCache>> =
    std::sync::LazyLock::new(Default::default);

/// One page of at most `limit` hits inside the page range, after `after`. A hit's key is
/// its PDF page and its ordinal among the hits of that page.
fn pdf_hits_page(
    results: &PdfSearchResults,
    page_from: Option<i32>,
    page_to: Option<i32>,
    after: Option<(u32, u32)>,
    limit: usize,
) -> (Vec<AgentPdfHit>, u64, Option<AgentPosition>) {
    let mut keyed = Vec::new();
    let mut ordinal = 0u32;
    let mut last_page = None;
    for result in &results.results {
        if last_page != Some(result.page_index) {
            ordinal = 0;
            last_page = Some(result.page_index);
        }
        let key = (result.page_index.max(0) as u32, ordinal);
        ordinal += 1;
        if page_from.is_some_and(|from| result.page_index < from) || page_to.is_some_and(|to| result.page_index > to) {
            continue;
        }
        keyed.push((key, result));
    }
    let total = keyed.len() as u64;
    let remaining: Vec<_> = keyed.into_iter().filter(|(key, _)| after.is_none_or(|after| *key > after)).collect();
    let next_position = (remaining.len() > limit)
        .then(|| remaining[limit - 1].0)
        .map(|(page_id, ordinal)| AgentPosition::HitKey { page_id, ordinal });
    let hits = remaining
        .into_iter()
        .take(limit)
        .map(|(_, r)| AgentPdfHit { page: r.page_index, start: r.char_index, end: r.char_index + r.char_count })
        .collect();
    (hits, total, next_position)
}

pub async fn documents_pdf_search(
    Extension(user): Extension<CurrentUser>,
    headers: HeaderMap,
    AgentJson(body): AgentJson<DocumentsPdfSearchRequest>,
) -> AgentResult<DocumentsPdfSearchResponse> {
    let deadline = Deadline::start();
    deadline.run(documents_pdf_search_body(&user, &headers, body, deadline)).await.map(Json)
}

fn select_pdf_source(available: &[common::document_sources::DocumentPdfSourceItem], name: &str) -> Option<common::document_sources::DocumentPdfSourceItem> {
    if name.is_empty() {
        available.iter().find(|source|!source.is_ocr()).or_else(||available.first()).cloned()
    } else {
        available.iter().find(|source|source.source_name() == name || (source.is_ocr() && format!("ocr_{}_{}",source.engine,source.languages) == name)).cloned()
    }
}

async fn documents_pdf_search_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: DocumentsPdfSearchRequest,
    deadline: Deadline,
) -> Result<DocumentsPdfSearchResponse, AgentError> {
    let after = match &body.position {
        None => None,
        Some(AgentPosition::HitKey { page_id, ordinal }) => Some((*page_id, *ordinal)),
        Some(other) => return Err(wrong_position_kind("documents/pdf_search", other, "HitKey")),
    };
    if let (Some(from), Some(to)) = (body.page_from, body.page_to)
        && from > to
    {
        return Err(AgentError::invalid_argument("page_from must not be after page_to"));
    }
    let identifier = document_identifier(user, headers, &body.collectionname, &body.file_hash, DatasetRow::Any).await?;
    let source = format!("{}:pdf:{}", body.file_hash, body.source);
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let available = get_document_sources::get_pdf_sources(user,identifier.clone()).await.map_err(AgentError::from_anyhow)?;
    let source_item = select_pdf_source(&available,&body.source);
    if source_item.is_none() { return Err(AgentError::invalid_argument("PDF source not found")); }
    let pdf_url = source_item
        .as_ref()
        .map(|s| s.url(&identifier.collection_dataset, &identifier.file_hash))
        .unwrap_or_else(|| identifier.get_absolute_url_path());

    let key: PdfCacheKey =
        (identifier.collection_dataset.clone(), body.file_hash.clone(), body.source.clone(), body.query.clone());
    let kept = PDF_SEARCH_CACHE.lock().ok().and_then(|mut cache| cache.get(&key, std::time::Instant::now()));
    let results = match kept {
        Some(results) => results,
        None => {
            let results = search_document_pdf::search_document_pdf_with_timeout(
                user,
                identifier,
                body.query.clone(),
                source_item,
                deadline.remaining(),
            )
            .await
            .map_err(AgentError::from_anyhow)?;
            let results = std::sync::Arc::new(results);
            if let Ok(mut cache) = PDF_SEARCH_CACHE.lock() {
                cache.put(key, results.clone(), std::time::Instant::now());
            }
            results
        }
    };

    let (hit_positions, total, next_position) =
        pdf_hits_page(&results, body.page_from, body.page_to, after, PDF_HITS_PAGE_SIZE);
    Ok(DocumentsPdfSearchResponse {
        source_used: body.source,
        pdf_url,
        hit_count: results.total.max(0) as u64,
        hit_positions,
        page_info: AgentPageInfo { source, next_position, total: Some(total), partial: false },
    })
}

#[cfg(test)]
mod page_choice_tests {
    use super::{chosen_page, requested_page};

    #[test]
    fn no_page_and_page_zero_open_the_first_stored_page_after_a_gap() {
        // The source has no stored page 1 or 2. Its first stored page is 3.
        assert_eq!(chosen_page(requested_page(None), &[], 3), 3);
        assert_eq!(chosen_page(requested_page(Some(0)), &[], 3), 3);
    }

    #[test]
    fn a_positive_page_stays_exact_and_a_query_opens_its_best_page() {
        assert_eq!(chosen_page(requested_page(Some(5)), &[(4, 9)], 3), 5);
        assert_eq!(chosen_page(requested_page(Some(1)), &[], 3), 1);
        assert_eq!(chosen_page(requested_page(Some(0)), &[(4, 1), (7, 9)], 3), 7);
    }
}

#[cfg(test)]
mod blob_storage_tests {
    use super::name_blob_storage;

    #[test]
    fn the_storage_flag_becomes_a_named_place() {
        let mut row = serde_json::json!({"blob_hash": "h", "stored_in_clickhouse": 0});
        name_blob_storage(&mut row);
        assert_eq!(row, serde_json::json!({"blob_hash": "h", "bytes_stored_in": "object_storage"}));
        let mut row = serde_json::json!({"stored_in_clickhouse": "1"});
        name_blob_storage(&mut row);
        assert_eq!(row["bytes_stored_in"], "clickhouse");
    }
}
