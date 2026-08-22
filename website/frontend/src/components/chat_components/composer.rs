//! Chat composer: textarea, Deep Research / Internet tools checkboxes, submit arrow.
//!
//! Deliberately has **no** file-attachment / paperclip control — documents enter through
//! the processing pipeline, not the chat UI.
//!
//! The two checkboxes disappear from here once the conversation has a turn in it: they
//! are frozen onto the session at that point and shown read-only above the transcript
//! by [`LockedOptionsBar`](super::locked_options::LockedOptionsBar). Leaving an editable
//! control that silently does nothing would be worse than removing it.

use common::chat_types::{ChatOptions, MAX_MESSAGE_CHARS};
use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::md_av_icons::MdStop};

#[component]
pub fn ChatComposer(
    draft: Signal<String>,
    options: Signal<ChatOptions>,
    sending: Signal<bool>,
    retry_after_seconds: Signal<Option<u64>>,
    on_submit: EventHandler<()>,
    /// The stop button, shown in place of send while a turn is in flight.
    on_stop: Option<EventHandler<()>>,
) -> Element {
    // Only a rate-limit lockout disables typing: while a turn streams the user can
    // already draft the next message (the server serialises turns per session).
    let disabled = retry_after_seconds.read().is_some();
    let locked = options.read().locked;

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
                        // `sending` too, not just `disabled`: typing stays enabled while
                        // a turn streams so the next message can be drafted, and without
                        // this an Enter on that draft would be a second send the server
                        // then refuses.
                        if !disabled && !*sending.read() {
                            on_submit.call(());
                        }
                    }
                },
            }
            div {
                style: "display: flex; align-items: center; gap: 16px; flex-wrap: wrap;",
                if !locked {
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
                }
                div { style: "flex: 1;" }
                if let Some(secs) = *retry_after_seconds.read() {
                    span {
                        style: "font-size: 13px; color: #B45309;",
                        "Try again in {secs} s"
                    }
                }
                if *sending.read() {
                    if let Some(stop) = on_stop {
                        // An SVG with an explicit box, not a `■` glyph at a smaller
                        // font-size than the send arrow it replaces: the glyph's ink is
                        // a fraction of its em, so a 14px `■` inside a 40px disc read as
                        // a dot in a circle. Stopping a generation is also an ordinary
                        // action rather than a destructive one, so it takes the
                        // composer's own indigo instead of the alert red.
                        button {
                            style: "width: 40px; height: 40px; border-radius: 999px; border: none; \
                                    background: #4F46E5; color: white; cursor: pointer; \
                                    display: flex; align-items: center; justify-content: center;",
                            // Says what a stop does, not what it might have done. The
                            // agent writes the transcript only when its run finishes, so
                            // a cancelled run discards everything the user watched stream
                            // in. Keeping it would mean an unmarked fragment in the
                            // conversation's permanent memory that a later turn reads
                            // back as though the assistant had said it.
                            title: "Stop the answer (the partial answer is discarded)",
                            onclick: move |_| stop.call(()),
                            Icon { icon: MdStop, style: "width: 20px; height: 20px; color: white;" }
                        }
                    } else {
                        // No `on_stop` means there is nothing to stop yet — the homepage
                        // is still creating the conversation. It used to render the same
                        // red stop button anyway, wired to a handler that did nothing:
                        // a control that looks live, is the obvious thing to press, and
                        // silently ignores the press.
                        span {
                            title: "Starting the conversation\u{2026}",
                            style: "width: 40px; height: 40px; border-radius: 999px; \
                                    background: #E2E8F0; color: #94A3B8; font-size: 14px; \
                                    display: flex; align-items: center; justify-content: center;",
                            "\u{22EF}"
                        }
                    }
                } else {
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
}
