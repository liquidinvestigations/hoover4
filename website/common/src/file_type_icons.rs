//! The one place a canonical file type becomes a symbol and a label.
//!
//! `file_type_canonical.file_type` is simultaneously a storage key, a search facet value
//! and the thing five different components draw a glyph for — the search result card, the
//! storage browser, the viewer's title bar, an email's attachment cards and the preview
//! source selector. Before this module three of those drew a generic page icon for
//! everything and the fourth had its own four-arm match, so a spreadsheet and an email
//! looked identical in a result list while the viewer knew perfectly well which was
//! which. The same argument `document_sources.rs` gives for centralising `extracted_by`
//! formatting applies here and more strongly: five call sites means five chances to
//! disagree about what a document is.
//!
//! `common` deliberately does not depend on `dioxus-free-icons` — it is compiled into the
//! backend too. So this module names a [`FileTypeGlyph`], and the frontend's
//! `components::file_type_icon` maps that one enum to one icon. Adding a type here
//! without giving it a glyph there is a non-exhaustive-match compile error, which is the
//! point.

use serde::{Deserialize, Serialize};

/// The canonical types the indexer can write, most specific first. Mirrors
/// `SPECIFICITY` in `tasks/P6_index_data/canonical_file_type.py`.
pub const CANONICAL_FILE_TYPES: [&str; 13] = [
    "email", "pdf", "table", "doc", "xls", "ppt", "image", "video", "audio", "archive",
    "html", "text", "other",
];

/// The symbol a canonical file type is drawn as.
///
/// Coarser than the type list: `doc`, `text` and `html` all read as "a document with
/// text in it" at 20 px, and a distinct glyph per canonical type would be a lot of bytes
/// on the wire to say something the label beside it already says.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum FileTypeGlyph {
    Email,
    Pdf,
    /// A parsed spreadsheet or delimited file — one this build can open in the grid.
    Table,
    /// A spreadsheet the pipeline did NOT parse into cells. Deliberately a different
    /// glyph from [`FileTypeGlyph::Table`]: the two look the same to a reader otherwise,
    /// and only one of them opens on a grid.
    Spreadsheet,
    Slides,
    Image,
    Video,
    Audio,
    Archive,
    /// Text, HTML, word-processor documents and anything unrecognised.
    Document,
}

/// The glyph for a canonical file type. An unknown or empty type is a document — a type
/// this build has not heard of is still a file, and a missing `file_type_canonical` row
/// (a document indexed before the type resolver ran) is the ordinary case, not an error.
pub fn file_type_glyph(file_type: &str) -> FileTypeGlyph {
    match file_type {
        "email" => FileTypeGlyph::Email,
        "pdf" => FileTypeGlyph::Pdf,
        "table" => FileTypeGlyph::Table,
        "xls" => FileTypeGlyph::Spreadsheet,
        "ppt" => FileTypeGlyph::Slides,
        "image" => FileTypeGlyph::Image,
        "video" => FileTypeGlyph::Video,
        "audio" => FileTypeGlyph::Audio,
        "archive" => FileTypeGlyph::Archive,
        _ => FileTypeGlyph::Document,
    }
}

/// The `title` a reader gets when they hover the glyph.
pub fn file_type_label(file_type: &str) -> &'static str {
    match file_type {
        "email" => "Email",
        "pdf" => "PDF",
        "table" => "Spreadsheet (browsable)",
        "doc" => "Document",
        "xls" => "Spreadsheet",
        "ppt" => "Presentation",
        "image" => "Image",
        "video" => "Video",
        "audio" => "Audio",
        "archive" => "Archive",
        "html" => "Web page",
        "text" => "Text",
        "" => "File",
        _ => "File",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_canonical_type_has_a_glyph_and_a_label() {
        for file_type in CANONICAL_FILE_TYPES {
            // No panics, no empty labels: the point of the table is that no type falls
            // through to a blank square.
            let _ = file_type_glyph(file_type);
            assert!(!file_type_label(file_type).is_empty(), "{file_type}");
        }
    }

    /// The whole reason this module exists: a parsed table must not look like every
    /// other file in a result list.
    #[test]
    fn a_parsed_table_is_not_a_generic_document() {
        assert_eq!(file_type_glyph("table"), FileTypeGlyph::Table);
        assert_ne!(file_type_glyph("table"), file_type_glyph("doc"));
        // …nor like a spreadsheet nobody parsed.
        assert_ne!(file_type_glyph("table"), file_type_glyph("xls"));
    }

    #[test]
    fn an_unknown_or_missing_type_is_a_document_not_a_panic() {
        assert_eq!(file_type_glyph(""), FileTypeGlyph::Document);
        assert_eq!(file_type_glyph("something-the-indexer-learned-later"), FileTypeGlyph::Document);
        assert_eq!(file_type_label(""), "File");
    }
}
