use anyhow::Context;
use common::{document_metadata::DocumentMetadataTableInfo, pdf_to_html_conversion::PDFToHtmlConversionResponse, search_result::DocumentIdentifier};
use reqwest::Body;

use crate::api::documents::{download_document::get_document_content_stream, get_raw_metadata::get_raw_metadata};

pub async fn get_document_type_is_pdf(document_identifier: DocumentIdentifier) -> anyhow::Result<bool> {
    let meta = get_raw_metadata(document_identifier, DocumentMetadataTableInfo::new("pdfs", "pdf_hash")).await?;
    Ok(!meta.is_empty())
}

pub async fn get_pdf_to_html_conversion(document_identifier: DocumentIdentifier) -> anyhow::Result<PDFToHtmlConversionResponse> {
    make_pdf_to_html_conversion(document_identifier).await
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


