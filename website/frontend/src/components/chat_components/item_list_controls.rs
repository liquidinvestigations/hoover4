//! The controls of the chat history and the board list: the search, the group filter, the
//! time order, the creator filter, the pager, the match highlight and the running chip.
//!
//! Each control gives the changed query to `on_change`. The page writes the query into its
//! route, and the route change reads the page again. A change of a filter opens page 1.

use common::item_list::{page_count, ItemListQuery};
use common::text_highlight::case_insensitive_parts;
use dioxus::prelude::*;

use crate::components::admin_components::{INPUT, LABEL, SELECT};
use crate::tr;

const BAR: &str = "display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 15px;";
const BUTTON: &str = "background-color: white; border: 1px solid; border-color: var(--x-border); \
     border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: var(--x-text-sm); color: var(--x-ink);";

/// The search, the group filter and the time order. `mine` and `boards` show the two chat
/// history checkboxes.
#[component]
pub fn ItemListBar(
    query: ItemListQuery,
    groups: Vec<String>,
    show_chat_filters: bool,
    on_change: EventHandler<ItemListQuery>,
) -> Element {
    let mut text = use_signal(|| query.search.clone());
    let submitted = query.search.clone();
    // A route change from outside the bar, for example the Back button, shows its search.
    use_effect(use_reactive!(|submitted| text.set(submitted)));
    let changed = {
        let query = query.clone();
        move |edit: &dyn Fn(&mut ItemListQuery)| {
            let mut next = query.clone();
            edit(&mut next);
            next.page = 1;
            next
        }
    };
    let on_search = {
        let changed = changed.clone();
        move |e: FormEvent| {
            e.prevent_default();
            let value = text.peek().clone();
            on_change.call(changed(&move |q| q.search = value.clone()));
        }
    };
    let on_group = {
        let changed = changed.clone();
        move |e: FormEvent| {
            let value = e.value();
            on_change.call(changed(&move |q| q.group = value.clone()));
        }
    };
    let on_sort = {
        let changed = changed.clone();
        move |e: FormEvent| {
            let oldest = e.value() == "oldest";
            on_change.call(changed(&move |q| q.oldest_first = oldest));
        }
    };
    let on_mine = {
        let changed = changed.clone();
        move |e: FormEvent| {
            let on = e.checked();
            on_change.call(changed(&move |q| q.mine = on));
        }
    };
    let on_boards = {
        let changed = changed.clone();
        move |e: FormEvent| {
            let on = e.checked();
            on_change.call(changed(&move |q| q.include_boards = on));
        }
    };

    rsx! {
        div { class: "x-item-list-bar", style: BAR,
            form { style: "display: flex; gap: 6px; align-items: center;", onsubmit: on_search,
                input {
                    class: "x-item-list-search",
                    r#type: "search",
                    style: "{INPUT} min-width: 240px;",
                    placeholder: tr!("item-list-search-titles-and-summaries"),
                    aria_label: tr!("item-list-search-titles-and-summaries"),
                    value: "{text}",
                    oninput: move |e: FormEvent| text.set(e.value()),
                }
                button { r#type: "submit", style: BUTTON, {tr!("item-list-search")} }
            }
            label { style: LABEL,
                {tr!("item-list-group")}
                select { class: "x-item-list-group", style: SELECT, onchange: on_group,
                    option { value: "", selected: query.group.is_empty(), {tr!("item-list-all-groups")} }
                    for g in groups.iter() {
                        option { key: "{g}", value: "{g}", selected: *g == query.group, "{g}" }
                    }
                }
            }
            label { style: LABEL,
                {tr!("item-list-sort")}
                select { class: "x-item-list-sort", style: SELECT, onchange: on_sort,
                    option { value: "", selected: !query.oldest_first, {tr!("item-list-newest-first")} }
                    option { value: "oldest", selected: query.oldest_first, {tr!("item-list-oldest-first")} }
                }
            }
            if show_chat_filters {
                label { style: LABEL,
                    input { class: "x-item-list-mine", r#type: "checkbox", checked: query.mine, onchange: on_mine }
                    {tr!("item-list-chats-started-by-me")}
                }
                label { style: LABEL,
                    input { class: "x-history-show-boards", r#type: "checkbox", checked: query.include_boards, onchange: on_boards }
                    {tr!("ai-chat-history-show-board-chats")}
                }
            }
        }
    }
}

/// The count of matches and the page buttons.
#[component]
pub fn ItemPager(query: ItemListQuery, total: u64, on_change: EventHandler<ItemListQuery>) -> Element {
    let pages = page_count(total);
    let page = query.page.clamp(1, pages);
    let go = move |to: u32| {
        let mut next = query.clone();
        next.page = to;
        on_change.call(next);
    };
    let go_back = go.clone();
    let go_on = go;
    rsx! {
        div { class: "x-item-pager", style: "display: flex; gap: 12px; align-items: center; margin-top: 15px;",
            span { style: "font-size: var(--x-text-sm); color: var(--x-ink-muted);",
                {tr!("item-list-matches", total: total.to_string())}
            }
            if pages > 1 {
                button {
                    class: "x-item-pager-previous",
                    style: BUTTON,
                    disabled: page <= 1,
                    onclick: move |_| go_back(page - 1),
                    {tr!("item-list-previous")}
                }
                span { style: "font-size: var(--x-text-sm); color: var(--x-ink);",
                    {tr!("item-list-page-of", page: page.to_string(), pages: pages.to_string())}
                }
                button {
                    class: "x-item-pager-next",
                    style: BUTTON,
                    disabled: page >= pages,
                    onclick: move |_| go_on(page + 1),
                    {tr!("item-list-next")}
                }
            }
        }
    }
}

/// `text` with each case-insensitive match of `needle` marked.
#[component]
pub fn Highlighted(text: String, needle: String) -> Element {
    let needle = needle.trim().to_string();
    if needle.is_empty() {
        return rsx! { "{text}" };
    }
    rsx! {
        for (i, (part, hit)) in case_insensitive_parts(&text, &needle).into_iter().enumerate() {
            if hit {
                mark { key: "{i}", class: "x-item-list-match", style: "background-color: #FEF08A; color: inherit; border-radius: 2px;", "{part}" }
            } else {
                span { key: "{i}", "{part}" }
            }
        }
    }
}

/// The chip of a chat whose turn runs now. It takes the place of the delete button.
#[component]
pub fn RunningChip() -> Element {
    rsx! {
        span {
            class: "x-chat-running",
            style: "flex-shrink: 0; font-size: var(--x-text-xs); font-weight: 600; color: var(--x-link); \
                    background-color: #EEF2FF; border-radius: 999px; padding: 3px 10px; white-space: nowrap;",
            {tr!("item-list-running")}
        }
    }
}
