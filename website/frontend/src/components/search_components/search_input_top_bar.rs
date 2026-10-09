//! Search input and controls in the top bar.
//!
//! The pill strip is gone: one **Filter** button opens a modal holding every category,
//! one **Sort** control sets the order, and the chips after Sort say what is currently
//! narrowing the results. See `filter_modal.rs` for why.

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
    icons::md_content_icons::MdFilterList,
};

const CONTROL_BUTTON_STYLE: &str = "
    display: inline-flex; align-items: center; gap: 4px;
    height: var(--x-control-height); padding: 0 11px;
    border: 1px solid rgba(0,0,0,0.35); border-radius: 100px;
    background: white; cursor: pointer;
    font-size: var(--x-text-body); line-height: var(--x-line-body); white-space: nowrap;
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
    let trigger_search = move |_: ()| {
        navigator().push(Route::search_page_from_query(
            modified_search_query.read().clone(),
        ));
    };
    let search_button_background = use_memo(move || {
        if query_has_changed() {
            "rgba(0,0,255,1.0)"
        } else {
            "rgba(137,191,255,1.0)"
        }
    });
    // `disabled` is not a cursor keyword, so the old value fell back to `auto` and the
    // button pointed at a live control with nothing to search for.
    let search_button_cursor = use_memo(move || {
        if query_has_changed() {
            "pointer"
        } else {
            "default"
        }
    });
    let search_button_opacity = use_memo(move || if query_has_changed() { "1" } else { "0.6" });
    let input_value = use_memo(move || modified_search_query.read().query_string.clone());

    // `None` means closed; `Some(category)` both opens the modal and selects its pane, so
    // a chip click can land on the pane that owns it.
    let mut open_category = use_signal(|| None::<FilterCategory>);
    let active_filter_count = use_memo(move || {
        let q = modified_search_query.read();
        FilterCategory::ALL.iter().filter(|c| c.is_active(&q)).count()
    });

    rsx! {
        // One wrapping row for the controls and the chips, so the chips follow Sort and
        // wrap under the controls. `FilterChips` limits them to one row more than the
        // controls use. The row does not clip its overflow, because the Sort menu is
        // positioned inside it.
        div {
            id: "x-search-toolbar-row",
            style: "display: flex; align-items: center; flex-wrap: wrap; gap: 8px 10px; width: 100%; min-width: 0;",

            div {
                id: "x-search-input-search-box",
                style: "width: 500px; max-width: 100%; margin-left: 16px;",
                crate::components::search_input::SearchInput {
                    value: input_value,
                    placeholder: "Search in knowledgebase",
                    on_change: move |value: String| modified_search_query.write().query_string = value,
                    on_submit: move |_| trigger_search(()),
                }
            }

            // Enabled only when something is pending: the whole toolbar edits a
            // pending query, so this is the one place that says whether anything is
            // waiting to be applied.
            button {
                style: "
                    font-size: 15px; line-height: 23px; font-weight: 700; font-family: Roboto, sans-serif;
                    background-color: {search_button_background()};
                    color:white; border: none;
                    border-radius:100px; height: 34px; padding: 0 15px;
                    cursor: {search_button_cursor()};
                    opacity: {search_button_opacity()};
                ",
                disabled: !query_has_changed(),
                title: if query_has_changed() { "Search with the pending changes" } else { "Nothing new to search for" },
                onclick: move |event: Event<MouseData>| {
                    event.prevent_default();
                    event.stop_propagation();
                    trigger_search(());
                },
                "Search"
            }

            button {
                id: "x-search-open-filters",
                style: "{CONTROL_BUTTON_STYLE}",
                class: "hoover4-hover-shadow-background",
                title: "Open all filters",
                onclick: move |_| open_category.set(Some(FilterCategory::Collections)),
                Icon { icon: MdFilterList, style: "width: 19px; height: 19px; color: rgba(0,0,0,0.8);" }
                if active_filter_count() > 0 {
                    "Filter ({active_filter_count()})"
                } else {
                    "Filter"
                }
            }

            SortControl {
                original_query,
                query: modified_search_query,
                on_commit: Callback::new(move |_| trigger_search(())),
            }

            // Directly after Sort: the chip row measures the row of the element before it.
            FilterChips {
                query: modified_search_query,
                on_open: Callback::new(move |category: FilterCategory| {
                    open_category.set(Some(category));
                }),
                on_commit: Callback::new(move |_| trigger_search(())),
            }
        }

        FilterModal {
            pending: modified_search_query,
            open_category,
            on_apply: Callback::new(move |_| trigger_search(())),
        }
    }
}
