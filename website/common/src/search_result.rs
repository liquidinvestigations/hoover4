use serde::{Deserialize, Serialize};

use crate::{search_query::SearchQuery, text_highlight::HighlightTextSpan};


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultDocuments {
    pub query: SearchQuery,
    pub results: Vec<SearchResultDocumentItem>,
    pub prev_hash: Option<DocumentIdentifier>,
    pub next_hash: Option<DocumentIdentifier>,
    pub page_number: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Hash, Eq, PartialOrd, Ord)]
pub struct DocumentIdentifier {
    pub collection_dataset: String,
    pub file_hash: String,
}


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchResultDocumentItem {
    pub title: String,
    pub highlight_text_spans: Vec<HighlightTextSpan>,
    pub highlight_filenames_spans: Vec<HighlightTextSpan>,
    pub file_hash: String,
    pub collection_dataset: String,
    pub result_index_in_page: u64,
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