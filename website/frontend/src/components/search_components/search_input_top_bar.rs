//! Search input and controls in the top bar.
//!
//! The pill strip is gone: one **Filter** button opens a modal holding every category,
//! one **Sort** control sets the order, and the chip row underneath says what is
//! currently narrowing the results. See `filter_modal.rs` for why.

use crate::{
    components::search_components::{
        filter_modal::{FilterCategory, FilterChips, FilterModal},
        sort_control::SortControl,
    },
    routes::Route,
};
use common::search_query::SearchQuery;
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{md_action_icons::MdSearch, md_content_icons::MdFilterList},
};

const CONTROL_BUTTON_STYLE: &str = "
    display: inline-flex; align-items: center; gap: 6px;
    height: 42px; padding: 0 14px;
    border: 1px solid rgba(0,0,0,0.35); border-radius: 100px;
    background: white; cursor: pointer;
    font-size: 15px; line-height: 22px; white-space: nowrap;
";

#[component]
pub fn SearchInputTopBar(original_query: ReadSignal<SearchQuery>) -> Element {
    let mut modified_search_query = use_signal(|| original_query.read().clone());
    // when url changes (the read signal given to us), we need to update the signals, as they are not reset by navigation.
    use_effect(move || {
        let new_query = original_query.read().clone();
        modified_search_query.set(new_query);
    });
    let query_has_changed =
        use_memo(move || modified_search_query.read().clone() != original_query.read().clone());
    let search_button_color = use_memo(move || {
        if query_has_changed() {
            "blue"
        } else {
            "#6B7280"
        }
    });
    let trigger_search = move |_: ()| {
        navigator().push(Route::search_page_from_query(
            modified_search_query.read().clone(),
        ));
    };
    let apply_filter_button_background = use_memo(move || {
        if query_has_changed() {
            "rgba(0,0,255,1.0)"
        } else {
            "rgba(137,191,255,1.0)"
        }
    });
    // `disabled` is not a cursor keyword, so the old value fell back to `auto` and the
    // button pointed at a live control with nothing to apply.
    let apply_filter_button_cursor = use_memo(move || {
        if query_has_changed() {
            "pointer"
        } else {
            "default"
        }
    });
    let apply_filter_button_opacity = use_memo(move || if query_has_changed() { "1" } else { "0.6" });
    let search_oninput = move |event: Event<FormData>| {
        let new_q = event.value();
        modified_search_query.write().query_string = new_q;
    };
    let search_onkeydown = move |event: Event<KeyboardData>| {
        if event.key() == Key::Enter {
            trigger_search(());
        }
    };

    // `None` means closed; `Some(category)` both opens the modal and selects its pane, so
    // a chip click can land on the pane that owns it.
    let mut open_category = use_signal(|| None::<FilterCategory>);
    let active_filter_count = use_memo(move || {
        let q = modified_search_query.read();
        FilterCategory::ALL.iter().filter(|c| c.is_active(&q)).count()
    });

    rsx! {
        div {
            style: "display: flex; flex-direction: column; width: 100%; min-width: 0;",

            div {
                style: "display: flex; align-items: center; flex-wrap: wrap; gap: 10px; width: 100%; min-width: 0;",

                div {
                    id: "x-search-input-search-box",
                    style: "
                        display:flex;
                        align-items:center;
                        gap: 16px;
                        background-color: white;
                        border-radius: 9999px;
                        padding: 10px 14px;
                        height: 44px;
                        color: #111827;
                        border: 1px solid rgba(101, 101, 101, 0.8);
                        width: 500px;
                        max-width: 100%;
                        margin-left: 16px;
                    ",

                    button {
                        style: "border: none; background: none; cursor: pointer;",
                        onclick: move |_| trigger_search(()),
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
                            min-width: 0;
                        ",
                        value: "{modified_search_query.read().query_string}",
                        oninput: search_oninput,
                        onkeydown: search_onkeydown,
                    }
                }

                // Enabled only when something is pending: the whole toolbar edits a
                // pending query, so this is the one place that says whether anything is
                // waiting to be applied.
                button {
                    style: "
                        font-size: 15px; font-weight: 700; font-family: Roboto, sans-serif;
                        background-color: {apply_filter_button_background()};
                        color:white; border: none;
                        border-radius:100px; height: 42px; padding: 0 16px;
                        cursor: {apply_filter_button_cursor()};
                        opacity: {apply_filter_button_opacity()};
                    ",
                    disabled: !query_has_changed(),
                    title: if query_has_changed() { "Apply the pending changes" } else { "Nothing to apply" },
                    onclick: move |event: Event<MouseData>| {
                        event.prevent_default();
                        event.stop_propagation();
                        trigger_search(());
                    },
                    "Apply Filters"
                }

                button {
                    id: "x-search-open-filters",
                    style: "{CONTROL_BUTTON_STYLE}",
                    class: "hoover4-hover-shadow-background",
                    title: "Open all filters",
                    onclick: move |_| open_category.set(Some(FilterCategory::Collections)),
                    Icon { icon: MdFilterList, style: "width: 20px; height: 20px; color: rgba(0,0,0,0.8);" }
                    if active_filter_count() > 0 {
                        "Filter ({active_filter_count()})"
                    } else {
                        "Filter"
                    }
                }

                SortControl { original_query, query: modified_search_query }
            }

            FilterChips {
                query: modified_search_query,
                on_open: Callback::new(move |category: FilterCategory| {
                    open_category.set(Some(category));
                }),
            }
        }

        FilterModal {
            original_query,
            pending: modified_search_query,
            open_category,
            on_apply: Callback::new(move |_| trigger_search(())),
        }
    }
}
