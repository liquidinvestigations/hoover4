//! Full-page document viewer components.

use common::document_sources::DocumentSourceItem;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::{
    doc_preview_for_search::{
        doc_preview_find_query::DocPreviewFindQueryInputBox,
        doc_preview_source_selector::DocumentPreviewSourceSelector,
    },
    document_entities_panel::DocumentEntitiesPanel,
    doc_title_bar::DocTitleBar,
    raw_metadata_collector::RawMetadataCollector,
};

use crate::pages::search_page::DocViewerStateControl;
use crate::{
    components::document_view_components::doc_preview_for_search::{
        get_document_sources,
    },
    components::document_view_components::doc_preview_shared::{DocSourceDispatch, ProvidePreviewExtraSections},
    data_definitions::doc_viewer_state::DocViewerState,
};

#[component]
pub fn DocViewerRoot(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let mut doc_viewer_state = use_signal(|| Some(DocViewerState::default()));
    use_context_provider(move || DocViewerStateControl {
        doc_viewer_state: doc_viewer_state.into(),
        set_doc_viewer_state: Callback::new(move |state: DocViewerState| {
            doc_viewer_state.set(Some(state));
        }),
    });

    let mut doc_sources: Resource<Vec<DocumentSourceItem>> = use_resource(move || {
        let document_identifier = document_identifier.read().clone();
        async move { get_document_sources(document_identifier).await.unwrap_or_default() }
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

    let left_controls = rsx! {
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
                DocumentPreviewSourceSelector {
                    sources: doc_sources,
                    selected_source: currently_selected_source,
                    on_source_selected
                }
            }
        }
    };

    #[derive(Debug, Clone, Copy, PartialEq)]
    enum RightTab {
        Entities,
        Metadata,
    }
    let mut right_tab = use_signal(|| RightTab::Entities);

    let tab_button = |tab: RightTab, label: &'static str| {
        let is_active = right_tab() == tab;
        let border = if is_active {
            "2px solid rgba(0,0,0,0.9)"
        } else {
            "1px solid rgba(0,0,0,0.25)"
        };
        let bg = if is_active { "white" } else { "rgba(0,0,0,0.03)" };
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
                    right_tab.set(tab);
                },
                "{label}"
            }
        }
    };

    let right_panel = rsx! {
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
                {tab_button(RightTab::Entities, "Entities")}
                {tab_button(RightTab::Metadata, "Metadata")}
            }
            div {
                style: "flex: 1 1 auto; min-height: 0; overflow: hidden;",
                match right_tab() {
                    RightTab::Entities => rsx! { DocumentEntitiesPanel { document_identifier } },
                    RightTab::Metadata => rsx! { RawMetadataCollector { document_identifier } },
                }
            }
        }
    };

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
            children: content_view_inner
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
            div {
                style: "
                    flex: 1 1 auto;
                    min-width: 0;
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                ",
                DocTitleBar { document_identifier }
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
                        {left_controls}
                    }
                    div {
                        style: "
                            flex: 1 1 auto;
                            min-width: 0;
                            height: 100%;
                            overflow: hidden;
                        ",
                        {content_view}
                    }
                }
            }
            div {
                style: "
                    width: 420px;
                    flex: 0 0 auto;
                    height: 100%;
                    overflow: hidden;
                    background: white;
                ",
                {right_panel}
            }
        }
    }
}
