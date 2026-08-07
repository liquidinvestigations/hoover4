//! The result-order control: a button that names the current key and a glyph that flips
//! the direction without opening anything.
//!
//! The direction glyph is a control, not a decoration. The menu has four keys and no
//! direction affordance, so if the glyph did not toggle there would be no way to ask for
//! "oldest first" at all.

use common::search_query::{SearchQuery, SortKey, SortSpec};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        md_content_icons::MdSort,
        md_navigation_icons::{MdArrowDownward, MdArrowUpward, MdCheck},
    },
};

const MENU_STYLE: &str = "
    position: absolute;
    top: 46px;
    right: 0px;
    min-width: 220px;
    background: white;
    border: 1px solid rgba(0,0,0,0.25);
    border-radius: 10px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.18);
    z-index: 1200;
    padding: 6px 0;
";

const MENU_ITEM_STYLE: &str = "
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 14px;
    font-size: 16px;
    line-height: 22px;
    cursor: pointer;
    width: 100%;
    border: none;
    background: none;
    text-align: left;
";

const BUTTON_STYLE: &str = "
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 42px;
    padding: 0 12px;
    border-radius: 100px;
    background: white;
    cursor: pointer;
    font-size: 15px;
    line-height: 22px;
    white-space: nowrap;
";

#[component]
pub fn SortControl(query: Signal<SearchQuery>) -> Element {
    let mut menu_open = use_signal(|| false);

    // The spec the UI shows is the RESOLVED one: with no query string, Relevance is not
    // a valid order and the server would silently sort by date anyway. Showing "Sort"
    // while the results come back date-ordered is the confusing half of that.
    let effective = use_memo(move || {
        let q = query.read();
        q.sort.resolved(&q.query_string)
    });
    let relevance_available = use_memo(move || !query.read().query_string.trim().is_empty());
    let is_default = use_memo(move || query.read().sort == SortSpec::default());

    let label = use_memo(move || {
        if is_default() {
            "Sort".to_string()
        } else {
            format!("Sort: {}", effective().key.label())
        }
    });

    let direction_tooltip = use_memo(move || {
        if effective().desc {
            "Descending — click for ascending"
        } else {
            "Ascending — click for descending"
        }
    });

    let mut set_key = move |key: SortKey| {
        let mut q = query.write();
        // A new key keeps a sensible default direction: newest/biggest first for the
        // numeric keys, A→Z for the name.
        q.sort = SortSpec { key, desc: !matches!(key, SortKey::Name) };
        menu_open.set(false);
    };

    rsx! {
        div {
            style: "position: relative; display: inline-flex; align-items: center;",

            button {
                style: "{BUTTON_STYLE} border: 1px solid rgba(0,0,0,0.35);",
                class: "hoover4-hover-shadow-background",
                title: "Change the order of the results",
                onclick: move |_| {
                    let open = *menu_open.read();
                    menu_open.set(!open);
                },
                Icon { icon: MdSort, style: "width: 20px; height: 20px; color: rgba(0,0,0,0.8);" }
                "{label()}"
            }

            // Direction toggle. Separate button so a click here never opens the menu.
            button {
                style: "{BUTTON_STYLE} border: none; padding: 0 8px;",
                class: "hoover4-hover-shadow-background",
                title: "{direction_tooltip}",
                onclick: move |event: Event<MouseData>| {
                    event.stop_propagation();
                    let mut q = query.write();
                    let current = q.sort.resolved(&q.query_string);
                    q.sort = SortSpec { key: current.key, desc: !current.desc };
                },
                if effective().desc {
                    Icon { icon: MdArrowDownward, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.8);" }
                } else {
                    Icon { icon: MdArrowUpward, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.8);" }
                }
            }

            if *menu_open.read() {
                // Click-away layer, below the menu and above everything else.
                div {
                    style: "position: fixed; inset: 0; z-index: 1100;",
                    onclick: move |_| menu_open.set(false),
                }
                div {
                    style: "{MENU_STYLE}",
                    for key in SortKey::ALL {
                        {
                            let enabled = key != SortKey::Relevance || relevance_available();
                            let selected = effective().key == key;
                            // rsx! interpolation takes an expression, not a block.
                            let cursor = if enabled { "pointer" } else { "not-allowed" };
                            let colour = if enabled { "rgb(17,24,39)" } else { "rgba(17,24,39,0.4)" };
                            let tooltip = if enabled { "" } else { "There is no relevance without a query" };
                            rsx! {
                                button {
                                    key: "{key:?}",
                                    class: if enabled { "x-facet-list-item" } else { "" },
                                    style: "{MENU_ITEM_STYLE} cursor: {cursor}; color: {colour};",
                                    title: "{tooltip}",
                                    disabled: !enabled,
                                    onclick: move |_| { if enabled { set_key(key); } },
                                    // Fixed-width slot so the labels line up whether or
                                    // not the check is there.
                                    div {
                                        style: "width: 20px; display: flex; align-items: center; justify-content: center; flex-shrink: 0;",
                                        if selected {
                                            Icon { icon: MdCheck, style: "width: 18px; height: 18px; color: rgba(243,140,104,0.95);" }
                                        }
                                    }
                                    "{key.label()}"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
