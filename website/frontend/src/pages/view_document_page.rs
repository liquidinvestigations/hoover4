//! Document view page layout.

use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::{
    components::document_view_components::doc_viewer_full_page::DocViewerRoot,
    data_definitions::{
        doc_viewer_state::{DocViewerState, ViewerRightTabState},
        url_param::UrlParam,
    },
};

/// View document page
#[component]
pub fn ViewDocumentPage(
    document_identifier: UrlParam<DocumentIdentifier>,
    doc_viewer_state: UrlParam<Option<DocViewerState>>,
    viewer_right_tab_state: UrlParam<ViewerRightTabState>,
) -> Element {
    let document_identifier = document_identifier.0.clone();
    rsx! {
        Title { "Hoover Search - View Document" }
        DocViewerRoot { document_identifier, doc_viewer_state: doc_viewer_state.0.clone(), viewer_right_tab_state: viewer_right_tab_state.0.clone() }

    }
}
