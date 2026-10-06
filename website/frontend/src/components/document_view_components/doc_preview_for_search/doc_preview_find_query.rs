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
        crate::components::search_input::SearchInput {
            value: modified_find_query,
            placeholder: "Search in document",
            on_change: move |value: String| modified_find_query.set(value),
            on_submit: move |_| on_find_query_changed.call(modified_find_query()),
        }
    }
}
