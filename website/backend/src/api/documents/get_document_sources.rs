//! Endpoint for fetching document text sources.

use anyhow::Context;
use common::{
    document_sources::{
        DocumentAudioSourceItem, DocumentEmailSourceItem, DocumentImageSourceItem,
        DocumentPdfSourceItem, DocumentSourceItem, DocumentTextSourceItem, DocumentVideoSourceItem,
    },
    search_result::DocumentIdentifier,
};

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

pub(crate) async fn get_text_sources(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentTextSourceItem>> {
    let client = get_clickhouse_client();
    let query = r#"
    SELECT extracted_by,min(page_id) as min_page,max(page_id) as max_page FROM text_content
    WHERE file_hash = ? AND collection_dataset = ?
    GROUP BY extracted_by
    LIMIT 1000"#;
    let query = client
        .query(query)
        .bind(&document_identifier.file_hash)
        .bind(&document_identifier.collection_dataset);
    let result = query.fetch_all::<(String, u32, u32)>().await?;
    let result = result
        .into_iter()
        .map(
            |(extracted_by, min_page, max_page)| DocumentTextSourceItem {
                extracted_by,
                min_page,
                max_page,
            },
        )
        .collect::<Vec<_>>();
    Ok(result)
}

use common::document_metadata::DocumentMetadataTableInfo;

use crate::api::documents::get_raw_metadata::get_raw_metadata;

pub(crate) async fn get_pdf_sources(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentPdfSourceItem>> {
    let meta = get_raw_metadata(
        document_identifier,
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
    )
    .await?;
    let obj = meta.first().context("No PDF metadata found")?;
    let page_count = obj
        .get("page_count")
        .and_then(|v| v.as_u64())
        .context("No page count found")?;
    Ok(Some(DocumentPdfSourceItem {
        page_count: page_count as u32,
    }))
}

async fn get_email_sources(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentEmailSourceItem>> {
    let client = get_clickhouse_client();
    let query = r#"
        SELECT
            subject,
            addresses,
            formatDateTime(date_sent, '%FT%TZ') AS date_sent,
            raw_headers_json
        FROM email_headers
        WHERE collection_dataset = ? AND email_hash = ?
        LIMIT 1
    "#;
    let query = client
        .query(query)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash);
    let result = query
        .fetch_all::<(String, String, String, String)>()
        .await?;
    let Some((subject, addresses, date_sent, raw_headers_json)) = result.into_iter().next() else {
        return Ok(None);
    };
    Ok(Some(DocumentEmailSourceItem {
        subject,
        addresses,
        date_sent,
        raw_headers_json,
    }))
}

#[tracing::instrument(level = "debug", err(Debug))]
async fn get_image_sources(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentImageSourceItem>> {
    let meta = get_raw_metadata(
        document_identifier,
        DocumentMetadataTableInfo::new3("image", "image_hash", vec!["image_metadata"]),
    )
    .await?;
    let obj = meta.first().context("No image metadata found")?;
    let metadata = obj
        .get("image_metadata")
        .and_then(|v| v.as_object())
        .context("No image metadata found")?;

    let streams = metadata
        .get("streams")
        .and_then(|v| v.as_array())
        .context("No stream found")?;
    let stream = streams
        .first()
        .context("No stream found")?
        .as_object()
        .context("No stream found")?;
    let width = stream
        .get("width")
        .and_then(|v| v.as_u64())
        .context("No width found")?;
    let height = stream
        .get("height")
        .and_then(|v| v.as_u64())
        .context("No height found")?;
    return Ok(Some(DocumentImageSourceItem {
        width: width as u32,
        height: height as u32,
    }));
}

async fn get_video_sources(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentVideoSourceItem>> {
    let meta = get_raw_metadata(
        document_identifier,
        DocumentMetadataTableInfo::new3("video_metadata", "hash", vec!["video_metadata_json"]),
    )
    .await?;
    let obj = meta
        .first()
        .context("No video metadata found")?
        .as_object()
        .context("No video metadata found")?;
    let duration = obj
        .get("duration_seconds")
        .and_then(|v| v.as_f64())
        .context("No duration found")?;
    let width = obj
        .get("width")
        .and_then(|v| v.as_u64())
        .context("No width found")?;
    let height = obj
        .get("height")
        .and_then(|v| v.as_u64())
        .context("No height found")?;
    return Ok(Some(DocumentVideoSourceItem {
        width: width as u32,
        height: height as u32,
        duration_seconds: duration as f32,
    }));
}

async fn get_audio_sources(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentAudioSourceItem>> {
    let meta = get_raw_metadata(
        document_identifier,
        DocumentMetadataTableInfo::new3("audio_metadata", "hash", vec!["audio_metadata_json"]),
    )
    .await?;
    let obj = meta
        .first()
        .context("No video metadata found")?
        .as_object()
        .context("No video metadata found")?;
    let duration = obj
        .get("duration_seconds")
        .and_then(|v| v.as_f64())
        .context("No duration found")?;
    return Ok(Some(DocumentAudioSourceItem {
        duration_seconds: duration as f32,
    }));
}

#[allow(for_loops_over_fallibles)]
pub async fn get_document_sources(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentSourceItem>> {
    let (txt, pdf, email, img, vid, aud) = tokio::join!(
        get_text_sources(document_identifier.clone()),
        get_pdf_sources(document_identifier.clone()),
        get_email_sources(document_identifier.clone()),
        get_image_sources(document_identifier.clone()),
        get_video_sources(document_identifier.clone()),
        get_audio_sources(document_identifier.clone()),
    );

    let mut sources = vec![];
    for source in txt.unwrap_or_default() {
        sources.push(DocumentSourceItem::Text(source));
    }
    for source in pdf.unwrap_or_default() {
        sources.push(DocumentSourceItem::Pdf(source));
    }
    for source in email.unwrap_or_default() {
        sources.push(DocumentSourceItem::Email(source));
    }
    for source in img.unwrap_or_default() {
        sources.push(DocumentSourceItem::Image(source));
    }
    for source in vid.unwrap_or_default() {
        sources.push(DocumentSourceItem::Video(source));
    }
    for source in aud.unwrap_or_default() {
        sources.push(DocumentSourceItem::Audio(source));
    }
    sources.push(DocumentSourceItem::FileLocations);
    sources.push(DocumentSourceItem::Metadata);
    sources.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    Ok(sources)
}
