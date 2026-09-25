//! The document routes: `documents/read`, `documents/search_text`, `documents/sources`,
//! `documents/metadata`, `documents/email`, `documents/diff_sources` and `documents/pdf_search`.

use super::*;
use crate::api::documents::search_document_itemcount::SourceCount;
use crate::api::documents::search_document_text::DOCUMENT_HIT_ROW_LIMIT;

#[cfg(test)]
#[path = "document_pages_tests.rs"]
mod document_pages_tests;

// ===================================================================================
// documents: the shared reads
// ===================================================================================

/// Resolves one document of a collection that the caller may read, in a dataset that
/// holds `row` when one does.
async fn document_identifier(
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

/// The stored text pages of one document, as the document routes read them. Each
/// method reads at most one page, so a call costs the same on a document of any length.
trait TextPages {
    /// Counts the stored pages of a source, and gives its highest page id. It loads no
    /// page text.
    async fn extent(&self, extracted_by: &str) -> Result<(u64, u32), AgentError>;
    /// Reads one page, or `None` when the page id has no stored row.
    async fn page_text(&self, extracted_by: &str, page_id: u32) -> Result<Option<String>, AgentError>;
    /// Gives the lowest stored page id above `page_id`.
    async fn page_after(&self, extracted_by: &str, page_id: u32) -> Result<Option<u32>, AgentError>;
    /// Reads the query hit spans of one page.
    async fn page_hits(&self, extracted_by: &str, page_id: u32, query: &str) -> Result<Vec<HighlightTextSpan>, AgentError>;
}

/// [`TextPages`] over `text_content` and the document's Manticore shard.
struct StoredTextPages<'a> {
    user: &'a CurrentUser,
    identifier: &'a DocumentIdentifier,
    collectionname: &'a str,
    deadline: Deadline,
}

impl TextPages for StoredTextPages<'_> {
    async fn extent(&self, extracted_by: &str) -> Result<(u64, u32), AgentError> {
        self.deadline
            .collection_client(self.collectionname)
            .query("SELECT uniqExact(page_id), max(page_id) FROM text_content WHERE collection_dataset = ? AND file_hash = ? AND extracted_by = ?")
            .bind(&self.identifier.collection_dataset)
            .bind(&self.identifier.file_hash)
            .bind(extracted_by)
            .fetch_one()
            .await
            .map_err(AgentError::from_clickhouse)
    }

    async fn page_text(&self, extracted_by: &str, page_id: u32) -> Result<Option<String>, AgentError> {
        self.deadline
            .collection_client(self.collectionname)
            .query("SELECT text FROM text_content WHERE collection_dataset = ? AND file_hash = ? AND extracted_by = ? AND page_id = ? LIMIT 1")
            .bind(&self.identifier.collection_dataset)
            .bind(&self.identifier.file_hash)
            .bind(extracted_by)
            .bind(page_id)
            .fetch_optional()
            .await
            .map_err(AgentError::from_clickhouse)
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

    async fn page_hits(&self, extracted_by: &str, page_id: u32, query: &str) -> Result<Vec<HighlightTextSpan>, AgentError> {
        let rows = search_document_text::search_document_text_for_hits(
            self.user,
            self.identifier.clone(),
            query.to_string(),
            extracted_by.to_string(),
            page_id,
        )
        .await
        .map_err(AgentError::from_anyhow)?;
        Ok(rows.into_iter().next().map(|row| row.highlight_text_spans).unwrap_or_default())
    }
}

/// The `source` of one document text source: its page count and highest page id change
/// when the document is parsed again.
fn text_source_fingerprint(file_hash: &str, extracted_by: &str, extent: (u64, u32)) -> String {
    format!("{file_hash}:{extracted_by}:{}:{}", extent.0, extent.1)
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

/// The query hits of one text source, page by page in page order, and whether the count
/// stopped at the website's [`DOCUMENT_HIT_ROW_LIMIT`]. The limit applies to the rows the
/// index returned, before duplicates are removed.
async fn source_hit_counts(
    user: &CurrentUser,
    identifier: &DocumentIdentifier,
    extracted_by: &str,
    query: &str,
) -> Result<(Vec<(u32, u64)>, bool), AgentError> {
    let (rows, returned_rows) =
        search_document_text::search_document_text_hit_count_rows(user, identifier.clone(), query.to_string())
            .await
            .map_err(AgentError::from_anyhow)?;
    let partial = returned_rows >= DOCUMENT_HIT_ROW_LIMIT;
    let mut pages: Vec<(u32, u64)> = rows
        .into_iter()
        .filter(|row| row.extracted_by == extracted_by && row.hit_count > 0)
        .map(|row| (row.page_id, row.hit_count))
        .collect();
    pages.sort_unstable();
    Ok((pages, partial))
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

/// One page of at most `limit` hits after `after`, in page order. It reads only the
/// pages that hold the hits it returns. The position is absent when no hit remains.
async fn text_hits_page<P: TextPages>(
    pages: &P,
    extracted_by: &str,
    query: &str,
    counts: &[(u32, u64)],
    after: Option<(u32, u32)>,
    limit: usize,
) -> Result<(Vec<AgentTextHit>, Option<AgentPosition>), AgentError> {
    let mut hits: Vec<AgentTextHit> = Vec::new();
    for (index, &(page_id, count)) in counts.iter().enumerate() {
        let first = match after {
            Some((after_page, _)) if page_id < after_page => continue,
            Some((after_page, ordinal)) if page_id == after_page => {
                if u64::from(ordinal) + 1 >= count {
                    continue;
                }
                ordinal as usize + 1
            }
            _ => 0,
        };
        let spans = pages.page_hits(extracted_by, page_id, query).await?;
        let page_hits = hits_from_spans(page_id, &spans);
        let available = page_hits.len();
        for hit in page_hits.into_iter().skip(first) {
            hits.push(hit);
            if hits.len() == limit {
                let last = hits.last().map(|hit| (hit.page, hit.ordinal)).unwrap_or_default();
                let more_here = (last.1 as usize) + 1 < available;
                let more_later = counts[index + 1..].iter().any(|(_, count)| *count > 0);
                let next = (more_here || more_later)
                    .then_some(AgentPosition::HitKey { page_id: last.0, ordinal: last.1 });
                return Ok((hits, next));
            }
        }
    }
    Ok((hits, None))
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
    extent: (u64, u32),
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
    let (wanted_source, wanted_page) = match body.position.clone() {
        None => (body.source.clone(), body.page),
        Some(AgentPosition::TextPage { source, page_id }) => (Some(source), Some(page_id)),
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
        let pages = StoredTextPages { user, identifier: &identifier, collectionname: &body.collectionname, deadline };
        let extent = match &chosen {
            Some(source) => pages.extent(&source.extracted_by).await?,
            None => (0, 0),
        };
        planned.push(PlannedRead { file_hash: file_hash.clone(), identifier, chosen, extent });
    }
    let source = planned
        .iter()
        .map(|plan| match &plan.chosen {
            Some(chosen) => text_source_fingerprint(&plan.file_hash, &chosen.extracted_by, plan.extent),
            None => format!("{}:no_text", plan.file_hash),
        })
        .collect::<Vec<_>>()
        .join("|");
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let mut documents = Vec::with_capacity(planned.len());
    let mut partial = false;
    for plan in &planned {
        let read = read_one_document(user, &body.collectionname, plan, query.as_deref(), wanted_page, deadline);
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
                    file_hash: plan.file_hash.clone(),
                    path: String::new(),
                    title: String::new(),
                    source_used: plan.chosen.as_ref().map(|c| c.extracted_by.clone()).unwrap_or_default(),
                    page: None,
                    min_page: plan.chosen.as_ref().map(|c| c.min_page),
                    max_page: plan.chosen.as_ref().map(|c| c.max_page),
                    text: String::new(),
                    hit_count: 0,
                    hit_pages: Vec::new(),
                    count_state: "timed_out".to_string(),
                    next_position: None,
                });
            }
        }
    }
    let (next_position, total) = match (documents.as_slice(), planned.as_slice()) {
        ([document], [plan]) => (document.next_position.clone(), Some(plan.extent.0)),
        _ => (None, None),
    };
    Ok(DocumentsReadResponse { documents, page_info: AgentPageInfo { source, next_position, total, partial } })
}

/// Reads one page of one document. The second value is true when the hit count stopped
/// at the website's row limit.
async fn read_one_document(
    user: &CurrentUser,
    collectionname: &str,
    plan: &PlannedRead,
    query: Option<&str>,
    wanted_page: Option<u32>,
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
                file_hash: plan.file_hash.clone(),
                path,
                title,
                source_used: String::new(),
                page: None,
                min_page: None,
                max_page: None,
                text: String::new(),
                hit_count: 0,
                hit_pages: Vec::new(),
                count_state: "no_text".to_string(),
                next_position: None,
            },
            false,
        ));
    };
    let (counts, stopped) = match query {
        Some(query) => source_hit_counts(user, &plan.identifier, &chosen.extracted_by, query).await?,
        None => (Vec::new(), false),
    };
    let page_id = wanted_page.or_else(|| most_hits_page(&counts)).unwrap_or(chosen.min_page);
    let pages = StoredTextPages { user, identifier: &plan.identifier, collectionname, deadline };
    let (text, next) = read_text_page(&pages, &chosen.extracted_by, page_id).await?;
    Ok((
        AgentDocumentText {
            collectionname: collectionname.to_string(),
            file_hash: plan.file_hash.clone(),
            path,
            title,
            source_used: chosen.extracted_by.clone(),
            page: Some(page_id),
            min_page: Some(chosen.min_page),
            max_page: Some(chosen.max_page),
            text,
            hit_count: counts.iter().map(|(_, count)| count).sum(),
            hit_pages: counts.iter().take(MAX_HIT_PAGES).map(|(page, _)| *page).collect(),
            count_state: "read".to_string(),
            next_position: next.map(|page_id| AgentPosition::TextPage { source: chosen.extracted_by.clone(), page_id }),
        },
        stopped,
    ))
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
        None => sources.first().ok_or_else(|| AgentError::not_found("the document has no text source"))?,
    };
    let pages = StoredTextPages { user, identifier: &identifier, collectionname: &body.collectionname, deadline };
    let extent = pages.extent(&chosen.extracted_by).await?;
    let source = text_source_fingerprint(&body.file_hash, &chosen.extracted_by, extent);
    verify_expected_source(body.expected_source.as_deref(), &source)?;

    let (counts, partial) = source_hit_counts(user, &identifier, &chosen.extracted_by, &body.query).await?;
    let (hits, next_position) =
        text_hits_page(&pages, &chosen.extracted_by, &body.query, &counts, after, TEXT_HITS_PAGE_SIZE).await?;
    let hit_count = counts.iter().map(|(_, count)| count).sum();
    Ok(DocumentsSearchTextResponse {
        source_used: chosen.extracted_by.clone(),
        hit_count,
        hits,
        page_info: AgentPageInfo { source, next_position, total: Some(hit_count), partial },
    })
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
            source: if pdf.is_ocr() { format!("ocr_{}_{}", pdf.engine, pdf.languages) } else { String::new() },
            label: pdf.label(),
            page_count: Some(pdf.page_count),
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
        DocumentSourceItem::FileLocations | DocumentSourceItem::Metadata => return None,
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
    }
}

async fn documents_sources_body(
    user: &CurrentUser,
    headers: &HeaderMap,
    body: DocumentsSourcesRequest,
    deadline: Deadline,
) -> Result<DocumentsSourcesResponse, AgentError> {
    let identifier = document_identifier(user, headers, &body.collectionname, &body.file_hash, DatasetRow::Any).await?;
    let items: Vec<DocumentSourceItem> = get_document_sources::get_document_sources(user, identifier.clone())
        .await
        .map_err(AgentError::from_anyhow)?
        .into_iter()
        .filter(|item| !matches!(item, DocumentSourceItem::FileLocations | DocumentSourceItem::Metadata))
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
    Ok(DocumentsSourcesResponse { sources, page_info: AgentPageInfo { source, next_position: None, total, partial } })
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
    let download_links = AgentDownloadLinks { original: identifier.get_absolute_url_path(), ocr_pdf };

    Ok(DocumentsMetadataResponse {
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
    let pages = StoredTextPages { user, identifier: &identifier, collectionname: &body.collectionname, deadline };
    let mut fingerprints = Vec::with_capacity(2);
    let mut chosen_pages = Vec::with_capacity(2);
    for (wanted, page) in [(&body.source_a, body.page_a), (&body.source_b, body.page_b)] {
        let Some(found) = sources.iter().find(|source| &source.extracted_by == wanted) else {
            return Err(AgentError::not_found(format!("no text source {wanted:?}")));
        };
        fingerprints.push(text_source_fingerprint(&body.file_hash, wanted, pages.extent(wanted).await?));
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

    let source_item = match TextSource::parse(&body.source) {
        TextSource::Ocr { engine, languages } => Some(DocumentPdfSourceItem { page_count: 0, engine, languages }),
        TextSource::Native { .. } => None,
    };
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
