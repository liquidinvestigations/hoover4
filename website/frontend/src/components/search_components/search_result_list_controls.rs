//! Controls for search result list settings.

use common::search_const::{MAX_PAGINATION_DOCUMENT_LIMIT, PAGE_SIZE};
use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::md_navigation_icons::{MdArrowBack, MdArrowDownward, MdArrowForward, MdArrowLeft, MdArrowRight, MdArrowUpward}};
use dioxus_primitives::{ContentAlign, ContentSide};

use crate::{components::hover_card::{HoverCard, HoverCardContent, HoverCardTrigger}, components::search_components::search_panel_left_view::SearchResultsState};

#[component]
pub fn SearchResultListControls() -> Element {
    rsx! {
        div {
            id: "x-search-panel-left-title-row",
            style: "
                display: flex;
                flex-direction: row;
                gap: 6px;
                padding: 7px;
                margin: 1px;
                height: 56px;
                width: 100%;
            ",
            h1 {
                style: "font-size: 20px; font-weight: 300; color:rgb(75, 87, 112);  border-bottom: 1px solid rgb(75, 87, 112);",
                SearchForResultsHitCountString { }
            }
            // empty space
            div {
                style: "
                flex-grow: 1;"
            }
            // pagination buttons
            PaginationControls {}
        }
    }
}


#[component]
fn PaginationControls() -> Element {

    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 16px;
            ",

            ControlNextPrevDocument {}

            ControlNextPrevPage {}
        }
    }
}


#[component]
fn ControlNextPrevDocument() -> Element {
    let search_results_state = use_context::<SearchResultsState>();
    let hit_count = search_results_state.hit_count;
    let hit_count = use_memo(move || hit_count.read().cloned().unwrap_or(Ok(0)).unwrap_or(0).min(MAX_PAGINATION_DOCUMENT_LIMIT));
    let selected_result_hash = use_memo(move || search_results_state.selected_result_hash.read().clone());
    let result_hashes = use_memo(move || {
        let search_result = search_results_state.search_result.read();
        let search_result = search_result.as_ref();
        let Some(Ok(search_result)) = search_result else { return Vec::new() };
        return search_result.results.iter().map(|result| result.document_identifier()).collect::<Vec<_>>();
    });
    let current_list_position = use_memo(move || {
        //
        let result_hashes = result_hashes();
        let Some(selected_result_hash) = selected_result_hash() else { return None };
        result_hashes.iter().position(|hash| hash == &selected_result_hash).map(|i| i as u64)
    });

    let total_result_index = use_memo(move || {
        let current_page = *search_results_state.current_search_result_page.read();
        let idx = current_list_position();
        idx.map(|i| i + 1 + current_page * PAGE_SIZE)
    });

    let total_result_index_txt = use_memo(move || {
        let idx = total_result_index();
        idx.map(|idx| format!("{}", idx)).unwrap_or("-".to_string())
    });

    let can_go_to_previous_result = use_memo(move || {
        let idx = total_result_index();
        idx.map(|idx| idx > 1).unwrap_or(false)
    });
    let can_go_to_next_result = use_memo(move || {
        let idx = total_result_index();
        idx.map(|idx| idx < *hit_count.read()).unwrap_or(false)
    });

    let go_previous = move |_e| {
        let current_list_position = current_list_position();
        let Some(current_list_position) = current_list_position else {
            return;
        };
        if current_list_position == 0 {
            // fetch previous page and id
            let search_result = search_results_state.search_result.read();
            let search_result = search_result.as_ref();
            if let Some(Ok(search_result)) = search_result {
                if let Some(prev_hash) = search_result.prev_hash.clone() {
                    // fetch previous page and id
                    if *search_results_state.current_search_result_page.read() > 0 {
                        search_results_state.set_selected_result_hash_and_page.call((Some(prev_hash.clone()), *search_results_state.current_search_result_page.read() - 1));
                    }
                }
            }
        } else {
            let result_hashes = result_hashes();
            let prev_hash = &result_hashes[current_list_position as usize - 1];
            search_results_state.set_selected_result_hash.call(Some(prev_hash.clone()));
        }
    };

    let go_next = move |_e| {
        let current_list_position = current_list_position();
        let Some(current_list_position) = current_list_position else {
            return;
        };
        let result_hashes = result_hashes();
        if current_list_position == result_hashes.len() as u64 - 1 {
            let search_result = search_results_state.search_result.read();
        let search_result = search_result.as_ref();
        if let Some(Ok(next_hash)) = search_result {
            if let Some(next_hash) = next_hash.next_hash.clone() {
                // fetch next page and id
                search_results_state.set_selected_result_hash_and_page.call((Some(next_hash.clone()), *search_results_state.current_search_result_page.read() + 1));
            }
        }
        } else {
            let next_hash = &result_hashes[current_list_position as usize + 1];
            search_results_state.set_selected_result_hash.call(Some(next_hash.clone()));
        }
    };
    rsx! {
        // prev result
        NavigationButton {
            icon: MdArrowUpward,
            label: "Previous Result",
            disabled: !can_go_to_previous_result(),
            onclick: go_previous
        }
        // current result counter
        div {
            style: "
                font-size: 20px;
                line-height: 28px;
                font-weight: 400;
            ",
            "{total_result_index_txt()} / {*hit_count.read()}"
        }
        // next result
        NavigationButton {
            icon: MdArrowDownward,
            label: "Next Result",
            disabled: !can_go_to_next_result(),
            onclick: go_next
        }
    }
}

#[component]
fn ControlNextPrevPage() -> Element {
    let search_results_state = use_context::<SearchResultsState>();
    let hit_count = search_results_state.hit_count;
    let search_result_page = search_results_state.current_search_result_page;
    let set_current_page = search_results_state.set_current_page;

    let hit_count = use_memo(move || hit_count.read().cloned().unwrap_or(Ok(0)).unwrap_or(0).min(MAX_PAGINATION_DOCUMENT_LIMIT));
    let max_pages = use_memo(move || {
        let hit_count = *hit_count.read();
        let page_count = hit_count / common::search_const::PAGE_SIZE;
        if hit_count > 0 {
            page_count + 1
        } else {
            0
        }
    });
    let selected_page = use_memo(move || {
        let current_page = *search_result_page.read()+1;
        if current_page > *max_pages.read() {
            *max_pages.read()
        } else {
            current_page
        }
    });
    let can_go_to_previous_page = use_memo(move || {
        selected_page() > 1
    });
    let can_go_to_next_page = use_memo(move || {
        selected_page() < *max_pages.read()
    });

    rsx! {
        // prev page
        NavigationButton {
            icon: MdArrowBack,
            label: "Previous Page",
            disabled: !can_go_to_previous_page(),
            onclick: move |_| {set_current_page(search_result_page() - 1);}
        }
        // current page counter
        div {
            style: "
                font-size: 16px;
                line-height: 21px;
                font-weight: 400;
                background-color: white;
                border-radius: 2px;
                border-left: 1px solid rgba(0,0,0,0.1);
                border-right: 1px solid rgba(0,0,0,0.1);
                padding: 4px 26px;
                margin-left: -28px;
                margin-right: -28px;
                align-items: center;
                align-content: center;
            ",
            "{selected_page()}"
            span {
                style: "color: rgba(0,0,0,0.5);",
                "/{*max_pages.read()}"
            }
        }
        // next page
        NavigationButton {
            icon: MdArrowForward,
            label: "Next Page",
            disabled: !can_go_to_next_page(),
            onclick: move |_| {
                // dioxus::logger::tracing::info!("NEXT PAGE!");
                set_current_page(search_result_page() + 1);
            }
        }
    }
}

#[component]
pub fn NavigationButton<I: dioxus_free_icons::IconShape + Clone + PartialEq + 'static>(icon: I, label: String, disabled: ReadSignal<bool>, onclick: Callback<()>) -> Element {
    let btn_color = use_memo(move || if *disabled.read() { "rgba(0,0,0,0.3)" } else { "rgba(0,0,0,1)" });
    let tooltip_color = use_memo(move || if *disabled.read() { "rgba(0,0,0,0.6)" } else { "rgba(0,0,0,1)" });
    let btn_cursor = use_memo(move || if *disabled.read() { "not-allowed" } else { "pointer" });
    rsx! {
        HoverCard {
            HoverCardTrigger {
                button {
                    disabled: *disabled.read(),
                    style: "
                        width: 32px;
                        height: 32px;
                        background: white;
                        border-radius: 8px;
                        padding: 4px;
                        box-shadow: 0 2px 4px 0 rgba(0, 0, 0, 0.16);
                        cursor: {btn_cursor};
                    ",
                    onclick: move |_| {
                        if !*disabled.read() {
                            onclick(());
                        }
                    },
                    Icon { icon: icon, style: "width: 26px; height: 26px; color: {btn_color};" }
                },

            },
            HoverCardContent {
                side: ContentSide::Bottom,
                align: ContentAlign::Center,
                div {
                    style: "
                        color:{tooltip_color};
                        background-color:white;
                        padding:10px;
                        border-radius:5px;
                        border: 1px solid black;
                        width: fit-content;
                    ",
                    "{label}",
                }
            }
        }
    }
}


#[component]
fn SearchForResultsHitCountString(hit_count: ReadSignal<Option<Result<u64, ServerFnError>>>) -> Element {

    let search_results_state = use_context::<SearchResultsState>();
    let hit_count = search_results_state.hit_count;


    match hit_count.read().cloned() {
        Some(Err(e)) => return rsx! { "! error: {e:?}" },
        Some(Ok(s)) => return rsx! { "{s} documents found" },
        None => return rsx! {"..."}
    };
}