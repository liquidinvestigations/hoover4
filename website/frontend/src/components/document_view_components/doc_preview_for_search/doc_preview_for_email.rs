use common::{
    document_sources::{DocumentEmailSourceItem, DocumentTextSourceItem, EMAIL_TEXT_EXTRACTOR},
    search_result::DocumentIdentifier,
};
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::text_preview_with_search::DocumentPreviewTextWithSearch;

#[component]
pub fn DocumentPreviewForEmail(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentEmailSourceItem>,
) -> Element {
    let sent_date = source.read().sent_date().map(str::to_string);
    let preamble = rsx! {
        div {
            style: "
                padding: 12px;
                border: 1px solid rgba(0, 0, 0, 0.15);
                border-radius: 12px;
                background: rgba(0, 0, 0, 0.02);
                margin-bottom: 12px;
            ",
            div { style: "font-size: 18px; font-weight: 600; margin-bottom: 6px;", "{source.read().subject}" }
            div { style: "font-size: 14px; color: rgba(0, 0, 0, 0.75); margin-bottom: 6px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;", "{source.read().addresses}" }
            match sent_date.as_deref() {
                Some(date) => rsx! {
                    div { style: "font-size: 13px; color: rgba(0, 0, 0, 0.65);", "{date}" }
                },
                // Said rather than left blank: an absent line reads as a rendering gap,
                // and this agrees with the Metadata tab on the same screen.
                None => rsx! {
                    div { style: "font-size: 13px; color: rgba(0, 0, 0, 0.45); font-style: italic;", "No date sent" }
                },
            }
        }
    };

    // `text_content.page_id` is 1-based, so page 0 matches no row and the body request
    // 404s. The range comes from the email source's own `email_parser` rows; the floor is
    // here as well because viewer state restored from an older URL carries no range.
    let min_page = source.read().min_page.max(1);
    let max_page = source.read().max_page.max(min_page);

    rsx! {
        DocumentPreviewTextWithSearch {
            document_identifier,
            source: DocumentTextSourceItem {
                extracted_by: EMAIL_TEXT_EXTRACTOR.to_string(),
                min_page,
                max_page,
            },
            preamble,
        }
    }
}
