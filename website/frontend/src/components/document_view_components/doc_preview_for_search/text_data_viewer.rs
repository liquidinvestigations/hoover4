//! Document preview text viewer component.

use std::collections::BTreeMap;

use common::{document_sources::DocumentTextSourceItem, search_result::DocumentIdentifier};
use dioxus::prelude::*;

use crate::{
    components::{
        document_view_components::doc_preview_for_search::text_preview_with_search::DocumentViewerResultStore, error_boundary::ComponentErrorDisplay, suspend_boundary::LoadingIndicator
    },
    pages::search_page::DocViewerStateControl,
};

#[component]
pub fn TextDataViewer() -> Element {
    let mounts: Signal<BTreeMap<u32, Event<MountedData>>> = use_signal(|| BTreeMap::new());
    let current_highlighted_word_index =
        use_context::<DocumentViewerResultStore>().current_highlighted_word_index;
    use_effect(move || {
        let current = *current_highlighted_word_index.read();
        if let Some(mount) = mounts.read().get(&(current as u32)) {
            dioxus::logger::tracing::info!("Scrolling to span: {current}");
            let _x = mount.scroll_to_with_options(ScrollToOptions {
                behavior: ScrollBehavior::Smooth,
                vertical: ScrollLogicalPosition::Center,
                horizontal: ScrollLogicalPosition::Center,
            });
        } else {
            dioxus::logger::tracing::info!("No span found to scroll to: {current}");
        }
    });
    rsx! {
        TextDataInner { mounts }
    }
}

#[component]
fn TextDataInner(mut mounts: Signal<BTreeMap<u32, Event<MountedData>>>) -> Element {
    let current_text_data = use_context::<DocumentViewerResultStore>().current_text_data;
    let document_identifier = use_context::<DocumentViewerResultStore>().document_identifier;
    let source = use_context::<DocumentViewerResultStore>().source;
    // let current_query = use_context::<DocViewerStateControl>()
    //     .doc_viewer_state
    //     .read()
    //     .as_ref()
    //     .map(|state| state.find_query.clone())
    //     .unwrap_or("".to_string());
    let text_data = match current_text_data.read().clone() {
        Some(Ok(text_data)) => {
            if text_data.is_empty() {
                return rsx! {
                    TextDataFallback{document_identifier, source}

                    // div {
                    //     style: "padding: 12px; margin: 12px; font-size: 26px;",
                    //     "No matches found for "
                    //     i { b {
                    //         "{current_query}"
                    //     } }
                    // }
                };
            }
            text_data[0].clone()
        }
        Some(Err(_error)) => {
            return rsx! {
                div {
                    LoadingIndicator {  }
                }
            };
        }
        None => {
            return rsx! {
                LoadingIndicator {  }
            };
        }
    };

    let spans = text_data
        .highlight_text_spans
        .iter()
        .map(|i| {
            let i = i.clone();
            let index = i.index as u32;
            rsx! {
                if i.is_highlighted {
                    TextDataSpan { mounts, index, text: i.text }
                } else {
                    TextDataSpanClean { text: i.text }
                }
            }
        })
        .collect::<Vec<_>>();

    rsx! {
        div {
            style: "
                height: 100%;
                width: 100%;
                overflow-y: scroll;
            ",
            pre {
                style: "
                    white-space: pre-wrap; word-wrap: break-word;
                    font-size: 16px;
                    line-height: 23px;
                    font-weight: 400;
                    color: rgb(0, 0, 0);
                ",
                {spans.into_iter()}
            }

        }
    }
}

#[server]
async fn get_document_text_by_id_and_source(document_identifier: DocumentIdentifier, 
source: DocumentTextSourceItem,
) -> Result<String, ServerFnError> {
    backend::api::documents::search_document_text::get_document_text_by_id_and_source(document_identifier, source).await.map_err(|e| ServerFnError::new(format!("{e:#?}")))
}

#[component]
fn TextDataFallback(

         document_identifier: ReadSignal<DocumentIdentifier>,
     source: ReadSignal<DocumentTextSourceItem>,

) -> Element {

    let _data = use_resource(move || {
        let document_identifier = document_identifier.read().clone();
        let source = source.read().clone();
        get_document_text_by_id_and_source(document_identifier, source)
    });

    let text=   _data.read();
    let text = match text.as_ref() {
        Some(Ok(v)) => {
            v
        }
        Some(Err(e)) =>{ return rsx!{
            ComponentErrorDisplay {
                error_txt: "{e:#?}",
            }
        }}
        None => {return rsx!{
            LoadingIndicator {  }
        }}
    };


    rsx! {
         div {
            style: "
                height: 100%;
                width: 100%;
                overflow-y: scroll;
            ",
            pre {
                style: "
                    white-space: pre-wrap; word-wrap: break-word;
                    font-size: 16px;
                    line-height: 23px;
                    font-weight: 400;
                    color: rgb(0, 0, 0);
                ",
                TextDataSpanClean { text }
            }
        }
        
    }
}

#[component]
fn TextDataSpan(
    mounts: Signal<BTreeMap<u32, Event<MountedData>>>,
    index: u32,
    text: String,
) -> Element {
    let current_highlighted_word_index =
        use_context::<DocumentViewerResultStore>().current_highlighted_word_index;
    let color = use_memo(move || {
        if index == *current_highlighted_word_index.read() as u32 {
            return "black";
        }
        return "transparent";
    });

    rsx! {
        span {
            onmounted:  move |event| async move {
                mounts.write().insert(index, event.clone());
            },
            style: "background-color: #eb3f004d; color: rgb(0, 0, 0); white-space:pre-wrap; word-wrap: break-word; border: 2px dotted {color};",
            "{text}"
        }
    }
}

#[component]
fn TextDataSpanClean(text: String) -> Element {
    rsx! {
        span {
            style: "color: rgb(0, 0, 0); white-space:pre-wrap; word-wrap: break-word;",
            "{text}"
        }
    }
}
