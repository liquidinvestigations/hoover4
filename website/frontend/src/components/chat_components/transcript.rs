//! Transcript of a chat session: user bubbles, assistant markdown, tools, doc cards.

use common::chat_types::{ChatMessageItem, ChatRole};
use dioxus::prelude::*;

use crate::components::chat_components::{
    doc_ref_card::ChatDocRefCard, markdown_text::MarkdownishText,
    tool_disclosure::ToolCallDisclosure,
};

#[component]
pub fn ChatTranscript(
    messages: Vec<ChatMessageItem>,
    find_query: Signal<String>,
    match_index: Signal<usize>,
    match_count: Signal<usize>,
) -> Element {
    let q = find_query.read().clone().to_lowercase();
    let matches: Vec<usize> = if q.is_empty() {
        Vec::new()
    } else {
        messages
            .iter()
            .enumerate()
            .filter(|(_, m)| m.content.to_lowercase().contains(&q))
            .map(|(i, _)| i)
            .collect()
    };
    let count = matches.len();
    if *match_count.read() != count {
        match_count.set(count);
    }
    let active_msg = matches.get(*match_index.read()).copied();

    rsx! {
        div {
            style: "flex: 1; overflow-y: auto; padding: 18px; display: flex; \
                    flex-direction: column; gap: 12px;",
            if messages.is_empty() {
                div { style: "color: #94A3B8; font-size: 14px;",
                    "Ask a question about the documents in your collections."
                }
            }
            for (i, m) in messages.into_iter().enumerate() {
                {
                    let highlight = active_msg == Some(i);
                    rsx! {
                        MessageEntry {
                            key: "{m.seq}",
                            message: m,
                            highlight,
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn MessageEntry(message: ChatMessageItem, highlight: bool) -> Element {
    let ring = if highlight {
        "outline: 2px solid #F59E0B; outline-offset: 2px;"
    } else {
        ""
    };

    match message.role {
        ChatRole::User => rsx! {
            div {
                style: "align-self: flex-end; background: #4096FF; color: white; max-width: 78%; \
                        padding: 10px 14px; border-radius: 14px; white-space: pre-wrap; \
                        word-break: break-word; line-height: 1.55; {ring}",
                "{message.content}"
            }
        },
        ChatRole::Assistant => rsx! {
            div {
                style: "align-self: stretch; max-width: 96%; padding: 4px 2px; {ring}",
                MarkdownishText { text: message.content.clone() }
            }
        },
        ChatRole::Tool => {
            let refs = message.parsed_doc_refs();
            rsx! {
                div { style: "display: flex; flex-direction: column; gap: 8px; {ring}",
                    ToolCallDisclosure {
                        tool_name: message.tool_name.clone(),
                        tool_input: message.tool_input.clone(),
                        tool_output: message.tool_output.clone(),
                        content_summary: message.content.clone(),
                    }
                    for (i, doc) in refs.into_iter().enumerate() {
                        ChatDocRefCard { key: "{doc.file_hash}-{i}", doc, index: i as u64 }
                    }
                }
            }
        }
        ChatRole::Error => rsx! {
            div {
                style: "align-self: flex-start; background: #FEF2F2; color: #991B1B; max-width: 88%; \
                        border: 1px solid #FECACA; padding: 10px 14px; border-radius: 12px; {ring}",
                "{message.content}"
            }
        },
    }
}
