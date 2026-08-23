use std::collections::HashSet;

use common::{current_user::CurrentUser, pdf_search_results::PdfSearchResults, search_result::DocumentIdentifier};
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

/// Ceiling on a document sent to the sidecar for highlighting.
///
/// The whole PDF is buffered three times over (here, on the wire, and inside pdfium's
/// wasm heap), so this is a memory bound on the server, not a policy about documents.
/// A document above it still opens, downloads and searches by text; only the in-page
/// highlight overlay is unavailable, which is the right thing to lose.
const MAX_PDF_SEARCH_BYTES: u64 = 128 * 1024 * 1024;

/// Longest a single in-PDF search may take. The sidecar parses and scans the whole
/// document per keyword; without a bound, one pathological PDF holds a server-function
/// slot open indefinitely.
const PDF_SEARCH_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(120);

pub async fn search_document_pdf(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    query: String,
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

    for result in text_results {
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
    let pdf_bytes = crate::api::documents::download_document::read_blob_bytes(
        user,
        &document_identifier,
        MAX_PDF_SEARCH_BYTES,
    )
    .await?;

    let keywords_param = json!(keywords).to_string();
    let pdf_results = reqwest::ClientBuilder::new()
        .timeout(PDF_SEARCH_TIMEOUT)
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
