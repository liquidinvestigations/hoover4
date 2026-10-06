//! Endpoint for fetching document text sources.

use anyhow::Context;
use common::{
    current_user::CurrentUser,
    document_sources::{
        DocumentAudioSourceItem, DocumentEmailSourceItem, DocumentImageSourceItem,
        DocumentPdfSourceItem, DocumentProcessingStatus, DocumentSourceItem, DocumentSourcesStatus, DocumentTableSourceItem,
        DocumentTextSourceItem, DocumentVideoSourceItem, BINARY_WORD_TEXT_EXTRACTOR,
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
    let mut result = result
        .into_iter()
        .map(
            |(extracted_by, min_page, max_page)| DocumentTextSourceItem {
                extracted_by,
                min_page,
                max_page,
            },
        )
        .collect::<Vec<_>>();
    prefer_binary_word(&mut result);
    Ok(result)
}

fn prefer_binary_word(sources: &mut [DocumentTextSourceItem]) {
    sources.sort_by_key(|source| source.extracted_by != BINARY_WORD_TEXT_EXTRACTOR);
}

use common::document_metadata::DocumentMetadataTableInfo;

use crate::api::documents::get_raw_metadata::get_raw_metadata;

pub(crate) async fn get_pdf_sources(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentPdfSourceItem>> {
    let (sources, variant_error) = get_pdf_sources_with_status(user, document_identifier).await?;
    if let Some(error) = variant_error {
        tracing::warn!(%error, "PDF OCR source query failed");
    }
    Ok(sources)
}

async fn get_pdf_sources_with_status(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<(Vec<DocumentPdfSourceItem>, Option<anyhow::Error>)> {
    let meta = get_raw_metadata(
        user,
        document_identifier.clone(),
        DocumentMetadataTableInfo::new("pdfs", "pdf_hash"),
    )
    .await?;
    let Some(obj) = meta.first() else {
        return Ok((Vec::new(), None));
    };
    let page_count = obj
        .get("page_count")
        .and_then(|v| v.as_u64())
        .context("No page count found")? as u32;

    // The original first, always: it is the file the investigation actually holds, and an
    // OCR'd rendering of it is an aid, not a replacement.
    let sources = vec![DocumentPdfSourceItem {
        page_count,
        engine: String::new(),
        languages: String::new(),
    }];

    // One entry per live `pdf_ocr_results` row. `page_count` comes from the derived PDF's
    // own row rather than the source's: the two agree today (the assembler emits one page
    // per input page, deliberately, so page numbers keep matching the viewer) and if they
    // ever stop agreeing the selector must report what the file it is about to serve
    // actually contains.
    let variants: anyhow::Result<Vec<(String, String, u32)>> = async {
        let client = get_client_for_dataset(&document_identifier.collection_dataset).await?;
        let rows = client
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
        .await?;
        Ok(rows)
    }.await;
    Ok(append_pdf_variants(sources, page_count, variants))
}

fn append_pdf_variants(
    mut sources: Vec<DocumentPdfSourceItem>,
    page_count: u32,
    variants: anyhow::Result<Vec<(String, String, u32)>>,
) -> (Vec<DocumentPdfSourceItem>, Option<anyhow::Error>) {
    let variants = match variants {
        Ok(variants) => variants,
        Err(error) => return (sources, Some(error)),
    };
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
    (sources, None)
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
/// fraction of document opens with nothing wrong. Enough to make the log useless as a
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
    let Some(obj) = meta.first() else {
        return Ok(None);
    };
    let obj = obj.as_object().context("Invalid video metadata")?;
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
    let Some(obj) = meta.first() else {
        return Ok(None);
    };
    let obj = obj.as_object().context("Invalid audio metadata")?;
    let duration = obj
        .get("duration_seconds")
        .and_then(|v| v.as_f64())
        .context("No duration found")?;
    Ok(Some(DocumentAudioSourceItem {
        duration_seconds: duration as f32,
    }))
}

/// The grid source, for a document the pipeline read into cells.
///
/// One `table_documents` lookup and nothing else: the variant carries identity only, so
/// the sheets and columns are not needed until the explorer asks for them. `None` is the
/// ordinary answer. Most documents are not tables.
async fn get_table_sources(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Option<DocumentTableSourceItem>> {
    let manifest = crate::api::documents::table_browse::load_table_manifest(
        user,
        &document_identifier,
    )
    .await?;
    Ok(manifest.map(|manifest| DocumentTableSourceItem {
        sheet_count: manifest.sheet_count,
        row_count: manifest.row_count,
        column_count: manifest.column_count,
        table_format: manifest.table_format,
    }))
}

#[allow(for_loops_over_fallibles)]
pub async fn get_document_sources(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<Vec<DocumentSourceItem>> {
    let status = get_document_sources_status(user, document_identifier).await?;
    if !status.errors.is_empty() {
        anyhow::bail!("Could not load all document sources: {}", status.errors.join(", "));
    }
    Ok(status.sources)
}

pub async fn get_document_sources_status(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentSourcesStatus> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let (txt, pdf, email, img, vid, aud, table, processing) = tokio::join!(
        get_text_sources(user, document_identifier.clone()),
        get_pdf_sources_with_status(user, document_identifier.clone()),
        get_email_sources(user, document_identifier.clone()),
        get_image_sources(user, document_identifier.clone()),
        get_video_sources(user, document_identifier.clone()),
        get_audio_sources(user, document_identifier.clone()),
        get_table_sources(user, document_identifier.clone()),
        get_processing_status(&document_identifier),
    );

    let mut sources = vec![];
    let mut errors = Vec::new();
    let text_sources = txt.unwrap_or_else(|error| {
        tracing::warn!(%error, "text source query failed");
        errors.push("Text sources could not load".to_string());
        Vec::new()
    });
    let (pdf, pdf_variant_error) = pdf.unwrap_or_else(|error| {
        tracing::warn!(%error, "PDF source query failed");
        errors.push("PDF sources could not load".to_string());
        (Vec::new(), None)
    });
    if let Some(error) = pdf_variant_error {
        tracing::warn!(%error, "PDF OCR source query failed");
        errors.push("PDF OCR sources could not load".to_string());
    }
    let email = email.unwrap_or_else(|error| {
        tracing::warn!(%error, "email source query failed");
        errors.push("Email source could not load".to_string());
        None
    });
    let img = img.unwrap_or_else(|error| {
        tracing::warn!(%error, "image source query failed");
        errors.push("Image source could not load".to_string());
        None
    });
    let vid = vid.unwrap_or_else(|error| {
        tracing::warn!(%error, "video source query failed");
        errors.push("Video source could not load".to_string());
        None
    });
    let aud = aud.unwrap_or_else(|error| {
        tracing::warn!(%error, "audio source query failed");
        errors.push("Audio source could not load".to_string());
        None
    });
    let table = table.unwrap_or_else(|error| {
        tracing::warn!(%error, "table source query failed");
        errors.push("Table source could not load".to_string());
        None
    });
    // The email preview renders the parsed body, which is an ordinary `text_content`
    // variant. Hand the email source that variant's page range so the viewer asks for a
    // page that exists; `page_id` is 1-based, so 1 is the floor and 0 is never valid.
    //
    // Headers and body are stored independently. A message can have headers without
    // readable body text, so the viewer must not request an absent body page.
    let body_range = text_sources
        .iter()
        .find(|s| s.extracted_by == EMAIL_TEXT_EXTRACTOR)
        .map(|s| (s.min_page.max(1), s.max_page.max(1)));
    let (body_min_page, body_max_page) = body_range.unwrap_or((1, 1));
    for source in text_sources {
        sources.push(DocumentSourceItem::Text(source));
    }
    for source in pdf {
        sources.push(DocumentSourceItem::Pdf(source));
    }
    for mut source in email {
        source.min_page = body_min_page;
        source.max_page = body_max_page;
        source.has_body = body_range.is_some();
        sources.push(DocumentSourceItem::Email(source));
    }
    for source in img {
        sources.push(DocumentSourceItem::Image(source));
    }
    for source in vid {
        sources.push(DocumentSourceItem::Video(source));
    }
    for source in aud {
        sources.push(DocumentSourceItem::Audio(source));
    }
    // Declared before `Text` in the enum and therefore sorted above it below, so a
    // workbook opens on its grid rather than on the tab-separated flattening of it that
    // the text extractor also produced for the same file.
    for source in table {
        sources.push(DocumentSourceItem::Table(source));
    }
    // Nothing else is pushed here. `Metadata` and the file locations are DESCRIPTIONS of
    // the document, not renderings of it, and each has its own right-hand tab in the
    // viewer (`RawMetadataCollector` and `DocumentFileLocationsPanel`). Offering either as
    // a preview source puts a second copy of that panel where the document belongs, and
    // since both sort last and neither is ever selected by default it is reachable only as
    // a dead end. `Metadata` stays a variant so a bookmarked URL naming it still parses;
    // the selector falls back to the first real source.
    sources.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let processing = processing.unwrap_or_else(|error| {
        tracing::warn!(%error, "document processing query failed");
        errors.push("The document processing state could not load".to_string());
        DocumentProcessingStatus::QueryFailed
    });
    Ok(DocumentSourcesStatus { sources, errors, processing })
}

/// Read plan completion, file failures, and the latest operation in one query.
const DOCUMENT_PROCESSING_SQL: &str = r#"
WITH
    plans AS (SELECT plan_hash FROM processing_plan_hits FINAL
              WHERE collection_dataset = ? AND item_hash = ?),
    latest_operation AS (
        SELECT p.op_id AS op_id, o.state AS state
        FROM operation_plans AS p FINAL
        INNER JOIN Hoover4_Processing.operations AS o FINAL ON o.op_id = p.op_id
        WHERE p.collection_dataset = ? AND p.plan_hash IN plans
        ORDER BY p.listed_at DESC, o.started_at DESC, p.op_id DESC LIMIT 1)
SELECT
    ifNull((SELECT count() FROM plans), 0) AS planned,
    ifNull((SELECT count() FROM processing_plan_finished FINAL
     WHERE collection_dataset = ? AND plan_hash IN plans), 0) AS finished,
    ifNull((SELECT groupUniqArray(20)(task_name) FROM processing_errors FINAL
     WHERE collection_dataset = ? AND hash = ?
       AND (op_id IN (SELECT op_id FROM latest_operation)
            OR (op_id = '' AND (SELECT count() FROM latest_operation) = 0))), []) AS tasks,
    ifNull((SELECT any(state) FROM latest_operation), '') AS operation_state
"#;

#[derive(clickhouse::Row, serde::Deserialize)]
struct ProcessingStatusRow {
    planned: u64,
    finished: u64,
    tasks: Vec<String>,
    operation_state: String,
}

async fn get_processing_status(identifier: &DocumentIdentifier) -> anyhow::Result<DocumentProcessingStatus> {
    let client = get_client_for_dataset(&identifier.collection_dataset).await?;
    let row: ProcessingStatusRow = client
        .query(DOCUMENT_PROCESSING_SQL)
        .bind(&identifier.collection_dataset).bind(&identifier.file_hash)
        .bind(&identifier.collection_dataset).bind(&identifier.collection_dataset)
        .bind(&identifier.collection_dataset).bind(&identifier.file_hash)
        .fetch_one().await?;
    Ok(document_processing_status(row.planned, row.finished, row.tasks, row.operation_state))
}

fn document_processing_status(planned: u64, finished: u64, mut tasks: Vec<String>,
                              operation_state: String) -> DocumentProcessingStatus {
    if !tasks.is_empty() {
        tasks.sort();
        return DocumentProcessingStatus::Failed { tasks };
    }
    if planned == 0 {
        return DocumentProcessingStatus::NotPlanned;
    }
    if finished >= planned {
        return DocumentProcessingStatus::Done;
    }
    match operation_state.as_str() {
        "pending" | "queued" | "running" => DocumentProcessingStatus::Running,
        "" => DocumentProcessingStatus::NotPlanned,
        _ => DocumentProcessingStatus::Stopped { operation_state },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unfinished_plans_follow_their_operation_state() {
        assert_eq!(document_processing_status(1, 0, vec![], "running".into()), DocumentProcessingStatus::Running);
        assert_eq!(document_processing_status(1, 0, vec![], "".into()), DocumentProcessingStatus::NotPlanned);
        for state in ["errored", "cancelled", "finished"] {
            assert_eq!(document_processing_status(1, 0, vec![], state.into()),
                       DocumentProcessingStatus::Stopped { operation_state: state.into() });
        }
        assert_eq!(document_processing_status(1, 1, vec![], "finished".into()), DocumentProcessingStatus::Done);
        assert_eq!(document_processing_status(1, 1, vec!["parse".into()], "errored".into()),
                   DocumentProcessingStatus::Failed { tasks: vec!["parse".into()] });
    }

    #[test]
    fn ocr_query_failure_keeps_original_pdf_source() {
        let original = DocumentPdfSourceItem {
            page_count: 4,
            engine: String::new(),
            languages: String::new(),
        };
        let (sources, error) = append_pdf_variants(
            vec![original.clone()], 4, Err(anyhow::anyhow!("OCR query failed")),
        );
        assert_eq!(sources, vec![original]);
        assert_eq!(error.unwrap().to_string(), "OCR query failed");
    }

    #[test]
    fn default_agent_text_source_prefers_binary_word() {
        let source = |name: &str| DocumentTextSourceItem {
            extracted_by: name.to_string(), min_page: 1, max_page: 1,
        };
        let mut sources = vec![source("extractous"), source("raw_text"), source("binary_word")];
        prefer_binary_word(&mut sources);
        assert_eq!(sources, vec![source("binary_word"), source("extractous"), source("raw_text")]);
    }
}
