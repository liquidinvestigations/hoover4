//! Transcript of a chat session: user bubbles, assistant markdown, tools, doc cards.

use std::collections::HashMap;

use common::chat_types::{ChatDocRef, ChatMessageItem, ChatRole, StreamTurn, merge_citations};
use dioxus::prelude::*;

use crate::components::chat_components::{
    doc_ref_card::ChatDocRefCard,
    markdown_text::{MarkdownishText, source_anchor_id},
    tool_cards::ToolCard,
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
    // Gathered once for the whole transcript rather than per card: the tool that lists a
    // document's entities names it by collection and hash, and the dataset that makes it
    // addressable was named earlier in the same conversation by whatever found it.
    let datasets = dataset_by_hash(&messages);

    rsx! {
        div {
            style: "flex: 1; overflow-y: auto; padding: 18px; display: flex; \
                    flex-direction: column; gap: 12px;",
            if messages.is_empty() {
                div { style: "color: #94A3B8; font-size: 14px;",
                    "Ask a question about the documents in your collections."
                }
            }
            for (i, m) in messages.iter().cloned().enumerate() {
                {
                    let highlight = active_msg == Some(i);
                    // The strip belongs to the ANSWER, and the citations arrive on the
                    // tool rows before it. Collected here rather than inside
                    // `MessageEntry`, which sees one message and cannot know which turn
                    // it closes.
                    let sources = if m.role == ChatRole::Assistant {
                        citations_for_answer(&messages, i)
                    } else {
                        Vec::new()
                    };
                    rsx! {
                        MessageEntry {
                            key: "{m.seq}",
                            message: m,
                            highlight,
                            sources,
                            datasets: datasets.clone(),
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
                            datasets: datasets.clone(),
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

/// Every document hash this conversation has named a dataset for.
///
/// The first naming wins. A hash is the same document in every dataset that holds it, so
/// a later row naming a second dataset describes the same bytes and would only move a
/// link from one copy to another.
fn dataset_by_hash(messages: &[ChatMessageItem]) -> HashMap<String, String> {
    let mut datasets: HashMap<String, String> = HashMap::new();
    for message in messages {
        for doc in message.parsed_doc_refs() {
            if !doc.file_hash.is_empty() && !doc.collection_dataset.is_empty() {
                datasets.entry(doc.file_hash).or_insert(doc.collection_dataset);
            }
        }
        if message.tool_output.is_empty() {
            continue;
        }
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(&message.tool_output) {
            collect_datasets(&value, &mut datasets, 0);
        }
    }
    datasets
}

/// Walk a tool result for objects carrying both a hash and a dataset.
///
/// Shape-agnostic on purpose: a search hit, a cited document and a read document all
/// carry the pair, at three different depths, and a walker keyed on the tool's name would
/// need a branch per tool and would miss the next one.
fn collect_datasets(
    value: &serde_json::Value,
    datasets: &mut HashMap<String, String>,
    depth: usize,
) {
    // Deep enough for every envelope the agent tier wraps a result in, and a bound rather
    // than none because the payload is not this build's to trust.
    if depth > 8 {
        return;
    }
    match value {
        serde_json::Value::Object(fields) => {
            let hash = fields.get("file_hash").and_then(|v| v.as_str()).unwrap_or_default();
            let dataset = fields
                .get("collection_dataset")
                .and_then(|v| v.as_str())
                .unwrap_or_default();
            if !hash.is_empty() && !dataset.is_empty() {
                datasets
                    .entry(hash.to_string())
                    .or_insert_with(|| dataset.to_string());
            }
            for nested in fields.values() {
                collect_datasets(nested, datasets, depth + 1);
            }
        }
        serde_json::Value::Array(items) => {
            for item in items {
                collect_datasets(item, datasets, depth + 1);
            }
        }
        _ => {}
    }
}

/// The citations of the turn that ends at `answer_index`.
///
/// Walks backwards over the tool rows of that turn and stops at the previous answer or
/// the user's message: a handle from an earlier turn still resolves, but its strip
/// belongs under the answer that used it, not under every answer after it.
fn citations_for_answer(messages: &[ChatMessageItem], answer_index: usize) -> Vec<ChatDocRef> {
    let mut refs: Vec<ChatDocRef> = Vec::new();
    for message in messages[..answer_index].iter().rev() {
        match message.role {
            ChatRole::Tool => {
                if message.tool_name == "cite_documents" {
                    refs.extend(message.parsed_doc_refs());
                }
            }
            // Anything that is not a tool row closes the turn.
            _ => break,
        }
    }
    refs.reverse();
    merge_citations(refs)
}

#[component]
fn MessageEntry(
    message: ChatMessageItem,
    highlight: bool,
    /// The documents this answer cited, for the strip beneath it. Empty for every role
    /// but the assistant's.
    #[props(default)]
    sources: Vec<ChatDocRef>,
    /// See [`dataset_by_hash`]. Read by the entities card and by nothing else.
    #[props(default)]
    datasets: HashMap<String, String>,
) -> Element {
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
            // Absent for a turn nothing counted, and for every streaming partial: the
            // counts arrive with the finished row, and a footer that appears mid-answer
            // showing zeros would read as a measurement of nothing.
            let context_footer = message.context_footer();
            rsx! {
                div {
                    style: "align-self: stretch; max-width: 96%; padding: 4px 2px; {ring}",
                    if !message.reasoning.is_empty() {
                        ReasoningDisclosure { reasoning: message.reasoning.clone() }
                    }
                    MarkdownishText { text: message.content.clone() }
                    if !sources.is_empty() {
                        SourcesStrip { sources: sources.clone() }
                    }
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
                    if let Some(footer) = context_footer {
                        div {
                            style: "margin-top: 6px; font-size: 0.78em; color: #6B7280; \
                                    font-variant-numeric: tabular-nums;",
                            title: "Tokens the conversation carries, the largest single \
                                    context this turn was billed for, and how much of \
                                    the model's window that used",
                            "{footer}"
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
                        datasets: datasets.clone(),
                    }
                    if !refs.is_empty() {
                        DocRefsDisclosure { tool_name: message.tool_name.clone(), refs }
                    }
                }
            }
        }
        // Deliberately unlike both neighbours it could be confused with: not the blue
        // user bubble, because the user did not write it, and not the red error card,
        // because nothing has gone wrong. A narrow inset note, aligned with the
        // assistant's own column, reads as the turn talking to itself.
        ChatRole::Nag => rsx! {
            div {
                style: "align-self: flex-start; max-width: 88%; background: #F5F3FF; \
                        color: #5B21B6; border-left: 3px solid #A78BFA; padding: 8px 12px; \
                        border-radius: 0 8px 8px 0; font-size: 0.9em; \
                        white-space: pre-wrap; word-break: break-word; {ring}",
                div { style: "font-weight: 600; margin-bottom: 2px;", "Nudged to continue" }
                div { "{message.content}" }
            }
        },
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
                // Keyed on the hash alone. Appending the loop index made two rows for the
                // same document distinct nodes, so any duplicate that reached here was
                // guaranteed to render twice; `extract_doc_refs` now collapses them, and
                // the key no longer hides it if that ever stops being true.
                for (i, doc) in refs.into_iter().enumerate() {
                    ChatDocRefCard { key: "{doc.file_hash}", doc, index: i as u64 }
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

/// The documents the agent put forward, under the answer that used them.
///
/// Not the search cards, which stay where they are under their disclosure. Those are
/// everything a search returned; this is the agent's own claim about what mattered, and
/// showing the first in place of the second is what turns an answer into a pile of links.
///
/// Each entry carries the handle that appears in the prose, so a reader following `[D3]`
/// out of a sentence lands on the document it names.
#[component]
fn SourcesStrip(sources: Vec<ChatDocRef>) -> Element {
    rsx! {
        div {
            style: "margin-top: 10px; border-top: 1px solid #E2E8F0; padding-top: 8px;",
            div {
                style: "font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 6px;",
                "Sources"
            }
            div {
                style: "display: flex; flex-direction: column; gap: 8px;",
                for (index, doc) in sources.into_iter().enumerate() {
                    div {
                        key: "{doc.handle}-{doc.file_hash}",
                        id: "{source_anchor_id(&doc.handle)}",
                        class: "x-source-entry",
                        style: "display: flex; gap: 8px; align-items: flex-start;",
                        if !doc.handle.is_empty() {
                            div {
                                style: "
                                    flex-shrink: 0; font-size: 12px; font-weight: 600;
                                    color: #3730A3; background: #EEF2FF;
                                    border: 1px solid #C7D2FE; border-radius: 5px;
                                    padding: 1px 5px; margin-top: 10px;
                                ",
                                "{doc.handle}"
                            }
                        }
                        div {
                            style: "flex: 1 1 auto; min-width: 0;",
                            ChatDocRefCard { doc: doc.clone(), index: index as u64 }
                            if !doc.why.is_empty() {
                                div {
                                    style: "font-size: 12px; color: #475569; padding: 0 4px 2px 4px;",
                                    "{doc.why}"
                                }
                            }
                            // A quote the server could not find in the document is shown
                            // and marked, never dropped. A model that stops citing is a
                            // worse outcome than a marked quote, and the marker is a fact
                            // the reader can act on.
                            if !doc.quote.is_empty() && !doc.quote_verified {
                                div {
                                    style: "
                                        font-size: 12px; color: #92400E; background: #FFFBEB;
                                        border: 1px solid #FDE68A; border-radius: 6px;
                                        padding: 3px 7px; margin: 2px 4px;
                                    ",
                                    "Unverified quote — this wording was not found in the document."
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
