//! Endpoint for fetching document text sources.

use anyhow::Context;
use common::{
    current_user::CurrentUser,
    document_sources::{
        DocumentAudioSourceItem, DocumentEmailSourceItem, DocumentImageSourceItem,
        DocumentPdfSourceItem, DocumentSourceItem, DocumentTextSourceItem, DocumentVideoSourceItem,
        EMAIL_TEXT_EXTRACTOR,
    },
    search_result::DocumentIdentifier,
};

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

pub(crate) async fn get_text_sources(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentTextSourceItem>> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
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
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentPdfSourceItem>> {
    let meta = get_raw_metadata(
        user,
        document_identifier.clone(),
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
    )
    .await?;
    let obj = meta.first().context("No PDF metadata found")?;
    let page_count = obj
        .get("page_count")
        .and_then(|v| v.as_u64())
        .context("No page count found")? as u32;

    // The original first, always: it is the file the investigation actually holds, and an
    // OCR'd rendering of it is an aid, not a replacement.
    let mut sources = vec![DocumentPdfSourceItem {
        page_count,
        engine: String::new(),
        languages: String::new(),
    }];

    // One entry per live `pdf_ocr_results` row. `page_count` comes from the derived PDF's
    // own row rather than the source's: the two agree today (the assembler emits one page
    // per input page, deliberately, so page numbers keep matching the viewer) and if they
    // ever stop agreeing the selector must report what the file it is about to serve
    // actually contains.
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let variants = client
        .query(
            "SELECT engine, languages, argMax(page_count, updated_at) \
             FROM pdf_ocr_results \
             WHERE collection_dataset = ? AND pdf_hash = ? \
             GROUP BY engine, languages \
             HAVING argMax(is_deleted, updated_at) = 0 \
             ORDER BY engine, languages",
        )
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all::<(String, String, u32)>()
        .await
        // A missing or unreadable table must not cost the reader the original PDF.
        .unwrap_or_default();

    for (engine, languages, variant_pages) in variants {
        sources.push(DocumentPdfSourceItem {
            page_count: if variant_pages > 0 {
                variant_pages
            } else {
                page_count
            },
            engine,
            languages,
        });
    }
    Ok(sources)
}

async fn get_email_sources(
    _user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentEmailSourceItem>> {
    let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
    let query = r#"
        SELECT
            subject,
            addresses,
            -- `date_sent` falls back to the epoch when the `Date:` header did not parse,
            -- and the epoch is also a real instant, so `date_sent_known` is the only
            -- thing that separates them. An unknown date leaves as an empty string
            -- rather than as 1970-01-01, which the viewer would print as a sent date
            -- while the Metadata tab says the document has no confirmed date.
            if(date_sent_known = 1, formatDateTime(date_sent, '%FT%TZ'), '') AS date_sent,
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
    // The body's page range and whether there is a body at all are filled in by
    // `get_document_sources`, which has the text sources; 1 is the smallest `page_id`
    // that can exist.
    Ok(Some(DocumentEmailSourceItem {
        subject,
        addresses,
        date_sent,
        raw_headers_json,
        min_page: 1,
        max_page: 1,
        has_body: false,
    }))
}

/// The image dimensions, or `None` for a document that is not an image.
///
/// **Absence is the ordinary answer here, not a failure.** Most documents are not images,
/// so returning an error for "no `image` row" puts an ERROR line in the log on a large
/// fraction of document opens with nothing wrong — enough to make the log useless as a
/// signal, because every real error is buried among them. `err(Debug)` on the instrument
/// attribute logs at ERROR level by default, which is what turns that last resort into
/// the common case.
#[tracing::instrument(level = "debug", err(level = "debug", Debug))]
pub async fn get_image_sources(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentImageSourceItem>> {
    let meta = get_raw_metadata(
        user,
        document_identifier,
        DocumentMetadataTableInfo::new3("image", "image_hash", vec!["image_metadata"]),
    )
    .await?;
    let Some(obj) = meta.first() else {
        return Ok(None);
    };
    let Some(metadata) = obj.get("image_metadata").and_then(|v| v.as_object()) else {
        return Ok(None);
    };

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
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentVideoSourceItem>> {
    let meta = get_raw_metadata(
        user,
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
    Ok(Some(DocumentVideoSourceItem {
        width: width as u32,
        height: height as u32,
        duration_seconds: duration as f32,
    }))
}

async fn get_audio_sources(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentAudioSourceItem>> {
    let meta = get_raw_metadata(
        user,
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
    Ok(Some(DocumentAudioSourceItem {
        duration_seconds: duration as f32,
    }))
}

#[allow(for_loops_over_fallibles)]
pub async fn get_document_sources(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentSourceItem>> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let (txt, pdf, email, img, vid, aud) = tokio::join!(
        get_text_sources(user, document_identifier.clone()),
        get_pdf_sources(user, document_identifier.clone()),
        get_email_sources(user, document_identifier.clone()),
        get_image_sources(user, document_identifier.clone()),
        get_video_sources(user, document_identifier.clone()),
        get_audio_sources(user, document_identifier.clone()),
    );

    let mut sources = vec![];
    let text_sources = txt.unwrap_or_default();
    // The email preview renders the parsed body, which is an ordinary `text_content`
    // variant. Hand the email source that variant's page range so the viewer asks for a
    // page that exists; `page_id` is 1-based, so 1 is the floor and 0 is never valid.
    //
    // The variant's ABSENCE is reported just as carefully. Headers and body are stored
    // independently, and a mail file can have the first without the second — a body of
    // one character after stripping is dropped by the text writer, as is a message whose
    // only body part is HTML. Guessing a range for a variant that has no rows is what
    // makes the viewer render `document not found!` where the body belongs.
    let body_range = text_sources
        .iter()
        .find(|s| s.extracted_by == EMAIL_TEXT_EXTRACTOR)
        .map(|s| (s.min_page.max(1), s.max_page.max(1)));
    let (body_min_page, body_max_page) = body_range.unwrap_or((1, 1));
    for source in text_sources {
        sources.push(DocumentSourceItem::Text(source));
    }
    for source in pdf.unwrap_or_default() {
        sources.push(DocumentSourceItem::Pdf(source));
    }
    for mut source in email.unwrap_or_default() {
        source.min_page = body_min_page;
        source.max_page = body_max_page;
        source.has_body = body_range.is_some();
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
    // Not `Metadata`: metadata is not a rendering of the document, it is a description of
    // it, and the viewer already has a whole right-hand tab for it (`RawMetadataCollector`
    // — dates, email headers, every raw table). Offering it here as well put a second copy
    // of that panel where the document should be, and — because it sorts last while
    // nothing selected it — was only ever reachable as a dead end. The variant is kept so
    // bookmarked URLs still parse; the selector falls back to the first real source.
    sources.push(DocumentSourceItem::FileLocations);
    sources.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    Ok(sources)
}
