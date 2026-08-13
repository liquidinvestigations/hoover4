//! Transcript of a chat session: user bubbles, assistant markdown, tools, doc cards.

use common::chat_types::{ChatDocRef, ChatMessageItem, ChatRole, StreamTurn};
use dioxus::prelude::*;

use crate::components::chat_components::{
    doc_ref_card::ChatDocRefCard, markdown_text::MarkdownishText, tool_cards::ToolCard,
};

#[component]
pub fn ChatTranscript(
    messages: Vec<ChatMessageItem>,
    find_query: Signal<String>,
    match_index: Signal<usize>,
    match_count: Signal<usize>,
    /// The in-flight turn, rendered as pending entries after the finished rows.
    stream: Option<StreamTurn>,
    /// False when `stream` is the leftovers of an interrupted turn rather than one that
    /// is still being produced. The content is the same; the promise it makes is not.
    stream_live: Option<bool>,
) -> Element {
    let stream_live = stream_live.unwrap_or(true);
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
    // Reported to the find bar from an effect, never from the render body: writing a
    // signal mid-render schedules another render from inside one.
    use_effect(move || {
        if *match_count.peek() != count {
            match_count.set(count);
        }
    });
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
            if let Some(turn) = stream {
                for tool in turn.tool_rows.clone() {
                    div {
                        key: "stream-tool-{tool.seq}",
                        style: "display: flex; flex-direction: column; gap: 8px;",
                        ToolCard {
                            tool_name: tool.tool_name.clone(),
                            // A stream row has no payload columns — the arguments and
                            // result are written only when the call finalises into
                            // chat_messages. Its `summary` *is* the arguments JSON while
                            // the call runs (`AgentToolCall::summary` takes `input`
                            // first), which is what lets the pending web_search card show
                            // the query. Truncated past 400 chars, so the cards parse it
                            // best-effort and fall back to a bare label.
                            tool_input: tool.summary.clone(),
                            tool_output: String::new(),
                            content_summary: tool.summary.clone(),
                            running: !tool.done,
                            elapsed_ms: tool.elapsed_ms,
                        }
                    }
                }
                if !turn.content.is_empty() {
                    div {
                        key: "stream-answer-{turn.answer_seq}",
                        style: "align-self: stretch; max-width: 96%; padding: 4px 2px;",
                        MarkdownishText { text: turn.content.clone() }
                        // The cursor marks this as the live tail rather than a finished
                        // answer — identical content, different promise.
                        if stream_live {
                            span { style: "color: #4F46E5;", "\u{258D}" }
                        }
                    }
                } else if turn.tool_rows.is_empty() && stream_live {
                    div {
                        style: "color: #64748B; font-size: 13px; font-style: italic;",
                        "The assistant is working\u{2026}"
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
        ChatRole::Assistant => {
            let retries = message.parsed_retry_errors();
            rsx! {
                div {
                    style: "align-self: stretch; max-width: 96%; padding: 4px 2px; {ring}",
                    if !message.reasoning.is_empty() {
                        ReasoningDisclosure { reasoning: message.reasoning.clone() }
                    }
                    MarkdownishText { text: message.content.clone() }
                    // A turn that only succeeded on retry is a healthy answer over an
                    // unhealthy agent tier. Worth saying, quietly, rather than hiding.
                    if !retries.is_empty() {
                        AttemptDisclosure {
                            summary: format!(
                                "Answered after {} failed attempt{}",
                                retries.len(),
                                if retries.len() == 1 { "" } else { "s" },
                            ),
                            errors: retries,
                            tone_color: "#B45309",
                        }
                    }
                }
            }
        }
        ChatRole::Tool => {
            let refs = message.parsed_doc_refs();
            rsx! {
                div { style: "display: flex; flex-direction: column; gap: 8px; {ring}",
                    ToolCard {
                        tool_name: message.tool_name.clone(),
                        tool_input: message.tool_input.clone(),
                        tool_output: message.tool_output.clone(),
                        content_summary: message.content.clone(),
                    }
                    if !refs.is_empty() {
                        DocRefsDisclosure { tool_name: message.tool_name.clone(), refs }
                    }
                }
            }
        }
        ChatRole::Error => {
            let retries = message.parsed_retry_errors();
            rsx! {
                div {
                    style: "align-self: flex-start; background: #FEF2F2; color: #991B1B; \
                            max-width: 88%; border: 1px solid #FECACA; padding: 10px 14px; \
                            border-radius: 12px; {ring}",
                    div { "{message.content}" }
                    // The final error is often the least informative of the set — a
                    // timeout that followed a real 500 says much less than the 500 did.
                    // The list is every attempt including the one quoted above, so it is
                    // labelled by what it holds: reading it as "earlier" attempts turned
                    // one failure into a report of a turn that failed twice.
                    if !retries.is_empty() {
                        AttemptDisclosure {
                            summary: format!(
                                "{} failed attempt{}",
                                retries.len(),
                                if retries.len() == 1 { "" } else { "s" },
                            ),
                            errors: retries,
                            tone_color: "#991B1B",
                        }
                    }
                }
            }
        }
    }
}

/// The model's reasoning trace, collapsed by default — it narrates how the answer was
/// produced and is never part of the answer body.
#[component]
fn ReasoningDisclosure(reasoning: String) -> Element {
    let mut open = use_signal(|| false);
    rsx! {
        div { style: "margin-bottom: 6px;",
            button {
                style: "background: none; border: none; padding: 0; cursor: pointer; \
                        font-size: 12px; color: #64748B; text-decoration: underline;",
                onclick: move |_| {
                    let next = !*open.peek();
                    open.set(next);
                },
                if *open.read() { "Hide reasoning" } else { "Show reasoning" }
            }
            if *open.read() {
                pre {
                    style: "margin: 6px 0 0 0; white-space: pre-wrap; word-break: break-word; \
                            font-size: 12px; line-height: 1.5; color: #475569; \
                            background: #F1F5F9; padding: 8px 10px; border-radius: 8px; \
                            max-height: 260px; overflow: auto;",
                    "{reasoning}"
                }
            }
        }
    }
}

/// The documents one tool call surfaced, collapsed behind a line that counts them.
///
/// Collapsed by default because a search result set is *evidence for* the answer, not
/// the answer: one `search_collections` call rendered 46 document cards with a 400-
/// character preview each, so a page holding a 31-character answer was 22 168 characters
/// of scrolling. The summary line carries the two facts worth having without opening it —
/// which tool ran and how many documents it found — because a bare chevron makes the
/// reader open every one of them to find out whether it is worth opening.
#[component]
fn DocRefsDisclosure(tool_name: String, refs: Vec<ChatDocRef>) -> Element {
    let mut open = use_signal(|| false);
    let count = refs.len();
    let noun = if count == 1 { "document" } else { "documents" };
    let tool = if tool_name.is_empty() || tool_name == "tool" {
        "the tool".to_string()
    } else {
        tool_name
    };
    rsx! {
        div { style: "display: flex; flex-direction: column; gap: 8px;",
            button {
                class: "x-chat-docrefs-toggle",
                style: "align-self: flex-start; background: none; border: none; padding: 0; \
                        cursor: pointer; font-size: 12px; color: #4F46E5; \
                        text-decoration: underline;",
                onclick: move |_| {
                    let next = !*open.peek();
                    open.set(next);
                },
                if *open.read() {
                    "{count} {noun} from {tool} \u{2014} hide"
                } else {
                    "{count} {noun} from {tool} \u{2014} show"
                }
            }
            if *open.read() {
                for (i, doc) in refs.into_iter().enumerate() {
                    ChatDocRefCard { key: "{doc.file_hash}-{i}", doc, index: i as u64 }
                }
            }
        }
    }
}

/// Collapsed list of the errors from attempts that preceded this row.
#[component]
fn AttemptDisclosure(
    summary: String,
    errors: Vec<String>,
    tone_color: &'static str,
) -> Element {
    let mut open = use_signal(|| false);
    rsx! {
        div { style: "margin-top: 6px;",
            button {
                style: "background: none; border: none; padding: 0; cursor: pointer; \
                        font-size: 12px; text-decoration: underline; color: {tone_color};",
                onclick: move |_| {
                    let next = !*open.peek();
                    open.set(next);
                },
                if *open.read() { "{summary} \u{2014} hide" } else { "{summary} \u{2014} show" }
            }
            if *open.read() {
                ul {
                    class: "x-error-display",
                    style: "margin: 6px 0 0 0; padding-left: 18px; font-size: 12px; \
                            line-height: 1.5; opacity: 0.9;",
                    for (i, e) in errors.into_iter().enumerate() {
                        li { key: "{i}", style: "word-break: break-word;", "{e}" }
                    }
                }
            }
        }
    }
}
