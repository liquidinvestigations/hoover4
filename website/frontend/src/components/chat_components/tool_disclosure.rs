//! Compact tool-call line with expand + "search this" link for search_collections.

use common::search_query::SearchQuery;
use dioxus::prelude::*;

use crate::routes::Route;

#[component]
pub fn ToolCallDisclosure(
    tool_name: String,
    tool_input: String,
    tool_output: String,
    content_summary: String,
) -> Element {
    let mut expanded = use_signal(|| false);
    let label = collapsed_label(&tool_name, &tool_input, &content_summary);
    let search_route = search_route_from_tool_input(&tool_name, &tool_input);

    rsx! {
        div {
            style: "align-self: flex-start; max-width: 92%; background: #FFFBEB; \
                    border: 1px solid #FDE68A; border-radius: 10px; padding: 8px 12px; \
                    font-size: 13px; color: #78350F;",
            div {
                style: "display: flex; align-items: center; gap: 10px; flex-wrap: wrap;",
                span { style: "flex: 1; min-width: 0;", "{label}" }
                if let Some(route) = search_route {
                    Link {
                        to: route,
                        style: "color: #4F46E5; text-decoration: underline; font-size: 12px; \
                                white-space: nowrap;",
                        "Search this"
                    }
                }
                button {
                    style: "background: none; border: none; color: #92400E; cursor: pointer; \
                            font-size: 12px; padding: 0;",
                    onclick: move |_| {
                        let next = !*expanded.peek();
                        expanded.set(next);
                    },
                    if *expanded.read() { "Hide" } else { "Expand" }
                }
            }
            if *expanded.read() {
                div {
                    style: "margin-top: 8px; display: flex; flex-direction: column; gap: 6px;",
                    div {
                        style: "font-size: 11px; font-weight: 600; text-transform: uppercase; \
                                letter-spacing: 0.4px; opacity: 0.8;",
                        "Input"
                    }
                    pre {
                        style: "margin: 0; white-space: pre-wrap; word-break: break-word; \
                                font-family: ui-monospace, monospace; font-size: 11px; \
                                background: #FEF3C7; padding: 8px; border-radius: 6px; \
                                max-height: 200px; overflow: auto;",
                        "{tool_input}"
                    }
                    div {
                        style: "font-size: 11px; font-weight: 600; text-transform: uppercase; \
                                letter-spacing: 0.4px; opacity: 0.8;",
                        "Output"
                    }
                    pre {
                        style: "margin: 0; white-space: pre-wrap; word-break: break-word; \
                                font-family: ui-monospace, monospace; font-size: 11px; \
                                background: #FEF3C7; padding: 8px; border-radius: 6px; \
                                max-height: 280px; overflow: auto;",
                        "{tool_output}"
                    }
                }
            }
        }
    }
}

fn collapsed_label(tool_name: &str, tool_input: &str, summary: &str) -> String {
    match tool_name {
        "search_collections" => {
            let query = json_str_field(tool_input, "query").unwrap_or_default();
            let collections = json_string_array(tool_input, "collections");
            let filters = if collections.is_empty() {
                String::new()
            } else {
                format!(" · {}", collections.join(", "))
            };
            if query.is_empty() {
                format!("\u{1f50e} searched collections{filters}")
            } else {
                format!("\u{1f50e} searched collections · {query}{filters}")
            }
        }
        "list_collections" => "\u{1f50e} listed collections".to_string(),
        "get_document_text" => {
            let path = json_str_field(tool_input, "path")
                .or_else(|| json_str_field(tool_input, "file_hash"))
                .unwrap_or_default();
            if path.is_empty() {
                "\u{1f50e} read document".to_string()
            } else {
                format!("\u{1f50e} read document · {path}")
            }
        }
        "list_document_entities" => "\u{1f50e} listed entities".to_string(),
        "show_document" => "\u{1f50e} showed document".to_string(),
        other => {
            let short = if summary.chars().count() > 80 {
                format!("{}\u{2026}", summary.chars().take(80).collect::<String>())
            } else {
                summary.to_string()
            };
            format!("\u{1f50e} {other} · {short}")
        }
    }
}

fn search_route_from_tool_input(tool_name: &str, tool_input: &str) -> Option<Route> {
    if tool_name != "search_collections" {
        return None;
    }
    let query_string = json_str_field(tool_input, "query")?;
    let collections = json_string_array(tool_input, "collections");
    // MCP takes collection *names*; the search page wants collection_dataset ids.
    // Passing names into collection_datasets still lets the user land on /search with
    // the same query text; facet filters are empty (not recorded on the tool input).
    Some(Route::search_page_from_query(SearchQuery {
        query_string,
        collection_datasets: collections,
        facet_filters: Default::default(),
    }))
}

fn json_str_field(raw: &str, key: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(raw).ok()?;
    v.get(key)?.as_str().map(str::to_string)
}

fn json_string_array(raw: &str, key: &str) -> Vec<String> {
    let Ok(v) = serde_json::from_str::<serde_json::Value>(raw) else {
        return Vec::new();
    };
    v.get(key)
        .and_then(|x| x.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|i| i.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}
