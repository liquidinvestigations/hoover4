//! Tool-call card: what ran, a readable summary, then the raw JSON behind a second step.
//!
//! Three levels, because the three audiences are different:
//!
//! 1. **Collapsed**: the tool's type as a chip plus a one-line human summary
//!    ("searched collections · water levels"). This is what someone reading the
//!    conversation wants; it should never be raw JSON.
//! 2. **Expand**: the arguments and results rendered as labelled key/value rows.
//! 3. **Raw JSON**: a second toggle inside the expansion, for debugging.
//!
//! The previous version put level 3 where level 2 belongs, so a card either showed a
//! wall of JSON or, when the writer had not populated the payload columns, nothing.

use common::search_query::SearchQuery;
use dioxus::prelude::*;

use crate::components::chat_components::tool_cards::{tool_content, tool_failure};
use crate::routes::Route;

/// Longest value rendered inline in the readable view before it is clipped. Past this
/// the raw view is the right place to look.
const VALUE_CHARS: usize = 400;

#[component]
pub fn ToolCallDisclosure(
    tool_name: String,
    tool_input: String,
    tool_output: String,
    content_summary: String,
    /// True for a call the stream has reported started but not finished. There is no
    /// output to expand yet, so the card shows a running state instead.
    running: Option<bool>,
) -> Element {
    let mut expanded = use_signal(|| false);
    let mut show_raw = use_signal(|| false);
    let running = running.unwrap_or(false);

    let label = collapsed_label(&tool_name, &tool_input, &content_summary);
    let chip = tool_chip(&tool_name);
    let search_route = search_route_from_tool_input(&tool_name, &tool_input);
    // The collapsed label is built from the *arguments*, so on its own it describes what
    // was asked for and never whether it happened. Any tool can fail; the ones without a
    // card of their own must say so here or nowhere.
    let failure = tool_content(&tool_output).as_ref().and_then(tool_failure);
    let (background, border, ink) = match failure {
        Some(_) => ("#FEF2F2", "#FECACA", "#991B1B"),
        None => ("#FFFBEB", "#FDE68A", "#78350F"),
    };
    let chip_bg = if failure.is_some() { "#FECACA" } else { "#FDE68A" };

    // Older rows (and any writer that has not been taught the payload columns) have
    // empty input/output. Fall back to the summary so the expansion is never blank.
    // An empty disclosure looks like a bug even when the data predates it.
    let input_view = readable_fields(&tool_input);
    let output_view = readable_fields(&tool_output);
    let has_payload = !tool_input.is_empty() || !tool_output.is_empty();

    rsx! {
        div {
            style: "align-self: flex-start; max-width: 92%; background: {background}; \
                    border: 1px solid {border}; border-radius: 10px; padding: 8px 12px; \
                    font-size: 13px; color: {ink};",
            div {
                style: "display: flex; align-items: center; gap: 10px; flex-wrap: wrap;",
                span {
                    style: "flex-shrink: 0; background: {chip_bg}; color: {ink}; \
                            border-radius: 999px; padding: 1px 8px; font-size: 11px; \
                            font-weight: 600; font-family: ui-monospace, monospace;",
                    "{chip}"
                }
                span { style: "flex: 1; min-width: 0;", "{label}" }
                if let Some(f) = failure.clone() {
                    span {
                        title: "{f.message}",
                        style: "flex-shrink: 0; background: #DC2626; color: white; \
                                border-radius: 999px; padding: 1px 7px; font-size: 11px; \
                                font-weight: 600;",
                        "\u{26a0} {f.verb()}"
                    }
                }
                if running {
                    span {
                        style: "flex-shrink: 0; font-size: 12px; font-style: italic; color: #B45309;",
                        "running\u{2026}"
                    }
                }
                if let Some(route) = search_route {
                    Link {
                        to: route,
                        style: "color: #4F46E5; text-decoration: underline; font-size: 12px; \
                                white-space: nowrap;",
                        "Search this"
                    }
                }
                if !running {
                    button {
                        style: "background: none; border: none; color: #92400E; cursor: pointer; \
                                font-size: 12px; padding: 0; white-space: nowrap;",
                        onclick: move |_| {
                            let next = !*expanded.peek();
                            expanded.set(next);
                            if !next {
                                show_raw.set(false);
                            }
                        },
                        if *expanded.read() { "Hide" } else { "Expand" }
                    }
                }
            }

            if *expanded.read() {
                div {
                    style: "margin-top: 8px; display: flex; flex-direction: column; gap: 8px;",

                    if let Some(f) = failure.clone() {
                        div {
                            style: "background: white; color: #991B1B; border: 1px solid #FECACA; \
                                    border-radius: 6px; padding: 6px 8px; font-size: 12px; \
                                    word-break: break-word;",
                            "{f.message}"
                        }
                    }

                    if !has_payload {
                        div {
                            style: "font-size: 12px; font-style: italic; opacity: 0.75;",
                            "This step was recorded before tool arguments and results were \
                             stored. Only the summary below is available."
                        }
                        pre {
                            style: "margin: 0; white-space: pre-wrap; word-break: break-word; \
                                    font-family: ui-monospace, monospace; font-size: 11px; \
                                    background: #FEF3C7; padding: 8px; border-radius: 6px; \
                                    max-height: 220px; overflow: auto;",
                            "{content_summary}"
                        }
                    }

                    if !input_view.is_empty() {
                        FieldSection { heading: "Arguments", fields: input_view.clone() }
                    }
                    if !output_view.is_empty() {
                        FieldSection { heading: "Result", fields: output_view.clone() }
                    }

                    if has_payload {
                        div {
                            button {
                                style: "background: none; border: none; color: #92400E; \
                                        cursor: pointer; font-size: 12px; padding: 0; \
                                        text-decoration: underline;",
                                onclick: move |_| {
                                    let next = !*show_raw.peek();
                                    show_raw.set(next);
                                },
                                if *show_raw.read() { "Hide raw JSON" } else { "Show raw JSON" }
                            }
                        }
                    }

                    if *show_raw.read() {
                        RawJson { heading: "Input JSON", body: tool_input.clone() }
                        RawJson { heading: "Output JSON", body: tool_output.clone() }
                    }
                }
            }
        }
    }
}

#[component]
fn FieldSection(heading: &'static str, fields: Vec<(String, String)>) -> Element {
    rsx! {
        div {
            div {
                style: "font-size: 11px; font-weight: 600; text-transform: uppercase; \
                        letter-spacing: 0.4px; opacity: 0.8; margin-bottom: 4px;",
                "{heading}"
            }
            div {
                style: "display: grid; grid-template-columns: minmax(80px, auto) 1fr; \
                        gap: 3px 10px; align-items: baseline;",
                for (i, (k, v)) in fields.into_iter().enumerate() {
                    {
                        rsx! {
                            div {
                                key: "k{i}",
                                style: "font-family: ui-monospace, monospace; font-size: 11px; \
                                        opacity: 0.75; white-space: nowrap;",
                                "{k}"
                            }
                            div {
                                key: "v{i}",
                                style: "font-size: 12px; word-break: break-word; \
                                        overflow-wrap: anywhere;",
                                "{v}"
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn RawJson(heading: &'static str, body: String) -> Element {
    if body.is_empty() {
        return rsx! {};
    }
    rsx! {
        div {
            div {
                style: "font-size: 11px; font-weight: 600; text-transform: uppercase; \
                        letter-spacing: 0.4px; opacity: 0.8; margin-bottom: 2px;",
                "{heading}"
            }
            pre {
                style: "margin: 0; white-space: pre-wrap; word-break: break-word; \
                        font-family: ui-monospace, monospace; font-size: 11px; \
                        background: #FEF3C7; padding: 8px; border-radius: 6px; \
                        max-height: 280px; overflow: auto;",
                "{pretty_json(&body)}"
            }
        }
    }
}

/// Re-indent JSON for the raw view. Non-JSON is shown exactly as stored, a payload we
/// cannot parse is the case where seeing the literal bytes matters most.
fn pretty_json(raw: &str) -> String {
    match serde_json::from_str::<serde_json::Value>(raw) {
        Ok(v) => serde_json::to_string_pretty(&v).unwrap_or_else(|_| raw.to_string()),
        Err(_) => raw.to_string(),
    }
}

/// Flatten a JSON payload into labelled rows for the readable view.
///
/// One level deep on purpose: arrays and nested objects are summarised ("8 results")
/// rather than expanded, because the useful nested content is already rendered as
/// document cards beneath the card, and everything else is what the raw view is for.
pub fn readable_fields(raw: &str) -> Vec<(String, String)> {
    let Ok(value) = serde_json::from_str::<serde_json::Value>(raw) else {
        if raw.trim().is_empty() {
            return Vec::new();
        }
        return vec![("value".to_string(), clip(raw))];
    };
    match value {
        serde_json::Value::Object(map) => map
            .into_iter()
            .map(|(k, v)| (k, summarise_value(&v)))
            .collect(),
        other => vec![("value".to_string(), summarise_value(&other))],
    }
}

fn summarise_value(v: &serde_json::Value) -> String {
    match v {
        serde_json::Value::String(s) => clip(s),
        serde_json::Value::Null => "null".to_string(),
        serde_json::Value::Bool(b) => b.to_string(),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::Array(items) => {
            if items.is_empty() {
                return "(empty)".to_string();
            }
            // A list of plain scalars reads better in full than as a count.
            if items.iter().all(|i| i.is_string()) {
                let joined = items
                    .iter()
                    .filter_map(|i| i.as_str())
                    .collect::<Vec<_>>()
                    .join(", ");
                return clip(&joined);
            }
            format!("{} item{}", items.len(), if items.len() == 1 { "" } else { "s" })
        }
        serde_json::Value::Object(map) => {
            format!("{} field{}", map.len(), if map.len() == 1 { "" } else { "s" })
        }
    }
}

fn clip(s: &str) -> String {
    let flat: String = s.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= VALUE_CHARS {
        return flat;
    }
    format!("{}\u{2026}", flat.chars().take(VALUE_CHARS).collect::<String>())
}

/// Short chip identifying the tool. Falls back to the raw name so a tool added to an
/// MCP server tomorrow still labels itself correctly without a change here.
fn tool_chip(tool_name: &str) -> String {
    if tool_name.is_empty() || tool_name == "tool" {
        return "tool".to_string();
    }
    tool_name.to_string()
}

fn collapsed_label(tool_name: &str, tool_input: &str, summary: &str) -> String {
    match tool_name {
        "search_collections" => {
            let query = json_str_field(tool_input, "query").unwrap_or_default();
            let collections = json_string_array(tool_input, "collections");
            let filters = if collections.is_empty() {
                String::new()
            } else {
                format!(" \u{b7} {}", collections.join(", "))
            };
            if query.is_empty() {
                format!("searched collections{filters}")
            } else {
                format!("searched collections \u{b7} {query}{filters}")
            }
        }
        "cite_documents" => {
            // The count comes from the ARGUMENTS, so the label is right while the call is
            // still running and the result column is empty.
            let count = json_array_len(tool_input, "citations");
            match count {
                0 => "cited documents".to_string(),
                1 => "cited 1 document".to_string(),
                n => format!("cited {n} documents"),
            }
        }
        "list_collections" => "listed collections".to_string(),
        "get_document_text" => {
            let path = json_str_field(tool_input, "path")
                .or_else(|| json_str_field(tool_input, "file_hash"))
                .unwrap_or_default();
            if path.is_empty() {
                "read document".to_string()
            } else {
                format!("read document \u{b7} {path}")
            }
        }
        "list_document_entities" => "listed entities".to_string(),
        "show_document" => "showed document".to_string(),
        // The open-web tools all take a query or a url, and showing it is what the label is for.
        "web_search" | "search" | "news_search" | "wikipedia_search" => {
            match json_str_field(tool_input, "query") {
                Some(q) => format!("searched the web \u{b7} {q}"),
                None => "searched the web".to_string(),
            }
        }
        "browse" | "browse_url" | "fetch_url" | "get_page" => {
            match json_str_field(tool_input, "url") {
                Some(u) => format!("opened page \u{b7} {u}"),
                None => "opened a page".to_string(),
            }
        }
        "whois" => match json_str_field(tool_input, "domain") {
            Some(d) => format!("whois \u{b7} {d}"),
            None => "whois lookup".to_string(),
        },
        other => {
            // Unknown tool: prefer its arguments over the stored summary, which for a
            // row written before the payload columns existed is a JSON blob.
            let detail = first_scalar_argument(tool_input).unwrap_or_else(|| clip(summary));
            let short = if detail.chars().count() > 80 {
                format!("{}\u{2026}", detail.chars().take(80).collect::<String>())
            } else {
                detail
            };
            if short.is_empty() {
                format!("called {other}")
            } else {
                format!("called {other} \u{b7} {short}")
            }
        }
    }
}

/// Argument names that carry the point of a call, tried in this order.
///
/// Needed because `serde_json` keys are ordered alphabetically, not by position in the
/// call, so "the first argument" is meaningless, for `{"text": …, "lang": …}` it would
/// pick the language code and label the card with "en".
const LABEL_KEYS: [&str; 8] = ["query", "q", "url", "text", "path", "domain", "name", "term"];

/// The most descriptive scalar argument, for labelling a tool with no special case.
fn first_scalar_argument(raw: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(raw).ok()?;
    let map = v.as_object()?;

    for key in LABEL_KEYS {
        if let Some(serde_json::Value::String(s)) = map.get(key) {
            if !s.is_empty() {
                return Some(clip(s));
            }
        }
    }

    // No recognised key: the longest string is the best remaining guess at which
    // argument is the content and which is a flag or a locale.
    let longest = map
        .values()
        .filter_map(|v| v.as_str())
        .filter(|s| !s.is_empty())
        .max_by_key(|s| s.chars().count());
    if let Some(s) = longest {
        return Some(clip(s));
    }

    map.values().find_map(|v| v.as_number().map(|n| n.to_string()))
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
        ..Default::default()
    }))
}

fn json_str_field(raw: &str, key: &str) -> Option<String> {
    let v: serde_json::Value = serde_json::from_str(raw).ok()?;
    v.get(key)?.as_str().map(str::to_string)
}

/// How many entries a JSON array argument holds, zero when it is absent or malformed.
///
/// An XML-style tool-call parser hands a list argument across as a JSON *string*, so the
/// value is decoded a second time when the first decode produced one. Without that the
/// label reads "cited documents" for every call made through such a parser.
fn json_array_len(raw: &str, key: &str) -> usize {
    let Ok(v) = serde_json::from_str::<serde_json::Value>(raw) else {
        return 0;
    };
    let Some(field) = v.get(key) else {
        return 0;
    };
    if let Some(array) = field.as_array() {
        return array.len();
    }
    field
        .as_str()
        .and_then(|text| serde_json::from_str::<serde_json::Value>(text).ok())
        .and_then(|inner| inner.as_array().map(Vec::len))
        .unwrap_or(0)
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_chip_names_the_tool_type() {
        assert_eq!(tool_chip("search_collections"), "search_collections");
        assert_eq!(tool_chip("web_search"), "web_search");
        // The writer's fallback name should not be dressed up as a real tool.
        assert_eq!(tool_chip(""), "tool");
        assert_eq!(tool_chip("tool"), "tool");
    }

    #[test]
    fn a_known_tool_gets_a_prose_label_not_json() {
        let label = collapsed_label(
            "search_collections",
            r#"{"query":"water levels","collections":["testdata"]}"#,
            "",
        );
        assert_eq!(label, "searched collections \u{b7} water levels \u{b7} testdata");
        assert!(!label.contains('{'), "label must never be raw JSON");
    }

    #[test]
    fn web_tools_show_their_query() {
        assert_eq!(
            collapsed_label("web_search", r#"{"query":"danube level","max_results":5}"#, ""),
            "searched the web \u{b7} danube level"
        );
    }

    #[test]
    fn an_unknown_tool_labels_from_its_most_descriptive_argument() {
        // JSON keys arrive alphabetically, so "lang" precedes "text". Picking
        // positionally would label this card "en".
        let label = collapsed_label("translate", r#"{"text":"bonjour","lang":"en"}"#, "");
        assert_eq!(label, "called translate \u{b7} bonjour");
    }

    /// The count comes from the arguments, so the label is right while the call is still
    /// running and the result column is empty. A list argument arrives as a JSON string
    /// from an XML-style tool-call parser, which is the case that reads "cited documents"
    /// for every call if it is not handled.
    #[test]
    fn the_citation_label_counts_the_citations_however_they_arrive() {
        assert_eq!(
            collapsed_label("cite_documents", r#"{"citations":[{"a":1},{"b":2}]}"#, ""),
            "cited 2 documents"
        );
        assert_eq!(
            collapsed_label("cite_documents", r#"{"citations":"[{\"a\":1}]"}"#, ""),
            "cited 1 document"
        );
        assert_eq!(collapsed_label("cite_documents", "{}", ""), "cited documents");
        assert_eq!(collapsed_label("cite_documents", "not json", ""), "cited documents");
    }

    #[test]
    fn a_recognised_argument_name_wins_over_a_longer_one() {
        let label = collapsed_label(
            "some_tool",
            r#"{"query":"cats","note":"a much longer irrelevant string"}"#,
            "",
        );
        assert_eq!(label, "called some_tool \u{b7} cats");
    }

    #[test]
    fn a_tool_with_no_string_arguments_still_gets_a_label() {
        assert_eq!(collapsed_label("ping", r#"{"count":3}"#, ""), "called ping \u{b7} 3");
        assert_eq!(collapsed_label("ping", "{}", ""), "called ping");
    }

    #[test]
    fn readable_fields_flattens_an_object_and_counts_nested_data() {
        let fields = readable_fields(
            r#"{"success":true,"query":"water","results":[{"a":1},{"a":2}],"engines":["ddg","brave"]}"#,
        );
        let get = |k: &str| {
            fields
                .iter()
                .find(|(n, _)| n == k)
                .map(|(_, v)| v.clone())
                .unwrap_or_default()
        };
        assert_eq!(get("success"), "true");
        assert_eq!(get("query"), "water");
        assert_eq!(get("results"), "2 items");
        assert_eq!(get("engines"), "ddg, brave");
    }

    #[test]
    fn readable_fields_is_empty_for_an_empty_payload() {
        // Drives the "recorded before payloads were stored" notice rather than an
        // empty box.
        assert!(readable_fields("").is_empty());
        assert!(readable_fields("   ").is_empty());
    }

    #[test]
    fn readable_fields_keeps_unparseable_payloads_visible() {
        assert_eq!(
            readable_fields("not json at all"),
            vec![("value".to_string(), "not json at all".to_string())]
        );
    }

    #[test]
    fn an_empty_array_says_so_rather_than_counting_zero() {
        let fields = readable_fields(r#"{"results":[]}"#);
        assert_eq!(fields[0].1, "(empty)");
    }

    #[test]
    fn pretty_json_indents_valid_json_and_passes_through_the_rest() {
        assert!(pretty_json(r#"{"a":1}"#).contains("\n"));
        assert_eq!(pretty_json("<html>"), "<html>");
    }

    #[test]
    fn the_search_link_only_appears_for_collection_searches() {
        assert!(search_route_from_tool_input("web_search", r#"{"query":"x"}"#).is_none());
        assert!(
            search_route_from_tool_input("search_collections", r#"{"query":"x"}"#).is_some()
        );
        // No query means no reproducible search.
        assert!(search_route_from_tool_input("search_collections", "{}").is_none());
    }
}
