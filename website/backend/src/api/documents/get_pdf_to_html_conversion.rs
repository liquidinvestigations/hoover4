use anyhow::Context;
use clickhouse::Row;
use common::{document_metadata::DocumentMetadataTableInfo, pdf_to_html_conversion::PDFToHtmlConversionResponse, search_result::DocumentIdentifier};
use reqwest::Body;
use serde::{Deserialize, Serialize};

use crate::api::documents::{download_document::get_document_content_stream, get_raw_metadata::get_raw_metadata};
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Row)]
struct PDFToHtmlCacheRow {
    pub collection_dataset: String,
    pub pdf_hash: String,
    pub page_count: u32,
    pub styles: Vec<String>,
    pub pages: Vec<String>,
    pub page_width_px: f32,
    pub page_height_px: f32,
}

pub async fn get_document_type_is_pdf(document_identifier: DocumentIdentifier) -> anyhow::Result<bool> {
    let meta = get_raw_metadata(document_identifier, DocumentMetadataTableInfo::new("pdfs", "pdf_hash")).await?;
    Ok(!meta.is_empty())
}

pub async fn get_pdf_to_html_conversion(document_identifier: DocumentIdentifier) -> anyhow::Result<PDFToHtmlConversionResponse> {
    let client = get_clickhouse_client();
    let query = "SELECT collection_dataset, pdf_hash, page_count, styles, pages, page_width_px, page_height_px FROM pdf_to_html_cache WHERE collection_dataset = ? AND pdf_hash = ? LIMIT 1";
    let query = client.query(query)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash);

    let result = query.fetch_all::<PDFToHtmlCacheRow>().await?;
    if let Some(row) = result.into_iter().next() {
        tracing::info!("PDF to HTML cache: HIT");
        return Ok(PDFToHtmlConversionResponse {
            pages: row.pages,
            styles: row.styles,
            page_width_px: row.page_width_px,
            page_height_px: row.page_height_px,
        });
    }

    tracing::info!("PDF to HTML cache: MISS");
    let response = make_pdf_to_html_conversion(document_identifier.clone()).await?;

    let row = PDFToHtmlCacheRow {
        collection_dataset: document_identifier.collection_dataset.clone(),
        pdf_hash: document_identifier.file_hash.clone(),
        page_count: response.pages.len() as u32,
        styles: response.styles.clone(),
        pages: response.pages.clone(),
        page_width_px: response.page_width_px,
        page_height_px: response.page_height_px,
    };

    tracing::info!("PDF to HTML cache: SET");
    let mut insert = client.insert::<PDFToHtmlCacheRow>("pdf_to_html_cache").await?;
    insert.write(&row).await?;
    insert.end().await?;

    Ok(response)
}


async fn make_pdf_to_html_conversion(document_identifier: DocumentIdentifier) -> anyhow::Result<PDFToHtmlConversionResponse> {
    let is_pdf = get_document_type_is_pdf(document_identifier.clone()).await?;
    if !is_pdf {
        anyhow::bail!("Document is not a PDF");
    }
    tracing::info!("Document is a PDF, converting to HTML");

    let (stream_size, doc_stream) = get_document_content_stream(document_identifier.clone()).await?;
    tracing::info!("Document stream received");
    let client = reqwest::Client::new();
    let response = client.post(format!("{}", std::env::var("PDF_TO_HTML_ENDPOINT").context("PDF_TO_HTML_ENDPOINT is not set")?))
    .body(Body::wrap_stream(doc_stream))
    .header("Content-Length", format!("{}", stream_size))
    .send()
    .await?;
    tracing::info!("Response received");
    let response = response.error_for_status()?;
    let body = response.text().await?;
    let body = serde_json::from_str::<PDFToHtmlConversionResponse>(&body)?;
    Ok(body)
}


