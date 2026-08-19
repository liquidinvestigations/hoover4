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

/// The `extracted_by` value under which an email's parsed body is stored.
pub const EMAIL_TEXT_EXTRACTOR: &str = "email_parser";

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
    /// **The only place an `extracted_by` string is turned into display text.** The OCR
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
    fn an_email_with_no_parsed_date_has_no_sent_date() {
        let email = |date_sent: &str| DocumentEmailSourceItem {
            subject: String::new(),
            addresses: String::new(),
            date_sent: date_sent.to_string(),
            raw_headers_json: String::new(),
            min_page: 1,
            max_page: 1,
            has_body: true,
        };
        // The two shapes "we do not know" arrives in: the epoch the DateTime column
        // falls back to, and the empty string the query emits once it has consulted
        // `date_sent_known`.
        assert_eq!(email(EMAIL_DATE_UNKNOWN).sent_date(), None);
        assert_eq!(email("").sent_date(), None);
        assert_eq!(
            email("2013-10-10T17:04:49Z").sent_date(),
            Some("2013-10-10T17:04:49Z")
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

    /// Viewer state is URL-encoded and outlives the build that wrote it, so every field
    /// added to it has to decide what an absent value means. For `has_body` that is
    /// "present": a bookmark written before the field existed describes a document the
    /// server re-describes on load anyway, and the alternative default would tell a
    /// reader an ordinary email has no body until the fetch returns.
    #[test]
    fn an_email_source_without_a_stored_body_flag_still_reads_as_having_one() {
        use super::DocumentEmailSourceItem;
        let old: DocumentEmailSourceItem = serde_json::from_str(
            r#"{"subject":"s","addresses":"a","date_sent":"","raw_headers_json":"{}"}"#,
        )
        .expect("state written before the field existed must still parse");
        assert!(old.has_body);
        assert_eq!((old.min_page, old.max_page), (0, 0));

        let stated: DocumentEmailSourceItem = serde_json::from_str(
            r#"{"subject":"s","addresses":"a","date_sent":"","raw_headers_json":"{}","has_body":false}"#,
        )
        .unwrap();
        assert!(!stated.has_body);
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
    /// Page range of this email's parsed body in `text_content`, i.e. of its
    /// `email_parser` rows. Carried here because the email preview renders that text and
    /// has to ask for a page that exists: `page_id` is 1-based and a request for page 0
    /// matches nothing at all. Defaulted for URL-encoded viewer state written without it,
    /// and every reader floors it at 1 rather than trusting the default.
    ///
    /// Meaningless when [`DocumentEmailSourceItem::has_body`] is false — there is no row
    /// to name a page of.
    #[serde(default)]
    pub min_page: u32,
    #[serde(default)]
    pub max_page: u32,
    /// Whether this email has any parsed body text at all.
    ///
    /// A mail file gets an `emails` row for its headers and a separate `email_parser`
    /// text variant for its body, and the second is not implied by the first: the text
    /// writer drops a page whose stripped text is shorter than two characters, so mail
    /// whose whole `text/plain` part is a single `,` — Enron's export is full of them —
    /// stores headers and no body, exactly like mail whose only body part is HTML.
    /// Without this flag the viewer offers the Email source, asks for a body page that
    /// does not exist, and renders the text endpoint's 404 where the body belongs.
    ///
    /// Defaults to TRUE for URL-encoded viewer state written before the field existed:
    /// that state describes a document the server is about to re-describe anyway, and
    /// the old behaviour is the safer default of the two.
    #[serde(default = "email_body_present_by_default")]
    pub has_body: bool,
}

/// See [`DocumentEmailSourceItem::has_body`]: absent means "written before the field
/// existed", not "no body".
fn email_body_present_by_default() -> bool {
    true
}

/// `date_sent` as it arrives for an email whose `Date:` header never parsed.
///
/// `email_headers.date_sent` is a `DateTime` whose fallback is the epoch, so the epoch
/// and "no date" are the same value in storage — `date_sent_known` is the column that
/// separates them.
pub const EMAIL_DATE_UNKNOWN: &str = "1970-01-01T00:00:00Z";

impl DocumentEmailSourceItem {
    /// The `Date:` header as sent, or `None` when the document has none.
    ///
    /// The epoch is rejected here as well as at the query that fills the field: viewer
    /// state restored from a URL carries whatever was written into it, and printing
    /// `1970-01-01T00:00:00Z` as a sent date contradicts the Metadata tab, which reports
    /// the same document as having no confirmed date.
    pub fn sent_date(&self) -> Option<&str> {
        match self.date_sent.trim() {
            "" | EMAIL_DATE_UNKNOWN => None,
            date => Some(date),
        }
    }
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
    /// Not offered as a preview source — the viewer's Metadata tab is the metadata
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
