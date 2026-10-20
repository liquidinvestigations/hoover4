//! Pages that only the browser test harness opens.
//!
//! The cargo feature `browser-fixtures` compiles this module. A default build has none of
//! these pages, and the route list has no entry for them. The page for an unknown path
//! hands a fixture path to [`fixture_page`] in a build with the feature.
//!
//! `/_browser_fixture/two-previews/{document_a}/{state_a}/{document_b}/{state_b}` mounts two
//! document previews side by side. Each segment is a route parameter in the encoding of
//! [`UrlParam`]. Each preview is an instance of the product preview component with its own
//! `DocViewerStateControl` provider. Its setter writes a signal of that preview, so a find
//! query, a page or a source that one preview selects never reaches the other preview.

use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot;
use crate::components::suspend_boundary::SuspendWrapper;
use crate::data_definitions::doc_viewer_state::{DocViewerState, DocViewerStateControl};
use crate::data_definitions::url_param::UrlParam;

/// The first path segment of every fixture page.
pub const FIXTURE_PREFIX: &str = "_browser_fixture";

/// The parameters of the two-preview page, or `None` when the segments name another path.
fn two_previews(
    segments: &[String],
) -> Option<[(DocumentIdentifier, Option<DocViewerState>); 2]> {
    let [prefix, name, document_a, state_a, document_b, state_b] = segments else {
        return None;
    };
    if prefix != FIXTURE_PREFIX || name != "two-previews" {
        return None;
    }
    let document = |text: &str| text.parse::<UrlParam<DocumentIdentifier>>().ok().map(|p| p.0);
    let state = |text: &str| text.parse::<UrlParam<Option<DocViewerState>>>().ok().map(|p| p.0);
    Some([
        (document(document_a)?, state(state_a)?),
        (document(document_b)?, state(state_b)?),
    ])
}

/// The fixture page for these segments, or `None` when they name no fixture.
pub fn fixture_page(segments: &[String]) -> Option<Element> {
    let [(document_a, state_a), (document_b, state_b)] = two_previews(segments)?;
    Some(rsx! {
        div {
            "data-browser-fixture": "two-previews",
            style: "display: flex; flex-direction: row; gap: 12px; width: 100%; height: 100%; \
                    padding: 12px; box-sizing: border-box; background: #F5F6F8;",
            FixturePreview { slot: "a", document: document_a, initial_state: state_a }
            FixturePreview { slot: "b", document: document_b, initial_state: state_b }
        }
    })
}

/// One preview with its own viewer state. The state starts from the route parameter and
/// then changes only through this preview's own controls.
#[component]
fn FixturePreview(
    slot: String,
    document: DocumentIdentifier,
    initial_state: Option<DocViewerState>,
) -> Element {
    let mut viewer_state = use_signal(move || initial_state.clone());
    use_context_provider(move || DocViewerStateControl {
        doc_viewer_state: viewer_state.into(),
        set_doc_viewer_state: Callback::new(move |state: DocViewerState| {
            viewer_state.set(Some(state));
        }),
    });
    let selected = use_signal(move || Some(document.clone()));
    let query = use_signal(SearchQuery::default);
    rsx! {
        div {
            "data-browser-fixture-preview": "{slot}",
            style: "flex: 1 1 0; min-width: 0; height: 100%; background: #FFFFFF; \
                    border: 1px solid #E5E7EB; border-radius: 8px; overflow: hidden;",
            SuspendWrapper {
                DocumentPreviewForSearchRoot {
                    query,
                    selected_result_hash: selected,
                    show_finder: true,
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn encoded<T: serde::Serialize>(value: T) -> String {
        UrlParam(value).to_string()
    }

    fn identifier(hash: &str) -> DocumentIdentifier {
        DocumentIdentifier { collection_dataset: "d".into(), file_hash: hash.into() }
    }

    #[test]
    fn the_two_preview_path_gives_each_preview_its_own_document_and_state() {
        let state = DocViewerState::from_find_query("quokka".into());
        let segments = vec![
            FIXTURE_PREFIX.to_string(), "two-previews".into(),
            encoded(identifier("a")), encoded(Some(state.clone())),
            encoded(identifier("b")), encoded(None::<DocViewerState>),
        ];
        let [(a, state_a), (b, state_b)] = two_previews(&segments).expect("a fixture path");
        assert_eq!((a.file_hash.as_str(), b.file_hash.as_str()), ("a", "b"));
        assert_eq!(state_a, Some(state));
        assert_eq!(state_b, None);
    }

    #[test]
    fn another_path_or_a_bad_parameter_names_no_fixture() {
        let id = encoded(identifier("a"));
        let none = encoded(None::<DocViewerState>);
        for segments in [
            vec!["search".to_string()],
            vec![FIXTURE_PREFIX.into(), "two-previews".into(), id.clone(), none.clone(), id.clone()],
            vec![FIXTURE_PREFIX.into(), "other".into(), id.clone(), none.clone(), id.clone(), none.clone()],
            vec![FIXTURE_PREFIX.into(), "two-previews".into(), "%%".into(), none.clone(), id, none],
        ] {
            assert!(two_previews(&segments).is_none(), "{segments:?}");
        }
    }
}
