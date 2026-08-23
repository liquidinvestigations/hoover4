//! The result-order control: a button that names the applied key and a glyph that flips
//! the direction without opening anything.
//!
//! The direction glyph is a control, not a decoration. The menu has four keys and no
//! direction affordance, so if the glyph did not toggle there would be no way to ask for
//! "oldest first" at all.
//!
//! Picking an order applies it: the control edits the pending query and then runs the
//! search, so the results are in the order the button names by the time the menu closes.
//!
//! This is safe only because every other non-text control in the toolbar does the same.
//! The filter chips commit on removal too. The apply path pushes the WHOLE pending query,
//! so while filters still batched behind `Apply Filters` a sort click would have silently
//! committed filter edits the user had not confirmed. If filter editing is ever put back
//! behind an explicit apply, this must go back with it.
//!
//! The `applied → pending` accent labelling is kept for the window where the search is in
//! flight, and because the search can reject a query and leave the applied order behind.
//! The button names the order the results on screen are actually in; relabelling straight
//! to the new key was the original defect, since it claimed an order the list was not in.

use common::search_query::{SearchQuery, SortKey, SortSpec};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        md_content_icons::MdSort,
        md_navigation_icons::{MdArrowDownward, MdArrowForward, MdArrowUpward, MdCheck},
    },
};

/// The accent the filter modal marks pending/active state with.
const ACCENT: &str = "rgba(243,140,104,0.95)";

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
pub fn SortControl(
    /// The applied query. The order the results on screen are in.
    original_query: ReadSignal<SearchQuery>,
    /// The pending query every control in this toolbar edits.
    query: Signal<SearchQuery>,
    /// Run the search for the order just picked. See the module docs for why this is
    /// safe only while the filter chips commit on edit as well.
    on_commit: Callback<()>,
) -> Element {
    let mut menu_open = use_signal(|| false);

    // The spec the UI shows is the RESOLVED one: with no query string, Relevance is not
    // a valid order and the server would silently sort by date anyway. Showing "Sort"
    // while the results come back date-ordered is the confusing half of that.
    let applied = use_memo(move || {
        let q = original_query.read();
        q.sort.resolved(&q.query_string)
    });
    let effective = use_memo(move || {
        let q = query.read();
        q.sort.resolved(&q.query_string)
    });
    let relevance_available = use_memo(move || !query.read().query_string.trim().is_empty());
    let applied_is_default = use_memo(move || original_query.read().sort == SortSpec::default());

    // Compared after resolution, so a spec that only differs in a field the server would
    // ignore anyway does not advertise a change nobody would see.
    let key_pending = use_memo(move || effective().key != applied().key);
    let direction_pending = use_memo(move || effective().desc != applied().desc);
    let is_pending = use_memo(move || key_pending() || direction_pending());

    let label = use_memo(move || {
        if applied_is_default() {
            "Sort".to_string()
        } else {
            format!("Sort: {}", applied().key.label())
        }
    });

    let button_tooltip = use_memo(move || {
        if is_pending() {
            format!(
                "Results are ordered by {}. Press Apply Filters to switch to {}.",
                applied().key.label(),
                effective().key.label()
            )
        } else {
            "Change the order of the results".to_string()
        }
    });

    let direction_tooltip = use_memo(move || {
        let base = if effective().desc {
            "Descending — click for ascending"
        } else {
            "Ascending — click for descending"
        };
        if direction_pending() {
            format!("{base}. Not applied yet — press Apply Filters.")
        } else {
            base.to_string()
        }
    });
    // The glyph follows what this button EDITS, which is the pending query; the accent
    // says the results are not in that direction yet.
    let direction_colour = use_memo(move || {
        if direction_pending() { ACCENT } else { "rgba(0,0,0,0.8)" }
    });

    let mut set_key = move |key: SortKey| {
        {
            let mut q = query.write();
            // A new key keeps a sensible default direction: newest/biggest first for the
            // numeric keys, A→Z for the name.
            q.sort = SortSpec { key, desc: !matches!(key, SortKey::Name) };
        }
        menu_open.set(false);
        on_commit.call(());
    };

    rsx! {
        div {
            style: "position: relative; display: inline-flex; align-items: center;",

            button {
                style: "{BUTTON_STYLE} border: 1px solid rgba(0,0,0,0.35);",
                class: "hoover4-hover-shadow-background",
                title: "{button_tooltip()}",
                onclick: move |_| {
                    let open = *menu_open.read();
                    menu_open.set(!open);
                },
                Icon { icon: MdSort, style: "width: 20px; height: 20px; color: rgba(0,0,0,0.8);" }
                "{label()}"
                // The unapplied choice, drawn as the transition it is. Absent while the
                // control and the result list agree, so the button only grows when there
                // is something to apply.
                if key_pending() {
                    Icon { icon: MdArrowForward, style: "width: 16px; height: 16px; color: {ACCENT};" }
                    span { style: "color: {ACCENT};", "{effective().key.label()}" }
                }
            }

            // Direction toggle. Separate button so a click here never opens the menu.
            button {
                style: "{BUTTON_STYLE} border: none; padding: 0 8px;",
                class: "hoover4-hover-shadow-background",
                title: "{direction_tooltip}",
                onclick: move |event: Event<MouseData>| {
                    event.stop_propagation();
                    {
                        let mut q = query.write();
                        let current = q.sort.resolved(&q.query_string);
                        q.sort = SortSpec { key: current.key, desc: !current.desc };
                    }
                    on_commit.call(());
                },
                if effective().desc {
                    Icon { icon: MdArrowDownward, style: "width: 18px; height: 18px; color: {direction_colour()};" }
                } else {
                    Icon { icon: MdArrowUpward, style: "width: 18px; height: 18px; color: {direction_colour()};" }
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
