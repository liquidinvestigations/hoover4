use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct PdfSearchResults {
    pub results: Vec<PdfSearchResult>,
    pub total: i32,
}

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct PdfSearchResult {
    #[serde(rename = "pageIndex")]
    pub page_index: i32,
    #[serde(rename = "charIndex")]
    pub char_index: i32,
    #[serde(rename = "charCount")]
    pub char_count: i32,
    pub rects: Vec<PdfSearchResultRect>,
    pub context: PdfSearchResultContext,
}

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct PdfSearchResultRect {
    pub origin: RectPoint,
    pub size: RectSize,
}

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct RectPoint {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct RectSize {
    pub width: f64,
    pub height: f64,
}

#[derive(Debug, Deserialize, Clone, Serialize)]
pub struct PdfSearchResultContext {
    pub before: String,
    #[serde(rename = "match")]
    pub _match: String,
    pub after: String,
    #[serde(rename = "truncatedLeft")]
    pub truncated_left: bool,
    #[serde(rename = "truncatedRight")]
    pub truncated_right: bool,
}
