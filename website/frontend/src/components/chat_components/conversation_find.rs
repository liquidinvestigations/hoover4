//! "Search in conversation" bar — mirrors the find-box chrome of the document preview.

use dioxus::prelude::*;

#[component]
pub fn ConversationFindBar(
    query: Signal<String>,
    match_index: Signal<usize>,
    match_count: Signal<usize>,
) -> Element {
    let count = *match_count.read();
    let idx = *match_index.read();
    let display_idx = if count == 0 { 0 } else { idx + 1 };

    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 8px; padding: 10px 14px; \
                    border-bottom: 1px solid #E5E7EB; background: #F8FCFF; flex-shrink: 0;",
            input {
                r#type: "text",
                placeholder: "Search in conversation",
                style: "flex: 1; border: 1px solid rgba(0,0,0,0.35); border-radius: 14px; \
                        padding: 8px 12px; font-size: 14px; outline: none; background: white;",
                value: "{query}",
                oninput: move |e| {
                    query.set(e.value());
                    match_index.set(0);
                },
            }
            span {
                style: "font-size: 13px; color: #64748B; min-width: 42px; text-align: center;",
                "{display_idx}/{count}"
            }
            button {
                style: "border: 1px solid #E5E7EB; background: white; border-radius: 6px; \
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
                style: "border: 1px solid #E5E7EB; background: white; border-radius: 6px; \
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
        }
    }
}
