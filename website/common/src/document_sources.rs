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
pub const PDF_OCR_PREFIX: &str = "pdfocr_";

/// The `extracted_by` value under which an email's parsed body is stored.
pub const EMAIL_TEXT_EXTRACTOR: &str = "email_parser";

/// The format-specific text of a binary Word file.
pub const BINARY_WORD_TEXT_EXTRACTOR: &str = "binary_word";

/// OCR engines that may appear inside an `extracted_by` value.
pub const OCR_ENGINES: [&str; 2] = ["tesseract", "easyocr"];

/// One `extracted_by` value, taken apart for display.
///
/// ```text
/// native:       binary_word | pdftotext | extractous | office_xml | email_parser | email_html | email_rtf | email_richtext | raw_text | qpdf
/// OCR variants: ocr_<engine>_<languages>   e.g. ocr_tesseract_eng+ron, ocr_easyocr_en
/// ```
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TextSource {
    /// An extractor that read the file's own text.
    Native { extractor: String },
    /// An OCR pass, identified by the engine and the `+`-joined language set it ran with.
    Ocr { engine: String, languages: String },
    PdfOcr { engine: String, languages: String },
}

impl TextSource {
    /// Parse an `extracted_by` value. Anything that does not match the OCR shape exactly
    /// is treated as a native extractor rather than guessed at, a half-recognised label
    /// rendered as a broken OCR chip is worse than one rendered verbatim.
    pub fn parse(extracted_by: &str) -> Self {
        if let Some(rest) = extracted_by.strip_prefix(PDF_OCR_PREFIX).or_else(|| extracted_by.strip_prefix(OCR_PREFIX)) {
            // Split once: the language field may contain `+` and must stay intact.
            if let Some((engine, languages)) = rest.split_once('_') {
                if OCR_ENGINES.contains(&engine) && !languages.is_empty() {
                    return if extracted_by.starts_with(PDF_OCR_PREFIX) {
                        TextSource::PdfOcr { engine: engine.to_string(), languages: languages.to_string() }
                    } else {
                        TextSource::Ocr { engine: engine.to_string(), languages: languages.to_string() }
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
                "binary_word" => "Word text".to_string(),
                "pdftotext" => "PDF text".to_string(),
                "extractous" => "Extracted text".to_string(),
                "office_xml" => "Office XML".to_string(),
                "table_text" => "Table text".to_string(),
                "email_parser" => "Email body".to_string(),
                "email_html" => "Email HTML".to_string(),
                "email_rtf" => "Email RTF".to_string(),
                "email_richtext" => "Email rich text".to_string(),
                "raw_text" => "Raw file text".to_string(),
                other => other.to_string(),
            },
            TextSource::PdfOcr { engine, languages } => format!("PDF {}", TextSource::Ocr { engine: engine.clone(), languages: languages.clone() }.label()),
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
        matches!(self, TextSource::Ocr { .. } | TextSource::PdfOcr { .. })
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
    fn pdf_manifest_refresh_preserves_identity_and_changes_value() {
        let old: DocumentPdfSourceItem = serde_json::from_str(r#"{"page_count":1020,"engine":"tesseract","languages":"eng"}"#).unwrap();
        assert_eq!(old.kind(),"original");
        assert!(old.parts.is_empty());
        let mut refreshed = old.clone();
        refreshed.source_kind = "original".into();
        refreshed.parts = vec![DocumentPdfPart {part_index:1,first_page:1,last_page:100,size_bytes:30_000_000}];
        assert_ne!(old,refreshed);
        assert!(DocumentSourceItem::Pdf(old).same_source(&DocumentSourceItem::Pdf(refreshed.clone())));
        assert_eq!(refreshed.part_for_page(100).unwrap().part_index,1);
        assert!(refreshed.part_for_page(101).is_none());
        assert_eq!(refreshed.text_source(),"pdfocr_tesseract_eng");
        assert_eq!(refreshed.label(),"PDF · OCR · Tesseract · eng");
        let image = DocumentPdfSourceItem {source_kind:"image".into(),..refreshed};
        assert_eq!(image.text_source(),"ocr_tesseract_eng");
        assert_eq!(image.label(),"Preview OCR · Tesseract · eng");
        assert_eq!(text_source_label("pdfocr_tesseract_eng+ron"),"PDF OCR · Tesseract · eng+ron");
    }

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
        for native in ["binary_word", "pdftotext", "extractous", "office_xml", "table_text", "email_parser", "raw_text", "qpdf"] {
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
        assert_eq!(text_source_label("table_text"), "Table text");
        assert_eq!(text_source_label("binary_word"), "Word text");
        // An unknown extractor is shown verbatim rather than hidden.
        assert_eq!(text_source_label("some_new_parser"), "some_new_parser");
    }

    #[test]
    fn binary_word_text_precedes_extractous_text() {
        let source = |extracted_by: &str| DocumentSourceItem::Text(DocumentTextSourceItem {
            extracted_by: extracted_by.to_string(), min_page: 1, max_page: 1,
        });
        let mut sources = vec![source("extractous"), source("binary_word")];
        sources.sort();
        assert_eq!(sources[0], source("binary_word"));
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

    /// `get_document_sources` sorts by declaration order, so a workbook opens on its
    /// grid rather than on the tab-separated flattening of it that the text extractor
    /// also produced for the same document. That is the whole reason `Table` sits where
    /// it sits in the enum, and nothing else pins it.
    #[test]
    fn the_source_list_sorts_table_above_text() {
        let table = DocumentSourceItem::Table(DocumentTableSourceItem {
            sheet_count: 1,
            row_count: 701,
            column_count: 16,
            table_format: "csv".into(),
        });
        let text = DocumentSourceItem::Text(DocumentTextSourceItem {
            extracted_by: "extractous".into(),
            min_page: 1,
            max_page: 1,
        });
        let mut sources = vec![text.clone(), table.clone()];
        sources.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        assert_eq!(sources.first(), Some(&table));
        assert_eq!(sources.last(), Some(&text));
    }

    #[test]
    fn a_table_source_names_its_sheets_and_not_its_format() {
        let one = DocumentTableSourceItem {
            sheet_count: 1,
            row_count: 6,
            column_count: 300,
            table_format: "csv".into(),
        };
        assert_eq!(one.label(), "Table");
        let two = DocumentTableSourceItem { sheet_count: 2, table_format: "xlsx".into(), ..one };
        assert_eq!(two.label(), "Table (2 sheets)");
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

/// A PDF source with document page ranges.
#[derive(Debug, Clone, PartialEq, PartialOrd, Serialize, Deserialize)]
pub struct DocumentPdfSourceItem {
    pub page_count: u32,
    #[serde(default)]
    pub engine: String,
    #[serde(default)]
    pub languages: String,
    #[serde(default = "original_pdf_kind")]
    pub source_kind: String,
    #[serde(default)]
    pub parts: Vec<DocumentPdfPart>,
}

impl Default for DocumentPdfSourceItem {
    fn default() -> Self {
        Self {page_count:0,engine:String::new(),languages:String::new(),source_kind:original_pdf_kind(),parts:Vec::new()}
    }
}

fn original_pdf_kind() -> String { "original".into() }

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentPdfPart {
    pub part_index: u16,
    pub first_page: u32,
    pub last_page: u32,
    pub size_bytes: u64,
}

impl DocumentPdfSourceItem {
    pub fn identity(&self) -> (&str, &str, &str) { (self.kind(), &self.engine, &self.languages) }
    pub fn kind(&self) -> &str { if self.source_kind.is_empty() { "original" } else { &self.source_kind } }
    pub fn is_ocr(&self) -> bool { !self.engine.is_empty() }
    pub fn text_source(&self) -> String {
        if self.is_ocr() {
            format!("{}_{}_{}", if self.kind() == "image" { "ocr" } else { "pdfocr" }, self.engine, self.languages)
        } else { "pdftotext".into() }
    }
    pub fn source_name(&self) -> String {
        if self.is_ocr() { self.text_source() } else if self.kind() == "preview" { "preview".into() } else { String::new() }
    }
    pub fn label(&self) -> String {
        if self.kind() == "image" {
            return format!("Preview {}",TextSource::Ocr {engine:self.engine.clone(),languages:self.languages.clone()}.label());
        }
        let base = match self.kind() { "preview" => "PDF preview", _ => "PDF" };
        if self.is_ocr() {
            format!("{} · {}", base, TextSource::Ocr { engine: self.engine.clone(), languages: self.languages.clone() }.label())
        } else { base.into() }
    }
    pub fn url(&self, dataset: &str, hash: &str) -> String {
        if self.is_ocr() { format!("/_download_ocr_pdf/{dataset}/{hash}/{}/{}", self.engine, self.languages) }
        else if self.kind() == "preview" { format!("/_download_pdf/{dataset}/{hash}/preview") }
        else { format!("/_download_document/{dataset}/{hash}") }
    }
    pub fn part_url(&self, dataset: &str, hash: &str, part_index: u16) -> String {
        format!("/_download_pdf_part/{dataset}/{hash}/{}/{}/{}/{part_index}", self.kind(),
            if self.engine.is_empty() { "-" } else { &self.engine },
            if self.languages.is_empty() { "-" } else { &self.languages })
    }
    pub fn part_for_page(&self, page: u32) -> Option<&DocumentPdfPart> {
        self.parts.iter().find(|part| part.first_page <= page && page <= part.last_page)
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
    /// Meaningless when [`DocumentEmailSourceItem::has_body`] is false, there is no row
    /// to name a page of.
    #[serde(default)]
    pub min_page: u32,
    #[serde(default)]
    pub max_page: u32,
    /// Whether this email has any parsed body text at all.
    ///
    /// A mail file gets an `emails` row for its headers and a separate `email_parser`
    /// text variant for its body. Some messages have no readable body. Without this
    /// flag the viewer requests an absent body page and shows a text endpoint error.
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
/// and "no date" are the same value in storage: `date_sent_known` is the column that
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
    /// The worker stored a JPEG preview, which the viewer shows in place of the file.
    /// An older link has no such field and decodes as `false`.
    #[serde(default)]
    pub preview: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentVideoSourceItem {
    pub width: u32,
    pub height: u32,
    pub duration_seconds: f32,
    /// The worker stored the first frame as a JPEG, which the player shows as its poster.
    #[serde(default)]
    pub preview: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentAudioSourceItem {
    pub duration_seconds: f32,
}

/// A tabular document the pipeline read into cells, as the source selector names it.
///
/// **Identity, not view state.** This variant is the key of [`ItemHitCounts`]' map and the
/// value `sources.iter().find(|s| *s == &selected_source)` compares, so it holds only what
/// makes this source *this* source. The selected sheet, the sort, the filters and the
/// hidden columns live in the viewer state that goes into the URL; a variant that changed
/// when the reader clicked a column header would stop matching the selected source and
/// deselect itself on every interaction.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct DocumentTableSourceItem {
    pub sheet_count: u16,
    /// Rows summed across every sheet, as `table_documents` records it.
    pub row_count: u64,
    /// Widest column ordinal across every sheet.
    pub column_count: u32,
    /// `csv` | `tsv` | `xlsx` | `xls` | `ods` | ...
    pub table_format: String,
}

impl DocumentTableSourceItem {
    /// The label in the source selector: `Table (2 sheets)`. The file format is not in
    /// it, because the file name already shows the extension.
    pub fn label(&self) -> String {
        if self.sheet_count > 1 {
            format!("Table ({} sheets)", self.sheet_count)
        } else {
            "Table".to_string()
        }
    }
}

/// The `kind` of an email archive: a mail store such as PST, OST or mbox.
pub const EMAIL_ARCHIVE: &str = "email_archive";
/// The `kind` of another archive, such as ZIP, TAR, 7z or RAR.
pub const ARCHIVE: &str = "archive";

/// MIME types of mail stores, which hold many messages.
const MAIL_STORE_TYPES: &[&str] = &["application/x-hoover-pst", "application/vnd.ms-outlook-pst",
    "application/vnd.ms-outlook-ost", "application/mbox"];
/// MIME types of one message or of an attachment wrapper. Such a file is not an archive even
/// when the pipeline extracted its attachments.
const MESSAGE_TYPES: &[&str] = &["message/rfc822", "application/vnd.ms-outlook", "application/x-ms-msg",
    "application/ms-tnef", "application/vnd.ms-tnef"];
/// MIME types of archives.
const ARCHIVE_TYPES: &[&str] = &["application/zip", "application/x-zip-compressed", "application/x-tar",
    "application/x-ustar", "application/gzip", "application/x-gzip", "application/x-7z-compressed",
    "application/vnd.rar", "application/x-rar", "application/x-rar-compressed", "application/x-bzip2",
    "application/x-xz", "application/x-iso9660-image", "application/x-cpio"];

/// The archive kind of a file, or `None` for a file that is not an archive.
///
/// `archive_types` holds the MIME types of the file's `archives` row, when it has one, and
/// `mime` and `file_type` come from `file_type_canonical`. A mail store gives
/// [`EMAIL_ARCHIVE`]. One message or an attachment wrapper (EML, MSG, TNEF) gives `None`,
/// as do images and videos that have an `archives` row. A known archive type, or the
/// canonical type `archive`, gives [`ARCHIVE`]. A VFS container node is not evidence: an
/// email with attachments is a container, and an empty archive has no container node.
pub fn archive_kind(archive_types: &[&str], mime: &str, file_type: &str) -> Option<&'static str> {
    let has = |list: &[&str]| archive_types.iter().chain(std::iter::once(&mime)).any(|t| list.contains(t));
    if has(MAIL_STORE_TYPES) {
        return Some(EMAIL_ARCHIVE);
    }
    if has(MESSAGE_TYPES) || mime.starts_with("image/") || mime.starts_with("video/")
        || mime.starts_with("audio/") || archive_types.contains(&"video")
    {
        return None;
    }
    (has(ARCHIVE_TYPES) || file_type == "archive").then_some(ARCHIVE)
}

/// An archive or a mail store, for the Archive tab of the viewer and the `archive` object of
/// the agent document routes. One lookup fills both (`get_document_sources::archive_info`).
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize, PartialOrd)]
pub struct DocumentArchiveSourceItem {
    /// [`EMAIL_ARCHIVE`] or [`ARCHIVE`].
    pub kind: String,
    /// The canonical MIME type of the archive file.
    #[serde(default)]
    pub mime: String,
    /// The files that the pipeline extracted from the archive, through every level, as
    /// `vfs_nodes.subtree_file_count` counts their locations. `None` when the archive has no
    /// container node or the count is unknown. An extracted file is not always searchable.
    #[serde(default)]
    pub extracted_file_count: Option<u64>,
    /// The bytes of the extracted files (`vfs_nodes.subtree_size_bytes`), or `None`.
    #[serde(default)]
    pub extracted_size_bytes: Option<u64>,
    /// The size of the archive file itself, or `None`.
    #[serde(default)]
    pub size_bytes: Option<u64>,
    #[serde(default)]
    pub dataset: String,
    #[serde(default)]
    pub path: String,
    /// The folder node of the archive, which `folder_list` and the file browser open.
    /// `None` when the extraction created no container node.
    #[serde(default)]
    pub node_id: Option<String>,
    /// The `folder_term_id` that scopes a search to the archive, or `None`.
    #[serde(default)]
    pub folder_term_id: Option<u64>,
    /// The processing tasks that recorded an error for the archive file itself. One task
    /// can fail for several extracted messages, so this is not a count of failed files.
    #[serde(default)]
    pub processing_errors: u32,
}

impl DocumentArchiveSourceItem {
    /// The tab name: `Email Archive` or `Archive`.
    pub fn label(&self) -> &'static str {
        if self.kind == EMAIL_ARCHIVE { "Email Archive" } else { "Archive" }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub enum DocumentSourceItem {
    /// Declared first, so an archive opens on its Archive tab. Variants sort by declaration
    /// order, and the URL names a variant by its name, so older links decode unchanged.
    Archive(DocumentArchiveSourceItem),
    Pdf(DocumentPdfSourceItem),
    Email(DocumentEmailSourceItem),
    /// Declared before `Text` on purpose: variants sort by declaration order and
    /// `get_document_sources` sorts the list, so a workbook opens on its grid rather than
    /// on the tab-separated flattening of it that the text extractor also produced.
    Table(DocumentTableSourceItem),
    Image(DocumentImageSourceItem),
    Video(DocumentVideoSourceItem),
    Audio(DocumentAudioSourceItem),
    Text(DocumentTextSourceItem),
    /// Not offered as a preview source. The viewer's File Locations tab is where a
    /// document's paths live. Kept because it is part of the URL-encoded viewer state and
    /// dropping the variant would turn every bookmark carrying it into a parse failure,
    /// which the router shows as "Page not found".
    FileLocations,
    /// Not offered as a preview source. The viewer's Metadata tab is the metadata
    /// surface. Kept for the same reason as the variant above.
    Metadata,
}

impl DocumentSourceItem {
    pub fn route_identity(&self) -> Self {
        match self {
            Self::Pdf(source) => Self::Pdf(DocumentPdfSourceItem {page_count:0,parts:Vec::new(),..source.clone()}),
            // The counts change while processing runs, so the address holds the kind only.
            Self::Archive(source) => Self::Archive(DocumentArchiveSourceItem { kind: source.kind.clone(), ..Default::default() }),
            _ => self.clone(),
        }
    }
    pub fn same_source(&self, other: &Self) -> bool {
        match (self, other) {
            (Self::Pdf(a),Self::Pdf(b)) => a.identity() == b.identity(),
            (Self::Archive(_), Self::Archive(_)) => true,
            _ => self == other,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentSourcesStatus {
    pub sources: Vec<DocumentSourceItem>,
    pub errors: Vec<String>,
    #[serde(default)]
    pub processing: DocumentProcessingStatus,
}

/// The processing state of this document in its dataset.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum DocumentProcessingStatus {
    #[default]
    NotPlanned,
    Running,
    Failed { tasks: Vec<String> },
    Done,
    Stopped { operation_state: String },
    QueryFailed,
}

impl DocumentProcessingStatus {
    pub fn empty_source_message(&self) -> String {
        match self {
            Self::NotPlanned => "Processing has not reached this document.".to_string(),
            Self::Running => "Processing of this document is running.".to_string(),
            Self::Failed { tasks } => format!("Processing failed in {}.", tasks.join(", ")),
            Self::Done => "No text was found in this document.".to_string(),
            Self::Stopped { operation_state } => format!(
                "Processing of this document stopped when the operation ended with {operation_state}."),
            Self::QueryFailed => "The document processing state could not load.".to_string(),
        }
    }
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

/// The hit count of each source for the source selector. A source without an entry has
/// no count yet. A failed or timed-out count keeps its state and never reads as zero.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize, PartialOrd, Default)]
pub struct ItemHitCounts(pub Vec<(DocumentSourceItem, crate::document_text_pages::HitCountState)>);

#[cfg(test)]
mod archive_kind_tests {
    use super::*;

    #[test]
    fn mail_stores_messages_and_archives_are_told_apart() {
        let pst = ["application/octet-stream", "application/vnd.ms-outlook", "application/x-hoover-pst"];
        assert_eq!(archive_kind(&pst, "application/x-hoover-pst", "archive"), Some(EMAIL_ARCHIVE));
        assert_eq!(archive_kind(&["application/mbox", "message/rfc822"], "message/rfc822", "archive"), Some(EMAIL_ARCHIVE));
        let msg = ["application/octet-stream", "application/vnd.ms-outlook", "application/x-ms-msg"];
        assert_eq!(archive_kind(&msg, "application/vnd.ms-outlook", "archive"), None, "an MSG is one message");
        assert_eq!(archive_kind(&["application/ms-tnef"], "application/ms-tnef", "archive"), None);
        assert_eq!(archive_kind(&[], "message/rfc822", "email"), None, "an EML with attachments stays an email");
        assert_eq!(archive_kind(&["video"], "image/heic", "image"), None);
        assert_eq!(archive_kind(&["video"], "video/matroska", "archive"), None);
        assert_eq!(archive_kind(&["application/octet-stream", "application/zip"], "application/octet-stream", "other"),
                   Some(ARCHIVE), "a ZIP typed other");
        assert_eq!(archive_kind(&[], "application/zip", "archive"), Some(ARCHIVE), "an empty ZIP has no archives row");
        assert_eq!(archive_kind(&[], "application/vnd.rar", "other"), Some(ARCHIVE));
        assert_eq!(archive_kind(&[], "application/pdf", "pdf"), None);
    }

    #[test]
    fn the_archive_tab_sorts_first_and_old_links_decode() {
        let archive = DocumentSourceItem::Archive(DocumentArchiveSourceItem { kind: ARCHIVE.into(), ..Default::default() });
        let text = DocumentSourceItem::Text(DocumentTextSourceItem {
            extracted_by: "extractous".into(), min_page: 1, max_page: 1 });
        let mut list = vec![text.clone(), archive.clone()];
        list.sort();
        assert_eq!(list[0], archive);
        let old: DocumentSourceItem = serde_json::from_str(&serde_json::to_string(&text).unwrap()).unwrap();
        assert_eq!(old, text);
        let counted = DocumentSourceItem::Archive(DocumentArchiveSourceItem {
            kind: ARCHIVE.into(), extracted_file_count: Some(3), ..Default::default() });
        assert!(counted.route_identity().same_source(&archive));
    }
}
