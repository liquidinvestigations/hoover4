//! Shared search result models.

use serde::{Deserialize, Serialize};

use crate::{
    search_query::{SearchQuery, SortKey, SortSpec},
    text_highlight::HighlightTextSpan,
};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultDocuments {
    pub query: SearchQuery,
    pub results: Vec<SearchResultDocumentItem>,
    /// Filename-only matches among the previous and next page cursors.
    #[serde(default)]
    pub filename_only_cursors: Vec<DocumentIdentifier>,
    pub prev_hash: Option<DocumentIdentifier>,
    pub next_hash: Option<DocumentIdentifier>,
    pub page_number: u64,
    /// True when at least one shard could not be searched (see the fan-out
    /// partial-failure policy). The result list may be missing documents and the
    /// UI shows a notice.
    #[serde(default)]
    pub partial: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Hash, Eq, PartialOrd, Ord)]
pub struct DocumentIdentifier {
    pub collection_dataset: String,
    pub file_hash: String,
}

impl DocumentIdentifier {
    pub fn get_absolute_url_path(&self) -> String {
        format!(
            "/_download_document/{}/{}",
            self.collection_dataset, self.file_hash
        )
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultDocumentItem {
    pub title: String,
    pub highlight_text_spans: Vec<HighlightTextSpan>,
    pub highlight_filenames_spans: Vec<HighlightTextSpan>,
    pub file_hash: String,
    pub collection_dataset: String,
    pub result_index_in_page: u64,
    /// The query matched this document's FILENAME and nothing in its text.
    ///
    /// The filename is searchable through a synthetic pages row, and when that row is the
    /// only one that matched, the body snippet is `HIGHLIGHT()` over the filename. The
    /// title again, in the place a reader reads as "here is where it says that". The card
    /// says what happened instead of echoing the title.
    #[serde(default)]
    pub matched_by_filename: bool,
    /// The document's canonical file type (`table`, `pdf`, `email`, …), for the card's
    /// glyph. Read from `file_type_canonical` rather than decoded from Manticore's
    /// `file_types` term ids: the viewer draws its glyph from that same table, and two
    /// sources for one symbol is two ways for the list and the document to disagree
    /// about what a file is. Empty for a document the type resolver has not reached.
    #[serde(default)]
    pub file_type: String,
    /// The indexed file size in bytes, the value of the size sort. `None` when the
    /// document has no `vfs_files` row.
    #[serde(default)]
    pub file_size_bytes: Option<i64>,
    /// The earliest confirmed date, epoch seconds. `None` when the document has no date.
    #[serde(default)]
    pub document_date: Option<i64>,
    /// The latest confirmed date, epoch seconds. `None` when the document has no date.
    #[serde(default)]
    pub document_date_max: Option<i64>,
}

impl SearchResultDocumentItem {
    pub fn document_identifier(&self) -> DocumentIdentifier {
        DocumentIdentifier {
            collection_dataset: self.collection_dataset.clone(),
            file_hash: self.file_hash.clone(),
        }
    }

    /// The date that `sort` orders this result by. Newest first orders by the latest date,
    /// and every other order by the earliest date, as `search_sql::sort_column` does.
    pub fn sort_date(&self, sort: SortSpec) -> Option<i64> {
        let sort = sort.normalized();
        if sort.key == SortKey::Date && sort.desc { self.document_date_max } else { self.document_date }
    }

    /// The size line of the card, empty for an unknown size.
    pub fn card_size_label(&self) -> String {
        match self.file_size_bytes {
            Some(bytes) if bytes >= 0 => crate::storage_tree::format_size(bytes as u64),
            _ => String::new(),
        }
    }

    /// The date line of the card under `sort`, `YYYY-MM-DD` in UTC, empty for no date.
    pub fn card_date_label(&self, sort: SortSpec) -> String {
        self.sort_date(sort).map(crate::document_provenance::format_epoch_date_utc).unwrap_or_default()
    }
}

/// The size and the dates of one document, as the search sort reads them. A chat or board
/// card reads them with one point query, because its stored citation holds neither.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DocumentCardFacts {
    pub file_size_bytes: Option<i64>,
    pub date_min: Option<i64>,
    pub date_max: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultFacets {
    pub query: SearchQuery,
    pub facet_field: String,
    pub facet_values: Vec<SearchResultFacetItem>,
    /// True when at least one shard could not be searched (see the fan-out
    /// partial-failure policy). Buckets from the failed shard are missing, so
    /// counts may be lower than the real ones.
    #[serde(default)]
    pub partial: bool,
}

/// Hit-count endpoint response.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultHitCount {
    /// Sum of `count(distinct file_hash)` over all searched shards. Upper bound
    /// normally (the same file_hash can exist in two collections); a lower bound
    /// when `partial` is true, because the failed shards' counts are missing.
    pub total: u64,
    /// True when at least one shard could not be searched.
    #[serde(default)]
    pub partial: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultFacetItem {
    pub display_string: String,
    pub original_value: FacetOriginalValue,
    pub count: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialOrd, Ord, PartialEq, Eq)]
pub enum FacetOriginalValue {
    String(String),
    Int(u64),
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(size: Option<i64>, min: Option<i64>, max: Option<i64>) -> SearchResultDocumentItem {
        SearchResultDocumentItem {
            title: String::new(), highlight_text_spans: vec![], highlight_filenames_spans: vec![],
            file_hash: String::new(), collection_dataset: String::new(), result_index_in_page: 0,
            matched_by_filename: false, file_type: String::new(), file_size_bytes: size,
            document_date: min, document_date_max: max,
        }
    }

    #[test]
    fn the_card_date_follows_the_sort() {
        let doc = item(None, Some(10), Some(20));
        let sort = |key, desc| SortSpec { key, desc };
        assert_eq!(doc.sort_date(sort(SortKey::Date, true)), Some(20));
        assert_eq!(doc.sort_date(sort(SortKey::Date, false)), Some(10));
        assert_eq!(doc.sort_date(sort(SortKey::Relevance, true)), Some(10));
        assert_eq!(doc.sort_date(sort(SortKey::Relevance, false)), Some(10));
        assert_eq!(doc.sort_date(sort(SortKey::FileSize, true)), Some(10));
        assert_eq!(doc.sort_date(sort(SortKey::Name, false)), Some(10));
    }

    #[test]
    fn the_card_size_is_empty_when_unknown() {
        assert_eq!(item(None, None, None).card_size_label(), "");
        assert_eq!(item(Some(-1), None, None).card_size_label(), "");
        assert_eq!(item(Some(0), None, None).card_size_label(), "0 B");
        assert_eq!(item(Some(535_552), None, None).card_size_label(), "523 KB");
        assert_eq!(item(Some(2_501_818_040), None, None).card_size_label(), "2.33 GB");
        assert_eq!(item(None, None, None).card_date_label(SortSpec::default()), "");
        assert_eq!(item(None, Some(1_191_970_800), None).card_date_label(SortSpec::default()), "2007-10-09");
    }
}
