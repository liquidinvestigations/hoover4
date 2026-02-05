use dioxus::prelude::*;
use common::search_query::SearchQuery;
use dioxus_free_icons::{Icon, icons::{go_icons::GoDatabase, md_action_icons::MdSearch, md_communication_icons::MdLocationOn, md_editor_icons::MdInsertDriveFile, md_navigation_icons::{MdApps, MdArrowDropDown}}};
use crate::{components::{search_components::search_facets::{FacetButtonStrip}, suspend_boundary::SuspendWrapper}, routes::Route};


#[component]
pub fn SearchInputTopBar(original_query: ReadSignal<SearchQuery>) -> Element {
    let mut modified_search_query = use_signal(|| original_query.read().clone());
    // when url changes (the read signal given to us), we need to update the signals, as they are not reset by navigation.
    use_effect(move || {
        let new_query = original_query.read().clone();
        // orig_query.set(new_query.clone());
        modified_search_query.set(new_query);
    });
    let query_has_changed = use_memo(move || modified_search_query.read().clone() != original_query.read().clone());
    let search_button_color = use_memo(move || if query_has_changed() { "blue" } else { "#6B7280" });
    let trigger_search = move |_: ()| {
        navigator().push(Route::search_page_from_query(modified_search_query.read().clone()));
    };
    let search_oninput = move |event: Event<FormData>| {
        let new_q = event.value();
        modified_search_query.write().query_string = new_q;
    };
    let search_onkeydown = move |event: Event<KeyboardData>| {
        if event.key() == Key::Enter {
            trigger_search(());
        }
    };
    rsx! {
        div {
            id: "x-search-input-search-box",
            style: "
                display:flex;
                align-items:center;
                gap: 16px;
                padding: 16px;
                border-bottom: 1px;
                background-color: white;
                border-radius: 9999px;
                padding: 10px 14px;
                height: 44px;
                color: #111827;
                border: 1px solid rgba(101, 101, 101, 0.8);
                width: 500px;
                margin-left: 16px;

            ",

            button {
                style: "
                    border: none;
                    background: none;
                    cursor: pointer;
                ",
                onclick: move |_| {
                    trigger_search(())
                },
                Icon { icon: MdSearch, style: "width: 20px; height: 20px; color:{search_button_color()};" }
            }
            input {
                r#type: "text",
                placeholder: "Search in knowledgebase",
                style: "
                    flex:1;
                    border: none;
                    outline: none;
                    background: transparent;
                    color: #111827;
                    font-size: 20px;
                    font-weight: 400;
                    font-family: Roboto, sans-serif;
                ",
                value: "{modified_search_query.read().query_string}",
                oninput: search_oninput,
                onkeydown: search_onkeydown,
            }
        }
        FacetButtonStrip{original_query, modified_search_query, trigger_search}
    }
}
