//! Full-page document viewer components.

use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::{doc_title_bar::DocTitleBar, raw_metadata_collector::RawMetadataCollector};


#[component]
pub fn DocViewerRoot(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: column;
                height: 100%;
                width: 100%;
                overflow: hidden;
            ",
            DocTitleBar { document_identifier }
            div {
                style: "width: 100%; height: calc(100% - 54px); flex-grow: 0; flex-shrink: 0;",
                RawMetadataCollector {  document_identifier }
            }
        }
    }
}