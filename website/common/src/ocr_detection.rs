//! The OCR detection of a document, as the metadata tab shows it.
//!
//! The worker stores one `ocr_detection` row for each image and each examined PDF page.
//! The values describe the document, and they select no OCR language.

use serde::{Deserialize, Serialize};

/// One detected value and the pages that report it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct OcrDetectionValue {
    /// A script name such as `Latin`, or a language name in English.
    pub value: String,
    pub pages: u64,
}

/// The summary of the rows of one document, most frequent value first.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DocumentOcrDetection {
    pub pages_examined: u64,
    pub pages_with_text: u64,
    pub scripts: Vec<OcrDetectionValue>,
    pub languages: Vec<OcrDetectionValue>,
}
