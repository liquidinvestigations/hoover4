//! "Search in conversation" bar, mirrors the find-box chrome of the document preview. The input
//! is at most 350 px wide, and the counter and the buttons follow it. A board explore chat
//! shows a link back to its board at the right end of the row.

use dioxus::prelude::*;

use crate::routes::Route;

#[component]
pub fn ConversationFindBar(
    query: Signal<String>,
    match_index: Signal<usize>,
    match_count: Signal<usize>,
    /// The board of a board explore chat, with the chat's intent selected.
    #[props(default)]
    board: Option<Route>,
) -> Element {
    let count = *match_count.read();
    let idx = *match_index.read();
    let display_idx = if count == 0 { 0 } else { idx + 1 };

    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 8px; padding: 10px 14px; \
                    border-bottom: 1px solid; border-bottom-color: var(--x-border); background: #F8FCFF; flex-shrink: 0;",
            input {
                r#type: "text",
                placeholder: "Search in conversation",
                style: "flex: 0 1 350px; min-width: 0; border: 1px solid rgba(0,0,0,0.35); border-radius: 14px; \
                        padding: 8px 12px; font-size: var(--x-text-md); outline: none; background: white;",
                value: "{query}",
                oninput: move |e| {
                    query.set(e.value());
                    match_index.set(0);
                },
            }
            span {
                style: "font-size: var(--x-text-sm); color: var(--x-ink-muted); min-width: 42px; text-align: center;",
                "{display_idx}/{count}"
            }
            button {
                style: "border: 1px solid; border-color: var(--x-border); background: white; border-radius: 6px; \
                        width: 28px; height: 28px; cursor: pointer;",
                title: "Previous match",
                disabled: count == 0,
                onclick: move |_| {
                    if count == 0 {
                        return;
                    }
                    let next = if idx == 0 { count - 1 } else { idx - 1 };
                    match_index.set(next);
                },
                "\u{25b2}"
            }
            button {
                style: "border: 1px solid; border-color: var(--x-border); background: white; border-radius: 6px; \
                        width: 28px; height: 28px; cursor: pointer;",
                title: "Next match",
                disabled: count == 0,
                onclick: move |_| {
                    if count == 0 {
                        return;
                    }
                    match_index.set((idx + 1) % count);
                },
                "\u{25bc}"
            }
            span { style: "flex: 1;" }
            if let Some(route) = board {
                Link {
                    class: "x-chat-board-link",
                    to: route,
                    style: "color: var(--x-link); text-decoration: none; font-size: var(--x-text-sm); white-space: nowrap;",
                    "Investigation Board"
                }
            }
        }
    }
}
