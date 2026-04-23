use common::{
    document_sources::{DocumentEmailSourceItem, DocumentTextSourceItem},
    search_result::DocumentIdentifier,
};
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::text_preview_with_search::DocumentPreviewTextWithSearch;

const EMAIL_TEXT_EXTRACTOR: &str = "email_parser";

#[component]
pub fn DocumentPreviewForEmail(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentEmailSourceItem>,
) -> Element {
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
            div { style: "font-size: 13px; color: rgba(0, 0, 0, 0.65);", "{source.read().date_sent}" }
        }
    };

    rsx! {
        DocumentPreviewTextWithSearch {
            document_identifier,
            source: DocumentTextSourceItem {
                extracted_by: EMAIL_TEXT_EXTRACTOR.to_string(),
                min_page: 0,
                max_page: 0,
            },
            preamble,
        }
    }
}
