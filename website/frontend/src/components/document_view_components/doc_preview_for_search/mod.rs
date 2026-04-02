//! Document preview components for search results.

mod doc_preview_for_pdf;
mod doc_preview_for_text;
mod no_document_selected;
mod text_data_viewer;
mod doc_preview_source_selector;
mod doc_preview_find_query;

use common::document_sources::DocumentSourceItem;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::doc_preview_find_query::DocPreviewFindQueryInputBox;
use crate::components::document_view_components::doc_preview_for_search::doc_preview_source_selector::DocumentPreviewSourceSelector;
use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_pdf::DocumentPreviewForPdf;
use crate::components::document_view_components::doc_preview_for_search::doc_preview_for_text::DocumentPreviewForTextWithSearch;
use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::raw_metadata_collector::RawMetadataCollector;
use crate::components::suspend_boundary::LoadingIndicator;
use crate::pages::search_page::DocViewerStateControl;

#[component]
pub fn DocumentPreviewForSearchRoot(
    query: ReadSignal<SearchQuery>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
) -> Element {
    let Some(document_identifier) = selected_result_hash.read().clone() else {
        return rsx! {
            no_document_selected::NoDocumentSelected {}
        };
    };

    let mut doc_sources: Resource<Vec<DocumentSourceItem>> = use_resource(move || {
        let document_identifier = selected_result_hash.peek().clone();
        async move {
            let Some(document_identifier) = document_identifier else {
                return vec![];
            };
            get_document_sources(document_identifier)
                .await
                .unwrap_or_default()
        }
    });
    use_effect(move || {
        let _document_identifier = selected_result_hash.read().clone();
        // let Some(_document_identifier) = document_identifier else { return };
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
        return sources.first().cloned();
    })
    .into();

    let on_source_selected = Callback::new(move |source: DocumentSourceItem| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.selected_source = Some(source);
        state.selected_source_page = None;
        control.set_doc_viewer_state.call(state);
    });

    let preview_selector = rsx! {
        DocumentPreviewSourceSelector {
            sources: doc_sources,
            selected_source: currently_selected_source,
            on_source_selected
        }
    };

    let on_find_query_changed = Callback::new(move |query: String| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.find_query = query;
        control.set_doc_viewer_state.call(state);
    });

    let find_query_input_box = rsx! {
        DocPreviewFindQueryInputBox {
            on_find_query_changed: on_find_query_changed.clone(),
        }
    };


    match (
        doc_sources.read().as_ref(),
        currently_selected_source.read().as_ref(),
    ) {
        (Some(_sources), Some(selected_source)) => {
            rsx! {
                DocumentPreviewRender {
                    preview_selector,
                    find_query_input_box,
                    document_identifier,
                    source: selected_source.clone(),
                }
                // DocumentPreviewForPdf { document_identifier, page_count }
            }
        }
        // Some((false, _)) => {
        //     rsx! {
        //         DocumentPreviewForTextWithSearch { document_identifier }
        //     }
        // }
        _ => {
            return rsx! {
                LoadingIndicator {  }
            };
        }
    }
}

#[server]
pub async fn get_document_sources(
    document_identifier: DocumentIdentifier,
) -> Result<Vec<DocumentSourceItem>, ServerFnError> {
    let sources =
        backend::api::documents::get_document_sources::get_document_sources(document_identifier)
            .await
            .map_err(|e| ServerFnError::from(e))?;
    Ok(sources)
}

#[component]
fn DocumentPreviewRender(
    preview_selector: Element,
    find_query_input_box: Element,
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentSourceItem>,
) -> Element {
    let find_query = use_signal(move || find_query_input_box);
    let preview_selector = use_signal(move || preview_selector);
    use_context_provider(move || PreviewExtraSections {
        find_query: find_query.into(),
        preview_selector: preview_selector.into(),
    });
    rsx! {
        PreviewDocumentDispatch {
            document_identifier,
            source,
        }
    }
}

#[derive(Clone, Copy)]
struct PreviewExtraSections {
    find_query: ReadSignal<Element>,
    preview_selector: ReadSignal<Element>,
}

#[component]
pub fn PreviewControlsSection(children: Element) -> Element {
    let sections = use_context::<PreviewExtraSections>();
    rsx!{
        PreviewSubtitleBar2 {
            find_query_input_box: sections.find_query.read().clone(),
            preview_selector: sections.preview_selector.read().clone(),
            control: children,
        }
    }
}

#[component]
pub fn PreviewPageSection(children: Element) -> Element {
    rsx! {
        div {
            style: "
                width: 100%;
                height: calc(100% - 110px);
                padding: 10px;
            ",
            {children}

        }
    }
}



#[component]
fn PreviewSubtitleBar2(find_query_input_box: Element, preview_selector: Element, control: Element) -> Element {
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: row;
                gap: 12px;
                align-items: center;
                justify-content: space-between;
                height: 48px;
                width: 100%;
                background-color:rgba(0, 0, 0, 0.04);
                flex-shrink: 0;
                flex-grow: 0;
                border: 1px solid rgba(0, 0, 0, 0.3); border-top: none;
            ",

            // SEARCH BOX
            {find_query_input_box}


            // SPACER
            div {style:"flex-grow: 1;"}

            // CONTROLS
            div {
                style:"flex-grow: 13; flex-shrink: 1; height: 90%;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 4px;
                ",
                {control}
            }


            // SPACER
            div {style:"flex-grow: 1;"}

            // SEARCH HIT SELECTOR
            {preview_selector}

        }
    }
}


#[component]
fn PreviewDocumentDispatch(document_identifier: ReadSignal<DocumentIdentifier>, source: ReadSignal<DocumentSourceItem>) -> Element {
    let page = match source.read().clone() {
        DocumentSourceItem::Pdf(pdf) => {
            rsx! {
                DocumentPreviewForPdf {
                    document_identifier,
                    source: pdf,
                }
            }
        }
        DocumentSourceItem::Text(text) => {
            rsx! {
                DocumentPreviewForTextWithSearch {
                    document_identifier,
                    source: text,
                }
            }
        }
        DocumentSourceItem::Image(image) => {
            rsx! {
                PreviewControlsSection {
                    "Image; {image.width}x{image.height}"
                }
                PreviewPageSection {
                    img {
                        src: "{document_identifier().get_absolute_url_path()}",
                        style: "max-width: 100%; max-height: 100%;",
                        alt: "image preview"
                    }
                }
            }
        }
        DocumentSourceItem::Audio(audio) => {
            rsx! {
                PreviewControlsSection {
                    "Audio; {audio.duration_seconds} seconds"
                }
                PreviewPageSection {
                    audio {
                        src: "{document_identifier().get_absolute_url_path()}",
                        alt: "audio preview",
                        controls: true
                    }
                }
            }
        }
        DocumentSourceItem::Video(video) => {
            rsx! {
                PreviewControlsSection {
                    "Video; {video.width}x{video.height} - {video.duration_seconds} seconds"
                }
                PreviewPageSection {
                    video {
                        src: "{document_identifier().get_absolute_url_path()}",
                        alt: "video preview",
                        controls: true,
                        style: "max-width: 100%; max-height: 100%;",
                    }
                }
            }
        }


        DocumentSourceItem::Metadata => {
            rsx! {
                PreviewControlsSection {
                    "Metadata"
                }
                PreviewPageSection {
                    RawMetadataCollector { document_identifier }
                }
            }
        }
        _x => {
            rsx! {
                PreviewControlsSection {
                    "TODO CONTROLS: {_x:?}"
                }
                PreviewPageSection {
                    "TODO PAGE: {_x:?}"
                }
            }
        }
    };

    rsx! {
        DocTitleBar { document_identifier }
        {page}
    }

}