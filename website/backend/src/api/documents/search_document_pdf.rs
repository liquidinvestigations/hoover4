use std::collections::HashSet;

use common::{pdf_search_results::PdfSearchResults, search_result::DocumentIdentifier};
use serde::{Deserialize, Serialize};
use serde_json::json;

use crate::api::documents::{get_text_sources::get_text_sources, search_document_text::search_document_text_for_hits};

#[derive(Debug, Clone, Serialize, Deserialize)]
struct SearchPdfResultsSet {
    keyword: String,
    result_set: PdfSearchResults,
}



pub async fn search_document_pdf(
    document_identifier: DocumentIdentifier,
    query: String,
) -> anyhow::Result<PdfSearchResults> {
    let text_sources = get_text_sources(document_identifier.clone()).await?;
    tracing::info!("TEXT SOURCES COUNT: {:?}", text_sources.len());
    let mut text_results = vec![];
    for source in text_sources {
        for page_id in source.min_page..=source.max_page {
            let results = search_document_text_for_hits(document_identifier.clone(), query.clone(), source.extracted_by.clone(), page_id).await?;
            text_results.extend(results);
        }
    }

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
        "http://127.0.0.1:8080/_download_document/{}/{}",
        document_identifier.collection_dataset, document_identifier.file_hash
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
        .sort_by_key(|result| (result.page_index, result.char_index));
    tracing::info!("FINAL RESULTS COUNT: {:?}", final_results.results.len());
    Ok(final_results)
}
