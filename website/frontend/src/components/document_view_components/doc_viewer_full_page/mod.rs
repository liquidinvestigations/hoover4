//! Full-page document viewer components.

mod document_entities_panel;
mod raw_metadata_collector;

use common::document_sources::DocumentSourceItem;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::{
    components::document_view_components::{
        doc_preview_for_search::{
            doc_preview_find_query::DocPreviewFindQueryInputBox,
            doc_preview_source_selector::
                DocumentPreviewSourceSelectorList
            ,
        },
        doc_title_bar::DocTitleBar,
        doc_viewer_full_page::{
            document_entities_panel::DocumentEntitiesPanel,
            raw_metadata_collector::RawMetadataCollector,
        },
    },
    data_definitions::
        doc_viewer_state::{ViewerRightTabSelection, ViewerRightTabState}
    ,
    routes::Route,
};

use crate::pages::search_page::DocViewerStateControl;
use crate::{
    components::document_view_components::doc_preview_for_search::get_document_sources,
    components::document_view_components::doc_preview_shared::{
        DocSourceDispatch, ProvidePreviewExtraSections,
    },
    data_definitions::doc_viewer_state::DocViewerState,
};

#[component]
pub fn DocViewerRoot(
    document_identifier: ReadSignal<DocumentIdentifier>,
    doc_viewer_state: ReadSignal<Option<DocViewerState>>,
    viewer_right_tab_state: ReadSignal<ViewerRightTabState>,
) -> Element {
    use_context_provider(move || DocViewerStateControl {
        doc_viewer_state: doc_viewer_state.into(),
        set_doc_viewer_state: Callback::new(move |state: DocViewerState| {
            navigator().replace(Route::ViewDocumentPage {
                document_identifier: document_identifier.read().clone().into(),
                doc_viewer_state: Some(state).into(),
                viewer_right_tab_state: ViewerRightTabState::default().into(),
            });
        }),
    });

    let mut doc_sources: Resource<Vec<DocumentSourceItem>> = use_resource(move || {
        let document_identifier = document_identifier.read().clone();
        async move {
            get_document_sources(document_identifier)
                .await
                .unwrap_or_default()
        }
    });
    use_effect(move || {
        let _document_identifier = document_identifier.read().clone();
        doc_sources.clear();
        doc_sources.restart();
    });
    let doc_sources: ReadSignal<Option<Vec<DocumentSourceItem>>> =
        use_memo(move || doc_sources.read().clone()).into();

    let control = use_context::<DocViewerStateControl>();
    let currently_selected_source: ReadSignal<Option<DocumentSourceItem>> = use_memo(move || {
        let sources = doc_sources.read().clone().unwrap_or_default();
        if let Some(state) = control.doc_viewer_state.read().clone() {
            if let Some(selected_source) = state.selected_source {
                if let Some(source) = sources.iter().find(|s| *s == &selected_source) {
                    return Some(source.clone());
                }
            }
        }
        sources.first().cloned()
    })
    .into();

    let on_source_selected = Callback::new(move |source: DocumentSourceItem| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.selected_source = Some(source);
        state.selected_source_page = None;
        control.set_doc_viewer_state.call(state);
    });

    let on_find_query_changed = Callback::new(move |query: String| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.find_query = query;
        control.set_doc_viewer_state.call(state);
    });

    let on_viewer_right_tab_selected = Callback::new(move |state: ViewerRightTabState| {
        navigator().replace(Route::ViewDocumentPage {
            document_identifier: document_identifier.read().clone().into(),
            doc_viewer_state: control.doc_viewer_state.read().clone().into(),
            viewer_right_tab_state: state.into(),
        });
    });

    use_context_provider(move || ViewerPageControls {
        document_identifier,
        sources: doc_sources,
        selected_source: currently_selected_source,
        on_source_selected,
        on_find_query_changed,
        viewer_right_tab_state,
        on_viewer_right_tab_selected,
    });

    let content_view_inner = match currently_selected_source.read().clone() {
        Some(source) => rsx! { DocSourceDispatch { document_identifier, source } },
        None => rsx! { div { style: "padding: 12px;", "Loading..." } },
    };

    // Provide the same context that search-preview provides, but the triptych renders these
    // controls vertically in the left column; so we pass empty elements here to satisfy
    // `PreviewControlsSection` without duplicating UI.
    let content_view = rsx! {
        ProvidePreviewExtraSections {
            find_query_input_box: rsx! { div {} },
            preview_selector: rsx! { div {} },
            children: content_view_inner,
            wrapper_fn: _make_view_wrapper,
        }
    };

    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: row;
                height: 100%;
                width: 100%;
                overflow: hidden;
            ",
            {content_view}
            div {
                style: "
                    width: calc(max(35%, 575px));
                    flex: 0 0 auto;
                    height: 100%;
                    overflow: hidden;
                    background: white;
                ",
                RightPanel { document_identifier }
            }
        }
    }
}

#[component]
fn RightTabButton(
    right_tab: ReadSignal<ViewerRightTabState>,
    tab: ViewerRightTabSelection,
    label: &'static str,
    on_viewer_right_tab_selected: Callback<ViewerRightTabState>,
) -> Element {
    let is_active = right_tab().selected_tab == tab;
    let border = if is_active {
        "2px solid rgba(0,0,0,0.9)"
    } else {
        "1px solid rgba(0,0,0,0.25)"
    };
    let bg = if is_active {
        "white"
    } else {
        "rgba(0,0,0,0.03)"
    };

    rsx! {
        button {
            style: "
                cursor: pointer;
                padding: 8px 12px;
                border-radius: 10px;
                border: {border};
                background: {bg};
                font-size: 14px;
                font-weight: 600;
            ",
            onclick: move |_e| {
                _e.prevent_default();
                on_viewer_right_tab_selected.call(ViewerRightTabState { selected_tab: tab });
            },
            "{label}"
        }
    }
}

#[component]
fn RightPanel(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let page_controls = use_context::<ViewerPageControls>();
    let right_tab = page_controls.viewer_right_tab_state;
    let on_viewer_right_tab_selected = page_controls.on_viewer_right_tab_selected.clone();

    rsx! {
        div {
            style: "
                height: 100%;
                width: 100%;
                overflow: hidden;
                border-left: 1px solid rgba(0,0,0,0.2);
                display: flex;
                flex-direction: column;
            ",
            div {
                style: "
                    flex-shrink: 0;
                    display: flex;
                    flex-direction: row;
                    gap: 10px;
                    align-items: center;
                    padding: 10px;
                    border-bottom: 1px solid rgba(0,0,0,0.15);
                    background: rgba(0,0,0,0.02);
                ",
                RightTabButton { right_tab, on_viewer_right_tab_selected, tab: ViewerRightTabSelection::Entities, label: "Entities" }
                RightTabButton { right_tab, on_viewer_right_tab_selected, tab: ViewerRightTabSelection::Metadata, label: "Metadata" }
            }
            div {
                style: "flex: 1 1 auto; min-height: 0; overflow: hidden;",
                match right_tab().selected_tab {
                    ViewerRightTabSelection::Entities => rsx! { DocumentEntitiesPanel { document_identifier } },
                    ViewerRightTabSelection::Metadata => rsx! { RawMetadataCollector { document_identifier } },
                }
            }
        }
    }
}

#[component]
fn LeftControls(
    sources: ReadSignal<Option<Vec<DocumentSourceItem>>>,
    selected_source: ReadSignal<Option<DocumentSourceItem>>,
    on_source_selected: Callback<DocumentSourceItem>,
    on_find_query_changed: Callback<String>,
    controls: Element,
) -> Element {
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: column;
                gap: 12px;
                padding: 12px;
                height: 100%;
                overflow: hidden;
            ",
            div {
                style: "flex-shrink: 0;",
                DocPreviewFindQueryInputBox { on_find_query_changed }
            }
            div {
                style: "flex-shrink: 0;",
                {controls}
            }
            div {
                style: "flex-shrink: 0;",
                DocumentPreviewSourceSelectorList {
                    sources,
                    selected_source,
                    on_source_selected
                }
            }
        }
    }
}

#[derive(Clone, Copy)]
struct ViewerPageControls {
    pub document_identifier: ReadSignal<DocumentIdentifier>,
    pub sources: ReadSignal<Option<Vec<DocumentSourceItem>>>,
    pub selected_source: ReadSignal<Option<DocumentSourceItem>>,
    pub on_source_selected: Callback<DocumentSourceItem>,
    pub on_find_query_changed: Callback<String>,
    pub viewer_right_tab_state: ReadSignal<ViewerRightTabState>,
    pub on_viewer_right_tab_selected: Callback<ViewerRightTabState>,
}

fn _make_view_wrapper(controls: Element, page: Element) -> Element {
    let ViewerPageControls {
        document_identifier,
        sources,
        selected_source,
        on_source_selected,
        on_find_query_changed,
        ..
    } = use_context::<ViewerPageControls>();
    rsx! {


        div {
            style: "
                flex: 1 1 auto;
                min-width: 0;
                height: 100%;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            ",
            div {
                style: "
                    flex: 1 1 auto;
                    min-height: 0;
                    display: flex;
                    flex-direction: row;
                    overflow: hidden;
                ",
                div {
                    style: "
                        width: 340px;
                        flex: 0 0 auto;
                        height: 100%;
                        overflow: hidden;
                        border-right: 1px solid rgba(0,0,0,0.15);
                        background: rgba(0,0,0,0.02);
                    ",
                    LeftControls {
                        sources: sources,
                        selected_source: selected_source,
                        on_source_selected,
                        on_find_query_changed,
                        controls
                    }
                }
                div {
                    style: "
                        flex: 1 1 auto;
                        min-width: 0;
                        height: 100%;
                        overflow: hidden;
                    ",

                    DocTitleBar { document_identifier, show_new_tab_button: false }
                    div {
                        style: "width: 100%; height: calc(100% - 54px); border: 1px solid transparent; padding: 8px;",
                        {page}
                    }
                }
            }
        }
    }
}
