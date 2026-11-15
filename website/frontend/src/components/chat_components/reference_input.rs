//! A text input for text that goes to a model. A pasted Hoover link becomes a reference chip.
//!
//! The element is `contenteditable`, and `assets/reference-input.js` edits it: the caret,
//! the line ends, the chips and the paste. This component parses the pasted text with
//! `common::links::find_links`, inserts it at the caret with each link as a pending part,
//! and asks the server for the references (`resolve_references`). A link that resolves
//! becomes a chip with its number, its label and an X that removes it. A link of another
//! host, a link that does not parse and a link that does not resolve stay text.
//!
//! The value is a [`RichText`]: the text with `[Rn]` at each chip, numbered in text order,
//! and the references. The page owns the value. A change of the value from the page, such
//! as a cleared draft or a chosen follow-up, renders the element again, and a focused
//! element keeps the focus with the caret at the end. A change in the element calls
//! `on_change`.
//!
//! [`ReferenceText`] shows a stored text with its references as chips that open the link.

use std::sync::atomic::{AtomicU64, Ordering};

use common::links::{find_links, marked_parts, ChatReference, LinkHost, MarkedPart, RichText};
use dioxus::prelude::*;
use serde::Deserialize;

use crate::tr;

const REFERENCE_INPUT_JS: Asset = asset!("/assets/reference-input.js");

static NEXT_INPUT: AtomicU64 = AtomicU64::new(1);

/// The script of the channel. It waits for the script and the element, attaches the editor,
/// and passes each command to it.
fn channel_script(id: &str) -> String {
    format!( // i18n: data, JavaScript
        r#"
let el = null;
while (!window.hooverReferenceInput || !(el = document.getElementById({id:?}))) await new Promise(r => setTimeout(r, 30));
window.hooverReferenceInput.attach(el, (event) => dioxus.send(event));
dioxus.send({{kind: 'ready'}});
while (true) {{ window.hooverReferenceInput.command(el, await dioxus.recv()); }}
"#
    )
}

/// An event of the editor.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum EditorEvent {
    Ready,
    Change { text: String, references: Vec<ChatReference> },
    Enter,
    Paste { id: u64, text: String, origin: String },
}

/// The script tag of the editor. The application root renders it once.
#[component]
pub fn ReferenceInputScript() -> Element {
    rsx! { document::Script { src: REFERENCE_INPUT_JS } }
}

/// The name of a reference kind, shown in a chip whose item has no name.
pub fn kind_name(kind: &str) -> String {
    match kind {
        "search" => tr!("chat-reference-kind-search"),
        "document" => tr!("chat-reference-kind-document"),
        "storage" => tr!("chat-reference-kind-storage"),
        "collection" => tr!("chat-reference-kind-collection"),
        "folder" => tr!("chat-reference-kind-folder"),
        "email_graph" => tr!("chat-reference-kind-email-graph"),
        "chat" => tr!("chat-reference-kind-chat"),
        "board" => tr!("chat-reference-kind-board"),
        "manual" => tr!("chat-reference-kind-manual"),
        _ => kind.to_string(),
    }
}

/// The text of a chip: the label of the item, else the name of its kind.
pub fn chip_label(reference: &ChatReference) -> String {
    if reference.label.trim().is_empty() { kind_name(&reference.kind) } else { reference.label.clone() }
}

fn kinds_json() -> String {
    let kinds = ["search", "document", "storage", "collection", "folder", "email_graph", "chat", "board", "manual"];
    let map: serde_json::Map<String, serde_json::Value> =
        kinds.iter().map(|k| (k.to_string(), serde_json::Value::String(kind_name(k)))).collect();
    serde_json::Value::Object(map).to_string()
}

/// The text and link parts of a paste, as the editor inserts them. Each link part has a key
/// `<paste>-<n>`.
pub fn paste_parts(id: u64, text: &str, origin: &str) -> (Vec<serde_json::Value>, Vec<(String, String)>) {
    let mut parts = Vec::new();
    let mut links = Vec::new();
    let mut last = 0;
    for (index, (range, _)) in find_links(text, LinkHost::Own(origin)).into_iter().enumerate() {
        if range.start > last {
            parts.push(serde_json::json!({"text": &text[last..range.start]}));
        }
        let key = format!("{id}-{index}");
        let link = text[range.clone()].to_string();
        parts.push(serde_json::json!({"link": link, "key": key}));
        links.push((key, link));
        last = range.end;
    }
    if last < text.len() {
        parts.push(serde_json::json!({"text": &text[last..]}));
    }
    (parts, links)
}

/// The editor message that renders `value`. A focused element keeps the focus, with the
/// caret at the end. `shown` is the text that the element last sent. The editor ignores the
/// message when its text changed since then, so a value from an older render does not
/// replace newer typing. `None` renders without that check.
fn set_message(value: &RichText, shown: Option<&RichText>) -> serde_json::Value {
    serde_json::json!({
        "kind": "set",
        "text": value.text,
        "references": value.references,
        "shown": shown.map(|s| s.text.clone()),
    })
}

#[component]
pub fn ReferenceInput(
    value: RichText,
    on_change: EventHandler<RichText>,
    /// Enter without Shift calls it. Without it, Enter adds a line.
    #[props(default)]
    on_enter: Option<EventHandler<()>>,
    #[props(default)]
    placeholder: String,
    /// The most characters of the text, with each marker counted. 0 for no limit.
    #[props(default)]
    max_chars: usize,
    #[props(default)]
    disabled: bool,
    /// The class of the element, which browser tests select.
    #[props(default)]
    class: String,
    #[props(default)]
    style: String,
    /// The accessible name, when no visible label names the input.
    #[props(default)]
    label: String,
    /// Marks the chat composer (`data-chat-composer`).
    #[props(default)]
    composer: bool,
) -> Element {
    let id = use_hook(|| format!("x-ref-input-{}", NEXT_INPUT.fetch_add(1, Ordering::Relaxed)));
    let mut eval = use_signal(|| None::<document::Eval>);
    let mut ready = use_signal(|| false);
    // The value that the element shows: the last value that it sent or that was rendered.
    let mut shown = use_signal(|| None::<RichText>);
    let mut current = use_signal(|| value.clone());

    let send = move |message: serde_json::Value| {
        if let Some(channel) = *eval.peek() {
            if let Err(e) = channel.send(message) {
                dioxus::logger::tracing::warn!("reference input command failed: {e}");
            }
        }
    };

    let script = channel_script(&id);
    use_future(move || {
        let script = script.clone();
        async move {
            let mut channel = document::eval(&script);
            eval.set(Some(channel));
            loop {
                let event = match channel.recv::<EditorEvent>().await {
                    Ok(event) => event,
                    Err(e) => {
                        dioxus::logger::tracing::warn!("reference input channel ended: {e}");
                        break;
                    }
                };
                match event {
                    EditorEvent::Ready => {
                        ready.set(true);
                        let value = current.peek().clone();
                        shown.set(Some(value.clone()));
                        send(set_message(&value, None));
                    }
                    EditorEvent::Change { text, references } => {
                        let value = RichText { text, references };
                        shown.set(Some(value.clone()));
                        on_change.call(value);
                    }
                    EditorEvent::Enter => {
                        if let Some(handler) = on_enter {
                            handler.call(());
                        }
                    }
                    EditorEvent::Paste { id, text, origin } => {
                        let (parts, links) = paste_parts(id, &text, &origin);
                        send(serde_json::json!({"kind": "insert", "id": id, "parts": parts}));
                        if links.is_empty() {
                            continue;
                        }
                        let urls = links.iter().map(|(_, link)| link.clone()).collect();
                        let results = crate::api::chat_api::resolve_references(urls).await;
                        for (index, (key, _)) in links.iter().enumerate() {
                            let resolved = results.as_ref().ok().and_then(|list| list.get(index)).and_then(|r| r.as_ref().ok());
                            send(match resolved {
                                Some(reference) => serde_json::json!({"kind": "resolve", "key": key, "reference": reference}),
                                None => serde_json::json!({"kind": "unwrap", "key": key}),
                            });
                        }
                    }
                }
            }
        }
    });

    // A value from the page that the element does not show renders the element again.
    use_effect(use_reactive!(|value| {
        current.set(value.clone());
        if *ready.peek() && shown.peek().as_ref() != Some(&value) {
            let before = shown.peek().clone();
            shown.set(Some(value.clone()));
            send(set_message(&value, before.as_ref()));
        }
    }));

    let editable = if disabled { "false" } else { "true" };
    rsx! {
        div {
            id: "{id}",
            class: "x-ref-input {class}",
            style: "{style}",
            role: "textbox",
            "aria-multiline": "true",
            "aria-label": if label.is_empty() { None } else { Some(label.clone()) },
            "aria-placeholder": "{placeholder}",
            "aria-disabled": if disabled { "true" } else { "false" },
            "data-placeholder": "{placeholder}",
            "data-max-chars": "{max_chars}",
            "data-submit": if on_enter.is_some() { "true" } else { "false" },
            "data-remove-label": tr!("chat-reference-remove"),
            "data-kinds": kinds_json(),
            "data-chat-composer": if composer { Some("true") } else { None },
            contenteditable: editable,
            spellcheck: "true",
        }
    }
}

/// A stored text with its references as chips that open the link. Each chip shows the
/// number of its marker and the label of its item. A marker without a reference stays text.
#[component]
pub fn ReferenceText(text: String, references: Vec<ChatReference>) -> Element {
    let parts = marked_parts(&text);
    rsx! {
        for (index, part) in parts.into_iter().enumerate() {
            match part {
                MarkedPart::Text(plain) => rsx! { span { key: "{index}", "{plain}" } },
                MarkedPart::Reference(n) => match references.iter().find(|r| r.handle == common::links::marker(n)) {
                    Some(reference) => rsx! { ReferenceChip { key: "{index}", number: n, reference: reference.clone() } },
                    None => rsx! { span { key: "{index}", {common::links::marker(n)} } },
                },
            }
        }
    }
}

/// One reference chip that opens its item.
#[component]
pub fn ReferenceChip(number: usize, reference: ChatReference) -> Element {
    let label = chip_label(&reference);
    rsx! {
        a {
            class: "x-ref-chip x-ref-chip-link",
            href: "{reference.url}",
            title: "{reference.url}",
            "data-reference": "{reference.handle}",
            span { class: "x-ref-chip-number", "{number}" }
            span { class: "x-ref-chip-label", "{label}" }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::paste_parts;

    #[test]
    fn a_paste_splits_into_text_and_link_parts() {
        let text = "Read https://hoover.example.org/ai_chat/boards/b1, not https://other.org/ai_chat/boards/b2.";
        let (parts, links) = paste_parts(4, text, "https://hoover.example.org");
        assert_eq!(links, vec![("4-0".to_string(), "https://hoover.example.org/ai_chat/boards/b1".to_string())]);
        assert_eq!(parts, vec![
            serde_json::json!({"text": "Read "}),
            serde_json::json!({"link": "https://hoover.example.org/ai_chat/boards/b1", "key": "4-0"}),
            serde_json::json!({"text": ", not https://other.org/ai_chat/boards/b2."}),
        ]);
        let (parts, links) = paste_parts(5, "no link", "https://hoover.example.org");
        assert!(links.is_empty());
        assert_eq!(parts, vec![serde_json::json!({"text": "no link"})]);
    }
}
