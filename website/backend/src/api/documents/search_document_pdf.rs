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
    // Manticore round trip per page of the document — a one-shot lookup becoming a
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
    tracing::info!("TEXT RESULT COUNT BEFORE TRIM: {:?}", keywords.len());
    let keywords = keywords.into_iter().take(50).collect::<Vec<_>>();
    tracing::info!("TEXT RESULT COUNT AFTER TRIM: {:?}", keywords.len());
    let pdf_url = format!(
        "http://127.0.0.1:8080{}",
        document_identifier.get_absolute_url_path()
    );

    let pdf_results = reqwest::ClientBuilder::new()
        .build()?
        .get("http://127.0.0.1:13500")
        .header("Content-Type", "application/json")
        .body(
            json!({
                "url": pdf_url,
                "keywords": keywords,
            })
            .to_string(),
        )
        .send()
        .await?
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
    tracing::info!("FINAL RESULTS COUNT: {:?}", final_results.results.len());
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
