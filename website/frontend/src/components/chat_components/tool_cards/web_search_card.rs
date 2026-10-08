//! The `web_search` card shows model-visible results and optional search detail.
//! The result list shows the title, host, matching forms, and snippet.
//! The detail artifact contains source timings and both ranking orders.
//!
//! Every string here is a text node and every link goes through `http_link` first. See
//! the module docstring in `tool_cards/mod.rs`.

use dioxus::prelude::*;

use crate::api::chat_api::chat_artifact_detail;
use crate::components::chat_components::tool_cards::{
    artifact_refs_from_text, focus, http_link, json_bool, json_f64, json_str, json_strings, json_u64,
    strip_artifact_marker, tool_content,
    tool_failure, CardShell, ElapsedCounter, FocusHandle, ModalCloseButton, ModalShell,
    ToolFailure,
};

#[derive(Debug, Clone, PartialEq)]
struct Row {
    title: String,
    url: String,
    display_url: String,
    snippet: String,
    sources: Vec<String>,
    kind: String,
    rrf_rank: u64,
    rerank_rank: Option<u64>,
    rerank_score: Option<f64>,
    published: String,
    forms: Vec<u64>,
}

fn parse_rows(v: &serde_json::Value, key: &str) -> Vec<Row> {
    v.get(key)
        .and_then(|x| x.as_array())
        .map(|items| {
            items
                .iter()
                .map(|r| Row {
                    title: json_str(r, "title"),
                    url: json_str(r, "url"),
                    display_url: json_str(r, "display_url"),
                    snippet: json_str(r, "snippet"),
                    sources: json_strings(r, "sources"),
                    kind: json_str(r, "kind"),
                    rrf_rank: json_u64(r, "rrf_rank"),
                    rerank_rank: r.get("rerank_rank").and_then(|x| x.as_u64()),
                    rerank_score: json_f64(r, "rerank_score"),
                    published: json_str(r, "published"),
                    forms: r.get("q").and_then(|q| q.as_array())
                        .map(|forms| forms.iter().filter_map(|form| form.as_u64()).collect())
                        .unwrap_or_default(),
                })
                .collect()
        })
        .unwrap_or_default()
}

fn detail_artifact_id(tool_output: &str, content: &serde_json::Value) -> String {
    artifact_refs_from_text(tool_output).into_iter()
        .find(|artifact| artifact.kind == "json")
        .map(|artifact| artifact.artifact_id)
        .or_else(|| content.get("_hoover4_artifacts").and_then(|refs| refs.as_array())
            .and_then(|refs| refs.iter().find(|reference| json_str(reference, "kind") == "json"
                && json_str(reference, "tool_name") == "web_search"))
            .map(|reference| json_str(reference, "artifact_id")))
        .unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::{detail_artifact_id, parse_rows};

    #[test]
    fn web_detail_uses_the_stored_json_artifact() {
        let content = serde_json::json!({"results": [], "_hoover4_artifacts": [
            {"artifact_id": "detail-1", "kind": "json", "tool_name": "web_search"}
        ]});
        assert_eq!(detail_artifact_id("", &content), "detail-1");
    }

    #[test]
    fn slim_rows_keep_kind_published_and_form_numbers() {
        let value = serde_json::json!({"results":[{"title":"A","url":"https://example.org/a","q":[0,2],"kind":"news","published":"2026-01-02"}]});
        let rows = parse_rows(&value, "results");
        assert_eq!(rows[0].forms, vec![0, 2]);
        assert_eq!(rows[0].kind, "news");
        assert_eq!(rows[0].published, "2026-01-02");
    }
}

#[component]
pub fn WebSearchCard(
    tool_input: String,
    tool_output: String,
    running: bool,
    elapsed_ms: Option<u32>,
) -> Element {
    let expanded = use_signal(|| false);
    let mut popup_open = use_signal(|| false);
    // The button that opened the popup, so focus returns to it on close.
    let mut opener: FocusHandle = use_signal(|| None);

    let input = serde_json::from_str::<serde_json::Value>(&tool_input).unwrap_or_default();
    let input = input.get("input").unwrap_or(&input);
    let queries = input.get("queries").and_then(|queries| queries.as_array())
        .map(|queries| queries.iter().filter_map(|query| query.as_str().map(str::to_string)).collect::<Vec<_>>())
        .unwrap_or_else(|| input.get("query").and_then(|query| query.as_str()).map(|query| vec![query.to_string()]).unwrap_or_default());
    let query = queries.first().cloned().unwrap_or_default();
    let requested_sources = serde_json::from_str::<serde_json::Value>(&tool_input)
        .ok()
        .map(|v| json_strings(&v, "sources"))
        .unwrap_or_default();

    if running {
        return rsx! { PendingSearch { query, sources: requested_sources, elapsed_ms } };
    }

    let Some(raw_content) = tool_content(&tool_output) else {
        // Not "the payload was not recorded": the payload IS recorded, it just did not
        // survive as JSON. Showing the bytes is worth more than a card that denies the
        // data exists. See `truncate_tool_payload`, which is why this happens far less
        // often now.
        return rsx! { UnparseableSearch { query, raw: tool_output.clone() } };
    };
    let content = if let Some(text) = raw_content.as_str() {
        serde_json::from_str::<serde_json::Value>(&strip_artifact_marker(text)).unwrap_or(raw_content)
    } else { raw_content };

    let results = parse_rows(&content, "results");
    let degraded = json_strings(&content, "no_results_from");
    let degraded_text = degraded.join(", ");
    let artifact_id = detail_artifact_id(&tool_output, &content);
    // A dead search used to read "0 results · 0 sources". A count, phrased as if the web
    // had nothing to say. The failure is the headline, so it goes in the header.
    let failure = tool_failure(&content);
    let error = failure.as_ref().map(|f| f.message.clone()).unwrap_or_default();

    let label = if query.is_empty() {
        "searched the web".to_string()
    } else if queries.len() > 1 {
        queries.iter().enumerate().map(|(index, form)| format!("{index}: {form}"))
            .collect::<Vec<_>>().join("; ")
    } else {
        format!("\u{201c}{query}\u{201d}")
    };
    let has_artifact = !artifact_id.is_empty();

    rsx! {
        div { "data-web-search-card": "true",
        CardShell {
            chip: "web_search".to_string(),
            label,
            running: false,
            expanded,
            failure: failure.clone(),
            raw_output: tool_output.clone(),
            badges: rsx! {
                // Counts only when there was a search to count. Beside a "failed" pip they
                // read as a result rather than as the absence of one.
                if failure.is_none() {
                    span {
                        style: "flex-shrink: 0; font-size: var(--x-text-xs); opacity: 0.8; \
                                font-variant-numeric: tabular-nums;",
                        "{results.len()} results"
                    }
                }
                if !degraded.is_empty() {
                    span {
                        title: "These sources returned nothing, so the results come from fewer than intended",
                        style: "flex-shrink: 0; background: #FEE2E2; color: var(--x-danger); \
                                border-radius: 999px; padding: 1px 7px; font-size: var(--x-text-xs);",
                        "\u{26a0} {degraded.len()} degraded"
                    }
                }
            },

            if !error.is_empty() {
                div {
                    style: "background: #FEF2F2; color: var(--x-danger); border: 1px solid #FECACA; \
                            border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-xs);",
                    "{error}"
                }
            }

            for (index, form) in queries.iter().enumerate() {
                div { style: "font-size: var(--x-text-xs);", "Form {index}: {form}" }
            }
            if !degraded.is_empty() { div { "No results from: {degraded_text}" } }
            if let Some(note) = content.get("note").and_then(|note| note.as_str()) { div { "{note}" } }

            for (i, row) in results.iter().enumerate() {
                ResultRow { key: "{i}-{row.url}", row: row.clone() }
            }

            if results.is_empty() && error.is_empty() {
                div {
                    style: "font-size: var(--x-text-xs); font-style: italic; opacity: 0.75;",
                    "No results. Every source answered and none of them had anything for this query."
                }
            }

            // Said out loud, because the alternative is a list that silently stops. The
            // model saw the whole result set; this row is the transcript's copy of it.
            if json_bool(&content, "truncated") {
                div {
                    style: "font-size: var(--x-text-xs); font-style: italic; opacity: 0.75;",
                    "The lowest-ranked results were dropped so this call fits in the \
                     transcript. The assistant saw all of them."
                }
            }

            if has_artifact {
                div {
                    button {
                        style: "background: none; border: none; color: var(--x-ink); cursor: pointer; \
                                font-size: var(--x-text-xs); padding: 0; text-decoration: underline;",
                        onmounted: move |e| opener.set(Some(e.data())),
                        onclick: move |_| popup_open.set(true),
                        "View search details."
                    }
                }
            }
        }

        if *popup_open.read() {
            SearchDetailPopup {
                artifact_id: artifact_id.clone(),
                on_close: move |_| {
                    popup_open.set(false);
                    focus(opener);
                },
            }
        }
        }
    }
}

/// While the search runs: the query, the sources it is waiting on, and a clock.
#[component]
fn PendingSearch(query: String, sources: Vec<String>, elapsed_ms: Option<u32>) -> Element {
    let waiting = if sources.is_empty() {
        "all sources".to_string()
    } else {
        sources.join(", ")
    };
    rsx! {
        div {
            style: "align-self: flex-start; max-width: 92%; background: #FFFFFF; \
                    border: 1px solid var(--x-border); border-radius: 10px; padding: 8px 12px; \
                    font-size: var(--x-text-sm); color: var(--x-ink-strong); display: flex; align-items: center; \
                    gap: 10px; flex-wrap: wrap;",
            span {
                style: "flex-shrink: 0; background: #E5E7EB; color: var(--x-ink-strong); \
                        border-radius: 999px; padding: 1px 8px; font-size: var(--x-text-xs); \
                        font-weight: 400; font-family: inherit;",
                "web_search"
            }
            span { style: "flex: 1; min-width: 0;", "\u{201c}{query}\u{201d}" }
            span { style: "flex-shrink: 0; font-size: var(--x-text-xs); opacity: 0.75;", "{waiting}" }
            ElapsedCounter { already_ms: elapsed_ms }
        }
    }
}

/// The stored payload did not parse as JSON.
///
/// It used to say "the result payload was not recorded", which was the card denying data
/// the transcript is holding: the payload was recorded and then byte-chopped at
/// `TOOL_PAYLOAD_CHARS`, and the card read the wreckage as absence. Storage now truncates
/// *inside* the JSON so this is rare, but when it happens the bytes are shown, an
/// unreadable result is exactly the case where seeing the literal text matters.
#[component]
fn UnparseableSearch(query: String, raw: String) -> Element {
    let expanded = use_signal(|| false);
    let label = if query.is_empty() {
        "searched the web".to_string()
    } else {
        format!("\u{201c}{query}\u{201d}")
    };
    rsx! {
        CardShell {
            chip: "web_search".to_string(),
            label,
            running: false,
            expanded,
            failure: ToolFailure {
                refused: false,
                message: "the stored result could not be read back as JSON".to_string(),
            },
            badges: rsx! {},

            if raw.trim().is_empty() {
                div {
                    style: "font-size: var(--x-text-xs); font-style: italic; opacity: 0.75;",
                    "Nothing was stored for this call."
                }
            } else {
                pre {
                    style: "margin: 0; white-space: pre-wrap; word-break: break-word; \
                            font-family: ui-monospace, monospace; font-size: var(--x-text-xs); \
                            background: #FEE2E2; padding: 8px; border-radius: 6px; \
                            max-height: 320px; overflow: auto;",
                    "{raw}"
                }
            }
        }
    }
}


#[component]
fn ResultRow(row: Row) -> Element {
    let link = http_link(&row.url);
    let title = if row.title.is_empty() { row.url.clone() } else { row.title.clone() };
    let host = row.url.split("//").nth(1).unwrap_or(&row.url).split('/').next().unwrap_or("").to_string();
    let forms = row.forms.iter().map(u64::to_string).collect::<Vec<_>>().join(", ");

    rsx! {
        div {
            style: "display: flex; gap: 8px; align-items: flex-start; padding: 4px 0; \
                    border-top: 1px solid #F1F5F9;",
            div {
                style: "min-width: 0; flex: 1;",
                div {
                    style: "display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap;",
                    // The title is a link only when the URL is plainly http/https,
                    // otherwise it stays text. See `http_link`.
                    if let Some(href) = link.clone() {
                        a {
                            href: "{href}",
                            target: "_blank",
                            rel: "noopener noreferrer nofollow",
                            style: "color: var(--x-link); text-decoration: none; font-weight: 500; \
                                    word-break: break-word;",
                            "{title}"
                        }
                    } else {
                        span { style: "font-weight: 500; word-break: break-word;", "{title}" }
                    }
                }
                div {
                    style: "font-size: var(--x-text-xs); color: #166534; word-break: break-all;",
                    "{host}"
                }
                if !forms.is_empty() {
                    div { style: "font-size: var(--x-text-xs);", "Forms: {forms}" }
                }
                if !row.kind.is_empty() {
                    div { style: "font-size: var(--x-text-xs);", "Kind: {row.kind}" }
                }
                if !row.published.is_empty() {
                    div { style: "font-size: var(--x-text-xs);", "Published: {row.published}" }
                }
                if !row.snippet.is_empty() {
                    div {
                        style: "font-size: var(--x-text-xs); line-height: 1.5; margin-top: 2px; \
                                word-break: break-word;",
                        "{row.snippet}"
                    }
                }
            }
        }
    }
}

/// The two orderings, side by side, from the search-detail artifact.
#[component]
fn SearchDetailPopup(artifact_id: String, on_close: EventHandler<()>) -> Element {
    let id = artifact_id.clone();
    let detail = use_resource(move || {
        let id = id.clone();
        async move { chat_artifact_detail(id).await.map_err(|e| e.to_string()) }
    });

    let body = match &*detail.read_unchecked() {
        None => rsx! { div { style: "padding: 20px; opacity: 0.7;", "Loading search detail\u{2026}" } },
        Some(Err(e)) => rsx! {
            div {
                class: "x-error-display",
                style: "padding: 20px; color: var(--x-danger);",
                "Could not load the search detail: {e}"
            }
        },
        Some(Ok(text)) => match serde_json::from_str::<serde_json::Value>(text) {
            Err(e) => rsx! {
                div {
                    class: "x-error-display",
                    style: "padding: 20px; color: var(--x-danger);",
                    "Malformed detail: {e}"
                }
            },
            Ok(doc) => {
                let before = parse_rows(&doc, "before_rerank");
                let after = parse_rows(&doc, "after_rerank");
                let rerank_ms = json_f64(&doc, "rerank_ms").unwrap_or(0.0);
                let applied = json_bool(&doc, "rerank_applied");
                let latency = doc.get("source_latency_ms").cloned().unwrap_or(serde_json::Value::Null);
                let counts = doc.get("source_counts").cloned().unwrap_or(serde_json::Value::Null);
                let degraded = json_strings(&doc, "degraded").join(", ");
                let dedupe = format!(
                    "{} results in, {} after deduplication",
                    json_u64(&doc, "total_before_dedupe"),
                    json_u64(&doc, "total_after_dedupe"),
                );
                rsx! {
                    div {
                        style: "padding: 12px 16px; border-bottom: 1px solid var(--x-border); \
                                font-size: var(--x-text-xs); color: var(--x-ink); line-height: 1.7;",
                        div { "The tool returned selected results to the model." }
                        div { "{dedupe}" }
                        if applied {
                            div { "The cross-encoder ranked results in {rerank_ms:.0} ms." }
                        } else {
                            div { style: "color: var(--x-ink);", "Results use reciprocal rank fusion." }
                        }
                        if !degraded.is_empty() {
                            div { style: "color: var(--x-danger);", "returned nothing: {degraded}" }
                        }
                        SourceTimings { latency, counts }
                    }
                    div {
                        style: "display: flex; gap: 0; align-items: stretch; overflow: auto; flex: 1;",
                        RankColumn {
                            heading: "All candidates use fusion order.".to_string(),
                            rows: before,
                            show_source_ranks: true,
                        }
                        RankColumn {
                            heading: (if applied {
                                "The cross-encoder ranks selected results."
                            } else {
                                "Selected results use fusion order."
                            }).to_string(),
                            rows: after,
                            show_source_ranks: false,
                        }
                    }
                }
            }
        },
    };

    rsx! {
        // Escape, the focus trap and the announced role all come from ModalShell. This
        // popup had none of the three: it could only be closed with a mouse, and Tab
        // walked straight past it into the transcript behind.
        ModalShell {
            label: "Search detail".to_string(),
            on_close,
            pane_size: "width: min(1100px, 96vw); height: min(80vh, 900px);".to_string(),
            header: rsx! {
                div {
                    style: "display: flex; align-items: center; justify-content: space-between; \
                            padding: 12px 16px; border-bottom: 1px solid var(--x-border);",
                    strong { style: "font-size: var(--x-text-md);", "Search detail" }
                    ModalCloseButton { on_close }
                }
            },
            {body}
        }
    }
}

#[component]
fn SourceTimings(latency: serde_json::Value, counts: serde_json::Value) -> Element {
    let Some(map) = latency.as_object() else {
        return rsx! {};
    };
    let counts = counts.as_object().cloned().unwrap_or_default();
    rsx! {
        div {
            style: "display: flex; gap: 10px; flex-wrap: wrap; margin-top: 4px;",
            for (name, ms) in map.clone() {
                {
                    let n = counts.get(&name).and_then(|c| c.as_u64()).unwrap_or(0);
                    let ms = ms.as_f64().unwrap_or(0.0);
                    rsx! {
                        span {
                            key: "{name}",
                            style: "background: #F1F5F9; border-radius: 6px; padding: 1px 7px; \
                                    font-size: var(--x-text-xs); font-variant-numeric: tabular-nums;",
                            "{name}: {n} in {ms:.0} ms"
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn RankColumn(heading: String, rows: Vec<Row>, show_source_ranks: bool) -> Element {
    rsx! {
        div {
            style: "flex: 1; min-width: 0; border-right: 1px solid var(--x-border); overflow-y: auto; \
                    padding: 10px 14px;",
            div {
                style: "font-size: var(--x-text-xs); font-weight: 600; text-transform: uppercase; \
                        letter-spacing: 0.4px; color: var(--x-ink-muted); margin-bottom: 8px; \
                        position: sticky; top: 0; background: white; padding-bottom: 4px;",
                "{heading}"
            }
            for (i, row) in rows.into_iter().enumerate() {
                div {
                    key: "{i}",
                    style: "display: flex; gap: 8px; padding: 5px 0; border-top: 1px solid #F1F5F9; \
                            font-size: var(--x-text-xs);",
                    span {
                        style: "flex-shrink: 0; min-width: 20px; text-align: right; color: var(--x-ink-faint); \
                                font-variant-numeric: tabular-nums;",
                        "{i + 1}"
                    }
                    div {
                        style: "min-width: 0;",
                        div { style: "word-break: break-word; color: var(--x-ink-strong);", "{row.title}" }
                        div { style: "font-size: var(--x-text-xs); color: #166534; word-break: break-all;", "{row.display_url}" }
                        div {
                            style: "font-size: var(--x-text-xs); color: var(--x-ink-muted); margin-top: 2px;",
                            if show_source_ranks {
                                "{row.sources.join(\", \")}"
                            } else if let Some(score) = row.rerank_score {
                                "score {score:.3} \u{b7} was RRF #{row.rrf_rank}"
                            } else {
                                "RRF #{row.rrf_rank}"
                            }
                        }
                    }
                }
            }
        }
    }
}
