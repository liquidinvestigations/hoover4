//! Frontend route definitions.

use common::search_result::DocumentIdentifier;
use common::vfs::PathDescriptor;
use dioxus::prelude::*;

use crate::components::navbar::Navbar;
use crate::data_definitions::doc_viewer_state::{DocViewerState, ViewerRightTabState};
use common::search_query::SearchQuery;

use crate::data_definitions::url_param::UrlParam;
use crate::pages::admin::{
    collection_detail::AdminCollectionPage, collections_list::AdminCollectionsPage,
    dashboard::AdminDashboardPage, dataset_detail::AdminDatasetPage,
    group_detail::AdminGroupPage, groups_list::AdminGroupsPage, settings::AdminSettingsPage,
    user_detail::AdminUserPage, users_list::AdminUsersPage,
};
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

    #[route("/file_browser/:collection/:path/:selected_result_hash/:doc_viewer_state")]
    FileBrowserPage {
        collection: String,
        path: UrlParam<PathDescriptor>,
        selected_result_hash: UrlParam<Option<DocumentIdentifier>>,
        doc_viewer_state: UrlParam<Option<DocViewerState>>,
    },

    #[route("/chatbot")]
    ChatbotPage {  },

    #[route("/pdfdemo")]
    PdfDemoPage {  },

    #[route("/admin")]
    AdminDashboardPage {},

    #[route("/admin/collections")]
    AdminCollectionsPage {},

    #[route("/admin/collections/:collection_id")]
    AdminCollectionPage { collection_id: String },

    #[route("/admin/collections/:collection_id/datasets/:dataset_id")]
    AdminDatasetPage { collection_id: String, dataset_id: String },

    #[route("/admin/users")]
    AdminUsersPage {},

    #[route("/admin/users/:username")]
    AdminUserPage { username: String },

    #[route("/admin/user_groups")]
    AdminGroupsPage {},

    #[route("/admin/user_groups/:groupname")]
    AdminGroupPage { groupname: String },

    #[route("/admin/settings")]
    AdminSettingsPage {},

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

    /// Construct a [`Route::FileBrowserPage`] for navigating to a folder,
    /// with no document selected and the default viewer state.
    pub fn file_browser_page(
        collection: String,
        path: PathDescriptor,
        selected: Option<DocumentIdentifier>,
    ) -> Self {
        Self::FileBrowserPage {
            collection,
            path: UrlParam::from(path),
            selected_result_hash: UrlParam::from(selected),
            doc_viewer_state: UrlParam::from(None),
        }
    }
}
