//! The OCR detection summary of one document.

use common::ocr_detection::{DocumentOcrDetection, OcrDetectionValue};

use crate::db_utils::clickhouse_utils::get_client_for_dataset;

#[derive(Debug, clickhouse::Row, serde::Deserialize)]
struct PageRow {
    has_text: u8,
    script: String,
    language: String,
}

fn counted(values: impl Iterator<Item = String>) -> Vec<OcrDetectionValue> {
    let mut pages = std::collections::BTreeMap::<String, u64>::new();
    for value in values {
        *pages.entry(value).or_default() += 1;
    }
    let mut counted: Vec<_> = pages.into_iter().map(|(value, pages)| OcrDetectionValue { value, pages }).collect();
    counted.sort_by(|a, b| b.pages.cmp(&a.pages).then_with(|| a.value.cmp(&b.value)));
    counted
}

fn summary(rows: Vec<PageRow>) -> DocumentOcrDetection {
    let with_text = || rows.iter().filter(|row| row.has_text == 1);
    DocumentOcrDetection {
        pages_examined: rows.len() as u64,
        pages_with_text: with_text().count() as u64,
        scripts: counted(with_text().filter(|row| !row.script.is_empty()).map(|row| row.script.clone())),
        languages: counted(with_text()
            .filter(|row| !row.language.is_empty() && row.language != "und")
            .map(|row| common::signals::language_name(&row.language))),
    }
}

/// The summary of one document. The caller has checked the read permission. A document
/// without a row has `pages_examined` 0. A failed query is an error.
pub async fn document_detection(collection_dataset: &str, file_hash: &str) -> anyhow::Result<DocumentOcrDetection> {
    let client = get_client_for_dataset(collection_dataset).await?;
    let rows: Vec<PageRow> = client
        .query(
            "SELECT has_text, script, language FROM ocr_detection FINAL \
             WHERE collection_dataset = ? AND hash = ?",
        )
        .bind(collection_dataset)
        .bind(file_hash)
        .fetch_all()
        .await?;
    Ok(summary(rows))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(has_text: u8, script: &str, language: &str) -> PageRow {
        PageRow { has_text, script: script.to_string(), language: language.to_string() }
    }

    #[test]
    fn a_summary_counts_pages_with_text_and_leaves_out_undetermined_values() {
        let found = summary(vec![
            row(1, "Latin", "en"), row(1, "Latin", "en"), row(1, "Hebrew", "und"), row(1, "", "und"), row(0, "", "und"),
        ]);
        assert_eq!((found.pages_examined, found.pages_with_text), (5, 4));
        assert_eq!(found.scripts, vec![
            OcrDetectionValue { value: "Latin".to_string(), pages: 2 },
            OcrDetectionValue { value: "Hebrew".to_string(), pages: 1 },
        ]);
        assert_eq!(found.languages, vec![OcrDetectionValue { value: "English".to_string(), pages: 2 }]);
    }

    #[test]
    fn a_document_without_rows_examined_nothing() {
        assert_eq!(summary(vec![]), DocumentOcrDetection::default());
    }
}
