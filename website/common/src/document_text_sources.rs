//! Shared types for document text source metadata.

use serde::{Deserialize, Serialize};

use crate::text_highlight::HighlightTextSpan;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentTextSourceItem {
    pub extracted_by: String,
    pub min_page: u32,
    pub max_page: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentTextSourceHit {
    pub extracted_by: String,
    pub page_id: u32,
    pub highlight_text_spans: Vec<HighlightTextSpan>,
}


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentTextSourceHitCount {
    pub extracted_by: String,
    pub page_id: u32,
    pub hit_count: u64,
}