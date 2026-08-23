//! The one place a canonical file type becomes a drawn glyph.
//!
//! The mapping itself lives in `common::file_type_icons`, which the backend also
//! compiles and which therefore cannot depend on `dioxus-free-icons`. This module is the
//! other half: one `match` from [`FileTypeGlyph`] to an icon, exhaustive, so a type added
//! to the shared table without a symbol here is a compile error rather than a blank
//! square in a result list.
//!
//! Five call sites draw this: the search result card, the storage browser's file rows,
//! the viewer's title bar, an email's attachment cards and the preview source selector.

use common::file_type_icons::{FileTypeGlyph, file_type_glyph, file_type_label};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        md_action_icons::MdDescription,
        md_communication_icons::MdEmail,
        md_content_icons::MdArchive,
        md_editor_icons::{MdInsertDriveFile, MdTableChart},
        md_image_icons::{MdAudiotrack, MdImage, MdPictureAsPdf, MdSlideshow, MdSwitchVideo},
    },
};

/// The glyph for one document's canonical file type.
///
/// `file_type` empty (a document the type resolver has not reached, or a response from a
/// build before the field existed) draws the generic file icon. That is the same thing
/// every one of these sites drew before, so an unfilled field degrades to the old
/// behaviour rather than to nothing.
#[component]
pub fn FileTypeGlyphIcon(file_type: String, size: u32) -> Element {
    let style = format!("width: {size}px; height: {size}px;");
    let title = file_type_label(&file_type);
    rsx! {
        span {
            title: "{title}",
            style: "display: inline-flex; align-items: center; justify-content: center;",
            match file_type_glyph(&file_type) {
                FileTypeGlyph::Email => rsx! { Icon { icon: MdEmail, style: "{style}" } },
                FileTypeGlyph::Pdf => rsx! { Icon { icon: MdPictureAsPdf, style: "{style}" } },
                // A parsed table gets the grid glyph and a spreadsheet nobody parsed gets
                // the plain description one: only the first opens on a grid, and drawing
                // them alike promises a browser that is not there.
                FileTypeGlyph::Table => rsx! { Icon { icon: MdTableChart, style: "{style}" } },
                FileTypeGlyph::Spreadsheet => rsx! { Icon { icon: MdDescription, style: "{style}" } },
                FileTypeGlyph::Slides => rsx! { Icon { icon: MdSlideshow, style: "{style}" } },
                FileTypeGlyph::Image => rsx! { Icon { icon: MdImage, style: "{style}" } },
                FileTypeGlyph::Video => rsx! { Icon { icon: MdSwitchVideo, style: "{style}" } },
                FileTypeGlyph::Audio => rsx! { Icon { icon: MdAudiotrack, style: "{style}" } },
                FileTypeGlyph::Archive => rsx! { Icon { icon: MdArchive, style: "{style}" } },
                FileTypeGlyph::Document => rsx! { Icon { icon: MdInsertDriveFile, style: "{style}" } },
            }
        }
    }
}
