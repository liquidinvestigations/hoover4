
use serde::{Deserialize, Serialize};

use crate::search_result::DocumentIdentifier;
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PDFToHtmlConversionResponse {
    pub pages: Vec<String>,
    pub styles: Vec<String>,
    pub page_width_px: f32,
    pub page_height_px: f32,
}