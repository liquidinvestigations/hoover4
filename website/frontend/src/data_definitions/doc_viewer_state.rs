//! State definitions for the document viewer.

use common::document_sources::DocumentSourceItem;
use common::document_tables::{TableColumnFilter, TableSort};
use dioxus::prelude::*;
use serde::{Deserialize, Serialize};

/// How the table explorer is currently looking at a workbook.
///
/// This lives in the viewer state — and therefore in the URL — rather than in the
/// `DocumentSourceItem::Table` variant, for a reason that is not stylistic: the variant
/// is the key of `ItemHitCounts` and the value the source selector compares against the
/// selected source, so a variant that changed when the reader clicked a column header
/// would stop equalling itself and deselect the grid on every interaction. It is in the
/// URL because a table view someone found is worth sending to a colleague, which is how
/// every other piece of viewer state in this app already works.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct DocTableState {
    /// The workbook's own sheet ordinal, not an index. `None` means "the first sheet the
    /// manifest lists", which is what a URL written before a sheet was picked describes.
    #[serde(default)]
    pub sheet_id: Option<u16>,
    /// Columns the reader hid. Hidden rather than visible, so a re-ingest that ADDS a
    /// column shows it instead of silently dropping it out of a shared link.
    #[serde(default)]
    pub hidden_columns: Vec<u32>,
    #[serde(default)]
    pub sort: Option<TableSort>,
    #[serde(default)]
    pub filters: Vec<TableColumnFilter>,
    /// 0-based page index.
    #[serde(default)]
    pub page: u64,
}

impl DocTableState {
    /// Changing what is shown resets the pager: page 40 of an unfiltered sheet is very
    /// rarely page 40 of the filtered one, and landing past the end reads as no results.
    pub fn reset_page(mut self) -> Self {
        self.page = 0;
        self
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocViewerState {
    pub find_query: String,
    pub selected_source: Option<DocumentSourceItem>,
    pub selected_source_page: Option<u32>,
    /// Absent means "the default view", which is what a URL written before the table
    /// browser existed describes — the same reasoning as
    /// `DocumentEmailSourceItem::has_body`.
    #[serde(default)]
    pub table_state: Option<DocTableState>,
    /// The one entity whose explainer card the entities panel opens on arrival.
    ///
    /// The normalised value, compared exactly against what the panel lists. It is in the
    /// URL because an entity card someone found is worth sending, which is how every
    /// other piece of viewer state here already works. A link written before the field
    /// existed takes `None` and opens the panel the way it always did.
    #[serde(default)]
    pub selected_entity: Option<String>,
}

impl DocViewerState {
    pub fn from_find_query(find_query: String) -> Self {
        Self {
            find_query,
            selected_source: None,
            selected_source_page: None,
            table_state: None,
            selected_entity: None,
        }
    }

    /// The viewer state that opens one entity's card, with nothing else selected.
    pub fn for_entity(value: String) -> Self {
        Self {
            selected_entity: Some(value),
            ..Self::default()
        }
    }

    /// The table view this URL describes, defaulted for a URL that describes none.
    pub fn table_state(&self) -> DocTableState {
        self.table_state.clone().unwrap_or_default()
    }
}

impl Default for DocViewerState {
    fn default() -> Self {
        Self {
            find_query: "".to_string(),
            selected_source: None,
            selected_source_page: None,
            table_state: None,
            selected_entity: None,
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

    /// A viewer URL written before `DocumentSourceItem::Table` existed. CBOR carries the
    /// variant NAME, not its index, so wedging `Table` into the middle of the enum cannot
    /// change what an old bookmark means — and `table_state` is `#[serde(default)]`, so a
    /// state that never had the field is "the default view" rather than a parse failure
    /// the router shows as "Page not found".
    #[test]
    fn a_viewer_url_written_before_the_table_source_existed_still_parses() {
        // `{"find_query":"acme","selected_source":{"Text":{"extracted_by":"extractous",
        //   "min_page":1,"max_page":1}},"selected_source_page":null}` in the three-field
        // shape, encoded by this build's own Display impl.
        let legacy = UrlParam(LegacyDocViewerState {
            find_query: "acme".to_string(),
            selected_source: None,
            selected_source_page: None,
        })
        .to_string();
        let parsed = UrlParam::<DocViewerState>::from_str(&legacy)
            .expect("a viewer URL written before the table browser must still parse");
        assert_eq!(parsed.0.find_query, "acme");
        assert!(parsed.0.table_state.is_none());
        assert_eq!(parsed.0.table_state(), DocTableState::default());
    }

    /// The three-field shape this state had before the table browser.
    #[derive(Serialize)]
    struct LegacyDocViewerState {
        find_query: String,
        selected_source: Option<DocumentSourceItem>,
        selected_source_page: Option<u32>,
    }

    /// The explorer's whole view survives a copied link, which is the only reason it is
    /// in the URL at all.
    #[test]
    fn a_table_view_survives_the_url() {
        use common::document_tables::TableFilterKind;
        let state = DocViewerState {
            find_query: "acme".into(),
            selected_source: None,
            selected_source_page: None,
            table_state: Some(DocTableState {
                sheet_id: Some(2),
                hidden_columns: vec![3, 7],
                sort: Some(TableSort { column_id: 4, desc: true }),
                filters: vec![TableColumnFilter {
                    column_id: 1,
                    kind: TableFilterKind::NumberRange { min: Some(10.0), max: None },
                }],
                page: 3,
            }),
            selected_entity: None,
        };
        let encoded = UrlParam(state.clone()).to_string();
        let parsed = UrlParam::<DocViewerState>::from_str(&encoded)
            .expect("a URL this build wrote must parse")
            .0;
        assert_eq!(parsed, state);
    }

    /// The whole point of putting the open card in the address: a card reached from a
    /// conversation is a link, and the link opens the same card.
    #[test]
    fn a_selected_entity_survives_the_url() {
        let state = DocViewerState::for_entity("AD1200012030200359100100".to_string());
        let encoded = UrlParam(state.clone()).to_string();
        let parsed = UrlParam::<DocViewerState>::from_str(&encoded)
            .expect("a URL this build wrote must parse")
            .0;
        assert_eq!(parsed, state);
        assert_eq!(parsed.selected_entity.as_deref(), Some("AD1200012030200359100100"));
    }

    #[test]
    fn changing_what_is_shown_sends_the_reader_back_to_the_first_page() {
        let state = DocTableState { page: 40, ..Default::default() };
        assert_eq!(state.reset_page().page, 0);
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
