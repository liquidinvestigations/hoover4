use dioxus::prelude::*;

use crate::pages::search_page::DocViewerStateControl;

#[component]
pub fn DocPreviewFindQueryInputBox(on_find_query_changed: Callback<String>) -> Element {
    let state = use_context::<DocViewerStateControl>();
    let find_query = use_memo(move || {
        let r = state.doc_viewer_state.read().clone();
        let Some(state) = &r else {
            return "".to_string();
        };
        state.find_query.clone()
    });
    let mut modified_find_query = use_signal(move || find_query.read().clone());
    use_effect(move || {
        let q = find_query.read().clone();
        modified_find_query.set(q);
    });

    rsx! {
        div {
                style: "
                    flex-grow: 0;
                    flex-shrink: 0;
                ",
                input {
                    r#type: "text",
                    placeholder: "Search in document",
                    style: "
                        width: 100%;
                        height: 100%;
                        border: none;
                        outline: none;
                        background: white;
                        border: 1px solid rgba(0, 0, 0, 0.5);
                        border-radius: 14px;
                        padding: 8px 12px;
                        font-size: 14px;
                        font-weight: 400;
                        color: rgba(0, 0, 0, 0.8);
                        margin-left: 12px;
                        ",
                    value: "{find_query.read()}",
                    oninput: move |e| {
                        let q = e.value();
                        modified_find_query.set(q);
                    },
                    onkeydown: move |e| {
                        if e.key() == Key::Enter {
                            dioxus::logger::tracing::info!("Find Query: {}", find_query.read().clone());
                            on_find_query_changed.call(modified_find_query.read().clone());
                        }
                    },
                }
            }
    }
}
