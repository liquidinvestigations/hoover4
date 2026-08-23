//! Shared search result models.

use serde::{Deserialize, Serialize};

use crate::{search_query::SearchQuery, text_highlight::HighlightTextSpan};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultDocuments {
    pub query: SearchQuery,
    pub results: Vec<SearchResultDocumentItem>,
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
}

impl SearchResultDocumentItem {
    pub fn document_identifier(&self) -> DocumentIdentifier {
        DocumentIdentifier {
            collection_dataset: self.collection_dataset.clone(),
            file_hash: self.file_hash.clone(),
        }
    }
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
