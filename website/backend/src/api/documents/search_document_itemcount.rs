use common::{
    current_user::CurrentUser,
    document_sources::{DocumentPdfSourceItem, DocumentSourceItem, DocumentTextSourceHitCount, ItemHitCounts},
    search_result::DocumentIdentifier,
};

use crate::api::documents::{
    search_document_pdf::{PDF_SEARCH_TIMEOUT, search_document_pdf_with_timeout},
    search_document_text::{DOCUMENT_HIT_ROW_LIMIT, search_document_text_hit_count_rows},
};
use crate::auth::permissions;

/// The text source that holds an email's parsed body. The Email source takes its count.
const EMAIL_BODY_EXTRACTED_BY: &str = "email_parser";

/// The result of the hit count of one source.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceCount {
    /// The count finished. `stopped_at_limit` is true for a text or Email source when the
    /// text read returned [`DOCUMENT_HIT_ROW_LIMIT`] rows, so the count can be too low.
    Counted { hits: u64, stopped_at_limit: bool },
    /// A PDF count that did not finish in its time limit.
    TimedOut,
    /// A text or table count that failed, or a PDF count that failed for a cause other
    /// than its time limit.
    Failed,
}

/// The hit count of every source, one entry for each source in the order given, and the
/// error of the text count read when that read failed.
#[derive(Debug, Default)]
pub struct SourceCounts {
    pub counts: Vec<(DocumentSourceItem, SourceCount)>,
    pub text_error: Option<anyhow::Error>,
}

/// The hit count of every source, for the website's source selector. A count that fails
/// or does not finish in [`PDF_SEARCH_TIMEOUT`] counts 0 here.
pub async fn search_document_item_count(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    find_query: String,
    sources: Vec<DocumentSourceItem>,
) -> anyhow::Result<ItemHitCounts> {
    let counts =
        search_document_item_count_with_timeout(user, document_identifier, find_query, sources, PDF_SEARCH_TIMEOUT)
            .await?;
    Ok(ItemHitCounts(
        counts
            .counts
            .into_iter()
            .map(|(source, count)| match count {
                SourceCount::Counted { hits, .. } => (source, hits),
                SourceCount::TimedOut | SourceCount::Failed => (source, 0),
            })
            .collect(),
    ))
}

/// The hit count of every source, one entry for each source in the order given. The
/// text, table and PDF counts run at once. Each PDF count stops after `pdf_timeout`, and
/// its entry is then [`SourceCount::TimedOut`]. A count that fails is
/// [`SourceCount::Failed`].
pub async fn search_document_item_count_with_timeout(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    find_query: String,
    sources: Vec<DocumentSourceItem>,
    pdf_timeout: std::time::Duration,
) -> anyhow::Result<SourceCounts> {
    crate::api::telemetry::record_event(&user.username, crate::api::telemetry::EVENT_USER_GET_DOCUMENT, "");
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    if find_query.is_empty() || sources.is_empty() {
        return Ok(SourceCounts::default());
    }
    tracing::debug!(
        "item hit counts for {:?}, find={:?}, {} sources",
        document_identifier,
        &find_query,
        sources.len()
    );

    // The Email source counts the hits of its parsed body, which is a text source.
    let needs_text = sources
        .iter()
        .any(|source| matches!(source, DocumentSourceItem::Text(_) | DocumentSourceItem::Email(_)));
    let has_table = sources.iter().any(|source| matches!(source, DocumentSourceItem::Table(_)));

    let pdf_tasks = sources
        .iter()
        .filter_map(|source| match source {
            DocumentSourceItem::Pdf(item) => Some(item.clone()),
            _ => None,
        })
        .map(|source| {
            let user = user.clone();
            let doc_id = document_identifier.clone();
            let query = find_query.clone();
            let selected_source = source.clone();
            let task = tokio::task::spawn(async move {
                tokio::time::timeout(
                    pdf_timeout,
                    search_document_pdf_with_timeout(&user, doc_id, query, Some(selected_source), pdf_timeout),
                )
                .await
            });
            (source, task)
        })
        .collect::<Vec<_>>();

    let text_count = async {
        if needs_text {
            search_document_text_hit_count_rows(user, document_identifier.clone(), find_query.clone()).await
        } else {
            Ok((Vec::new(), 0))
        }
    };
    // Cells whose text contains the find query, across every sheet of the document. The
    // count goes beside the Table source the way page hits go beside a text source, and a
    // failure here costs that one number rather than the whole hit-count response.
    let table_count = async {
        if has_table {
            crate::api::documents::table_browse::count_table_cell_matches(user, &document_identifier, &find_query)
                .await
                .ok()
        } else {
            Some(0)
        }
    };
    let (text_read, table_count) = tokio::join!(text_count, table_count);
    let (text_hits, text_error) = match text_read {
        Ok((hits, returned_rows)) => (Some((hits, returned_rows >= DOCUMENT_HIT_ROW_LIMIT)), None),
        Err(error) => (None, Some(error)),
    };

    let mut pdf_counts = Vec::with_capacity(pdf_tasks.len());
    for (source, task) in pdf_tasks {
        let count = match task.await {
            Ok(Ok(Ok(pdf_search))) => {
                SourceCount::Counted { hits: pdf_search.results.len() as u64, stopped_at_limit: false }
            }
            Ok(Ok(Err(error))) if is_timeout(&error) => SourceCount::TimedOut,
            Ok(Err(_elapsed)) => SourceCount::TimedOut,
            _ => SourceCount::Failed,
        };
        pdf_counts.push((source, count));
    }

    let text = text_hits.as_ref().map(|(hits, stopped_at_limit)| (hits.as_slice(), *stopped_at_limit));
    Ok(SourceCounts { counts: assemble_counts(sources, text, table_count, &pdf_counts), text_error })
}

fn is_timeout(error: &anyhow::Error) -> bool {
    error.chain().any(|cause| cause.downcast_ref::<reqwest::Error>().is_some_and(reqwest::Error::is_timeout))
}

/// One entry for each source, in the order given. An Email source takes the hits of the
/// `email_parser` text, and appears once. `text` is the text hits and whether the read
/// stopped at its row limit, and is `None` when the read failed. `table_count` is `None`
/// when the table count failed.
fn assemble_counts(
    sources: Vec<DocumentSourceItem>,
    text: Option<(&[DocumentTextSourceHitCount], bool)>,
    table_count: Option<u64>,
    pdf_counts: &[(DocumentPdfSourceItem, SourceCount)],
) -> Vec<(DocumentSourceItem, SourceCount)> {
    let text_total = |extracted_by: &str| -> SourceCount {
        match text {
            Some((hits, stopped_at_limit)) => SourceCount::Counted {
                hits: hits.iter().filter(|hit| hit.extracted_by == extracted_by).map(|hit| hit.hit_count).sum(),
                stopped_at_limit,
            },
            None => SourceCount::Failed,
        }
    };
    sources
        .into_iter()
        .map(|source| {
            let count = match &source {
                DocumentSourceItem::Pdf(item) => pdf_counts
                    .iter()
                    .find(|(pdf_source, _)| pdf_source == item)
                    .map_or(SourceCount::Failed, |(_, count)| *count),
                DocumentSourceItem::Table(_) => match table_count {
                    Some(hits) => SourceCount::Counted { hits, stopped_at_limit: false },
                    None => SourceCount::Failed,
                },
                DocumentSourceItem::Text(item) => text_total(&item.extracted_by),
                DocumentSourceItem::Email(_) => text_total(EMAIL_BODY_EXTRACTED_BY),
                _ => SourceCount::Counted { hits: 0, stopped_at_limit: false },
            };
            (source, count)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::document_sources::{DocumentEmailSourceItem, DocumentTableSourceItem, DocumentTextSourceItem};

    fn email_source() -> DocumentSourceItem {
        DocumentSourceItem::Email(DocumentEmailSourceItem {
            subject: "s".into(),
            addresses: String::new(),
            date_sent: String::new(),
            raw_headers_json: String::new(),
            min_page: 1,
            max_page: 1,
            has_body: true,
        })
    }

    fn hit(extracted_by: &str, page_id: u32, hit_count: u64) -> DocumentTextSourceHitCount {
        DocumentTextSourceHitCount { extracted_by: extracted_by.into(), page_id, hit_count }
    }

    fn counted(hits: u64) -> SourceCount {
        SourceCount::Counted { hits, stopped_at_limit: false }
    }

    fn text_source(extracted_by: &str) -> DocumentSourceItem {
        DocumentSourceItem::Text(DocumentTextSourceItem { extracted_by: extracted_by.into(), min_page: 1, max_page: 2 })
    }

    fn table_source() -> DocumentSourceItem {
        DocumentSourceItem::Table(DocumentTableSourceItem { sheet_count: 1, row_count: 3, column_count: 2, table_format: "csv".into() })
    }

    #[test]
    fn an_email_source_appears_once_with_its_body_count() {
        let text = text_source("email_parser");
        let hits = [hit("email_parser", 1, 2), hit("email_parser", 2, 3), hit("raw_text", 1, 7)];
        let counts = assemble_counts(vec![email_source(), text.clone()], Some((&hits, false)), Some(0), &[]);
        assert_eq!(counts, vec![(email_source(), counted(5)), (text, counted(5))]);
    }

    #[test]
    fn a_pdf_count_that_did_not_finish_is_timed_out() {
        let pdf = DocumentPdfSourceItem { page_count: 3, engine: String::new(), languages: String::new() };
        let counts = assemble_counts(
            vec![DocumentSourceItem::Pdf(pdf.clone())],
            Some((&[], false)),
            Some(0),
            &[(pdf.clone(), SourceCount::TimedOut)],
        );
        assert_eq!(counts, vec![(DocumentSourceItem::Pdf(pdf), SourceCount::TimedOut)]);
    }

    #[test]
    fn a_failed_table_count_is_failed() {
        let counts = assemble_counts(vec![table_source()], Some((&[], false)), None, &[]);
        assert_eq!(counts, vec![(table_source(), SourceCount::Failed)]);
    }

    #[test]
    fn a_failed_text_read_fails_the_text_and_email_sources() {
        let text = text_source("raw_text");
        let counts = assemble_counts(vec![text.clone(), email_source(), table_source()], None, Some(4), &[]);
        assert_eq!(
            counts,
            vec![(text, SourceCount::Failed), (email_source(), SourceCount::Failed), (table_source(), counted(4))]
        );
    }

    #[test]
    fn a_text_read_at_its_row_limit_marks_the_text_and_email_counts() {
        let text = text_source("raw_text");
        let hits = [hit("raw_text", 1, 2), hit("email_parser", 1, 1)];
        let counts = assemble_counts(vec![text.clone(), email_source(), table_source()], Some((&hits, true)), Some(4), &[]);
        assert_eq!(
            counts,
            vec![
                (text, SourceCount::Counted { hits: 2, stopped_at_limit: true }),
                (email_source(), SourceCount::Counted { hits: 1, stopped_at_limit: true }),
                (table_source(), counted(4)),
            ]
        );
    }
}
