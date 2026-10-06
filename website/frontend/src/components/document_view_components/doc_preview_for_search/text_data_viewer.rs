//! Document preview text viewer component.

use common::{document_sources::DocumentTextSourceItem, search_result::DocumentIdentifier};
use dioxus::prelude::*;

use crate::{
    components::{
        document_view_components::doc_preview_for_search::text_preview_with_search::DocumentViewerResultStore, error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator
    },
};

#[component]
pub fn TextDataViewer() -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let control = use_context::<crate::pages::search_page::DocViewerStateControl>();
    use_effect(move || {
        let current = *store.current_highlighted_word_index.read();
        let _query = control.doc_viewer_state.read().clone();
        let _document = store.document_identifier.read().clone();
        let _source = store.source.read().clone();
        let _page = store.current_text_data.read().clone();
        document::eval(&format!(r#"
            requestAnimationFrame(() => {{
                const root = document.getElementById('x-document-text-viewer');
                const hit = root?.querySelector('[data-text-hit="{current}"]');
                hit?.scrollIntoView({{block:'center', inline:'nearest'}});
            }});
        "#));
    });
    rsx! { TextDataInner {} }
}

#[component]
fn TextDataInner() -> Element {
    let current_text_data = use_context::<DocumentViewerResultStore>().current_text_data;
    let document_identifier = use_context::<DocumentViewerResultStore>().document_identifier;
    let source = use_context::<DocumentViewerResultStore>().source;
    // Read out of the context in the component body, not in the click handler below: a
    // hook inside a closure runs an unpredictable number of times per render and shifts
    // every hook index after it. The signal is `Copy`, so the closure captures it.
    let mut current_highlighted_word_index =
        use_context::<DocumentViewerResultStore>().current_highlighted_word_index;

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
        current_highlighted_word_index.set(clicked_index);
    });
    let spans = text_data
        .highlight_text_spans
        .iter().enumerate()
        .map(|(nth, i)| {
            let i = i.clone();
            let index = i.index as u32;
            let key = format!("{document_identifier:?}-{nth}-{source:?}-{}", text_data.page_id);
            rsx! {
                if i.is_highlighted {
                    TextDataSpan { key: "{key}", index, text: i.text, key2: key.clone(), onclick}
                } else {
                    TextDataSpanClean { key: "{key}", text: i.text, key2: key.clone() }
                }
            }
        })
        .collect::<Vec<_>>();

    rsx! {
        div {
            id: "x-document-text-viewer",
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
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::search_document_text::get_document_text_by_id_and_source(&user, document_identifier, source.extracted_by.clone(), source.min_page).await.map_err(crate::api::error_util::to_server_fn_error)
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
            ServerErrorDisplay { error: e.clone() }
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
    index: u32,
    text: String,
    key2: String,
    onclick: Callback<u32>,
) -> Element {
    let current_highlighted_word_index =
        use_context::<DocumentViewerResultStore>().current_highlighted_word_index;
    let is_selected = index == *current_highlighted_word_index.read();

    let text = text_to_span_html(text, true, is_selected);

    rsx! {
        span {
            key: "{key2}",
            "data-text-hit": "{index}",
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