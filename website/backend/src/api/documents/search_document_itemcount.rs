use std::collections::{BTreeSet, HashMap};

use common::{
    current_user::CurrentUser,
    document_sources::{DocumentPdfSourceItem, DocumentSourceItem, DocumentTextSourceHitCount, ItemHitCounts},
    document_text_pages::HitCountState,
    search_result::DocumentIdentifier,
};

use crate::api::documents::{
    search_document_pdf::{PDF_SEARCH_TIMEOUT, search_document_pdf_with_timeout},
    search_document_text::{DOCUMENT_HIT_ROW_LIMIT, document_hit_texts, exact_highlight_spans},
};
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_client_for_dataset;

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
    /// A text or Email count whose index rows hold another version of a stored page, so
    /// the count of the stored text is not known.
    Unavailable,
}

/// The text hits of one document read, after each index row is checked against the
/// stored text of its page.
#[derive(Debug, Default, PartialEq)]
pub struct TextCounts {
    /// The matches of each page whose first stored-text row was found, once per page.
    pub hits: Vec<DocumentTextSourceHitCount>,
    /// The read returned [`DOCUMENT_HIT_ROW_LIMIT`] rows, so more pages can match.
    pub stopped_at_limit: bool,
    /// The sources with a page whose index rows all hold another text than the stored one.
    pub differs: BTreeSet<String>,
}

/// The validated text hits of a document. `rows` are the index rows as
/// `(extracted_by, page_id, highlighted text)`, and `stored` maps each stored page to the
/// SHA-256 of its latest text. A row of a page without stored text is obsolete and counts
/// nothing. Each page counts once, from its first row whose text is the stored text, with
/// the match semantics of the viewer highlights ([`exact_highlight_spans`]).
pub fn count_validated(rows: &[(String, u32, String)], stored: &HashMap<(String, u32), String>, stopped_at_limit: bool) -> TextCounts {
    let mut counted: HashMap<(String, u32), u64> = HashMap::new();
    let mut unmatched: BTreeSet<(String, u32)> = BTreeSet::new();
    for (extracted_by, page_id, text) in rows {
        let key = (extracted_by.clone(), *page_id);
        let Some(digest) = stored.get(&key) else { continue };
        if counted.contains_key(&key) {
            continue;
        }
        let plain = text.replace("<hoover4_strong>", "").replace("</hoover4_strong>", "");
        let spans = (sha256::digest(plain.as_str()) == *digest).then(|| exact_highlight_spans(text, &plain)).flatten();
        match spans {
            Some(spans) => {
                unmatched.remove(&key);
                counted.insert(key, spans.iter().filter(|span| span.is_highlighted).count() as u64);
            }
            None => {
                unmatched.insert(key);
            }
        }
    }
    let mut hits: Vec<DocumentTextSourceHitCount> = counted
        .into_iter()
        .map(|((extracted_by, page_id), hit_count)| DocumentTextSourceHitCount { extracted_by, page_id, hit_count })
        .collect();
    hits.sort_by(|a, b| (&a.extracted_by, a.page_id).cmp(&(&b.extracted_by, b.page_id)));
    TextCounts { hits, stopped_at_limit, differs: unmatched.into_iter().map(|(extracted_by, _)| extracted_by).collect() }
}

/// The text hits of a document, checked against `text_content`. One index read and one
/// digest read of the matching pages. The caller has verified read access.
pub(crate) async fn validated_text_counts(identifier: &DocumentIdentifier, find_query: &str) -> anyhow::Result<TextCounts> {
    let rows = document_hit_texts(identifier, find_query).await?;
    let stopped_at_limit = rows.len() >= DOCUMENT_HIT_ROW_LIMIT;
    if rows.is_empty() {
        return Ok(TextCounts { stopped_at_limit, ..Default::default() });
    }
    let sources: Vec<String> = rows.iter().map(|row| row.0.clone()).collect::<BTreeSet<_>>().into_iter().collect();
    let pages: Vec<u32> = rows.iter().map(|row| row.1).collect::<BTreeSet<_>>().into_iter().collect();
    let client = get_client_for_dataset(&identifier.collection_dataset).await?;
    let stored = client
        .query(
            "SELECT extracted_by, page_id, lower(hex(SHA256(argMax(text, version)))) AS body_digest
            FROM text_content
            WHERE collection_dataset = ? AND file_hash = ? AND has(?, extracted_by) AND has(?, page_id)
            GROUP BY extracted_by, page_id",
        )
        .bind(&identifier.collection_dataset)
        .bind(&identifier.file_hash)
        .bind(&sources)
        .bind(&pages)
        .fetch_all::<(String, u32, String)>()
        .await?
        .into_iter()
        .map(|(extracted_by, page_id, digest)| ((extracted_by, page_id), digest))
        .collect();
    Ok(count_validated(&rows, &stored, stopped_at_limit))
}

/// The hit count of every source, one entry for each source in the order given, and the
/// error of the text count read when that read failed.
#[derive(Debug, Default)]
pub struct SourceCounts {
    pub counts: Vec<(DocumentSourceItem, SourceCount)>,
    pub text_error: Option<anyhow::Error>,
}

/// The hit count of every source, for the website's source selector. A count that fails
/// or does not finish in [`PDF_SEARCH_TIMEOUT`] keeps that state, and a count that
/// stopped at the text read's row limit is a lower bound. A text count counts only index
/// rows that hold the stored text of their page, and a source with a page whose rows hold
/// another text has no count ([`SourceCount::Unavailable`]).
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
            .map(|(source, count)| (source, hit_count_state(count)))
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
            validated_text_counts(&document_identifier, &find_query).await
        } else {
            Ok(TextCounts::default())
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
        Ok(counts) => (Some(counts), None),
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

    Ok(SourceCounts { counts: assemble_counts(sources, text_hits.as_ref(), table_count, &pdf_counts), text_error })
}

/// The selector state of one source count.
pub fn hit_count_state(count: SourceCount) -> HitCountState {
    match count {
        SourceCount::Counted { hits, stopped_at_limit: false } => HitCountState::Exact(hits),
        SourceCount::Counted { hits, stopped_at_limit: true } => HitCountState::AtLeast(hits),
        SourceCount::TimedOut => HitCountState::TimedOut,
        SourceCount::Failed => HitCountState::Failed,
        SourceCount::Unavailable => HitCountState::Unavailable,
    }
}

fn is_timeout(error: &anyhow::Error) -> bool {
    error.chain().any(|cause| cause.downcast_ref::<reqwest::Error>().is_some_and(reqwest::Error::is_timeout))
}

/// One entry for each source, in the order given. An Email source takes the hits of the
/// `email_parser` text, and appears once. `text` is the validated text hits, and is
/// `None` when the read failed. `table_count` is `None` when the table count failed.
fn assemble_counts(
    sources: Vec<DocumentSourceItem>,
    text: Option<&TextCounts>,
    table_count: Option<u64>,
    pdf_counts: &[(DocumentPdfSourceItem, SourceCount)],
) -> Vec<(DocumentSourceItem, SourceCount)> {
    let text_total = |extracted_by: &str| -> SourceCount {
        match text {
            Some(counts) if counts.differs.contains(extracted_by) => SourceCount::Unavailable,
            Some(counts) => SourceCount::Counted {
                hits: counts.hits.iter().filter(|hit| hit.extracted_by == extracted_by).map(|hit| hit.hit_count).sum(),
                stopped_at_limit: counts.stopped_at_limit,
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

    fn texts(hits: &[DocumentTextSourceHitCount], stopped_at_limit: bool) -> TextCounts {
        TextCounts { hits: hits.to_vec(), stopped_at_limit, differs: BTreeSet::new() }
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
        let counts = assemble_counts(vec![email_source(), text.clone()], Some(&texts(&hits, false)), Some(0), &[]);
        assert_eq!(counts, vec![(email_source(), counted(5)), (text, counted(5))]);
    }

    #[test]
    fn a_pdf_count_that_did_not_finish_is_timed_out() {
        let pdf = DocumentPdfSourceItem { page_count: 3, engine: String::new(), languages: String::new(), ..Default::default() };
        let counts = assemble_counts(
            vec![DocumentSourceItem::Pdf(pdf.clone())],
            Some(&TextCounts::default()),
            Some(0),
            &[(pdf.clone(), SourceCount::TimedOut)],
        );
        assert_eq!(counts, vec![(DocumentSourceItem::Pdf(pdf), SourceCount::TimedOut)]);
    }

    #[test]
    fn a_failed_table_count_is_failed() {
        let counts = assemble_counts(vec![table_source()], Some(&TextCounts::default()), None, &[]);
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
    fn the_selector_keeps_partial_timed_out_and_failed_counts_apart_from_zero() {
        assert_eq!(hit_count_state(counted(0)), HitCountState::Exact(0));
        assert_eq!(hit_count_state(SourceCount::Counted { hits: 7, stopped_at_limit: true }), HitCountState::AtLeast(7));
        assert_eq!(hit_count_state(SourceCount::TimedOut), HitCountState::TimedOut);
        assert_eq!(hit_count_state(SourceCount::Failed), HitCountState::Failed);
    }

    #[test]
    fn a_text_read_at_its_row_limit_marks_the_text_and_email_counts() {
        let text = text_source("raw_text");
        let hits = [hit("raw_text", 1, 2), hit("email_parser", 1, 1)];
        let counts = assemble_counts(vec![text.clone(), email_source(), table_source()], Some(&texts(&hits, true)), Some(4), &[]);
        assert_eq!(
            counts,
            vec![
                (text, SourceCount::Counted { hits: 2, stopped_at_limit: true }),
                (email_source(), SourceCount::Counted { hits: 1, stopped_at_limit: true }),
                (table_source(), counted(4)),
            ]
        );
    }

    fn stored(pages: &[(&str, u32, &str)]) -> HashMap<(String, u32), String> {
        pages.iter().map(|(source, page, text)| (((*source).to_string(), *page), sha256::digest(*text))).collect()
    }

    fn row(source: &str, page: u32, text: &str) -> (String, u32, String) {
        (source.to_string(), page, text.to_string())
    }

    #[test]
    fn a_count_reads_only_rows_that_hold_the_stored_text_and_counts_a_page_once() {
        let m = |word: &str| format!("<hoover4_strong>{word}</hoover4_strong>");
        let bodies = stored(&[("raw_text", 1, "quokka and quokka"), ("raw_text", 2, "one quokka"), ("ocr", 1, "new text quokka")]);
        let rows = vec![
            row("raw_text", 1, &format!("{} and {}", m("quokka"), m("quokka"))),
            // A duplicate row of the same page counts nothing more.
            row("raw_text", 1, &format!("{} and {}", m("quokka"), m("quokka"))),
            row("raw_text", 2, &format!("one {}", m("quokka"))),
            // A page without stored text is obsolete and counts nothing.
            row("raw_text", 9, &format!("gone {}", m("quokka"))),
            // An older text of a stored page leaves its source without a count.
            row("ocr", 1, &format!("old text {}", m("quokka"))),
        ];
        let counts = count_validated(&rows, &bodies, false);
        assert_eq!(counts.hits, vec![hit("raw_text", 1, 2), hit("raw_text", 2, 1)]);
        assert_eq!(counts.differs, BTreeSet::from(["ocr".to_string()]));
        let sources = vec![text_source("raw_text"), text_source("ocr")];
        assert_eq!(
            assemble_counts(sources.clone(), Some(&counts), Some(0), &[]),
            vec![(sources[0].clone(), counted(3)), (sources[1].clone(), SourceCount::Unavailable)]
        );
        assert_eq!(hit_count_state(SourceCount::Unavailable), HitCountState::Unavailable);
        // A second row that holds the stored text gives the count.
        let mut fixed = rows.clone();
        fixed.push(row("ocr", 1, &format!("new text {}", m("quokka"))));
        let counts = count_validated(&fixed, &bodies, true);
        assert!(counts.differs.is_empty() && counts.stopped_at_limit);
        assert_eq!(hit_count_state(assemble_counts(vec![text_source("ocr")], Some(&counts), Some(0), &[])[0].1), HitCountState::AtLeast(1));
    }
}
