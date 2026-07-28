//! Chat composer: textarea, Deep Research / Internet tools checkboxes, submit arrow.
//!
//! Deliberately has **no** file-attachment / paperclip control — documents enter through
//! the processing pipeline, not the chat UI.

use common::chat_types::MAX_MESSAGE_CHARS;
use dioxus::prelude::*;

#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct ComposerOptions {
    pub deep_research: bool,
    pub internet_tools: bool,
}

#[component]
pub fn ChatComposer(
    draft: Signal<String>,
    options: Signal<ComposerOptions>,
    sending: Signal<bool>,
    retry_after_seconds: Signal<Option<u64>>,
    on_submit: EventHandler<()>,
) -> Element {
    let disabled = *sending.read() || retry_after_seconds.read().is_some();

    rsx! {
        div {
            style: "background: white; border: 1px solid #E5E7EB; border-radius: 16px; \
                    padding: 14px 16px; display: flex; flex-direction: column; gap: 10px; \
                    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);",
            textarea {
                style: "width: 100%; resize: none; border: none; outline: none; \
                        font-size: 15px; font-family: inherit; min-height: 56px; \
                        line-height: 1.5; color: #0F172A; background: transparent;",
                rows: 2,
                maxlength: MAX_MESSAGE_CHARS as i64,
                placeholder: "Write a query to send commands to the AI",
                value: "{draft}",
                disabled: disabled,
                oninput: move |e| draft.set(e.value()),
                onkeypress: move |e| {
                    if e.key() == Key::Enter && !e.modifiers().shift() {
                        e.prevent_default();
                        if !disabled {
                            on_submit.call(());
                        }
                    }
                },
            }
            div {
                style: "display: flex; align-items: center; gap: 16px; flex-wrap: wrap;",
                label {
                    style: "display: flex; align-items: center; gap: 6px; font-size: 13px; \
                            color: #475569; cursor: pointer; user-select: none;",
                    input {
                        r#type: "checkbox",
                        checked: options.read().deep_research,
                        disabled: disabled,
                        onchange: move |e| {
                            let mut o = *options.read();
                            o.deep_research = e.checked();
                            options.set(o);
                        },
                    }
                    "Deep Research"
                }
                label {
                    style: "display: flex; align-items: center; gap: 6px; font-size: 13px; \
                            color: #475569; cursor: pointer; user-select: none;",
                    input {
                        r#type: "checkbox",
                        checked: options.read().internet_tools,
                        disabled: disabled,
                        onchange: move |e| {
                            let mut o = *options.read();
                            o.internet_tools = e.checked();
                            options.set(o);
                        },
                    }
                    "Internet tools"
                }
                div { style: "flex: 1;" }
                if let Some(secs) = *retry_after_seconds.read() {
                    span {
                        style: "font-size: 13px; color: #B45309;",
                        "Try again in {secs} s"
                    }
                }
                button {
                    style: {
                        let ready = !draft.read().trim().is_empty() && !disabled;
                        let bg = if ready { "#4F46E5" } else { "#E2E8F0" };
                        let color = if ready { "white" } else { "#94A3B8" };
                        format!(
                            "width: 40px; height: 40px; border-radius: 999px; border: none; \
                             background: {bg}; color: {color}; cursor: {}; font-size: 18px; \
                             display: flex; align-items: center; justify-content: center;",
                            if ready { "pointer" } else { "default" }
                        )
                    },
                    disabled: disabled || draft.read().trim().is_empty(),
                    title: "Send",
                    onclick: move |_| on_submit.call(()),
                    "\u{2191}"
                }
            }
        }
    }
}
