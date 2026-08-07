//! The `web_search` card: pending, collapsed, expanded, and the ranking popup.
//!
//! Four states, because the four questions are different:
//!
//! * **Pending** — the query and an elapsed counter, while the search runs. This exists
//!   only because Phase 1 made in-flight tool calls visible at all.
//! * **Collapsed** — `web_search · "danube water level" · 18 results · 5 sources`, plus a
//!   warning pip when a source came back empty.
//! * **Expanded** — the result list: rank badge, domain chip, the title as a real link,
//!   the *full* snippet, the sources that corroborated it, and an `RRF #7 → #2` badge
//!   where reranking moved it. This is the level that answers "what did it actually find".
//! * **Popup** — both orderings side by side, fetched lazily from the search-detail
//!   artifact. `TOOL_PAYLOAD_CHARS` cannot carry two orderings of forty candidates, which
//!   is why the artifact exists.
//!
//! Every string here is a text node and every link goes through `http_link` first — see
//! the module docstring in `tool_cards/mod.rs`.

use dioxus::prelude::*;

use crate::api::chat_api::chat_artifact_detail;
use crate::components::chat_components::tool_cards::{
    http_link, json_bool, json_f64, json_str, json_strings, json_u64, tool_content, CardShell,
    ElapsedCounter,
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
                })
                .collect()
        })
        .unwrap_or_default()
}

#[component]
pub fn WebSearchCard(tool_input: String, tool_output: String, running: bool) -> Element {
    let expanded = use_signal(|| false);
    let mut popup_open = use_signal(|| false);

    let query = serde_json::from_str::<serde_json::Value>(&tool_input)
        .ok()
        .map(|v| json_str(&v, "query"))
        .unwrap_or_default();
    let requested_sources = serde_json::from_str::<serde_json::Value>(&tool_input)
        .ok()
        .map(|v| json_strings(&v, "sources"))
        .unwrap_or_default();

    if running {
        return rsx! { PendingSearch { query, sources: requested_sources } };
    }

    let Some(content) = tool_content(&tool_output) else {
        return rsx! { EmptySearch { query } };
    };

    let results = parse_rows(&content, "results");
    let sources_used = json_strings(&content, "sources_used");
    let degraded = json_strings(&content, "degraded");
    let unknown_sources = json_strings(&content, "unknown_sources");
    let rerank_applied = json_bool(&content, "rerank_applied");
    let rerank_error = json_str(&content, "rerank_error");
    let artifact_id = json_str(&content, "artifact_id");
    let error = json_str(&content, "error");
    let total_ms = json_f64(&content, "total_ms").unwrap_or(0.0);
    let before = json_u64(&content, "total_before_dedupe");
    let after = json_u64(&content, "total_after_dedupe");

    let label = if query.is_empty() {
        "searched the web".to_string()
    } else {
        format!("\u{201c}{query}\u{201d}")
    };
    let has_artifact = !artifact_id.is_empty();

    rsx! {
        CardShell {
            chip: "web_search".to_string(),
            label,
            running: false,
            expanded,
            badges: rsx! {
                span {
                    style: "flex-shrink: 0; font-size: 11px; opacity: 0.8; \
                            font-variant-numeric: tabular-nums;",
                    "{results.len()} results \u{b7} {sources_used.len()} sources"
                }
                if !degraded.is_empty() {
                    span {
                        title: "These sources returned nothing, so the results come from fewer than intended",
                        style: "flex-shrink: 0; background: #FEE2E2; color: #991B1B; \
                                border-radius: 999px; padding: 1px 7px; font-size: 11px;",
                        "\u{26a0} {degraded.len()} degraded"
                    }
                }
                if !rerank_applied {
                    span {
                        title: "The cross-encoder did not run, so these are in fusion order",
                        style: "flex-shrink: 0; background: #E0E7FF; color: #3730A3; \
                                border-radius: 999px; padding: 1px 7px; font-size: 11px;",
                        "not reranked"
                    }
                }
            },

            if !error.is_empty() {
                div {
                    style: "background: #FEF2F2; color: #991B1B; border: 1px solid #FECACA; \
                            border-radius: 6px; padding: 6px 8px; font-size: 12px;",
                    "{error}"
                }
            }

            SearchSummaryStrip {
                sources_used: sources_used.clone(),
                degraded: degraded.clone(),
                unknown_sources: unknown_sources.clone(),
                rerank_applied,
                rerank_error: rerank_error.clone(),
                total_ms,
                before,
                after,
            }

            for (i, row) in results.iter().enumerate() {
                ResultRow { key: "{i}-{row.url}", row: row.clone() }
            }

            if results.is_empty() && error.is_empty() {
                div {
                    style: "font-size: 12px; font-style: italic; opacity: 0.75;",
                    "No results. Every source answered and none of them had anything for this query."
                }
            }

            if has_artifact {
                div {
                    button {
                        style: "background: none; border: none; color: #92400E; cursor: pointer; \
                                font-size: 12px; padding: 0; text-decoration: underline;",
                        onclick: move |_| popup_open.set(true),
                        "Search detail \u{2014} before and after reranking"
                    }
                }
            }
        }

        if *popup_open.read() {
            SearchDetailPopup {
                artifact_id: artifact_id.clone(),
                on_close: move |_| popup_open.set(false),
            }
        }
    }
}

/// While the search runs: the query, the sources it is waiting on, and a clock.
#[component]
fn PendingSearch(query: String, sources: Vec<String>) -> Element {
    let waiting = if sources.is_empty() {
        "all sources".to_string()
    } else {
        sources.join(", ")
    };
    rsx! {
        div {
            style: "align-self: flex-start; max-width: 92%; background: #FFFBEB; \
                    border: 1px solid #FDE68A; border-radius: 10px; padding: 8px 12px; \
                    font-size: 13px; color: #78350F; display: flex; align-items: center; \
                    gap: 10px; flex-wrap: wrap;",
            span {
                style: "flex-shrink: 0; background: #FDE68A; color: #78350F; \
                        border-radius: 999px; padding: 1px 8px; font-size: 11px; \
                        font-weight: 600; font-family: ui-monospace, monospace;",
                "web_search"
            }
            span { style: "flex: 1; min-width: 0;", "\u{201c}{query}\u{201d}" }
            span { style: "flex-shrink: 0; font-size: 11px; opacity: 0.75;", "{waiting}" }
            ElapsedCounter {}
        }
    }
}

#[component]
fn EmptySearch(query: String) -> Element {
    rsx! {
        div {
            style: "align-self: flex-start; background: #FFFBEB; border: 1px solid #FDE68A; \
                    border-radius: 10px; padding: 8px 12px; font-size: 13px; color: #78350F;",
            "web_search \u{b7} \u{201c}{query}\u{201d} \u{2014} the result payload was not recorded."
        }
    }
}

#[component]
fn SearchSummaryStrip(
    sources_used: Vec<String>,
    degraded: Vec<String>,
    unknown_sources: Vec<String>,
    rerank_applied: bool,
    rerank_error: String,
    total_ms: f64,
    before: u64,
    after: u64,
) -> Element {
    let used = sources_used.join(", ");
    let dead = degraded.join(", ");
    let unknown = unknown_sources.join(", ");
    rsx! {
        div {
            style: "font-size: 11px; opacity: 0.85; line-height: 1.6; \
                    border-bottom: 1px solid #FDE68A; padding-bottom: 6px;",
            div { "sources: {used}" }
            if !dead.is_empty() {
                div { style: "color: #991B1B;", "returned nothing: {dead}" }
            }
            if !unknown.is_empty() {
                div { style: "color: #92400E;", "ignored (no such source): {unknown}" }
            }
            div { "{before} results from the sources, {after} after deduplication, in {total_ms:.0} ms" }
            if !rerank_applied {
                div {
                    style: "color: #3730A3;",
                    if rerank_error.is_empty() {
                        "Reranking did not run; these are in fusion order."
                    } else {
                        "Reranking did not run ({rerank_error}); these are in fusion order."
                    }
                }
            }
        }
    }
}

#[component]
fn ResultRow(row: Row) -> Element {
    let link = http_link(&row.url);
    let moved = match row.rerank_rank {
        Some(new) if row.rrf_rank > 0 && new != row.rrf_rank => {
            Some(format!("RRF #{} \u{2192} #{new}", row.rrf_rank))
        }
        _ => None,
    };
    let rank = row.rerank_rank.unwrap_or(row.rrf_rank);
    let title = if row.title.is_empty() { row.display_url.clone() } else { row.title.clone() };

    rsx! {
        div {
            style: "display: flex; gap: 8px; align-items: flex-start; padding: 4px 0; \
                    border-top: 1px solid #FEF3C7;",
            span {
                style: "flex-shrink: 0; min-width: 22px; text-align: right; font-size: 11px; \
                        opacity: 0.6; font-variant-numeric: tabular-nums; padding-top: 2px;",
                "{rank}"
            }
            div {
                style: "min-width: 0; flex: 1;",
                div {
                    style: "display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap;",
                    // The title is a link only when the URL is plainly http/https —
                    // otherwise it stays text. See `http_link`.
                    if let Some(href) = link.clone() {
                        a {
                            href: "{href}",
                            target: "_blank",
                            rel: "noopener noreferrer nofollow",
                            style: "color: #1D4ED8; text-decoration: none; font-weight: 500; \
                                    word-break: break-word;",
                            "{title}"
                        }
                    } else {
                        span { style: "font-weight: 500; word-break: break-word;", "{title}" }
                    }
                    if !row.kind.is_empty() && row.kind != "web" {
                        span {
                            style: "flex-shrink: 0; background: #DBEAFE; color: #1E40AF; \
                                    border-radius: 999px; padding: 0 6px; font-size: 10px;",
                            "{row.kind}"
                        }
                    }
                }
                div {
                    style: "font-size: 11px; color: #166534; word-break: break-all;",
                    "{row.display_url}"
                }
                if !row.snippet.is_empty() {
                    div {
                        style: "font-size: 12px; line-height: 1.5; margin-top: 2px; \
                                word-break: break-word;",
                        "{row.snippet}"
                    }
                }
                div {
                    style: "display: flex; gap: 5px; flex-wrap: wrap; margin-top: 3px; \
                            font-size: 10px; opacity: 0.8;",
                    for source in row.sources.clone() {
                        span {
                            key: "{source}",
                            style: "background: #FEF3C7; border-radius: 999px; padding: 0 6px;",
                            "{source}"
                        }
                    }
                    if let Some(m) = moved.clone() {
                        span {
                            style: "background: #DCFCE7; color: #166534; border-radius: 999px; \
                                    padding: 0 6px;",
                            "{m}"
                        }
                    }
                    if !row.published.is_empty() {
                        span { style: "opacity: 0.75;", "{row.published}" }
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
                style: "padding: 20px; color: #991B1B;",
                "Could not load the search detail: {e}"
            }
        },
        Some(Ok(text)) => match serde_json::from_str::<serde_json::Value>(text) {
            Err(e) => rsx! { div { style: "padding: 20px; color: #991B1B;", "Malformed detail: {e}" } },
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
                        style: "padding: 12px 16px; border-bottom: 1px solid #E2E8F0; \
                                font-size: 12px; color: #334155; line-height: 1.7;",
                        div { "{dedupe}" }
                        if applied {
                            div { "cross-encoder reranked in {rerank_ms:.0} ms" }
                        } else {
                            div { style: "color: #3730A3;", "reranking did not run \u{2014} this is fusion order in both columns" }
                        }
                        if !degraded.is_empty() {
                            div { style: "color: #991B1B;", "returned nothing: {degraded}" }
                        }
                        SourceTimings { latency, counts }
                    }
                    div {
                        style: "display: flex; gap: 0; align-items: stretch; overflow: auto; flex: 1;",
                        RankColumn {
                            heading: "Before reranking (fusion order)".to_string(),
                            rows: before,
                            show_source_ranks: true,
                        }
                        RankColumn {
                            heading: "After reranking (cross-encoder score)".to_string(),
                            rows: after,
                            show_source_ranks: false,
                        }
                    }
                }
            }
        },
    };

    rsx! {
        div {
            style: "position: fixed; inset: 0; background: rgba(15,23,42,0.55); z-index: 900; \
                    display: flex; align-items: center; justify-content: center; padding: 24px;",
            onclick: move |_| on_close.call(()),
            div {
                style: "background: white; border-radius: 12px; width: min(1100px, 96vw); \
                        height: min(80vh, 900px); display: flex; flex-direction: column; \
                        overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.3);",
                // Clicks inside the pane must not reach the backdrop's close handler.
                onclick: move |e| e.stop_propagation(),
                div {
                    style: "display: flex; align-items: center; justify-content: space-between; \
                            padding: 12px 16px; border-bottom: 1px solid #E2E8F0;",
                    strong { style: "font-size: 14px;", "Search detail" }
                    button {
                        style: "background: none; border: none; font-size: 20px; cursor: pointer; \
                                color: #64748B; line-height: 1;",
                        onclick: move |_| on_close.call(()),
                        "\u{00d7}"
                    }
                }
                {body}
            }
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
                                    font-size: 11px; font-variant-numeric: tabular-nums;",
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
            style: "flex: 1; min-width: 0; border-right: 1px solid #E2E8F0; overflow-y: auto; \
                    padding: 10px 14px;",
            div {
                style: "font-size: 11px; font-weight: 600; text-transform: uppercase; \
                        letter-spacing: 0.4px; color: #64748B; margin-bottom: 8px; \
                        position: sticky; top: 0; background: white; padding-bottom: 4px;",
                "{heading}"
            }
            for (i, row) in rows.into_iter().enumerate() {
                div {
                    key: "{i}",
                    style: "display: flex; gap: 8px; padding: 5px 0; border-top: 1px solid #F1F5F9; \
                            font-size: 12px;",
                    span {
                        style: "flex-shrink: 0; min-width: 20px; text-align: right; color: #94A3B8; \
                                font-variant-numeric: tabular-nums;",
                        "{i + 1}"
                    }
                    div {
                        style: "min-width: 0;",
                        div { style: "word-break: break-word; color: #0F172A;", "{row.title}" }
                        div { style: "font-size: 11px; color: #166534; word-break: break-all;", "{row.display_url}" }
                        div {
                            style: "font-size: 10px; color: #64748B; margin-top: 2px;",
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
