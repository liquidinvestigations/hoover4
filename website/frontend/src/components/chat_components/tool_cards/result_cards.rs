//! Cards for collection result pages, documents, todos, citations and plan tools.

use dioxus::prelude::*;
use common::chat_types::ChatDocRef;
use crate::components::chat_components::markdown_text::MarkdownishText;
use crate::components::chat_components::doc_ref_card::ChatDocOpen;
use crate::components::chat_components::tool_disclosure::{search_all_route_from_tool_input, search_route_from_tool_input};
use crate::api::storage_api::list_storage_tree;

use super::{CardShell, json_str, page_rows, tool_content, tool_failure};

fn rows_label(rows: usize, more: bool) -> String {
    let suffix = if more { " · more available" } else { "" };
    format!("{rows} {}{suffix}", if rows == 1 { "row" } else { "rows" })
}

fn numbered_forms(tool_input: &str) -> Vec<String> {
    let input = serde_json::from_str::<serde_json::Value>(tool_input).unwrap_or_default();
    let input = input.get("input").unwrap_or(&input);
    let mut forms = Vec::new();
    if let Some(query) = input.get("query").and_then(|query| query.as_str()).filter(|query| !query.is_empty()) {
        forms.push(query.to_string());
    }
    if let Some(queries) = input.get("queries").and_then(|queries| queries.as_array()) {
        forms.extend(queries.iter().filter_map(|query| query.as_str().map(str::to_string)));
    }
    forms
}

fn search_label(tool_name: &str, tool_input: &str, rows: usize, more: bool,
                fields: &serde_json::Map<String, serde_json::Value>) -> String {
    let value = serde_json::from_str::<serde_json::Value>(tool_input).unwrap_or_default();
    let input = value.get("input").unwrap_or(&value);
    let forms = numbered_forms(tool_input).len();
    let collections = input.get("collectionname").or_else(|| input.get("collections"))
        .map(|v| match v {
            serde_json::Value::Array(names) => names.iter().filter_map(|name| name.as_str()).collect::<Vec<_>>().join(", "),
            serde_json::Value::String(name) => name.clone(),
            _ => String::new(),
        }).unwrap_or_default();
    let filters = input.as_object().into_iter().flat_map(|object| object.iter())
        .filter(|(key, _)| !matches!(key.as_str(), "input" | "query" | "queries" | "collectionname" | "collections"))
        .map(|(key, value)| format!("{key}: {value}"))
        .collect::<Vec<_>>().join(", ");
    let total = fields.get("total").or_else(|| fields.get("total_count")).or_else(|| fields.get("total_documents"))
        .map(|value| format!(" · {value} documents")).unwrap_or_default();
    let mut label = format!("{tool_name} · {forms} forms");
    if !collections.is_empty() { label.push_str(&format!(" in {collections}")); }
    if !filters.is_empty() { label.push_str(&format!(" · {filters}")); }
    label.push_str(&format!(" · {}{total}", rows_label(rows, more)));
    label
}

fn read_label(tool_name: &str, rows: &[serde_json::Value], more: bool) -> String {
    let first = rows.first();
    let path = first.map(|row| json_str(row, "path")).unwrap_or_default();
    let page = first.and_then(|row| row.get("page").or_else(|| row.get("page_number")))
        .map(|value| format!(" · page {value}")).unwrap_or_default();
    let cut = if rows.iter().any(|row| row.get("cut").is_some_and(|value| !value.is_null() && value != false)) { " · cut" } else { "" };
    format!("{tool_name} · {path}{page} · {}{cut}", rows_label(rows.len(), more))
}

#[component]
fn HashLink(row: serde_json::Value, refs: Vec<ChatDocRef>) -> Element {
    let hash = json_str(&row, "file_hash");
    if hash.is_empty() { return rsx! {}; }
    let collection = json_str(&row, "collectionname");
    let found = refs.into_iter().find(|reference| {
        reference.file_hash.starts_with(&hash)
            && (collection.is_empty() || reference.collectionname == collection)
    });
    if let (Some(reference), Some(open)) = (found, try_use_context::<ChatDocOpen>()) {
        let identifier = reference.document_identifier();
        let find = reference.find_query;
        rsx! {
            button {
                style: "background: none; border: none; color: var(--x-link); cursor: pointer; padding: 0; text-decoration: underline;",
                onclick: move |_| open.open.call((identifier.clone(), find.clone())),
                "{hash}"
            }
        }
    } else {
        rsx! { span { "{hash}" } }
    }
}

#[component]
pub fn SearchCard(tool_name: String, tool_input: String, tool_output: String, running: bool,
                  doc_refs: Vec<ChatDocRef>) -> Element {
    let mut expanded = use_signal(|| false);
    let needs_tree = tool_name == "search_collections" &&
        !crate::components::chat_components::tool_disclosure::call_collections(&tool_input).is_empty();
    let collection_tree = use_resource(move || async move {
        if needs_tree { list_storage_tree().await } else { Ok(Vec::new()) }
    });
    let forms = numbered_forms(&tool_input);
    let page = page_rows(&tool_output);
    let (label, rows, fields, failure) = match page {
        Some(page) => (search_label(&tool_name, &tool_input, page.items.len(), page.more, &page.fields), page.items, page.fields, None),
        None => (tool_name.clone(), Vec::new(), serde_json::Map::new(), tool_content(&tool_output).as_ref().and_then(tool_failure)),
    };
    let search_route = if needs_tree {
        collection_tree.read().as_ref().and_then(|result| result.as_ref().ok())
            .and_then(|tree| search_route_from_tool_input(&tool_name, &tool_input, tree))
    } else {
        search_route_from_tool_input(&tool_name, &tool_input, &[])
    };
    let search_all_route = search_all_route_from_tool_input(&tool_name, &tool_input);
    rsx! { CardShell { chip: "Search", label, running, expanded, failure, raw_output: tool_output.clone(),
        badges: rsx! {},
        if let Some(route) = search_route { Link { to: route, "Search this" } }
        if let Some(route) = search_all_route { Link { to: route, "Search every collection" } }
        for (index, form) in forms.iter().enumerate() {
            div { style: "font-size: var(--x-text-xs);", "Form {index}: {form}" }
        }
        div { style: "font-size: var(--x-text-xs); color: var(--x-ink);", "{tool_input}" }
        for (key, value) in fields.iter() {
            if key != "source" { div { style: "font-size: var(--x-text-xs);", "{key}: {value}" } }
        }
        for (index, row) in rows.into_iter().enumerate() {
            div { key: "{index}", style: "border-top: 1px solid; border-top-color: var(--x-border); padding-top: 6px;",
                for (key, value) in row.as_object().into_iter().flat_map(|row| row.iter()) {
                    if key != "snippet" && key != "file_hash" { div { style: "font-size: var(--x-text-xs);", "{key}: {value}" } }
                }
                HashLink { row: row.clone(), refs: doc_refs.clone() }
                if !json_str(&row, "snippet").is_empty() {
                    MarkdownishText { text: json_str(&row, "snippet") }
                }
            }
        }
    }}
}

#[component]
pub fn ReadCard(tool_name: String, tool_input: String, tool_output: String, running: bool,
                doc_refs: Vec<ChatDocRef>) -> Element {
    let mut expanded = use_signal(|| false);
    let page = page_rows(&tool_output);
    let (label, rows, failure) = match page {
        Some(page) => (read_label(&tool_name, &page.items, page.more), page.items, None),
        None => (tool_name.clone(), Vec::new(), tool_content(&tool_output).as_ref().and_then(tool_failure)),
    };
    rsx! { CardShell { chip: "Read", label, running, expanded, failure, raw_output: tool_output.clone(),
        badges: rsx! {},
        div { style: "font-size: var(--x-text-xs); color: var(--x-ink);", "{tool_input}" }
        for (index, row) in rows.into_iter().enumerate() {
            ReadRow { key: "{index}", row, refs: doc_refs.clone() }
        }
    }}
}

#[component]
fn ReadRow(row: serde_json::Value, refs: Vec<ChatDocRef>) -> Element {
    let text = read_row_text(&row);
    let excerpt: String = text.chars().take(400).collect();
    let cut = text.chars().count() > 400;
    rsx! {
        div { style: "border-top: 1px solid; border-top-color: var(--x-border); padding-top: 6px; white-space: pre-wrap;",
            for (key, value) in row.as_object().into_iter().flat_map(|row| row.iter()) {
                if key != "text" && key != "file_hash" { div { style: "font-size: var(--x-text-xs);", "{key}: {value}" } }
            }
            HashLink { row: row.clone(), refs }
            div { "{excerpt}" }
            if cut {
                details {
                    summary { "Show full text" }
                    div { "{text}" }
                }
            }
        }
    }
}

fn read_row_text(row: &serde_json::Value) -> String {
    row.as_str().map(str::to_string).unwrap_or_else(|| json_str(row, "text"))
}

#[component]
pub fn CiteCard(tool_input: String, tool_output: String, running: bool, doc_refs: Vec<ChatDocRef>) -> Element {
    let expanded = use_signal(|| false);
    let output = tool_content(&tool_output).unwrap_or_default();
    let citations = output.get("citations").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let input = serde_json::from_str::<serde_json::Value>(&tool_input).unwrap_or_default();
    let input = input.get("input").unwrap_or(&input);
    let requests = input.get("citations").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let missing = citations.iter().filter(|citation| citation.get("quote_reason").and_then(|value| value.as_str()).is_some_and(|value| !value.is_empty())).count();
    let label = format!("cite_documents · {} documents · {missing} quotes not found", citations.len());
    let failure = tool_failure(&output);
    rsx! { CardShell { chip: "Cite", label, running, expanded, failure, raw_output: tool_output.clone(),
        badges: rsx! {},
        div { style: "font-size: var(--x-text-xs); color: var(--x-ink);", "{tool_input}" }
        for (index, citation) in citations.into_iter().enumerate() {
            {
                let request = requests.get(index).cloned().unwrap_or_default();
                let quote = json_str(&request, "quote");
                let why = json_str(&request, "why");
                let reason = json_str(&citation, "quote_reason");
                let check = if citation.get("quote_verified").and_then(|value| value.as_bool()) == Some(true) { "Quote found" } else if !reason.is_empty() { "Quote not found" } else { "Quote not checked" };
                rsx! {
            div { key: "{index}", style: "border-top: 1px solid; border-top-color: var(--x-border); padding-top: 6px; white-space: pre-wrap;",
                div { "{check}" }
                if !quote.is_empty() { div { "Quote: {quote}" } }
                if !why.is_empty() { div { "Reason: {why}" } }
                for (key, value) in citation.as_object().into_iter().flat_map(|citation| citation.iter()) {
                    if key != "file_hash" { div { "{key}: {value}" } }
                }
                HashLink { row: citation.clone(), refs: doc_refs.clone() }
            }
                }
            }
        }
    }}
}

#[component]
pub fn QuestionCard(tool_input: String, tool_output: String, running: bool, draft: Option<Signal<String>>) -> Element {
    let mut expanded = use_signal(|| true);
    let input = serde_json::from_str::<serde_json::Value>(&tool_input).unwrap_or_default();
    let input = input.get("input").unwrap_or(&input);
    let question = input.get("question").and_then(|value| value.as_str()).unwrap_or("The agent asked a question.").to_string();
    let options = input.get("options").and_then(|value| value.as_array()).cloned().unwrap_or_default();
    let failure = tool_content(&tool_output).as_ref().and_then(tool_failure);
    rsx! { CardShell { chip: "Question", label: question, running, expanded, failure, raw_output: tool_output.clone(),
        badges: rsx! {},
        for (index, option) in options.into_iter().enumerate() {
            if let Some(answer) = option.as_str() {
                QuestionOption { key: "{index}", answer: answer.to_string(), draft }
            }
        }
    }}
}

#[component]
fn QuestionOption(answer: String, draft: Option<Signal<String>>) -> Element {
    let chosen = answer.clone();
    rsx! {
        button {
            style: "border: 1px solid; border-color: var(--x-border); background: white; border-radius: 6px; padding: 6px; cursor: pointer;",
            onclick: move |_| { if let Some(mut draft) = draft { draft.set(chosen.clone()); } },
            "{answer}"
        }
    }
}

#[component]
pub fn TodoCard(tool_name: String, tool_input: String, tool_output: String, running: bool,
                todo_versions: Vec<common::chat_types::TodoSnapshot>) -> Element {
    let mut expanded = use_signal(|| false);
    let value = tool_content(&tool_output).unwrap_or_default();
    let failure = tool_failure(&value);
    let version = value.get("version").and_then(|value| value.as_u64()).map(|version| version as u32);
    let current = version.and_then(|version| todo_versions.iter().find(|snapshot| snapshot.version == version)).cloned();
    let previous = version.and_then(|version| version.checked_sub(1))
        .and_then(|version| todo_versions.iter().find(|snapshot| snapshot.version == version)).cloned();
    let label = version.map(|version| format!("{tool_name} · version {version}"))
        .unwrap_or_else(|| tool_name.clone());
    rsx! { CardShell { chip: "Todo", label, running, expanded, failure, raw_output: tool_output.clone(),
        badges: rsx! {},
        if let Some(snapshot) = current {
            div { style: "font-weight: 600;", "{snapshot.goal}" }
            for item in snapshot.items.iter() {
                {
                    let before = previous.as_ref().and_then(|old| old.items.iter().find(|old| old.id == item.id));
                    let changed = before.is_none_or(|old| old != item);
                    let old_status = before.map(|old| old.status.clone());
                    rsx! {
                        div { style: if changed { "font-weight: 700;" } else { "" },
                            if let Some(old_status) = old_status {
                                if changed { s { "{old_status}" } " → " }
                            }
                            "{item.id} {item.status}: {item.text}"
                            if !item.note.is_empty() { " ({item.note})" }
                        }
                    }
                }
            }
        } else {
            div { style: "white-space: pre-wrap;", "{tool_input}" }
            if !running { div { "The list at this version is not stored." } }
        }
    }}
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_row_label_names_a_following_page() {
        assert_eq!(rows_label(2, true), "2 rows · more available");
    }

    #[test]
    fn a_search_page_keeps_all_twenty_one_rows() {
        let rows = (0..21).map(|n| serde_json::json!({"path": format!("/{n}")})).collect::<Vec<_>>();
        let output = serde_json::json!({"items": rows}).to_string();
        let page = page_rows(&output).unwrap();
        assert_eq!(page.items.len(), 21);
        assert_eq!(page.items[20]["path"], "/20");
        assert!(search_label("search_collections", r#"{"queries":["a","b"]}"#, page.items.len(), false, &page.fields).contains("2 forms"));
    }

    #[test]
    fn a_read_header_names_the_first_path_page_and_cut() {
        let rows = vec![serde_json::json!({"path":"/a","page":2,"cut":{"field":"/text"}})];
        assert!(read_label("read_documents", &rows, false).contains("/a · page 2 · 1 row · cut"));
    }

    #[test]
    fn a_cut_document_continuation_keeps_scalar_text_in_order() {
        let first = "First section";
        let second = "Second section".repeat(40);
        let output = serde_json::json!({"items":[first, second]}).to_string();
        let page = page_rows(&output).unwrap();
        let rendered_text: Vec<_> = page.items.iter().map(read_row_text).collect();
        assert_eq!(rendered_text, vec![first.to_string(), second.clone()]);
        assert!(rendered_text[1].chars().count() > 400);
        assert!(read_label("read_more · part 2 of read_documents #4", &page.items, false)
            .contains("part 2 of read_documents #4"));
    }

}

#[component]
pub fn TodoChanges(tool_output: String, running: bool, todo_versions: Vec<common::chat_types::TodoSnapshot>) -> Element {
    let value = tool_content(&tool_output).unwrap_or_default();
    let failure = tool_failure(&value);
    let version = value.get("version").and_then(|value| value.as_u64()).map(|version| version as u32);
    let current = version.and_then(|version| todo_versions.iter().find(|snapshot| snapshot.version == version));
    rsx! {
        div {
            class: "x-chat-todo-list",
            style: "background: #000; color: #fff; border-radius: 6px; padding: 14px 18px; font-size: var(--x-text-md);",
            if let Some(failure) = failure {
                div { role: "alert", "{failure.message}" }
            } else if let Some(current) = current {
                div { style: "font-size: var(--x-text-lg); font-weight: 700; margin-bottom: 8px;", "{current.goal}" }
                ul { style: "margin: 0; padding-left: 20px; list-style: disc;",
                    for item in current.items.clone() {
                        li { key: "{item.id}",
                            if item.status == "done" { s { "{item.text}" } }
                            else { span { "{item.text}" } }
                        }
                    }
                }
            } else if running {
                div { role: "status", "Updating tasks." }
            } else {
                div { "The task list is unavailable." }
            }
        }
    }
}
