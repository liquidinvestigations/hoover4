//! Document preview text viewer component.

use std::collections::BTreeMap;

use common::{document_sources::DocumentTextSourceItem, search_result::DocumentIdentifier};
use dioxus::{logger::tracing, prelude::*};

use crate::{
    components::{
        document_view_components::doc_preview_for_search::text_preview_with_search::DocumentViewerResultStore, error_boundary::ComponentErrorDisplay, suspend_boundary::LoadingIndicator
    },
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

    let text_data = match current_text_data.read().clone() {
        Some(Ok(text_data)) => {
            if text_data.is_empty() {
                return rsx! {
                    TextDataFallback{document_identifier, source}
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

    let document_identifier = document_identifier.peek().clone();
    let source = source.peek().clone();
    let onclick = Callback::new(move |clicked_index| {
        tracing::info!("Clicked index {clicked_index}");
        let mut current_highlighted_word_index = use_context::<DocumentViewerResultStore>().current_highlighted_word_index;
        current_highlighted_word_index.set(clicked_index);
    });
    let spans = text_data
        .highlight_text_spans
        .iter().enumerate()
        .map(|(nth, i)| {
            let i = i.clone();
            let index = i.index as u32;
            let key = format!("{document_identifier:?}-{nth}-{source:?}");
            rsx! {
                if i.is_highlighted {
                    TextDataSpan { mounts, index, text: i.text,  key2: key.clone() , onclick}
                } else {
                    TextDataSpanClean { text: i.text,  key2: key.clone() }
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
    backend::api::documents::search_document_text::get_document_text_by_id_and_source(document_identifier, source.extracted_by.clone(), source.min_page).await.map_err(|e| ServerFnError::new(format!("{e:#?}")))
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

    
    let document_identifier = document_identifier.read().clone();
    let source = source.read().clone();
    let fb = format!("fallback-{document_identifier:?}-{source:?}");


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
                TextDataSpanClean { text, key2: "{fb}" }
            }
        }
        
    }
}

#[component]
fn TextDataSpan(
    mounts: Signal<BTreeMap<u32, Event<MountedData>>>,
    index: u32,
    text: String,
    key2: String,
    onclick: Callback<u32>,
) -> Element {
    let current_highlighted_word_index =
        use_context::<DocumentViewerResultStore>().current_highlighted_word_index;
    let is_selected = use_memo(move || {
        index == *current_highlighted_word_index.read() as u32
    });

    let is_selected = is_selected();

    let text = text_to_span_html(text, true, is_selected);

    rsx! {
        span {
            key: "{key2}",
            onmounted:  move |event| async move {
                mounts.write().insert(index, event.clone());
            },
            onclick: move |_| onclick.call(index),
            
            dangerous_inner_html: text,
        }
    }
}

#[component]
fn TextDataSpanClean(text: String, key2: String) -> Element {
    let text = text_to_span_html(text, false, false);

    rsx! {
        span {
            key: "{key2}-clean",
            dangerous_inner_html: text,
        }
    }
}


fn text_to_span_html(text: String, is_match: bool, is_active_match: bool) -> String {
    // the "b" bug #105 - dioxus bug where it doesn't encode/decode html
    // and markup breaks. instead, we generate our own html here.
    let class = if is_match {
        if is_active_match {
            "x-hit-span-active-match"
        } else {
            "x-hit-span-inacti-match"
        }
    } else {
        "x-hit-span-non-match"
    };

    let text = html_escape::encode_text(&text).to_string();

    format!(r#"<span class="{class}">{text}</span>"#)
}