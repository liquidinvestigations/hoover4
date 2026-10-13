use std::collections::HashSet;

use common::{current_user::CurrentUser, document_sources::DocumentPdfSourceItem, pdf_search_results::PdfSearchResults, search_result::DocumentIdentifier};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::api::documents::search_document_text::search_document_text_all_hits;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SearchPdfResultsSet {
    keyword: String,
    result_set: PdfSearchResults,
}

use crate::auth::permissions;

/// Where the in-PDF search sidecar answers.
///
/// It is a **child process of this server**, not a service of its own (see
/// `server_extra::run_pdf_search_server`), so loopback is the right default and the
/// variable exists only so a deployment that moves it does not need a rebuild. This is
/// not `PDF_TO_HTML_ENDPOINT`: that names the page-rendering container, which speaks a
/// different protocol entirely (POST of raw PDF bytes, HTML back) and answers
/// `GET requests are not supported` to anything sent here.
pub fn pdf_search_endpoint() -> String {
    std::env::var("PDF_SEARCH_ENDPOINT")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| "http://127.0.0.1:13500".to_string())
}

/// Longest a single in-PDF search of the website may take. The sidecar parses and scans
/// the whole document per keyword; without a bound, one pathological PDF holds a
/// server-function slot open indefinitely. An agent route passes the time that remains of
/// its own deadline in its place.
pub const PDF_SEARCH_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(120);

pub async fn search_document_pdf(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    query: String,
    source: Option<DocumentPdfSourceItem>,
) -> anyhow::Result<PdfSearchResults> {
    search_document_pdf_with_timeout(user, document_identifier, query, source, PDF_SEARCH_TIMEOUT).await
}

/// [`search_document_pdf`] with the sidecar request bounded by `timeout`. A sidecar that
/// does not answer in time fails with a `reqwest` timeout error.
pub async fn search_document_pdf_with_timeout(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    query: String,
    source: Option<DocumentPdfSourceItem>,
    timeout: std::time::Duration,
) -> anyhow::Result<PdfSearchResults> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    // One query for every source and every page of this document.
    //
    // Do NOT turn this back into a nested loop over `source.min_page..=source.max_page`
    // per text source. `page_id` is a real PDF page number, so that loop issues one
    // Manticore round trip per page of the document, a one-shot lookup becoming a
    // thousand-shot one, on the intended semantics rather than on a bug.
    let text_results =
        search_document_text_all_hits(user, document_identifier.clone(), query.clone()).await?;

    let mut keywords = HashSet::new();

    let source = source.unwrap_or_default();
    let text_source = source.text_source();
    for result in text_results.into_iter().filter(|result| {
        if source.kind() == "image" { return result.extracted_by == text_source; }
        let native = if source.kind() == "preview" { !common::document_sources::TextSource::parse(&result.extracted_by).is_ocr() }
            else { result.extracted_by == "pdftotext" };
        native || (source.is_ocr() && result.extracted_by == text_source)
    }) {
        for span in result.highlight_text_spans {
            if span.is_highlighted {
                keywords.insert(span.text.to_lowercase());
            }
        }
    }
    tracing::debug!("in-pdf search: {} keywords before trim", keywords.len());
    let keywords = keywords.into_iter().take(50).collect::<Vec<_>>();
    tracing::debug!("in-pdf search: {} keywords after trim", keywords.len());
    if keywords.is_empty() {
        // Nothing matched in the text index, so there is nothing to locate on the page.
        // Reading and shipping the whole PDF to answer that would be pure waste.
        return Ok(PdfSearchResults { results: vec![], total: 0 });
    }

    // The sidecar is given the bytes. Handing it a URL pointing back at this server's own
    // HTTP port instead makes the server fetch a document it already knows how to read,
    // over a request that can carry no session, so requiring a session on the download
    // route silently kills in-document search.
    let parts = crate::server_extra::pdf_parts::source_parts(user,&document_identifier,&source).await?;
    let deadline = tokio::time::Instant::now() + timeout;
    let mut pdf_results = Vec::new();
    for part in parts {
        let pdf_bytes = crate::server_extra::pdf_parts::read_part_bytes(&document_identifier,&part).await?;
        let remaining = deadline.saturating_duration_since(tokio::time::Instant::now());
        anyhow::ensure!(!remaining.is_zero(), "PDF search timed out");
    let keywords_param = json!(keywords).to_string();
    let mut part_results = reqwest::ClientBuilder::new()
        .timeout(remaining)
        .build()?
        .post(pdf_search_endpoint())
        .query(&[("keywords", keywords_param.as_str())])
        .header("Content-Type", "application/pdf")
        .body(pdf_bytes)
        .send()
        .await?
        .error_for_status()?
        .json::<Vec<SearchPdfResultsSet>>()
        .await?;
        for item in &mut part_results {
            for hit in &mut item.result_set.results { hit.page_index += part.range.first_page as i32 - 1; }
        }
        pdf_results.extend(part_results);
    }

    let mut final_results = PdfSearchResults {
        results: vec![],
        total: 0,
    };
    for item in pdf_results {
        final_results.results.extend(item.result_set.results);
        final_results.total += item.result_set.total;
    }
    final_results
        .results
        .sort_by_key(|result| (result.page_index, result.char_index, -result.char_count));
    tracing::debug!("in-pdf search: {} results", final_results.results.len());
    Ok(remove_overlapping_results(final_results))
}

fn remove_overlapping_results(results: PdfSearchResults) -> PdfSearchResults {
    let mut new_results = PdfSearchResults {
        results: vec![],
        total: 0,
    };

    for result in results.results {
        let Some(prev_result) = new_results.results.last() else {
            new_results.results.push(result);
            continue;
        };
        if prev_result.page_index == result.page_index
            && prev_result.char_index <= result.char_index
            && (prev_result.char_index + prev_result.char_count) > result.char_index
        {
            continue;
        }
        new_results.results.push(result);
    }
    new_results.total = new_results.results.len() as i32;
    new_results
}
