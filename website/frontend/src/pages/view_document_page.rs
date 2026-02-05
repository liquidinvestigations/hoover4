use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::{components::document_view_components::doc_viewer_full_page::DocViewerRoot, data_definitions::url_param::UrlParam};


/// View document page
#[component]
pub fn ViewDocumentPage(document_identifier: UrlParam<DocumentIdentifier>) -> Element {
    let document_identifier = document_identifier.0.clone();
    rsx! {
        Title { "Hoover Search - View Document" }
        DocViewerRoot { document_identifier }

    }
}