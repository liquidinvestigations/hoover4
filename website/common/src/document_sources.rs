//! Shared types for document text source metadata.

use serde::{Deserialize, Serialize};

use crate::text_highlight::HighlightTextSpan;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentTextSourceItem {
    pub extracted_by: String,
    pub min_page: u32,
    pub max_page: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentTextSourceHit {
    pub extracted_by: String,
    pub page_id: u32,
    pub highlight_text_spans: Vec<HighlightTextSpan>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentTextSourceHitCount {
    pub extracted_by: String,
    pub page_id: u32,
    pub hit_count: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentPdfSourceItem {
    pub page_count: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentImageSourceItem {
    pub width: u32,
    pub height: u32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentVideoSourceItem {
    pub width: u32,
    pub height: u32,
    pub duration_seconds: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentAudioSourceItem {
    pub duration_seconds: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub enum DocumentSourceItem {
    Pdf(DocumentPdfSourceItem),
    Image(DocumentImageSourceItem),
    Video(DocumentVideoSourceItem),
    Audio(DocumentAudioSourceItem),
    Text(DocumentTextSourceItem),
    FileLocations,
    Metadata,
}
