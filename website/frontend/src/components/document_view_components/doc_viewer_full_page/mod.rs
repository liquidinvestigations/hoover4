//! Full-page document viewer components.

mod document_entities_panel;
mod document_red_flags;
mod raw_metadata_collector;

pub(crate) use raw_metadata_collector::{METADATA_KEY_STYLE, SECTION_HEADER_STYLE, SECTION_STYLE, get_document_dates};

use common::document_sources::{DocumentSourceItem, ItemHitCounts};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::{
    components::document_view_components::{
        doc_preview_for_search::{
            doc_preview_find_query::DocPreviewFindQueryInputBox,
            doc_preview_source_selector::{
                DocumentPreviewSourceSelectorList,
                search_document_item_hit_counts,
            },
        },
        doc_file_locations_panel::DocumentFileLocationsPanel,
        doc_title_bar::DocTitleBar,
        doc_viewer_full_page::{
            document_entities_panel::DocumentEntitiesPanel,
            raw_metadata_collector::RawMetadataCollector,
        },
    },
    data_definitions::doc_viewer_state::{ViewerRightTabSelection, ViewerRightTabState},
    routes::Route,
};

use crate::pages::search_page::DocViewerStateControl;
use crate::{
    components::document_view_components::doc_preview_for_search::get_document_sources,
    components::document_view_components::doc_preview_shared::{
        DocSourceDispatch, PreviewWrapper, ProvidePreviewExtraSections, SourceLoadNotice,
    },
    data_definitions::doc_viewer_state::DocViewerState,
};
use crate::tr;
use crate::i18n::SharedText;

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
                viewer_right_tab_state: viewer_right_tab_state.read().clone().into(),
            });
        }),
    });

    let document_identifier_value = document_identifier();
    // The identifier is passed by value through `use_reactive` rather than read as a
    // signal: a `ReadSignal` prop is a new signal on every parent render, so a resource
    // subscribed to it never re-runs and the pairing of `use_effect` + `restart()` that
    // used to compensate fired a second, identical request on every mount.
    let mut source_request = use_resource(use_reactive!(|document_identifier_value| {
        async move {
            let result = get_document_sources(document_identifier_value.clone()).await;
            (document_identifier_value, result)
        }
    }));
    let source_reply = use_memo(use_reactive!(|document_identifier_value| {
        source_request.read().as_ref().filter(|(answered, _)| answered == &document_identifier_value)
            .map(|(_, result)| result.clone())
    }));
    let doc_sources: ReadSignal<Option<Vec<DocumentSourceItem>>> =
        use_memo(move || source_reply.read().as_ref()
            .and_then(|r| r.as_ref().ok().map(|status| status.sources.clone()))).into();
    use_context_provider(move || crate::components::document_view_components::doc_preview_for_search::doc_preview_for_email::EmailNavigationSources(doc_sources));
    let source_error = use_memo(move || source_reply.read().as_ref().and_then(|result| {
        match result {
            Ok(status) if !status.errors.is_empty() => Some(status.errors.join(", ")),
            Err(error) => Some(error.to_string()),
            _ => None,
        }
    }));

    let empty_source_message = use_memo(move || source_reply.read().as_ref()
        .and_then(|result| result.as_ref().ok())
        .map(|status| status.processing.empty_source_message().shared()).unwrap_or_default());

    let control = use_context::<DocViewerStateControl>();
    let currently_selected_source: ReadSignal<Option<DocumentSourceItem>> = use_memo(move || {
        let sources = doc_sources.read().clone().unwrap_or_default();
        if let Some(state) = control.doc_viewer_state.read().clone() {
            if let Some(selected_source) = state.selected_source {
                if let Some(source) = sources.iter().find(|s| s.same_source(&selected_source)) {
                    return Some(source.clone());
                }
            }
        }
        sources.first().cloned()
    })
    .into();

    let on_source_selected = Callback::new(move |source: DocumentSourceItem| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.selected_source = Some(source.route_identity());
        // Source numbering can describe different units, so the page and match reset.
        state.selected_source_page = None;
        state.selected_match = None;
        control.set_doc_viewer_state.call(state);
    });

    let on_find_query_changed = Callback::new(move |query: String| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.find_query = query;
        // An explicit text page stays. Its match selection belonged to the old query.
        state.selected_match = None;
        if let Some(table) = &mut state.table_state {
            table.page = 0;
        }
        control.set_doc_viewer_state.call(state);
    });

    let on_viewer_right_tab_selected = Callback::new(move |state: ViewerRightTabState| {
        navigator().replace(Route::ViewDocumentPage {
            document_identifier: document_identifier.read().clone().into(),
            doc_viewer_state: control.doc_viewer_state.read().clone().into(),
            viewer_right_tab_state: state.into(),
        });
    });

    // ================ ITEM HIT COUNTS: ================
    let count_key = use_memo(use_reactive!(|document_identifier_value| {
        let sources = doc_sources.read().clone().unwrap_or_default();
        let query = control.doc_viewer_state.read().clone().unwrap_or_default().find_query;
        (document_identifier_value, query, sources)
    }));
    let counts = use_resource(move || {
        let key = count_key();
        async move {
            let result = search_document_item_hit_counts(key.0.clone(), key.1.clone(), key.2.clone()).await;
            (key, result)
        }
    });
    let item_hit_counts = use_memo(move || match counts.read().as_ref() {
        Some((answered, Ok(value))) if answered == &count_key() => value.clone(),
        Some((answered, Err(_))) if answered == &count_key() => ItemHitCounts(answered.2.iter().cloned()
            .map(|source| (source, common::document_text_pages::HitCountState::Failed)).collect()),
        _ => ItemHitCounts(Vec::new()),
    });

    use_context_provider(move || ViewerPageControls {
        document_identifier,
        sources: doc_sources,
        selected_source: currently_selected_source,
        on_source_selected,
        on_find_query_changed,
        viewer_right_tab_state,
        on_viewer_right_tab_selected,
        item_hit_counts: item_hit_counts.into(),
    });

    // `None` means two different things and they must not look the same. Until the
    // resource answers, `doc_sources` is `None` and the viewer is genuinely loading; once
    // it answers with an empty list there is no source and never will be, so a spinner
    // would run forever. Every source is a piece of extracted content, so a document
    // whose extraction produced nothing (or an identifier that resolves to no document
    // at all) lands here, and it still gets the title bar and the right-hand tabs:
    // the name and the metadata are exactly what someone looking at an empty document
    // came for.
    let sources_answered = use_memo(move || doc_sources.read().is_some());
    let content_view_inner = match currently_selected_source.read().clone() {
        Some(source) => rsx! { DocSourceDispatch { document_identifier, source } },
        None if sources_answered() => rsx! {
            PreviewWrapper {
                controls: rsx! { div {} },
                page: rsx! {
                    div {
                        style: "padding: 12px; color: rgba(0,0,0,0.45); font-style: italic;",
                        "{empty_source_message().shared()}"
                    }
                },
            }
        },
        None => rsx! { div { style: "padding: 12px;", {tr!("doc-viewer-full-loading")} } },
    };

    // Provide the same context that search-preview provides, but the triptych renders these
    // controls vertically in the left column; so we pass empty elements here to satisfy
    // `PreviewControlsSection` without duplicating UI.
    // The notice sits above the viewer in the same column, so the row layout beside the
    // details pane does not change.
    let content_view = rsx! {
        div {
            style: "flex: 1 1 auto; min-width: 0; height: 100%; display: flex; flex-direction: column; overflow: hidden;",
            if let Some(error) = source_error() {
                SourceLoadNotice { error, on_retry: move |_| source_request.restart() }
            }
            div {
                style: "flex: 1 1 auto; min-height: 0; display: flex; flex-direction: row; overflow: hidden;",
                ProvidePreviewExtraSections {
                    find_query_input_box: rsx! { div {} },
                    preview_selector: rsx! { div {} },
                    children: content_view_inner,
                    wrapper_fn: _make_view_wrapper,
                }
            }
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
            crate::components::resizable_sidebar::ResizablePane {
                storage_key: "hoover4.document-details-width-css-px",
                default_px: 360,
                min_px: 300,
                max_px: 900,
                side: crate::components::resizable_sidebar::PaneSide::Right,
                handle_id: "x-document-details-resize",
                max_share: "45%",
                pane_style: "background: white;".to_string(),
                RightPanel { document_identifier }
            }
        }
    }
}

#[component]
fn RightTabButton(
    right_tab: ReadSignal<ViewerRightTabState>,
    tab: ViewerRightTabSelection,
    label: String,
    on_viewer_right_tab_selected: Callback<ViewerRightTabState>,
) -> Element {
    let is_active = right_tab().selected_tab == tab;
    let border = if is_active {
        "2px solid rgba(0,0,0,0.9)"
    } else {
        "1px solid rgba(0,0,0,0.25)"
    };
    let bg = if is_active {
        "rgba(255,255,255,1.0)"
    } else {
        "rgba(0,0,0,0.03)"
    };

    rsx! {
        button {
            style: "
                cursor: pointer;
                padding: 4px 11px;
                border-radius: 10px;
                border: {border};
                background: {bg};
                font-size: 13px;
                line-height: 19px;
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
                    gap: 8px;
                    align-items: center;
                    padding: 8px;
                    border-bottom: 1px solid rgba(0,0,0,0.15);
                    background: rgba(0,0,0,0.02);
                ",
                RightTabButton { right_tab, on_viewer_right_tab_selected, tab: ViewerRightTabSelection::Entities, label: tr!("doc-viewer-full-entities") }
                RightTabButton { right_tab, on_viewer_right_tab_selected, tab: ViewerRightTabSelection::FileLocations, label: tr!("doc-viewer-full-file-locations") }
                RightTabButton { right_tab, on_viewer_right_tab_selected, tab: ViewerRightTabSelection::Metadata, label: tr!("doc-viewer-full-metadata") }
            }
            div {
                style: "flex: 1 1 auto; min-height: 0; overflow: hidden;",
                match right_tab().selected_tab {
                    ViewerRightTabSelection::Entities => rsx! { DocumentEntitiesPanel { document_identifier } },
                    ViewerRightTabSelection::FileLocations => rsx! { DocumentFileLocationsPanel { document_identifier } },
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
    item_hit_counts: ReadSignal<ItemHitCounts>,
) -> Element {
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: column;
                gap: 8px;
                padding: 8px;
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
                    on_source_selected,
                    item_hit_counts,
                }
            }
        }
    }
}

#[derive(Clone, Copy)]
struct ViewerPageControls {
    pub document_identifier: ReadSignal<DocumentIdentifier>,
    pub sources: ReadSignal<Option<Vec<DocumentSourceItem>>>,
    pub item_hit_counts: ReadSignal<ItemHitCounts>,
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
        item_hit_counts,
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
                crate::components::resizable_sidebar::ResizablePane {
                    storage_key: "hoover4.document-sources-width-css-px",
                    default_px: 224,
                    min_px: 200,
                    max_px: 560,
                    side: crate::components::resizable_sidebar::PaneSide::Left,
                    handle_id: "x-document-sources-resize",
                    max_share: "35%",
                    pane_style: "background: rgba(0,0,0,0.02);".to_string(),
                    LeftControls {
                        sources: sources,
                        selected_source: selected_source,
                        on_source_selected,
                        on_find_query_changed,
                        controls,
                        item_hit_counts,
                    }
                }
                div {
                    style: "
                        flex: 1 1 auto;
                        min-width: 0;
                        height: 100%;
                        overflow: hidden;
                    ",

                    DocTitleBar { document_identifier, show_new_tab_button: false, show_finder: true }
                    div {
                        style: "width: 100%; height: calc(100% - var(--x-doc-title-height)); border: 1px solid transparent; padding: 8px;",
                        {page}
                    }
                }
            }
        }
    }
}
