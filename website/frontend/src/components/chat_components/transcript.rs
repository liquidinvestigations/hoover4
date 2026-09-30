//! Transcript of a chat session: user bubbles, assistant markdown, tools, doc cards.

use std::collections::HashMap;

use common::chat_types::{ChatDocRef, ChatMessageItem, ChatRole, StreamTurn, merge_citations};
use common::storage_tree::compose_collection_dataset;
use dioxus::prelude::*;

use crate::components::chat_components::{
    doc_ref_card::{ChatDocRefCard, ChatDocRefRow},
    markdown_text::{MarkdownishText, source_anchor_id},
    plan_card::{PlanCard, PlanCardContext},
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
    /// The plan run id of a deep-research request that has no planner answer row yet. The
    /// transcript shows its card at the end while the planner writes the plan.
    #[props(default)]
    pending_plan: Option<String>,
    /// The handles that the `cite_documents` results of every run of the session issued,
    /// sub-agents included. A sub-agent writes no transcript row, so the rows alone miss
    /// its handles.
    #[props(default)]
    run_cited_handles: Vec<String>,
    /// Finished delegation batches read with the stored transcript.
    #[props(default)]
    subagent_batches: Vec<common::chat_types::SubagentBatchState>,
    #[props(default)]
    todo_versions: Vec<common::chat_types::TodoSnapshot>,
    /// Plain chats keep each todo write outside a tool group.
    #[props(default)]
    deep_research: bool,
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
    // Handles are allocated for the whole conversation, so a handle that any citation of
    // any run gave is a real one. The answers mark every other handle as not cited.
    let cited_handles = issued_handles(&messages, &run_cited_handles);
    let conflicting = conflicting_handles(&messages);
    let subagent_runs = stream
        .as_ref()
        .map(|t| t.subagent_runs.clone())
        .unwrap_or_default();
    // The newest plan run of the transcript and the seq of the last row. The line that
    // says why a research run stopped goes under the last row.
    let last_plan_run = messages
        .iter()
        .rev()
        .find_map(|m| m.plan_reference())
        .map(|r| (r.run_id, messages.last().map(|m| m.seq).unwrap_or_default()));
    // The pending card goes once a planner answer row names the same plan run.
    let pending_card = pending_plan.filter(|run_id| {
        !messages
            .iter()
            .filter_map(|m| m.plan_reference())
            .any(|r| &r.run_id == run_id)
    });
    // One row as `MessageEntry`. A run of tool rows renders the same entries inside its
    // group when the group is open.
    let entry = |i: usize| -> Element {
        let m = messages[i].clone();
        let highlight = active_msg == Some(i);
        // The strip belongs to the ANSWER, and the citations arrive on the tool rows before
        // it. Collected here rather than inside `MessageEntry`, which sees one message and
        // cannot know which turn it closes.
        let sources = if m.role == ChatRole::Assistant {
            citations_for_answer(&messages, i)
        } else {
            Vec::new()
        };
        // A planner answer that a later answer of the same plan run follows shows its card
        // as an earlier version, with no action.
        let plan_superseded = m.plan_reference().is_some_and(|r| {
            messages[i + 1..]
                .iter()
                .filter_map(|later| later.plan_reference())
                .any(|later| later.run_id == r.run_id)
        });
        let plan_question = if m.plan_reference().is_some() {
            asked_question(&messages[..i])
        } else {
            String::new()
        };
        let plan_question_options = if plan_question.is_empty() {
            Vec::new()
        } else {
            asked_options(&messages[..i])
        };
        let read_more_source = if m.tool_name == "read_more" {
            read_more_source(&messages, i)
        } else { None };
        let repeat_question = m.role == ChatRole::Assistant
            && asked_question(&messages[..i]) == m.content
            && !m.content.is_empty();
        // Only a delegation row reads the entries. The others get an empty list, so a poll
        // that moves a sub-agent re-renders that row alone.
        let runs = if m.tool_name == "run_subagent" || !m.plan_reference_json.is_empty() {
            subagent_runs.clone()
        } else {
            Vec::new()
        };
        let batches = if m.tool_name == "run_subagent" {
            subagent_batches.clone()
        } else {
            Vec::new()
        };
        rsx! {
            MessageEntry {
                key: "{m.seq}",
                message: m,
                highlight,
                sources,
                cited_handles: cited_handles.clone(),
                conflicting_handles: conflicting.clone(),
                datasets: datasets.clone(),
                subagent_runs: runs,
                subagent_batches: batches,
                todo_versions: todo_versions.clone(),
                plan_superseded,
                plan_question,
                plan_question_options,
                read_more_source,
                repeat_question,
                draft,
            }
        }
    };
    // Runs of tool and instruction rows, and every other row on its own, as index ranges.
    let segments = tool_run_segments(&messages, !deep_research);
    let live_tools = stream
        .as_ref()
        .map(|turn| turn.tool_rows.clone())
        .unwrap_or_default();
    let live_segments = live_tool_segments(&live_tools, !deep_research);
    let can_join = live_segments.first().is_some_and(|(_, _, todo)| !todo);
    let live_group_start = live_group_start(&messages, &segments, !deep_research, can_join);
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
            if let (Some((run_id, last_seq)), None) = (last_plan_run.clone(), stream.as_ref()) {
                ResearchEndLine { run_id, last_seq }
            }
            if let Some(run_id) = pending_card {
                PlanCard {
                    key: "pending-plan-{run_id}",
                    reference: common::plan_types::ChatPlanReference {
                        plan_id: String::new(),
                        run_id: run_id.clone(),
                        reviewed_version: 0,
                    },
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
                if (m.role == ChatRole::Tool || m.role.is_instruction())
                    && (messages[*start].role == ChatRole::Tool
                        || messages[*start].role.is_instruction())
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
    use_effect(move || {
        if live && !*open.peek() {
            open.set(true);
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
/// document, and the sources strip names the conflict.
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

fn asked_options(messages: &[ChatMessageItem]) -> Vec<String> {
    messages.iter().rev()
        .take_while(|message| message.role == ChatRole::Tool || message.role.is_instruction())
        .filter(|message| message.tool_name == "ask_user")
        .last()
        .and_then(|message| serde_json::from_str::<serde_json::Value>(&message.tool_input).ok())
        .map(|value| value.get("input").cloned().unwrap_or(value))
        .and_then(|value| value.get("options").and_then(|options| options.as_array()).cloned())
        .unwrap_or_default().iter().filter_map(|option| option.as_str().map(str::to_string)).collect()
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
    draft: Signal<String>,
    /// The documents this answer cited, for the strip beneath it. Empty for every role
    /// but the assistant's.
    #[props(default)]
    sources: Vec<ChatDocRef>,
    /// The handles that the citations of the conversation gave (`issued_handles`).
    #[props(default)]
    cited_handles: Vec<String>,
    /// See [`conflicting_handles`].
    #[props(default)]
    conflicting_handles: Vec<String>,
    /// See [`dataset_by_hash`]. Read by the entities card and by nothing else.
    #[props(default)]
    datasets: HashMap<String, String>,
    /// The sub-agent entries of the open turn, for a `run_subagent` row and a row with a
    /// plan card only.
    #[props(default)]
    subagent_runs: Vec<common::chat_types::SubagentRunEntry>,
    /// Terminal depth-one entries of a finished delegation batch.
    #[props(default)]
    subagent_batches: Vec<common::chat_types::SubagentBatchState>,
    #[props(default)]
    todo_versions: Vec<common::chat_types::TodoSnapshot>,
    /// True when a later planner answer names the same plan run.
    #[props(default)]
    plan_superseded: bool,
    /// The planner question that ended this answer's tool group.
    #[props(default)]
    plan_question: String,
    #[props(default)]
    plan_question_options: Vec<String>,
    #[props(default)]
    read_more_source: Option<(String, u32, u32)>,
    #[props(default)]
    repeat_question: bool,
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
            let plan = message.plan_reference();
            rsx! {
                div {
                    style: "align-self: stretch; max-width: 96%; padding: 4px 2px; {ring}",
                    if !message.reasoning.is_empty() {
                        ReasoningDisclosure { reasoning: message.reasoning.clone() }
                    }
                    if !repeat_question {
                        div {
                            "data-chat-answer": "{message.seq}",
                            MarkdownishText {
                                text: message.content.clone(),
                                cited_handles: Some(cited_handles.clone()),
                                conflicting_handles: conflicting_handles.clone(),
                            }
                        }
                    } else {
                        // The question card above shows this text. A browser test reads
                        // the answer of a turn that asked the user from this element.
                        span { "data-chat-asked": "{message.seq}", hidden: true, "{message.content}" }
                    }
                    if !sources.is_empty() {
                        SourcesStrip { sources: sources.clone(), conflicting: conflicting_handles.clone() }
                    }
                    if let Some(reference) = plan {
                        PlanCard {
                            reference,
                            subagent_runs: subagent_runs.clone(),
                            superseded: plan_superseded,
                            question: plan_question.clone(),
                            question_options: plan_question_options.clone(),
                        }
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
                div { "data-todo-change": if is_todo_write(&message) { "true" } else { "false" }, style: "display: flex; flex-direction: column; gap: 8px; {ring}",
                    ToolCard {
                        tool_name: message.tool_name.clone(),
                        tool_input: message.tool_input.clone(),
                        tool_output: message.tool_output.clone(),
                        doc_refs: refs.clone(),
                        content_summary: message.content.clone(),
                        datasets: datasets.clone(),
                        subagent_runs: subagent_runs.clone(),
                        subagent_batches: subagent_batches.clone(),
                        todo_versions: todo_versions.clone(),
                        read_more_source: read_more_source.clone(),
                        draft: Some(draft),
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
        // Collapsed: the text is an instruction the system gave the agent, which a person
        // reads only to see why the agent went on.
        ChatRole::Nag => rsx! {
            details {
                class: "x-chat-nag",
                style: "align-self: flex-start; max-width: 88%; background: #F5F3FF; \
                        color: #5B21B6; border-left: 3px solid #A78BFA; padding: 6px 12px; \
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

/// "Research stopped: <reason>." under the last row, for a terminal plan run that stopped
/// short. Read again when a row is added, because the last rows of a run arrive as it ends.
#[component]
fn ResearchEndLine(run_id: String, last_seq: u32) -> Element {
    let session_id = try_consume_context::<PlanCardContext>().map(|c| c.session_id);
    let view = use_resource(use_reactive!(|(run_id, last_seq)| async move {
        let _ = last_seq;
        let session_id = session_id?;
        let sid = session_id.peek().clone();
        crate::api::chat_api::chat_plan_view(sid, run_id, 0).await.ok().flatten()
    }));
    let reason = view.read().as_ref().and_then(|v| v.as_ref()).and_then(|v| v.stop_reason());
    rsx! {
        if let Some(reason) = reason {
            div {
                class: "x-chat-research-stopped",
                style: "align-self: flex-start; color: #92400E; font-size: 13px;",
                "Research stopped: {reason}."
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
fn SourcesStrip(
    sources: Vec<ChatDocRef>,
    /// See [`conflicting_handles`]. An entry with such a handle gets no jump target.
    #[props(default)]
    conflicting: Vec<String>,
) -> Element {
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
                        id: if conflicting.contains(&doc.handle) { String::new() } else { source_anchor_id(&doc.handle) },
                        "data-conflicting-handle": conflicting.contains(&doc.handle).to_string(),
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
                            if conflicting.contains(&doc.handle) {
                                div {
                                    style: "font-size: 12px; color: #B45309; padding: 0 4px 2px 4px;",
                                    "Citations of this conversation give {doc.handle} to more than one document. The answer links it to none of them."
                                }
                            }
                            if !doc.why.is_empty() {
                                div {
                                    style: "font-size: 12px; color: #475569; padding: 0 4px 2px 4px;",
                                    "{doc.why}"
                                }
                            }
                            // A quote the server could not find in the document is shown
                            // and marked, never dropped. A model that stops citing is a
                            // worse outcome than a marked quote, and the marker is a fact
                            // the reader can act on. An empty reason is an older stored
                            // result, so the page keeps the wording it already showed.
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
        Block, Span, mark_uncited_handles, parse_blocks,
    };

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
            plan_reference_json: String::new(),
            streaming: false,
        }
    }

    /// The spans of the answer `text` as the transcript marks them.
    fn marked(messages: &[ChatMessageItem], run_cited: &[String], text: &str) -> Vec<Span> {
        let issued = issued_handles(messages, run_cited);
        match mark_uncited_handles(parse_blocks(text), &issued).into_iter().next() {
            Some(Block::Paragraph(spans)) => spans,
            other => panic!("expected one paragraph, got {other:?}"),
        }
    }

    /// A transcript whose only citation row issued `[D1]`, then an organizer answer.
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
    fn a_handle_that_only_a_sub_agent_citation_issued_stays_a_chip() {
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
