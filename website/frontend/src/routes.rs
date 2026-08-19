//! Frontend route definitions.

use common::search_result::DocumentIdentifier;
use common::vfs::PathDescriptor;
use dioxus::prelude::*;

use crate::components::navbar::Navbar;
use crate::data_definitions::doc_viewer_state::{DocViewerState, ViewerRightTabState};
use common::search_query::SearchQuery;

use crate::data_definitions::url_param::UrlParam;
use crate::pages::admin::{
    ai_status::AdminAiStatusPage, collection_detail::AdminCollectionPage,
    collection_processing::AdminCollectionProcessingPage, collections_list::AdminCollectionsPage,
    dashboard::AdminDashboardPage, dataset_detail::AdminDatasetPage, group_detail::AdminGroupPage,
    groups_list::AdminGroupsPage, llm_config::AdminLlmPage, metrics::AdminMetricsPage,
    settings::AdminSettingsPage, user_detail::AdminUserPage, user_llm::AdminUserLlmPage,
    users_list::AdminUsersPage,
};
use crate::pages::ai_chat::{AiChatHistoryPage, AiChatPage, AiChatSessionPage};
use crate::pages::email_graph_page::EmailGraphPage;
use crate::pages::file_browser_page::{
    FileBrowserCollectionPage, FileBrowserCollectionsPage, FileBrowserPage,
};
use crate::pages::home_page::HomePage;
use crate::pages::not_found_page::NotFoundPage;
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

    // A collection landing page. Three segments against FileBrowserPage's five, so the
    // two cannot shadow each other whatever a collection is called.
    #[route("/file_browser/c/:collectionname")]
    FileBrowserCollectionPage { collectionname: String },

    #[route("/file_browser/:collection/:path/:selected_result_hash/:doc_viewer_state")]
    FileBrowserPage {
        collection: String,
        path: UrlParam<PathDescriptor>,
        selected_result_hash: UrlParam<Option<DocumentIdentifier>>,
        doc_viewer_state: UrlParam<Option<DocViewerState>>,
    },

    // `centre` is the message the graph was opened on and never changes while you
    // browse; `selected` is what the right-hand pane shows. That split is what makes the
    // back button mean "the node I was on before" instead of "a different graph".
    #[route("/email_graph/:centre/:selected/:doc_viewer_state")]
    EmailGraphPage {
        centre: UrlParam<DocumentIdentifier>,
        selected: UrlParam<Option<DocumentIdentifier>>,
        doc_viewer_state: UrlParam<Option<DocViewerState>>,
    },

    // /ai_chat/history must be declared before any /ai_chat/:param catch-all.
    #[route("/ai_chat")]
    AiChatPage {},

    #[route("/ai_chat/history")]
    AiChatHistoryPage {},

    #[route("/ai_chat/c/:session_id/:selected_result_hash/:doc_viewer_state")]
    AiChatSessionPage {
        session_id: String,
        selected_result_hash: UrlParam<Option<DocumentIdentifier>>,
        doc_viewer_state: UrlParam<Option<DocViewerState>>,
    },

    #[route("/admin")]
    AdminDashboardPage {},

    #[route("/admin/collections")]
    AdminCollectionsPage {},

    #[route("/admin/collections/:collection_id")]
    AdminCollectionPage { collection_id: String },

    #[route("/admin/collections/:collection_id/processing")]
    AdminCollectionProcessingPage { collection_id: String },

    #[route("/admin/collections/:collection_id/datasets/:dataset_id")]
    AdminDatasetPage { collection_id: String, dataset_id: String },

    #[route("/admin/users")]
    AdminUsersPage {},

    #[route("/admin/users/:username/llm")]
    AdminUserLlmPage { username: String },

    #[route("/admin/users/:username")]
    AdminUserPage { username: String },

    #[route("/admin/user_groups")]
    AdminGroupsPage {},

    #[route("/admin/user_groups/:groupname")]
    AdminGroupPage { groupname: String },

    #[route("/admin/settings")]
    AdminSettingsPage {},

    #[route("/admin/llm")]
    AdminLlmPage {},

    #[route("/admin/ai_status")]
    AdminAiStatusPage {},

    #[route("/admin/metrics")]
    AdminMetricsPage {},

    // LAST, and it must stay last: the router tries the variants in order, so anything
    // declared after this would be unreachable. It also catches a route whose parameter
    // failed to parse, which is why a stale bookmark now lands on a page instead of in
    // the global error boundary.
    #[route("/:..segments")]
    NotFoundPage { segments: Vec<String> },
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

    /// Open a chat session, optionally with a document selected in the preview pane.
    pub fn ai_chat_session(
        session_id: String,
        selected: Option<DocumentIdentifier>,
        doc_viewer_state: Option<DocViewerState>,
    ) -> Self {
        Self::AiChatSessionPage {
            session_id,
            selected_result_hash: UrlParam::from(selected),
            doc_viewer_state: UrlParam::from(doc_viewer_state),
        }
    }
}
