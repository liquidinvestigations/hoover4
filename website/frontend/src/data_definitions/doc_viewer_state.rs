//! State definitions for the document viewer.

use common::document_sources::DocumentSourceItem;
use dioxus::prelude::*;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocViewerState {
    pub find_query: String,
    pub selected_source: Option<DocumentSourceItem>,
    pub selected_source_page: Option<u32>,
}

impl DocViewerState {
    pub fn from_find_query(find_query: String) -> Self {
        Self {
            find_query,
            selected_source: None,
            selected_source_page: None,
        }
    }
}

impl Default for DocViewerState {
    fn default() -> Self {
        Self {
            find_query: "".to_string(),
            selected_source: None,
            selected_source_page: None,
        }
    }
}

/// Shared control so search, file-browser, and AI-chat pages can drive the document
/// preview pane through URL state. Each page provides a setter that pushes its own route.
#[derive(Debug, Clone, PartialEq, Copy)]
pub struct DocViewerStateControl {
    pub doc_viewer_state: ReadSignal<Option<DocViewerState>>,
    pub set_doc_viewer_state: Callback<DocViewerState>,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub enum ViewerRightTabSelection {
    Entities,
    /// Declaration order is the rendered order of the tab strip, so `FileLocations` sits
    /// here — between `Entities` and `Metadata` — and nowhere else.
    FileLocations,
    Metadata,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ViewerRightTabState {
    pub selected_tab: ViewerRightTabSelection,
}

impl Default for ViewerRightTabState {
    fn default() -> Self {
        Self {
            selected_tab: ViewerRightTabSelection::Entities,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data_definitions::url_param::UrlParam;
    use std::str::FromStr;

    fn round_trip(tab: ViewerRightTabSelection) -> ViewerRightTabSelection {
        let encoded = UrlParam(ViewerRightTabState { selected_tab: tab }).to_string();
        UrlParam::<ViewerRightTabState>::from_str(&encoded)
            .expect("a URL this build wrote must parse")
            .0
            .selected_tab
    }

    #[test]
    fn every_tab_survives_the_url() {
        for tab in [
            ViewerRightTabSelection::Entities,
            ViewerRightTabSelection::FileLocations,
            ViewerRightTabSelection::Metadata,
        ] {
            assert_eq!(round_trip(tab), tab);
        }
    }

    #[test]
    fn a_url_written_before_the_file_locations_tab_existed_still_parses() {
        // The two variants that predate `FileLocations`, encoded by the same Display
        // impl: CBOR carries the variant NAME, not its index, so wedging a variant into
        // the middle of the enum cannot shift what an old link means. This is the
        // assertion that keeps that true — a bookmarked viewer URL is a real thing.
        let entities = "oWxzZWxlY3RlZF90YWJoRW50aXRpZXM=";
        let metadata = "oWxzZWxlY3RlZF90YWJoTWV0YWRhdGE=";
        for (encoded, expected) in [
            (entities, ViewerRightTabSelection::Entities),
            (metadata, ViewerRightTabSelection::Metadata),
        ] {
            let parsed = UrlParam::<ViewerRightTabState>::from_str(encoded)
                .expect("an old URL must still parse");
            assert_eq!(parsed.0.selected_tab, expected);
        }
    }
}
