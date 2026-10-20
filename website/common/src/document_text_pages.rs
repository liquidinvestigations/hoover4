//! Stored text pages of one document text source, and the match steps between them.
//!
//! These types travel beside [`crate::document_sources::DocumentTextSourceItem`] and never
//! inside it: that item takes part in source selection, equality and the encoded viewer
//! URL, and a count or a neighbour identifier changes when a document is processed again.

use serde::{Deserialize, Serialize};

use crate::document_sources::TextSource;
use crate::text_highlight::HighlightTextSpan;

/// What the `page_id` of a text source counts.
///
/// The writers decide it. `insert_text_pages` stores document page numbers and
/// `insert_text_chunks` stores ordinals of size-based segments. An extractor that this
/// build does not know keeps [`TextSourceUnit::StoredEntry`], so the viewer never claims
/// that its numbers are PDF pages.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TextSourceUnit {
    /// `page_id` is the document page number. Native PDF text and PDF OCR text.
    DocumentPage,
    /// `page_id` is the 1-based ordinal of a segment of about 256 KiB. A segment can cross
    /// document page boundaries.
    TextSegment,
    /// The numbering of this source is not established.
    StoredEntry,
}

impl TextSourceUnit {
    /// The unit of one `extracted_by` value. Mirrors the writer each extractor calls in
    /// `main_services/processing/tasks/P3_parse_files`.
    pub fn of(extracted_by: &str) -> Self {
        if extracted_by == "pdftotext" {
            return Self::DocumentPage;
        }
        match TextSource::parse(extracted_by) {
            TextSource::PdfOcr { .. } => Self::DocumentPage,
            // Image OCR stores one image as segments of its recognised text.
            TextSource::Ocr { .. } => Self::TextSegment,
            TextSource::Native { extractor } => match extractor.as_str() {
                "extractous" | "binary_word" | "office_xml" | "raw_text" | "table_text" | "email_parser"
                | "email_html" | "email_rtf" | "email_richtext" => Self::TextSegment,
                _ => Self::StoredEntry,
            },
        }
    }

    /// The unit name in the page control, for example `Page 7`.
    pub fn label(self) -> &'static str {
        match self {
            Self::DocumentPage => "Page",
            Self::TextSegment => "Text segment",
            Self::StoredEntry => "Entry",
        }
    }

    /// The accessible description of the unit. A segment number is not a page number.
    pub fn description(self) -> &'static str {
        match self {
            Self::DocumentPage => "The number is the document page number.",
            Self::TextSegment => "A text segment holds about 256 KB of text and can cross document page boundaries.",
            Self::StoredEntry => "The number is the stored entry number of this source. It is not a document page number.",
        }
    }
}

/// Where one stored text page is among the stored pages of its source.
///
/// Page identifiers can have gaps and can start above 1, so `stored_count` and
/// `position` count stored entries and never derive from the highest identifier.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextPageNavigation {
    pub extracted_by: String,
    pub unit: TextSourceUnit,
    /// The identifier that the request named, or `None` for the initial selection.
    pub requested_page: Option<u32>,
    /// The stored page that the response describes. `None` when the requested identifier
    /// has no stored text, or the source has no stored text at all.
    pub page: Option<u32>,
    /// Distinct stored page identifiers of the source.
    pub stored_count: u64,
    /// The 1-based position of `page` among the stored identifiers.
    pub position: Option<u64>,
    pub first_page: Option<u32>,
    pub last_page: Option<u32>,
    /// The greatest stored identifier below the selection.
    pub previous_page: Option<u32>,
    /// The least stored identifier above the selection.
    pub next_page: Option<u32>,
    /// Count, range and highest writer version of the source. It changes when the source
    /// is written again. It is not a transactional snapshot of the index.
    pub revision: String,
}

/// The text of one stored page, or why there is none.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum TextPageBody {
    /// The latest stored version of the page. `spans` hold the find-query highlights when
    /// the query matched this page and the matching index row holds this stored text, and
    /// one plain span of the stored text otherwise. The spans never show index text that
    /// differs from the stored text.
    Text {
        page_id: u32,
        version: u64,
        spans: Vec<HighlightTextSpan>,
        /// The highlight read failed, or the index holds another version of the page.
        /// `spans` then hold the raw stored text.
        highlight_error: Option<String>,
    },
    /// The requested identifier has no stored text. Navigation names its neighbours.
    Absent,
    /// The source has no stored text.
    EmptySource,
}

impl TextPageBody {
    /// The number of find-query matches that the spans show.
    pub fn match_count(&self) -> u32 {
        match self {
            Self::Text { spans, .. } => spans.iter().filter(|span| span.is_highlighted).count() as u32,
            _ => 0,
        }
    }
}

/// One text page as the viewer shows it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct TextPageView {
    pub navigation: TextPageNavigation,
    pub body: TextPageBody,
    /// The search for an initial matching page failed. The view then shows the first
    /// stored page.
    #[serde(default)]
    pub match_error: Option<String>,
    /// The caller named a revision and the source no longer has it.
    #[serde(default)]
    pub source_changed: bool,
    /// The search for the first matching page when the request named no page and had a
    /// query. [`TextMatchStep::Incomplete`] means the first match is still unknown, and
    /// the view shows the first stored page. `None` without that search, after its
    /// failure (`match_error`), and in a response written before this field.
    #[serde(default)]
    pub initial_match: Option<TextMatchStep>,
}

/// The direction of a match step.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum MatchDirection {
    Forward,
    Backward,
}

/// The result of one source-scoped step to the next or previous matching page.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum TextMatchStep {
    /// The nearest stored page in the direction that matches the query.
    Found { page_id: u32 },
    /// No stored page beyond the start matches the query in this direction.
    NoMore,
    /// The step read its whole allowance of index rows without proving either result.
    /// A next step resumes from `resume_after`.
    Incomplete { resume_after: u32 },
}

/// A source hit count in the source selector.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Serialize, Deserialize)]
pub enum HitCountState {
    /// The count finished over index rows that each hold the stored text of their page.
    /// Zero is a successful empty result.
    Exact(u64),
    /// The count stopped at a read limit. The rows read hold the stored text of their
    /// pages, so the stored text holds at least this many.
    AtLeast(u64),
    /// The count did not finish in its time limit.
    TimedOut,
    /// The count failed.
    Failed,
    /// The index holds another version of a counted page, so no count of the stored text
    /// is known.
    Unavailable,
}

impl HitCountState {
    /// The text beside the source name. An exact zero shows nothing.
    pub fn display(self) -> String {
        match self {
            Self::Exact(0) => String::new(),
            Self::Exact(hits) => hits.to_string(),
            Self::AtLeast(hits) => format!("{hits}+"),
            Self::TimedOut | Self::Failed => "!".to_string(),
            Self::Unavailable => "?".to_string(),
        }
    }

    /// The accessible and hover description of the count.
    pub fn description(self) -> String {
        match self {
            Self::Exact(hits) => format!("{hits} matches"),
            Self::AtLeast(hits) => format!("At least {hits} matches. The count stopped at its read limit."),
            Self::TimedOut => "The match count did not finish in time.".to_string(),
            Self::Failed => "The match count failed.".to_string(),
            Self::Unavailable => "No match count. The search index holds another version of this text.".to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn page_numbers_come_only_from_paged_writers() {
        assert_eq!(TextSourceUnit::of("pdftotext"), TextSourceUnit::DocumentPage);
        assert_eq!(TextSourceUnit::of("pdfocr_tesseract_eng+ron"), TextSourceUnit::DocumentPage);
        for segmented in ["extractous", "raw_text", "email_parser", "binary_word", "office_xml", "table_text", "ocr_tesseract_eng"] {
            assert_eq!(TextSourceUnit::of(segmented), TextSourceUnit::TextSegment, "{segmented}");
        }
        for unknown in ["qpdf", "some_new_parser", "pdfocr_unknown_eng", "ocr_tesseract"] {
            assert_eq!(TextSourceUnit::of(unknown), TextSourceUnit::StoredEntry, "{unknown}");
        }
    }

    #[test]
    fn a_failed_count_is_not_a_zero_count() {
        assert_eq!(HitCountState::Exact(0).display(), "");
        assert_eq!(HitCountState::Exact(4).display(), "4");
        assert_eq!(HitCountState::AtLeast(900).display(), "900+");
        assert_eq!(HitCountState::Failed.display(), "!");
        assert_eq!(HitCountState::Unavailable.display(), "?");
        assert_ne!(HitCountState::Failed.description(), HitCountState::Exact(0).description());
    }

    #[test]
    fn the_match_count_reads_the_highlighted_spans() {
        let span = |text: &str, is_highlighted| HighlightTextSpan { text: text.into(), is_highlighted, index: 0 };
        let body = TextPageBody::Text {
            page_id: 3,
            version: 1,
            spans: vec![span("a ", false), span("x", true), span(" b ", false), span("x", true)],
            highlight_error: None,
        };
        assert_eq!(body.match_count(), 2);
        assert_eq!(TextPageBody::Absent.match_count(), 0);
    }
}
