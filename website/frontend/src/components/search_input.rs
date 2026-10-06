//! Search input with shared submit and clear controls.

use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::{md_action_icons::MdSearch, md_navigation_icons::MdClose}};

#[component]
pub fn SearchInput(
    value: ReadSignal<String>,
    placeholder: String,
    on_change: Callback<String>,
    #[props(default)] on_submit: Callback<()>,
) -> Element {
    rsx! {
        div {
            class: "x-search-input",
            style: "display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; height: 42px; padding: 6px 12px; border: 1px solid #888; border-radius: 24px; background: white;",
            button {
                r#type: "button", aria_label: "Submit search", title: "Submit search",
                style: "background: none; cursor: pointer; flex-shrink: 0;",
                onclick: move |_| on_submit.call(()),
                Icon { icon: MdSearch, style: "width: 20px; height: 20px;" }
            }
            input {
                r#type: "text", placeholder,
                style: "flex: 1; min-width: 0; outline: none; background: transparent; font-size: 16px;",
                value: "{value}",
                oninput: move |event| on_change.call(event.value()),
                onkeydown: move |event| {
                    if event.key() == Key::Enter {
                        event.prevent_default();
                        on_submit.call(());
                    }
                },
            }
            if !value.read().is_empty() {
                button {
                    r#type: "button", aria_label: "Clear search", title: "Clear search",
                    style: "background: none; cursor: pointer; flex-shrink: 0;",
                    onclick: move |_| { on_change.call(String::new()); on_submit.call(()); },
                    Icon { icon: MdClose, style: "width: 18px; height: 18px;" }
                }
            }
        }
    }
}
