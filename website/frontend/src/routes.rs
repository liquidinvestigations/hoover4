//! Frontend route definitions.

use common::search_result::DocumentIdentifier;
use common::vfs::PathDescriptor;
use dioxus::prelude::*;

use crate::components::navbar::Navbar;
use crate::data_definitions::doc_viewer_state::{DocViewerState, ViewerRightTabState};
use common::search_query::SearchQuery;

use crate::data_definitions::url_param::UrlParam;
use crate::pages::chatbot_page::ChatbotPage;
use crate::pages::file_browser_page::{FileBrowserCollectionsPage, FileBrowserPage};
use crate::pages::home_page::HomePage;
use crate::pages::pdfdemo_page::PdfDemoPage;
use crate::pages::search_page::SearchPage;
use crate::pages::view_document_page::ViewDocumentPage;

#[derive(Debug, Clone, Routable, PartialEq)]
#[rustfmt::skip]
pub enum Route {
    #[layout(Navbar)]


    #[route("/")]
    HomePage {},


    #[route("/search/:query/:current_search_result_page/:selected_result_hash/:doc_viewer_state")]
    SearchPage {
        query: UrlParam<SearchQuery> ,
        current_search_result_page: u64,
        selected_result_hash: UrlParam<Option<DocumentIdentifier>>,
        doc_viewer_state: UrlParam<Option<DocViewerState>>,
    },


    #[route("/view_document/:document_identifier/:doc_viewer_state/:viewer_right_tab_state")]
    ViewDocumentPage {
        document_identifier: UrlParam<DocumentIdentifier> ,
        doc_viewer_state: UrlParam<Option<DocViewerState>>,
        viewer_right_tab_state: UrlParam<ViewerRightTabState>,
    },


    #[route("/file_browser")]
    FileBrowserCollectionsPage {},

    #[route("/file_browser/:collection/:path")]
    FileBrowserPage {
        collection: String,
        path: UrlParam<PathDescriptor>,
    },

    #[route("/chatbot")]
    ChatbotPage {  },

    #[route("/pdfdemo")]
    PdfDemoPage {  },

}

impl Route {
    pub fn search_page_from_query(q: SearchQuery) -> Self {
        Self::SearchPage {
            query: UrlParam::from(q),
            current_search_result_page: 0_u64,
            selected_result_hash: UrlParam::from(None),
            doc_viewer_state: UrlParam::from(None),
        }
    }
}
