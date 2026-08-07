//! Shared types for document text source metadata.
//!
//! Also the Rust half of the `extracted_by` convention. The Python half is
//! `main_services/processing/tasks/text_sources.py`, and the duplication is deliberate
//! for the same reason `collectionname` validation is duplicated: neither runtime may
//! depend on the other being right about a value that is simultaneously a storage key
//! and a user-visible label.

use serde::{Deserialize, Serialize};

use crate::text_highlight::HighlightTextSpan;

/// Prefix marking an OCR variant. Native extractors carry no prefix.
pub const OCR_PREFIX: &str = "ocr_";

/// OCR engines that may appear inside an `extracted_by` value.
pub const OCR_ENGINES: [&str; 2] = ["tesseract", "easyocr"];

/// One `extracted_by` value, taken apart for display.
///
/// ```text
/// native:       pdftotext | extractous | office_xml | email_parser | raw_text | qpdf
/// OCR variants: ocr_<engine>_<languages>   e.g. ocr_tesseract_eng+ron, ocr_easyocr_en
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TextSource {
    /// An extractor that read the file's own text.
    Native { extractor: String },
    /// An OCR pass, identified by the engine and the `+`-joined language set it ran with.
    Ocr { engine: String, languages: String },
}

impl TextSource {
    /// Parse an `extracted_by` value. Anything that does not match the OCR shape exactly
    /// is treated as a native extractor rather than guessed at — a half-recognised label
    /// rendered as a broken OCR chip is worse than one rendered verbatim.
    pub fn parse(extracted_by: &str) -> Self {
        if let Some(rest) = extracted_by.strip_prefix(OCR_PREFIX) {
            // Split once: the language field may contain `+` and must stay intact.
            if let Some((engine, languages)) = rest.split_once('_') {
                if OCR_ENGINES.contains(&engine) && !languages.is_empty() {
                    return TextSource::Ocr {
                        engine: engine.to_string(),
                        languages: languages.to_string(),
                    };
                }
            }
        }
        TextSource::Native {
            extractor: extracted_by.to_string(),
        }
    }

    /// The label shown in the source selector, e.g. `OCR · Tesseract · eng+ron`.
    ///
    /// **The only place an `extracted_by` string is turned into display text.** The D4
    /// fan-out turns 3–4 sources into 6–10, and parsing this string in each component
    /// that renders one is how they start disagreeing about what a source is called.
    pub fn label(&self) -> String {
        match self {
            TextSource::Native { extractor } => match extractor.as_str() {
                "pdftotext" => "PDF text".to_string(),
                "extractous" => "Extracted text".to_string(),
                "office_xml" => "Office XML".to_string(),
                "email_parser" => "Email body".to_string(),
                "raw_text" => "Plain text".to_string(),
                other => other.to_string(),
            },
            TextSource::Ocr { engine, languages } => {
                let engine = match engine.as_str() {
                    "tesseract" => "Tesseract",
                    "easyocr" => "EasyOCR",
                    other => other,
                };
                format!("OCR · {engine} · {languages}")
            }
        }
    }

    pub fn is_ocr(&self) -> bool {
        matches!(self, TextSource::Ocr { .. })
    }
}

/// Convenience for call sites that only need the label.
pub fn text_source_label(extracted_by: &str) -> String {
    TextSource::parse(extracted_by).label()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ocr_variants_parse_into_engine_and_languages() {
        assert_eq!(
            TextSource::parse("ocr_tesseract_eng+ron"),
            TextSource::Ocr {
                engine: "tesseract".into(),
                languages: "eng+ron".into()
            }
        );
        assert_eq!(
            TextSource::parse("ocr_easyocr_en"),
            TextSource::Ocr {
                engine: "easyocr".into(),
                languages: "en".into()
            }
        );
    }

    #[test]
    fn native_extractors_are_not_ocr() {
        for native in ["pdftotext", "extractous", "office_xml", "email_parser", "raw_text", "qpdf"] {
            assert!(!TextSource::parse(native).is_ocr(), "{native}");
        }
    }

    #[test]
    fn malformed_labels_fall_back_to_native_rather_than_guessing() {
        for bad in ["ocr_tesseract", "ocr_unknown_eng", "ocr_tesseract_", "ocr_"] {
            assert!(!TextSource::parse(bad).is_ocr(), "{bad}");
        }
    }

    #[test]
    fn labels_are_human_readable() {
        assert_eq!(
            text_source_label("ocr_tesseract_eng+ron"),
            "OCR · Tesseract · eng+ron"
        );
        assert_eq!(text_source_label("pdftotext"), "PDF text");
        // An unknown extractor is shown verbatim rather than hidden.
        assert_eq!(text_source_label("some_new_parser"), "some_new_parser");
    }

    /// Mirrors `tests/unit/test_text_sources.py::test_language_order_is_preserved...`:
    /// `eng+ron` and `ron+eng` are genuinely different Tesseract requests and therefore
    /// different variants, so neither side may normalise the order.
    #[test]
    fn language_order_is_significant() {
        let a = TextSource::parse("ocr_tesseract_eng+ron");
        let b = TextSource::parse("ocr_tesseract_ron+eng");
        assert_ne!(a, b);
    }
}

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

/// One PDF the viewer can show for a document: the original, or a derived searchable one.
///
/// `engine` empty means the original file. A non-empty `engine`/`languages` pair names a
/// row in `pdf_ocr_results`, and those two fields *are* the storage key — the same pair
/// that keys the MinIO object and the `/_download_ocr_pdf/` route. They are carried here
/// rather than a ready-made url so the selector can label the source properly and the
/// viewer can build the url one way, in one place.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentPdfSourceItem {
    pub page_count: u32,
    /// `""` for the original document, otherwise `tesseract` | `easyocr`.
    #[serde(default)]
    pub engine: String,
    /// `+`-joined language codes the OCR pass ran with. Empty for the original.
    #[serde(default)]
    pub languages: String,
}

impl DocumentPdfSourceItem {
    pub fn is_ocr(&self) -> bool {
        !self.engine.is_empty()
    }

    /// The label in the source selector: `PDF`, or `PDF · OCR · Tesseract · eng+ron`.
    ///
    /// Built from the same formatter the text selector uses, so a document whose text and
    /// whose PDF both come from one OCR pass say the same thing about it in both places.
    pub fn label(&self) -> String {
        if self.is_ocr() {
            format!(
                "PDF \u{b7} {}",
                TextSource::Ocr {
                    engine: self.engine.clone(),
                    languages: self.languages.clone(),
                }
                .label()
            )
        } else {
            "PDF".to_string()
        }
    }

    /// Where the viewer fetches this source from.
    ///
    /// The original goes through the document route; a derived PDF has no `blobs` row by
    /// design and goes through its own, keyed by the same four values as its row.
    pub fn url(&self, collection_dataset: &str, file_hash: &str) -> String {
        if self.is_ocr() {
            format!(
                "/_download_ocr_pdf/{collection_dataset}/{file_hash}/{}/{}",
                self.engine, self.languages
            )
        } else {
            format!("/_download_document/{collection_dataset}/{file_hash}")
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentEmailSourceItem {
    pub subject: String,
    pub addresses: String,
    pub date_sent: String,
    pub raw_headers_json: String,
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
    Email(DocumentEmailSourceItem),
    Image(DocumentImageSourceItem),
    Video(DocumentVideoSourceItem),
    Audio(DocumentAudioSourceItem),
    Text(DocumentTextSourceItem),
    FileLocations,
    /// No longer offered as a preview source — the viewer's Metadata tab is the metadata
    /// surface. Kept because it is part of the URL-encoded viewer state and dropping the
    /// variant would turn every bookmark carrying it into a parse failure.
    Metadata,
}

impl Eq for DocumentSourceItem {}

// Ord can't be derived because the variants carry f32 fields (no total order);
// PartialOrd stays derived and NaN-shaped comparisons fall back to Less.
#[allow(clippy::derive_ord_xor_partial_ord)]
impl Ord for DocumentSourceItem {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.partial_cmp(other).unwrap_or(std::cmp::Ordering::Less)
    }
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, PartialOrd, Default)]
pub struct ItemHitCounts(pub Vec<(DocumentSourceItem, u64)>);
