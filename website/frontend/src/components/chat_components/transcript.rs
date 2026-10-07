//! Transcript of a chat session: user bubbles, assistant markdown, tools, doc cards.

use std::collections::{HashMap, HashSet};

use common::chat_types::{
    CITATION_NOTE_NAME, ChatDocRef, ChatMessageItem, ChatRole, StreamTurn, merge_citations,
};
use common::storage_tree::compose_collection_dataset;
use dioxus::prelude::*;

use crate::components::chat_components::{
    doc_ref_card::{ChatDocRefCard, ChatDocRefRow},
    markdown_text::{MarkdownishText, referenced_handles},
    web_page::WebPageCard,
    tool_cards::{ElapsedCounter, ToolCard},
    tool_run_summary::{run_duration_ms, timestamp_ms, tool_run_summary},
};

#[component]
pub fn ChatTranscript(
    messages: Vec<ChatMessageItem>,
    draft: Signal<String>,
    find_query: Signal<String>,
    match_index: Signal<usize>,
    match_count: Signal<usize>,
    /// The in-flight turn, rendered as pending entries after the finished rows.
    stream: Option<StreamTurn>,
    /// False when `stream` is the leftovers of an interrupted turn rather than one that
    /// is still being produced. The content is the same; the promise it makes is not.
    stream_live: Option<bool>,
    /// What a step of the in-flight turn waits for: `model` for a free model slot, `tool`
    /// for a free tool slot, or empty. A non-empty value shows a waiting line at the end
    /// of the turn, under its tool rows too.
    #[props(default)]
    queued_for: String,
    /// The handles that the `cite_documents` results of every run of the session issued,
    /// Stored citation handles stay available across conversation turns.
    #[props(default)]
    run_cited_handles: Vec<String>,
    /// Each stored handle identifies one document.
    #[props(default)]
    run_cited_refs: Vec<ChatDocRef>,
    #[props(default)]
    todo_versions: Vec<common::chat_types::TodoSnapshot>,
    /// The state of the newest turn, from `turn_state`. The root element carries it as
    /// `data-chat-turn`, so a browser test reads the turn state from the page.
    #[props(default)]
    turn: String,
) -> Element {
    let stream_live = stream_live.unwrap_or(true);
    let waiting_line = match queued_for.as_str() {
        "model" => "The turn waits for a free model slot.",
        "tool" => "The turn waits for a free tool slot.",
        _ => "",
    };
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
    use_effect(use_reactive!(|count| {
        if *match_count.peek() != count { match_count.set(count); }
        if count > 0 && *match_index.peek() >= count { match_index.set(0); }
    }));
    let active_msg = matches.get(*match_index.read()).copied();
    let active_seq = active_msg.map(|index| messages[index].seq);
    use_effect(use_reactive!(|active_seq| {
        if let Some(seq) = active_seq {
            document::eval(&format!("document.querySelector('[data-chat-message=\"{seq}\"]')?.firstElementChild?.scrollIntoView({{block: 'center'}});"));
        }
    }));
    // Gathered once for the whole transcript rather than per card: the tool that lists a
    // document's entities names it by collection and hash, and the dataset that makes it
    // addressable was named earlier in the same conversation by whatever found it.
    let datasets = dataset_by_hash(&messages);
    let collections = use_resource(crate::api::storage_api::list_storage_tree);
    let collection_tree = collections.read().as_ref().and_then(|result| result.as_ref().ok()).cloned().unwrap_or_default();
    // Handles are allocated for the whole conversation, so a handle that any citation of
    // any run gave is a real one. The answers mark every other handle as not cited.
    let mut cited_handles = issued_handles(&messages, &run_cited_handles);
    let web_pages = common::chat_pages::merge_page_refs(messages.iter().filter(|row| row.tool_name == "cite_pages")
        .flat_map(|row| common::chat_pages::extract_page_refs(&row.tool_output)).collect::<Vec<_>>());
    for page in &web_pages {
        if !cited_handles.contains(&page.handle) { cited_handles.push(page.handle.clone()); }
    }
    let conflicting = conflicting_handles(&messages);
    let mut all_sources = messages.iter().enumerate().filter(|(_, row)| row.tool_name == "cite_documents")
        .flat_map(|(index, _)| citation_search_context_with_tree(&messages, index, &collection_tree)).collect::<Vec<_>>();
    all_sources.extend(run_cited_refs.clone());
    all_sources.retain(|source| !source.handle.is_empty());
    let placements = citation_placements(&messages, &all_sources, &web_pages);
    // One row as `MessageEntry`. A run of tool rows renders the same entries inside its
    // group when the group is open.
    let entry = |i: usize| -> Element {
        let mut m = messages[i].clone();
        if m.tool_name == "cite_documents" {
            m.doc_refs = serde_json::to_string(&citation_search_context_with_tree(&messages, i, &collection_tree)).unwrap_or_default();
        }
        let highlight = active_msg == Some(i);
        // Source cards use the citations stored before this answer.
        let replaced = answer_replaced(&messages, i);
        // The replacement answer renders the source cards.
        let placement = placements.get(&i).cloned().unwrap_or_default();
        let sources = if replaced { Vec::new() } else { all_sources.clone() };
        let read_more_source = if m.tool_name == "read_more" {
            read_more_source(&messages, i)
        } else { None };
        let repeat_question = m.role == ChatRole::Assistant
            && asked_question(&messages[..i]) == m.content
            && !m.content.is_empty();
        rsx! {
            div { "data-chat-message": "{m.seq}", style: "display: contents;",
            MessageEntry {
                key: "{m.seq}",
                message: m.clone(),
                highlight,
                sources,
                card_handles: placement.inline,
                trailing_docs: placement.documents,
                trailing_pages: placement.pages,
                web_pages: web_pages.clone(),
                cited_handles: cited_handles.clone(),
                conflicting_handles: conflicting.clone(),
                datasets: datasets.clone(),
                todo_versions: todo_versions.clone(),
                read_more_source,
                repeat_question,
                replaced,
                draft,
            }
            }
        }
    };
    // Runs of tool and instruction rows, and every other row on its own, as index ranges.
    let segments = tool_run_segments(&messages, true);
    let live_tools = stream
        .as_ref()
        .map(|turn| turn.tool_rows.clone())
        .unwrap_or_default();
    let live_segments = live_tool_segments(&live_tools, true);
    let can_join = live_segments.first().is_some_and(|(_, _, todo)| !todo);
    let live_group_start = live_group_start(&messages, &segments, true, can_join);
    let joined_live_end = if live_group_start.is_some() {
        live_segments.first().map(|(_, end, _)| *end).unwrap_or(0)
    } else { 0 };
    let live_elapsed = stream.as_ref().and_then(|turn| {
        let before = live_group_start
            .and_then(|start| start.checked_sub(1).and_then(|index| messages.get(index)))
            .or_else(|| messages.last());
        before.and_then(|message| timestamp_ms(&message.created_ms)).map(|start| {
            turn.server_now_ms.saturating_sub(start).clamp(0, i64::from(u32::MAX)) as u32
        })
    });

    rsx! {
        div {
            id: "x-chat-transcript",
            "data-chat-turn": "{turn}",
            style: "flex: 1; overflow-y: auto; padding: 18px; display: flex; \
                    flex-direction: column; gap: 12px;",
            if messages.is_empty() {
                div { style: "color: #94A3B8; font-size: 14px;",
                    "Ask a question about the documents in your collections."
                }
            }
            for (start, end) in segments.iter().copied() {
                if end - start == 1
                    && messages[start].role != ChatRole::Tool
                    && !messages[start].role.is_instruction()
                    && !answer_replaced(&messages, start)
                    || end - start == 1 && (is_todo_write(&messages[start]) || is_question(&messages[start]))
                {
                    {entry(start)}
                } else {
                    ToolRunGroup {
                        key: "tools-{messages[start].seq}",
                        summary: if live_group_start == Some(start) {
                            format!(
                                "{} + {} running tool {}",
                                tool_run_summary(
                                    &messages[start..end],
                                    run_duration_ms(start.checked_sub(1).map(|b| &messages[b]), &messages[start..end]),
                                ),
                                joined_live_end,
                                if joined_live_end == 1 { "call" } else { "calls" },
                            )
                        } else {
                            tool_run_summary(
                                &messages[start..end],
                                run_duration_ms(start.checked_sub(1).map(|b| &messages[b]), &messages[start..end]),
                            )
                        },
                        force_open: active_msg.is_some_and(|a| (start..end).contains(&a)),
                        live: live_group_start == Some(start),
                        elapsed_ms: if live_group_start == Some(start) { live_elapsed } else { None },
                        for i in start..end {
                            {entry(i)}
                        }
                        if live_group_start == Some(start) {
                            for tool in live_tools[..joined_live_end].to_vec() {
                                div {
                                    key: "stream-tool-{tool.seq}",
                                    style: "display: flex; flex-direction: column; gap: 8px;",
                                    ToolCard {
                                        tool_name: tool.tool_name.clone(),
                                        tool_input: tool.summary.clone(),
                                        tool_output: String::new(),
                                        content_summary: tool.summary.clone(),
                                        running: !tool.done,
                                        elapsed_ms: tool.elapsed_ms,
                                        datasets: datasets.clone(),
                                    }
                                }
                            }
                        }
                    }
                }
            }
            if let Some(turn) = stream {
                for (start, end, todo) in live_segments.clone() {
                    if start >= joined_live_end {
                        if todo {
                            div { "data-todo-change": "true", style: "align-self: stretch;",
                                ToolCard {
                                    tool_name: turn.tool_rows[start].tool_name.clone(),
                                    tool_input: turn.tool_rows[start].summary.clone(),
                                    tool_output: String::new(),
                                    content_summary: turn.tool_rows[start].summary.clone(),
                                    running: !turn.tool_rows[start].done,
                                    elapsed_ms: turn.tool_rows[start].elapsed_ms,
                                    datasets: datasets.clone(),
                                }
                            }
                        } else {
                            ToolRunGroup {
                                key: "tools-{turn.tool_rows[start].seq}",
                                summary: format!("{} running tool {}", end - start, if end - start == 1 { "call" } else { "calls" }),
                                force_open: true,
                                live: true,
                                elapsed_ms: live_elapsed,
                                for tool in turn.tool_rows[start..end].to_vec() {
                                    ToolCard {
                                        tool_name: tool.tool_name.clone(),
                                        tool_input: tool.summary.clone(),
                                        tool_output: String::new(),
                                        content_summary: tool.summary.clone(),
                                        running: !tool.done,
                                        elapsed_ms: tool.elapsed_ms,
                                        datasets: datasets.clone(),
                                    }
                                }
                            }
                        }
                    }
                }
                if !turn.reasoning.is_empty() {
                    div {
                        key: "stream-reasoning-{turn.answer_seq}",
                        style: "align-self: stretch; max-width: 96%; padding: 4px 2px 0;",
                        ReasoningDisclosure { reasoning: turn.reasoning.clone() }
                    }
                }
                if !turn.content.is_empty() {
                    div {
                        key: "stream-answer-{turn.answer_seq}",
                        style: "align-self: stretch; max-width: 96%; padding: 4px 2px;",
                        // The live answer keeps every handle a chip. Its citation rows
                        // can still be in the stream, not in `messages`.
                        MarkdownishText { text: turn.content.clone() }
                        // The cursor marks this as the live tail rather than a finished
                        // answer, identical content, different promise.
                        if stream_live {
                            span { style: "color: #4F46E5;", "\u{258D}" }
                        }
                    }
                }
                if stream_live && !waiting_line.is_empty() {
                    div {
                        style: "color: #64748B; font-size: 13px; font-style: italic;",
                        "{waiting_line}"
                    }
                } else if turn.content.is_empty() && turn.tool_rows.is_empty() && stream_live {
                    div {
                        style: "color: #64748B; font-size: 13px; font-style: italic;",
                        "The assistant is working\u{2026}"
                    }
                }
            }
        }
    }
}

#[derive(Clone, Default)]
struct CitationPlacement {
    inline: Vec<String>,
    documents: Vec<ChatDocRef>,
    pages: Vec<common::chat_pages::ChatPageRef>,
}

fn citation_placements(messages: &[ChatMessageItem], docs: &[ChatDocRef], pages: &[common::chat_pages::ChatPageRef]) -> HashMap<usize, CitationPlacement> {
    let mut result = HashMap::new();
    let mut seen = HashSet::new();
    let identity = |handle: &str| {
        if handle.is_empty() { return None; }
        docs.iter().find(|doc| doc.handle == handle).map(|doc| format!("document:{}", doc.file_hash))
            .or_else(|| pages.iter().find(|page| page.handle == handle).map(|page| format!("page:{}", page.url)))
    };
    for (index, message) in messages.iter().enumerate() {
        if message.role != ChatRole::Assistant || answer_replaced(messages, index) { continue; }
        let mut placement = CitationPlacement::default();
        for handle in referenced_handles(&message.content) {
            if let Some(key) = identity(&handle) {
                if seen.insert(key) { placement.inline.push(handle); }
            }
        }
        let start = messages[..index].iter().rposition(|row| row.role == ChatRole::User).unwrap_or(0);
        let next_user = messages[index + 1..].iter().position(|row| row.role == ChatRole::User)
            .map(|offset| index + 1 + offset).unwrap_or(messages.len());
        let final_answer = !messages[index + 1..next_user].iter().any(|row| row.role == ChatRole::Assistant);
        if final_answer {
            let mut issued = Vec::new();
            for row in &messages[start..next_user] {
                if row.tool_name == "cite_documents" { issued.extend(row.parsed_doc_refs().into_iter().map(|doc| doc.handle)); }
                if row.tool_name == "cite_pages" { issued.extend(common::chat_pages::extract_page_refs(&row.tool_output).into_iter().map(|page| page.handle)); }
            }
            if index == messages.iter().rposition(|row| row.role == ChatRole::Assistant).unwrap_or(index) {
                issued.extend(docs.iter().map(|doc| doc.handle.clone()));
                issued.extend(pages.iter().map(|page| page.handle.clone()));
            }
            for handle in issued {
                if let Some(key) = identity(&handle) {
                    if seen.insert(key) {
                        if let Some(source) = docs.iter().find(|doc| doc.handle == handle) {
                            placement.documents.extend(docs.iter().filter(|doc| doc.file_hash == source.file_hash).cloned());
                        }
                        if let Some(page) = pages.iter().find(|page| page.handle == handle) { placement.pages.push(page.clone()); }
                    }
                }
            }
        }
        result.insert(index, placement);
    }
    result
}

#[component]
fn FollowUpSuggestions(prompts: Vec<String>, mut draft: Signal<String>) -> Element {
    rsx! {
        if prompts.len() == 3 {
            div { class: "x-chat-follow-ups", style: "background: #E5E7EB; border-radius: 8px; padding: 8px; display: flex; flex-direction: column; gap: 4px;",
                for (index, prompt) in prompts.into_iter().enumerate() {
                    button { key: "{index}", r#type: "button", style: "text-align: left; background: transparent; color: #333; border: 0; border-radius: 4px; padding: 10px; cursor: pointer; font: inherit;",
                        onclick: move |_| { draft.set(prompt.clone()); document::eval("document.querySelector('[data-chat-composer]')?.focus();"); },
                        "{prompt}"
                    }
                }
            }
        }
    }
}

/// The rows of `messages` as index ranges: each run of consecutive tool rows is one range,
/// and each other row is a range of its own.
fn is_todo_write(message: &ChatMessageItem) -> bool {
    matches!(message.tool_name.as_str(), "write_todo" | "edit_todo" | "mark_todo")
}

fn is_question(message: &ChatMessageItem) -> bool {
    message.role == ChatRole::Tool && message.tool_name == "ask_user"
}

fn live_tool_segments(rows: &[common::chat_types::StreamToolRow], split_todo: bool) -> Vec<(usize, usize, bool)> {
    let mut segments = Vec::new();
    for (index, row) in rows.iter().enumerate() {
        let todo = split_todo && matches!(row.tool_name.as_str(), "write_todo" | "edit_todo" | "mark_todo");
        if todo {
            segments.push((index, index + 1, true));
        } else if let Some((_, end, false)) = segments.last_mut() {
            *end = index + 1;
        } else {
            segments.push((index, index + 1, false));
        }
    }
    segments
}

fn tool_run_segments(messages: &[ChatMessageItem], split_todo: bool) -> Vec<(usize, usize)> {
    let mut out: Vec<(usize, usize)> = Vec::new();
    for (i, m) in messages.iter().enumerate() {
        if is_question(m) || split_todo && is_todo_write(m) {
            out.push((i, i + 1));
            continue;
        }
        match out.last_mut() {
            Some((start, end))
                if (m.role == ChatRole::Tool || m.role.is_instruction() || answer_replaced(messages, i))
                    && (messages[*start].role == ChatRole::Tool
                        || messages[*start].role.is_instruction() || answer_replaced(messages, *start))
                    && !is_question(&messages[*start])
                    && !(split_todo && is_todo_write(&messages[*start])) =>
            {
                *end = i + 1;
            }
            _ => out.push((i, i + 1)),
        }
    }
    out
}

/// The final stored tool group keeps its identity while stream rows extend it.
fn live_group_start(
    messages: &[ChatMessageItem],
    segments: &[(usize, usize)],
    split_todo: bool,
    has_live_tools: bool,
) -> Option<usize> {
    if !has_live_tools {
        return None;
    }
    let (start, end) = segments.last().copied()?;
    let first = &messages[start];
    if end == messages.len()
        && (first.role == ChatRole::Tool || first.role.is_instruction())
        && !(split_todo && is_todo_write(first))
    {
        Some(start)
    } else {
        None
    }
}

/// A run of tool rows, collapsed behind its summary line. The line expands to the cards.
/// `force_open` holds it open while the conversation search points at a row inside it.
#[component]
fn ToolRunGroup(
    summary: String,
    force_open: bool,
    #[props(default)] live: bool,
    #[props(default)] elapsed_ms: Option<u32>,
    children: Element,
) -> Element {
    let mut open = use_signal(|| false);
    let mut was_live = use_signal(|| false);
    use_effect(move || {
        if live != *was_live.peek() {
            was_live.set(live);
            open.set(live);
        }
    });
    let shown = *open.read() || force_open;
    let action = if shown { "Hide" } else { "Show" };
    rsx! {
        div {
            class: "x-chat-tool-run",
            style: "display: flex; flex-direction: column; gap: 8px;",
            button {
                class: "x-chat-tool-run-toggle",
                "aria-expanded": "{shown}",
                style: "align-self: flex-start; display: flex; gap: 8px; align-items: baseline; \
                        background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; \
                        padding: 5px 10px; cursor: pointer; font-size: 13px; color: #334155; \
                        text-align: left;",
                onclick: move |_| {
                    let next = !*open.peek();
                    open.set(next);
                },
                span { "{summary}" }
                if live { ElapsedCounter { already_ms: elapsed_ms } }
                span { style: "font-size: 12px; color: #4F46E5; text-decoration: underline;", "{action}" }
            }
            if shown {
                div {
                    style: "display: flex; flex-direction: column; gap: 12px; padding-left: 10px; \
                            border-left: 2px solid #E2E8F0;",
                    {children}
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
            let text = |key: &str| fields.get(key).and_then(|v| v.as_str()).unwrap_or_default();
            let hash = text("file_hash");
            // A paged search item carries the collection and the short dataset name that
            // `collections/list` returns, and no `collection_dataset`.
            let dataset = match (text("collection_dataset"), text("collectionname"), text("dataset")) {
                (full, _, _) if !full.is_empty() => full.to_string(),
                (_, collection, short) if !collection.is_empty() && !short.is_empty() => {
                    compose_collection_dataset(collection, short)
                }
                _ => String::new(),
            };
            if !hash.is_empty() && !dataset.is_empty() {
                datasets.entry(hash.to_string()).or_insert(dataset);
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

/// The handles that the citation rows of the conversation give to more than one document.
/// Records from before durable handles can hold such a handle. The answer links it to no
/// document, and its citation card names the conflict.
fn conflicting_handles(messages: &[ChatMessageItem]) -> Vec<String> {
    let mut documents: Vec<(String, String)> = Vec::new();
    let mut conflicting: Vec<String> = Vec::new();
    for message in messages {
        if message.role != ChatRole::Tool || message.tool_name != "cite_documents" {
            continue;
        }
        for doc in message.parsed_doc_refs() {
            if doc.handle.is_empty() {
                continue;
            }
            // A stored ref can hold the whole hash or its first 16 characters.
            let document: String = doc.file_hash.chars().take(16).collect();
            match documents.iter().find(|(handle, _)| handle == &doc.handle) {
                Some((_, known)) if known != &document => {
                    if !conflicting.contains(&doc.handle) {
                        conflicting.push(doc.handle.clone());
                    }
                }
                Some(_) => {}
                None => documents.push((doc.handle.clone(), document)),
            }
        }
    }
    conflicting
}

/// Every handle that a `cite_documents` result of the conversation gave: the handles of
/// the transcript rows, and `run_cited_handles`, which the server read from the run
/// threads of every depth.
fn issued_handles(messages: &[ChatMessageItem], run_cited_handles: &[String]) -> Vec<String> {
    let mut handles: Vec<String> = run_cited_handles.to_vec();
    for message in messages {
        if message.role == ChatRole::Tool && message.tool_name == "cite_documents" {
            for doc in message.parsed_doc_refs() {
                if !doc.handle.is_empty() && !handles.contains(&doc.handle) {
                    handles.push(doc.handle);
                }
            }
        }
    }
    handles
}

fn asked_question(messages: &[ChatMessageItem]) -> String {
    messages
        .iter()
        .rev()
        .take_while(|message| message.role == ChatRole::Tool || message.role.is_instruction())
        .filter(|message| message.tool_name == "ask_user")
        .last()
        .and_then(|message| serde_json::from_str::<serde_json::Value>(&message.tool_input).ok())
        .map(|value| value.get("input").cloned().unwrap_or(value))
        .and_then(|value| value.get("question").and_then(|value| value.as_str()).map(str::to_string))
        .unwrap_or_default()
}

fn read_more_source(messages: &[ChatMessageItem], index: usize) -> Option<(String, u32, u32)> {
    let input: serde_json::Value = serde_json::from_str(&messages.get(index)?.tool_input).ok()?;
    let input = input.get("input").unwrap_or(&input);
    let handle = input.get("continuation").and_then(|value| value.as_str())?;
    let prior = messages[..index].iter().enumerate().rev().find(|(_, row)| {
        row.role == ChatRole::Tool
            && crate::components::chat_components::tool_cards::tool_content(&row.tool_output)
                .as_ref().is_some_and(|value| {
                    value.get("more").and_then(|more| more.as_str()) == Some(handle)
                        || value.get("items").and_then(|items| items.as_array()).is_some_and(|items| {
                            items.iter().any(|item| item.get("more").and_then(|more| more.as_str()) == Some(handle))
                        })
                })
    })?;
    if prior.1.tool_name == "read_more" {
        let (name, seq, part) = read_more_source(messages, prior.0)?;
        Some((name, seq, part + 1))
    } else {
        Some((prior.1.tool_name.clone(), prior.1.seq, 2))
    }
}

/// Add the newest earlier search context for each cited document.
#[cfg(test)]
fn citation_search_context(messages: &[ChatMessageItem], index: usize) -> Vec<ChatDocRef> {
    citation_search_context_with_tree(messages, index, &[])
}

fn citation_search_context_with_tree(messages: &[ChatMessageItem], index: usize, tree: &[common::storage_tree::CollectionNode]) -> Vec<ChatDocRef> {
    let mut refs = messages[index].parsed_doc_refs();
    let extracted = common::chat_types::extract_doc_refs(
        &messages[index].tool_name, &messages[index].tool_output);
    for doc in &mut refs {
        if !doc.quote_verified {
            if let Some(candidate) = extracted.iter().find(|item| item.handle == doc.handle
                && item.file_hash == doc.file_hash && !item.snippet.is_empty()) {
                doc.snippet = candidate.snippet.clone();
                doc.find_query = candidate.find_query.clone();
            }
        }
        for search in messages[..index].iter().rev().filter(|row| {
            row.role == ChatRole::Tool && matches!(row.tool_name.as_str(), "search_collections" | "search_passages")
        }) {
            let input = serde_json::from_str::<serde_json::Value>(&search.tool_input).unwrap_or_default();
            let input = input.get("input").unwrap_or(&input);
            let queries = input.get("queries").and_then(|v| v.as_array()).map(|values|
                values.iter().filter_map(|v| v.as_str().map(str::to_string)).collect::<Vec<_>>())
                .or_else(|| input.get("query").and_then(|v| v.as_str()).map(|value| vec![value.to_string()]))
                .unwrap_or_default();
            let mut found = common::chat_types::extract_doc_refs_with_queries(
                &search.tool_name, &search.tool_output, &queries);
            found.extend(search.parsed_doc_refs());
            if let Some(hit) = found.into_iter().find(|hit| {
                let length = hit.file_hash.len().min(doc.file_hash.len());
                length >= 12 && (hit.file_hash.starts_with(&doc.file_hash) || doc.file_hash.starts_with(&hit.file_hash))
                    && (hit.collectionname.is_empty() || doc.collectionname.is_empty()
                        || hit.collectionname == doc.collectionname)
            }) {
                let matched_query = hit.find_query.clone();
                if doc.term.is_empty() {
                    doc.term = matched_query.clone();
                }
                doc.search_snippet = hit.snippet;
                if !doc.quote_verified && !matched_query.is_empty() {
                    doc.find_query = matched_query.clone();
                }
                let reproducible = input.as_object().is_some_and(|fields| fields.keys().all(|key|
                    matches!(key.as_str(), "query" | "queries" | "collectionname" | "collections" | "limit" | "max_results" | "offset")));
                if reproducible && !matched_query.is_empty() && doc.term == matched_query
                    && !doc.collection_dataset.is_empty()
                {
                    let mut matched_input = input.clone();
                    matched_input["query"] = serde_json::Value::String(matched_query.clone());
                    if let Some(crate::routes::Route::SearchPage { query, .. }) =
                        super::tool_disclosure::search_route_from_tool_input(&search.tool_name, &matched_input.to_string(), tree)
                    {
                        doc.search_route = crate::routes::Route::SearchPage {
                            query,
                            current_search_result_page: 0,
                            selected_result_hash: crate::data_definitions::url_param::UrlParam(Some(doc.document_identifier())),
                            doc_viewer_state: crate::data_definitions::url_param::UrlParam(Some(
                                crate::data_definitions::doc_viewer_state::DocViewerState::from_find_query(matched_query))),
                        }.to_string();
                    }
                }
                break;
            }
        }
    }
    refs
}

/// Return citations from the answer turn, including its repair round.
#[cfg(test)]
fn citations_for_answer(messages: &[ChatMessageItem], answer_index: usize) -> Vec<ChatDocRef> {
    let mut refs: Vec<ChatDocRef> = Vec::new();
    // True after the note of a citation repair round. The answer before that note is
    // replaced by this one, so the citations before it belong to this answer too.
    let mut after_note = false;
    for (index, message) in messages[..answer_index].iter().enumerate().rev() {
        match message.role {
            ChatRole::Tool => {
                if message.tool_name == "cite_documents" {
                    refs.extend(citation_search_context(messages, index));
                }
            }
            ChatRole::Nag if is_citation_note(message) => after_note = true,
            // Another nag is a prompt to the model inside the same turn.
            ChatRole::Nag => {}
            ChatRole::Assistant if after_note => after_note = false,
            // Anything else closes the turn.
            _ => break,
        }
    }
    refs.reverse();
    merge_citations(refs)
}

fn is_citation_note(message: &ChatMessageItem) -> bool {
    message.role == ChatRole::Nag && message.tool_name == CITATION_NOTE_NAME
}

/// Whether the answer at `index` is replaced by a later answer of its turn. That is so when
/// the note of a citation repair round follows it, and the round wrote an answer with text.
/// A round that wrote no text keeps the earlier answer.
fn answer_replaced(messages: &[ChatMessageItem], index: usize) -> bool {
    if messages[index].role != ChatRole::Assistant {
        return false;
    }
    let rest = &messages[index + 1..];
    let turn_end = rest
        .iter()
        .position(|m| m.role == ChatRole::User)
        .unwrap_or(rest.len());
    let turn = &rest[..turn_end];
    let Some(note) = turn.iter().position(|m| m.role == ChatRole::Assistant || is_citation_note(m))
    else {
        return false;
    };
    is_citation_note(&turn[note])
        && turn[note + 1..]
            .iter()
            .any(|m| m.role == ChatRole::Assistant && !m.content.trim().is_empty())
}

#[component]
fn MessageEntry(
    message: ChatMessageItem,
    highlight: bool,
    draft: Signal<String>,
    /// The documents rendered at citation positions in this answer.
    #[props(default)]
    sources: Vec<ChatDocRef>,
    #[props(default)]
    web_pages: Vec<common::chat_pages::ChatPageRef>,
    #[props(default)]
    card_handles: Vec<String>,
    #[props(default)]
    trailing_docs: Vec<ChatDocRef>,
    #[props(default)]
    trailing_pages: Vec<common::chat_pages::ChatPageRef>,
    /// The handles that the citations of the conversation gave (`issued_handles`).
    #[props(default)]
    cited_handles: Vec<String>,
    /// See [`conflicting_handles`].
    #[props(default)]
    conflicting_handles: Vec<String>,
    /// See [`dataset_by_hash`]. Read by the entities card and by nothing else.
    #[props(default)]
    datasets: HashMap<String, String>,
    #[props(default)]
    todo_versions: Vec<common::chat_types::TodoSnapshot>,
    #[props(default)]
    read_more_source: Option<(String, u32, u32)>,
    #[props(default)]
    repeat_question: bool,
    /// True when a later answer of the turn replaces this one (`answer_replaced`).
    #[props(default)]
    replaced: bool,
) -> Element {
    let ring = if highlight {
        "outline: 2px solid #F59E0B; outline-offset: 2px;"
    } else {
        ""
    };

    match message.role {
        ChatRole::User => rsx! {
            div {
                "data-chat-user": "{message.seq}",
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
                    if replaced {
                        // Collapsed, and not marked as an answer: the answer after the
                        // citation repair round replaces it.
                        details {
                            "data-chat-replaced-answer": "{message.seq}",
                            summary {
                                style: "cursor: pointer; color: #64748B; font-size: 13px;",
                                "Earlier answer"
                            }
                            MarkdownishText {
                                text: message.content.clone(),
                                cited_handles: Some(cited_handles.clone()),
                                conflicting_handles: conflicting_handles.clone(),
                                sources: sources.clone(),
                                pages: web_pages.clone(),
                                card_handles: Some(if replaced { Vec::new() } else { card_handles.clone() }),
                            }
                            if let Some(footer) = context_footer.as_ref() {
                                div {
                                    style: "margin-top: 6px; font-size: 0.78em; color: #6B7280; \
                                            font-variant-numeric: tabular-nums;",
                                    "{footer}"
                                }
                            }
                        }
                    } else if !repeat_question {
                        div {
                            "data-chat-answer": "{message.seq}",
                            MarkdownishText {
                                text: message.content.clone(),
                                cited_handles: Some(cited_handles.clone()),
                                conflicting_handles: conflicting_handles.clone(),
                                sources: sources.clone(),
                                pages: web_pages.clone(),
                                card_handles: Some(if replaced { Vec::new() } else { card_handles.clone() }),
                            }
                        }
                    } else {
                        // The question card above shows this text. A browser test reads
                        // the answer of a turn that asked the user from this element.
                        span { "data-chat-asked": "{message.seq}", hidden: true, "{message.content}" }
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
                    if !replaced {
                        if !trailing_docs.is_empty() || !trailing_pages.is_empty() {
                        div { "data-unreferenced-citations": "true",
                            if !trailing_docs.is_empty() {
                                DocumentCitationCards { sources: trailing_docs, conflicting: conflicting_handles.clone() }
                            }
                            for page in trailing_pages {
                                div { "data-citation-handle": "{page.handle}",
                                    "data-citation-aliases": serde_json::to_string(&web_pages.iter().filter(|source| source.url == page.url).map(|source| source.handle.clone()).collect::<Vec<_>>()).unwrap_or_default(),
                                    if !page.why.is_empty() { p { "{page.why}" } }
                                    else { p { {page.terms.join("; ")} } }
                                    WebPageCard { page: page.clone(), passages: web_pages.iter().filter(|source| source.url == page.url).cloned().collect::<Vec<_>>() }
                                }
                            }
                        }
                        }
                        FollowUpSuggestions { prompts: message.follow_up_prompts(), draft }
                    }
                    if let Some(footer) = context_footer.filter(|_| !replaced) {
                        div {
                            class: "x-chat-turn-footer",
                            style: "margin-top: 6px; padding-bottom: 12px; border-bottom: 1px solid #80808033; text-align: center; font-size: 0.78em; color: #6B7280; font-variant-numeric: tabular-nums;",
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
                div { "data-todo-change": if is_todo_write(&message) { "true" } else { "false" }, style: "display: flex; flex-direction: column; gap: 8px; {ring}",
                    ToolCard {
                        tool_name: message.tool_name.clone(),
                        tool_input: message.tool_input.clone(),
                        tool_output: message.tool_output.clone(),
                        doc_refs: refs.clone(),
                        content_summary: message.content.clone(),
                        datasets: datasets.clone(),
                        todo_versions: todo_versions.clone(),
                        read_more_source: read_more_source.clone(),
                        draft: Some(draft),
                    }
                    if !refs.is_empty() && message.tool_name != "cite_documents" {
                        DocRefsDisclosure { tool_name: message.tool_name.clone(), refs }
                    }
                }
            }
        }
        // Deliberately unlike both neighbours it could be confused with: not the blue
        // user bubble, because the user did not write it, and not the red error card,
        // because nothing has gone wrong. A narrow inset note, aligned with the
        // assistant's own column, reads as the turn talking to itself.
        // Collapsed: the text is an instruction the system gave the agent, which a person
        // reads only to see why the agent went on.
        ChatRole::Nag => rsx! {
            details {
                class: "x-chat-nag",
                style: "align-self: flex-start; max-width: 88%; background: white; \
                        color: #475569; border-left: 3px solid #AAAAAA33; padding: 6px 12px; \
                        border-radius: 0 8px 8px 0; font-size: 0.9em; {ring}",
                summary { style: "cursor: pointer; font-weight: 600;", "Instruction to the agent" }
                div {
                    style: "margin-top: 4px; white-space: pre-wrap; word-break: break-word;",
                    "{message.content}"
                }
            }
        },
        ChatRole::Compaction => rsx! {
            CompactionLine { content: message.content.clone(), ring: ring.to_string() }
        },
        ChatRole::Error => {
            let retries = message.parsed_retry_errors();
            rsx! {
                div {
                    style: "align-self: flex-start; background: #FEF2F2; color: #991B1B; \
                            max-width: 88%; border: 1px solid #FECACA; padding: 10px 14px; \
                            border-radius: 12px; {ring}",
                    div { "{message.content}" }
                    // The final error is often the least informative of the set. A
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

#[component]
fn CompactionLine(content: String, ring: String) -> Element {
    let value: serde_json::Value = serde_json::from_str(&content).unwrap_or_default();
    let state = value.get("state").and_then(|v| v.as_str()).unwrap_or_default();
    let before = value.get("tokens_before").and_then(|v| v.as_u64()).unwrap_or(0);
    let target = value.get("target").and_then(|v| v.as_u64()).unwrap_or(0);
    let after = value.get("tokens_after").and_then(|v| v.as_u64()).unwrap_or(0);
    let steps = value.get("steps_summarised").and_then(|v| v.as_u64()).unwrap_or(0);
    let reached = value.get("target_reached").and_then(|v| v.as_bool()).unwrap_or(true);
    // A version 2 line lists the state of each summary part. A version 3 line has one
    // summary, and `summary_state` is `failed` when it gave no text.
    let failed = value.get("part_states").and_then(|v| v.as_array()).map(|parts| {
        parts.iter().filter(|part| part.as_str() == Some("failed")).count()
    }).unwrap_or(0);
    let summary_failed = value.get("summary_state").and_then(|v| v.as_str()) == Some("failed");
    let mut record_open = use_signal(|| false);
    let line = if state == "running" {
        format!("Compacting the context: {before} tokens to a target of {target}.")
    } else if summary_failed {
        format!("The summary of the earlier steps failed. The model received the earlier steps unchanged, {after} tokens.")
    } else {
        format!("Context compacted: {steps} steps summarised, {before} tokens to {after}.")
    };
    rsx! {
        div { class: "x-chat-compaction", style: "align-self: stretch; font-size: 12px; color: #475569; {ring}",
            "{line}"
            if !reached && !summary_failed { span { " The context stays above the target of {target}." } }
            if failed > 0 { span { " {failed} summary parts failed. The record holds the lists only." } }
            if let Some(record) = value.get("record").and_then(|v| v.as_str()).filter(|r| !r.is_empty()) {
                button {
                    style: "margin-left: 8px; background: none; border: none; color: #4F46E5; cursor: pointer; text-decoration: underline;",
                    onclick: move |_| {
                        let next = !*record_open.peek();
                        record_open.set(next);
                    },
                    "Show the record"
                }
                if *record_open.read() { MarkdownishText { text: record.to_string() } }
            }
        }
    }
}

/// The model's reasoning trace, collapsed by default. It narrates how the answer was
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
/// of scrolling. The summary line carries the two facts worth having without opening it
/// (which tool ran and how many documents it found), because a bare chevron makes the
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
            if *open.read() && matches!(tool.as_str(), "search_collections" | "search_passages") {
                // A search row lists its documents as lines, each with an action that
                // opens the document at the query that matched it.
                for doc in refs.into_iter() {
                    ChatDocRefRow { key: "{doc.file_hash}", doc }
                }
            } else if *open.read() {
                // Keyed on the hash alone. Appending the loop index made two rows for the
                // same document distinct nodes, so any duplicate that reached here was
                // guaranteed to render twice; `extract_doc_refs` now collapses them, and
                // the key no longer hides it if that ever stops being true.
                for (i, doc) in refs.into_iter().enumerate() {
                    ChatDocRefRow { key: "{i}-{doc.file_hash}", doc }
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

/// Message for a nonempty unverified quote.
///
/// `quote_reason` values are written by `collection_search_server.citations`. An empty
/// reason is a stored message that never recorded one, so the wording stays the
/// message this page already showed.
fn unverified_quote_message(reason: &str) -> &'static str {
    match reason {
        "short" => "Unverified quote. The quoted span is too short to check.",
        "lookup_failed" => "Unverified quote. The document text could not be read.",
        _ => "Unverified quote. This wording was not found in the document.",
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
pub(super) fn DocumentCitationCards(
    sources: Vec<ChatDocRef>,
    /// See [`conflicting_handles`]. An entry with such a handle gets no jump target.
    #[props(default)]
    conflicting: Vec<String>,
) -> Element {
    let mut seen = HashSet::new();
    let grouped = merge_citations(sources.clone()).into_iter()
        .filter(|doc| seen.insert(doc.file_hash.clone())).collect::<Vec<_>>();
    rsx! {
        div {
            style: "margin-top: 10px; border-top: 1px solid #E2E8F0; padding-top: 8px;",
            div {
                style: "display: flex; flex-direction: column; gap: 8px;",
                for (index, doc) in grouped.into_iter().enumerate() {
                    div {
                        key: "{doc.handle}-{doc.file_hash}",
                        "data-citation-handle": if conflicting.contains(&doc.handle) { String::new() } else { doc.handle.clone() },
                        "data-citation-aliases": serde_json::to_string(&sources.iter().filter(|source| source.file_hash == doc.file_hash).map(|source| source.handle.clone()).collect::<Vec<_>>()).unwrap_or_default(),
                        "data-conflicting-handle": conflicting.contains(&doc.handle).to_string(),
                        class: "x-source-entry",
                        style: "display: flex; gap: 8px; align-items: flex-start;",
                        if !doc.handle.is_empty() {
                            div {
                                style: "
                                    flex-shrink: 0; font-size: 12px; font-weight: 600;
                                    color: #334155; background: #F8FAFC;
                                    border: 1px solid #E5E7EB; border-radius: 5px;
                                    padding: 1px 5px; margin-top: 10px;
                                ",
                                "{doc.handle}"
                            }
                        }
                        div {
                            style: "flex: 1 1 auto; min-width: 0;",
                            if !doc.why.is_empty() { div { style: "font-size: 13px; color: #475569; padding: 0 8px;", "{doc.why}" } }
                            ChatDocRefCard { doc: doc.clone(), index: index as u64, passages: sources.iter().filter(|source| source.file_hash == doc.file_hash).cloned().collect::<Vec<_>>() }
                            if conflicting.contains(&doc.handle) {
                                div {
                                    style: "font-size: 12px; color: #B45309; padding: 0 4px 2px 4px;",
                                    "Citations of this conversation give {doc.handle} to more than one document. The answer links it to none of them."
                                }
                            }
                            // Older stored citations can contain unverified quotes.
                            if !doc.quote.is_empty() && !doc.quote_verified {
                                div {
                                    style: "
                                        font-size: 12px; color: #92400E; background: #FFFBEB;
                                        border: 1px solid #FDE68A; border-radius: 6px;
                                        padding: 3px 7px; margin: 2px 4px;
                                    ",
                                    "{unverified_quote_message(&doc.quote_reason)}"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}


#[cfg(test)]
mod tests {
    use super::*;
    use crate::components::chat_components::markdown_text::{
        Block, Span, mark_handles, parse_blocks,
    };

    fn test_doc() -> ChatDocRef {
        serde_json::from_value(serde_json::json!({"collection_dataset":"c_d", "file_hash":"a".repeat(64)})).unwrap()
    }

    #[test]
    fn sources_appear_once_across_answers_and_unmarked_sources_follow_the_answer() {
        let docs = vec![ChatDocRef { handle: "[D1]".into(), file_hash: "a".repeat(64),
            collection_dataset: "c_d".into(), ..test_doc() },
            ChatDocRef { handle: "[D2]".into(), file_hash: "b".repeat(64),
            collection_dataset: "c_d".into(), ..test_doc() }];
        let refs = serde_json::to_string(&docs).unwrap();
        let messages = vec![row(0, ChatRole::User, "", "", "Question"),
            row(1, ChatRole::Tool, "cite_documents", &refs, ""),
            row(2, ChatRole::Assistant, "", "", "First [D1]. Again [D1]."),
            row(3, ChatRole::User, "", "", "Next question"),
            row(4, ChatRole::Assistant, "", "", "Earlier source [D1].")];
        let places = citation_placements(&messages, &docs, &[]);
        assert_eq!(places[&2].inline, vec!["[D1]"]);
        assert_eq!(places[&2].documents.iter().map(|doc| doc.handle.as_str()).collect::<Vec<_>>(), vec!["[D2]"]);
        assert!(places[&4].inline.is_empty() && places[&4].documents.is_empty());
    }

    #[test]
    fn unmarked_pages_and_document_aliases_share_one_source_card() {
        let mut first = test_doc();
        first.handle = "[D1]".into();
        let mut alias = first.clone();
        alias.handle = "[D2]".into();
        alias.collection_dataset = "another_dataset".into();
        let failed = test_doc();
        let docs = vec![first, alias, failed];
        let page = serde_json::from_value(serde_json::json!({"handle":"[W1]", "url":"https://example.org/",
            "final_url":"https://example.org/", "title":"Example", "artifact_id":"source-id",
            "version":"version", "terms":["Exact source"], "quotes":["Exact source text"], "quote_verified":true})).unwrap();
        let messages = vec![row(0, ChatRole::User, "", "", "Question"),
            row(1, ChatRole::Tool, "cite_documents", &serde_json::to_string(&docs).unwrap(), ""),
            row(2, ChatRole::Assistant, "", "", "First [D1], alias [D2].")];
        let places = citation_placements(&messages, &docs, &[page]);
        assert_eq!(places[&2].inline, vec!["[D1]"]);
        assert!(places[&2].documents.is_empty());
        assert_eq!(places[&2].pages.len(), 1);
    }

    #[test]
    fn citations_in_superseded_answers_do_not_consume_the_card() {
        let docs = vec![ChatDocRef { handle: "[D1]".into(), file_hash: "a".repeat(64), ..test_doc() }];
        let messages = vec![row(0, ChatRole::Assistant, "", "", "Draft [D1]."),
            row(1, ChatRole::Nag, CITATION_NOTE_NAME, "", "Repair"),
            row(2, ChatRole::Assistant, "", "", "Final [D1].")];
        let places = citation_placements(&messages, &docs, &[]);
        assert!(!places.contains_key(&0));
        assert_eq!(places[&2].inline, vec!["[D1]"]);
    }

    #[test]
    fn citation_context_uses_the_newest_earlier_search_for_its_document() {
        let hash = "a".repeat(64);
        let mut search = row(1, ChatRole::Tool, "search_collections", "", "");
        search.tool_input = r#"{"queries":["old term"]}"#.into();
        search.tool_output = serde_json::json!({"items":[{
            "file_hash": &hash[..16], "collectionname":"c", "dataset":"d", "snippet":"old passage"
        }]}).to_string();
        let mut newer = search.clone();
        newer.seq = 2;
        newer.tool_input = r#"{"queries":["new term"]}"#.into();
        newer.tool_output = newer.tool_output.replace("old passage", "new passage");
        let citation = row(3, ChatRole::Tool, "cite_documents", &serde_json::json!([{
            "file_hash":hash, "collectionname":"c", "collection_dataset":"c_d", "term":""
        }]).to_string(), "");
        let mut future = newer.clone();
        future.seq = 4;
        future.tool_output = future.tool_output.replace("new passage", "future passage");
        let mut messages = vec![search, newer, citation, future];
        let [doc]: [ChatDocRef; 1] = citation_search_context(&messages, 2).try_into().unwrap();
        assert_eq!(doc.term, "new term");
        assert_eq!(doc.search_snippet, "new passage");
        messages[2].doc_refs = messages[2].doc_refs.replace(r#""term":"""#, r#""term":"explicit term""#);
        assert_eq!(citation_search_context(&messages, 2)[0].term, "explicit term");
    }

    #[test]
    fn a_paged_search_item_names_its_dataset() {
        let page = serde_json::json!({
            "items": [{
                "collectionname": "testdata",
                "file_hash": "abc123",
                "path": "/reports/one.pdf",
                "title": "one.pdf",
                "snippet": "",
                "canonical_file_type": "pdf",
                "dataset": "testfiles"
            }]
        });
        let mut datasets = HashMap::new();
        collect_datasets(&page, &mut datasets, 0);
        assert_eq!(
            datasets.get("abc123").map(String::as_str),
            Some("testdata_testfiles")
        );
    }

    fn row(seq: u32, role: ChatRole, tool_name: &str, doc_refs: &str, content: &str) -> ChatMessageItem {
        ChatMessageItem {
            seq,
            role,
            content: content.to_string(),
            tool_name: tool_name.to_string(),
            tool_input: String::new(),
            tool_output: String::new(),
            doc_refs: doc_refs.to_string(),
            created_at: String::new(),
            created_ms: String::new(),
            agent_duration_ms: 0,
            retry_errors: String::new(),
            reasoning: String::new(),
            context_tokens: 0,
            peak_context_tokens: 0,
            context_window: 0,
            streaming: false,
            usage_json: String::new(),
        }
    }

    /// The spans of the answer `text` as the transcript marks them.
    fn marked(messages: &[ChatMessageItem], run_cited: &[String], text: &str) -> Vec<Span> {
        let issued = issued_handles(messages, run_cited);
        match mark_handles(parse_blocks(text), &issued, &[]).into_iter().next() {
            Some(Block::Paragraph(spans)) => spans,
            other => panic!("expected one paragraph, got {other:?}"),
        }
    }

    /// A transcript whose only citation row issued `[D1]`, then a chat answer.
    fn transcript_with_d1(answer: &str) -> Vec<ChatMessageItem> {
        vec![
            row(1, ChatRole::User, "", "", "question"),
            row(
                2,
                ChatRole::Tool,
                "cite_documents",
                r#"[{"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa"}]"#,
                "",
            ),
            row(3, ChatRole::Assistant, "", "", answer),
        ]
    }

    fn citation_note(seq: u32) -> ChatMessageItem {
        row(seq, ChatRole::Nag, CITATION_NOTE_NAME, "", "Call cite_documents")
    }

    #[test]
    fn an_answer_before_a_citation_round_with_a_new_answer_is_replaced() {
        let d1 = r#"[{"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa"}]"#;
        let d2 = r#"[{"handle": "[D2]", "collection_dataset": "c_ds", "file_hash": "bb"}]"#;
        let messages = vec![
            row(1, ChatRole::User, "", "", "question"),
            row(2, ChatRole::Tool, "cite_documents", d1, ""),
            row(3, ChatRole::Assistant, "", "", "first [D1] and Enron memo"),
            citation_note(4),
            row(5, ChatRole::Tool, "cite_documents", d2, ""),
            row(6, ChatRole::Assistant, "", "", "second [D1] [D2]"),
            row(7, ChatRole::User, "", "", "next"),
            row(8, ChatRole::Assistant, "", "", "third"),
        ];
        assert!(answer_replaced(&messages, 2));
        assert!(!answer_replaced(&messages, 5));
        assert!(!answer_replaced(&messages, 7));
        let handles: Vec<String> = citations_for_answer(&messages, 5)
            .into_iter()
            .map(|r| r.handle)
            .collect();
        assert_eq!(handles, vec!["[D1]", "[D2]"]);
    }

    #[test]
    fn a_nag_between_the_citation_call_and_the_answer_keeps_the_citations() {
        let d1 = r#"[{"handle": "[D1]", "collection_dataset": "c_ds", "file_hash": "aa"}]"#;
        let messages = vec![
            row(1, ChatRole::User, "", "", "question"),
            row(2, ChatRole::Tool, "cite_documents", d1, ""),
            row(3, ChatRole::Nag, "", "", "continue"),
            row(4, ChatRole::Assistant, "", "", "answer [D1]"),
        ];
        let handles: Vec<String> = citations_for_answer(&messages, 3)
            .into_iter()
            .map(|r| r.handle)
            .collect();
        assert_eq!(handles, vec!["[D1]"]);
    }

    #[test]
    fn a_citation_round_with_no_new_answer_or_another_note_keeps_the_answer() {
        let messages = vec![
            row(1, ChatRole::User, "", "", "question"),
            row(2, ChatRole::Assistant, "", "", "first"),
            citation_note(3),
            row(4, ChatRole::Tool, "cite_documents", "", ""),
            row(5, ChatRole::User, "", "", "next"),
            row(6, ChatRole::Assistant, "", "", "answer"),
            row(7, ChatRole::Nag, "", "", "continue"),
            row(8, ChatRole::Assistant, "", "", "later"),
        ];
        assert!(!answer_replaced(&messages, 1));
        assert!(!answer_replaced(&messages, 5));
    }

    #[test]
    fn tool_and_instruction_rows_share_a_group_and_plain_todos_split_it() {
        let messages = vec![
            row(1, ChatRole::Tool, "search_collections", "", ""),
            row(2, ChatRole::Nag, "", "", "continue"),
            row(3, ChatRole::Tool, "mark_todo", "", ""),
            row(4, ChatRole::Tool, "read_documents", "", ""),
        ];
        assert_eq!(tool_run_segments(&messages, true), vec![(0, 2), (2, 3), (3, 4)]);
        assert_eq!(tool_run_segments(&messages, false), vec![(0, 4)]);
    }

    #[test]
    fn live_tools_join_the_final_stored_tool_group() {
        let tools = vec![
            row(1, ChatRole::Tool, "search_collections", "", ""),
            row(2, ChatRole::Nag, "", "", "continue"),
        ];
        let segments = tool_run_segments(&tools, true);
        assert_eq!(live_group_start(&tools, &segments, true, true), Some(0));

        let closed = vec![
            row(1, ChatRole::Tool, "search_collections", "", ""),
            row(2, ChatRole::Assistant, "", "", "answer"),
        ];
        let segments = tool_run_segments(&closed, true);
        assert_eq!(live_group_start(&closed, &segments, true, true), None);
    }

    #[test]
    fn a_question_uses_the_tool_input_inside_its_envelope() {
        let mut question = row(1, ChatRole::Tool, "ask_user", "", "");
        question.tool_input = r#"{"input":{"question":"Which source should I read?"}}"#.to_string();
        assert_eq!(asked_question(&[question]), "Which source should I read?");
    }

    #[test]
    fn two_questions_follow_the_group_and_the_first_is_the_answer() {
        let tool = row(1, ChatRole::Tool, "read_todo", "", "");
        let mut first = row(2, ChatRole::Tool, "ask_user", "", "");
        first.tool_input = r#"{"input":{"question":"First?"}}"#.to_string();
        let mut second = row(3, ChatRole::Tool, "ask_user", "", "");
        second.tool_input = r#"{"input":{"question":"Second?"}}"#.to_string();
        let messages = vec![tool, first, second];
        assert_eq!(tool_run_segments(&messages, true), vec![(0, 1), (1, 2), (2, 3)]);
        assert_eq!(asked_question(&messages), "First?");
    }

    #[test]
    fn a_live_todo_splits_the_tool_groups() {
        let names = ["read_documents", "mark_todo", "search_collections"];
        let rows: Vec<common::chat_types::StreamToolRow> = names.iter().enumerate().map(|(i, name)| {
            common::chat_types::StreamToolRow {
                seq: i as u32 + 1, tool_call_index: i as u32,
                tool_name: (*name).to_string(), summary: String::new(), done: false,
                elapsed_ms: 0,
            }
        }).collect();
        assert_eq!(live_tool_segments(&rows, true), vec![(0, 1, false), (1, 2, true), (2, 3, false)]);
        assert_eq!(live_tool_segments(&rows, false), vec![(0, 3, false)]);
    }

    #[test]
    fn read_more_identifies_the_search_that_issued_its_handle() {
        let mut search = row(4, ChatRole::Tool, "search_collections", "", "");
        search.tool_output = r#"{"items":[],"more":"first"}"#.to_string();
        let mut second = row(5, ChatRole::Tool, "read_more", "", "");
        second.tool_input = r#"{"continuation":"first"}"#.to_string();
        second.tool_output = r#"{"items":[],"more":"second"}"#.to_string();
        let mut third = row(6, ChatRole::Tool, "read_more", "", "");
        third.tool_input = r#"{"continuation":"second"}"#.to_string();
        let messages = vec![search, second, third];
        assert_eq!(read_more_source(&messages, 2), Some(("search_collections".to_string(), 4, 3)));
    }

    #[test]
    fn read_more_identifies_a_document_item_handle() {
        let mut read = row(4, ChatRole::Tool, "read_documents", "", "");
        read.tool_output = r#"{"items":[{"path":"/a","more":"document-next"}]}"#.to_string();
        let mut next = row(5, ChatRole::Tool, "read_more", "", "");
        next.tool_input = r#"{"continuation":"document-next"}"#.to_string();
        assert_eq!(read_more_source(&[read, next], 1), Some(("read_documents".to_string(), 4, 2)));
    }

    #[test]
    fn a_handle_from_a_stored_run_citation_stays_a_chip() {
        let messages = transcript_with_d1("See [D2].");
        let spans = marked(&messages, &["[D2]".to_string()], "See [D2].");
        assert!(spans.contains(&Span::Handle("[D2]".to_string())), "{spans:?}");
    }

    #[test]
    fn a_handle_given_to_two_documents_is_conflicting_and_one_document_is_not() {
        let cite = |seq: u32, refs: &str| row(seq, ChatRole::Tool, "cite_documents", refs, "");
        let messages = vec![
            cite(1, r#"[{"handle": "[D1]", "collection_dataset": "c", "file_hash": "aaaaaaaaaaaaaaaa1111"},
                        {"handle": "[D2]", "collection_dataset": "c", "file_hash": "cccccccccccccccc"}]"#),
            cite(2, r#"[{"handle": "[D1]", "collection_dataset": "c", "file_hash": "bbbbbbbbbbbbbbbb"},
                        {"handle": "[D2]", "collection_dataset": "c", "file_hash": "cccccccccccccccc2222"}]"#),
        ];
        assert_eq!(conflicting_handles(&messages), vec!["[D1]".to_string()]);
        let blocks = crate::components::chat_components::markdown_text::mark_handles(
            parse_blocks("See [D1] and [D2]."),
            &["[D1]".to_string(), "[D2]".to_string()],
            &conflicting_handles(&messages),
        );
        let Block::Paragraph(spans) = &blocks[0] else {
            panic!("not a paragraph");
        };
        assert!(spans.contains(&Span::ConflictingHandle("[D1]".to_string())), "{spans:?}");
        assert!(spans.contains(&Span::Handle("[D2]".to_string())), "{spans:?}");
    }

    #[test]
    fn a_handle_that_no_citation_of_the_session_issued_is_marked() {
        let messages = transcript_with_d1("See [D3].");
        let spans = marked(&messages, &["[D2]".to_string()], "See [D3].");
        assert!(spans.contains(&Span::UncitedHandle("[D3]".to_string())), "{spans:?}");
    }

    #[test]
    fn a_handle_that_a_transcript_citation_row_issued_is_a_chip() {
        let messages = transcript_with_d1("See [D1].");
        let spans = marked(&messages, &[], "See [D1].");
        assert!(spans.contains(&Span::Handle("[D1]".to_string())), "{spans:?}");
    }
}
