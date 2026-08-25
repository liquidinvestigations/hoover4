//! The `web_search` card: pending, collapsed, expanded, and the ranking popup.
//!
//! Four states, because the four questions are different:
//!
//! * **Pending**: the query and an elapsed counter, while the search runs. This is
//!   possible only because in-flight tool calls are visible at all.
//! * **Collapsed**: `web_search · "danube water level" · 18 results · 5 sources`, plus a
//!   warning pip when a source came back empty.
//! * **Expanded** shows the result list: rank badge, domain chip, the title as a real link,
//!   the *full* snippet, the sources that corroborated it, and an `RRF #7 → #2` badge
//!   where reranking moved it. This is the level that answers "what did it actually find".
//! * **Popup**, both orderings side by side, fetched lazily from the search-detail
//!   artifact. `TOOL_PAYLOAD_CHARS` cannot carry two orderings of forty candidates, which
//!   is why the artifact exists.
//!
//! Every string here is a text node and every link goes through `http_link` first. See
//! the module docstring in `tool_cards/mod.rs`.

use dioxus::prelude::*;

use crate::api::chat_api::chat_artifact_detail;
use crate::components::chat_components::tool_cards::{
    focus, http_link, json_bool, json_f64, json_str, json_strings, json_u64, tool_content,
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

    let query = serde_json::from_str::<serde_json::Value>(&tool_input)
        .ok()
        .map(|v| json_str(&v, "query"))
        .unwrap_or_default();
    let requested_sources = serde_json::from_str::<serde_json::Value>(&tool_input)
        .ok()
        .map(|v| json_strings(&v, "sources"))
        .unwrap_or_default();

    if running {
        return rsx! { PendingSearch { query, sources: requested_sources, elapsed_ms } };
    }

    let Some(content) = tool_content(&tool_output) else {
        // Not "the payload was not recorded": the payload IS recorded, it just did not
        // survive as JSON. Showing the bytes is worth more than a card that denies the
        // data exists. See `truncate_tool_payload`, which is why this happens far less
        // often now.
        return rsx! { UnparseableSearch { query, raw: tool_output.clone() } };
    };

    let results = parse_rows(&content, "results");
    let sources_used = json_strings(&content, "sources_used");
    let degraded = json_strings(&content, "degraded");
    let unknown_sources = json_strings(&content, "unknown_sources");
    let rerank_applied = json_bool(&content, "rerank_applied");
    let rerank_error = json_str(&content, "rerank_error");
    let artifact_id = json_str(&content, "artifact_id");
    // A dead search used to read "0 results · 0 sources". A count, phrased as if the web
    // simply had nothing to say. The failure is the headline, so it goes in the header.
    let failure = tool_failure(&content);
    let error = failure.as_ref().map(|f| f.message.clone()).unwrap_or_default();
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
            failure: failure.clone(),
            badges: rsx! {
                // Counts only when there was a search to count. Beside a "failed" pip they
                // read as a result rather than as the absence of one.
                if failure.is_none() {
                    span {
                        style: "flex-shrink: 0; font-size: 11px; opacity: 0.8; \
                                font-variant-numeric: tabular-nums;",
                        "{results.len()} results \u{b7} {sources_used.len()} sources"
                    }
                }
                if !degraded.is_empty() {
                    span {
                        title: "These sources returned nothing, so the results come from fewer than intended",
                        style: "flex-shrink: 0; background: #FEE2E2; color: #991B1B; \
                                border-radius: 999px; padding: 1px 7px; font-size: 11px;",
                        "\u{26a0} {degraded.len()} degraded"
                    }
                }
                // Only meaningful about a search that ran: "not reranked" beside a failure
                // pip invites the reader to assume ranking was the problem.
                if !rerank_applied && failure.is_none() {
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

            // Said out loud, because the alternative is a list that silently stops. The
            // model saw the whole result set; this row is the transcript's copy of it.
            if json_bool(&content, "truncated") {
                div {
                    style: "font-size: 11px; font-style: italic; opacity: 0.75;",
                    "The lowest-ranked results were dropped so this call fits in the \
                     transcript. The assistant saw all of them."
                }
            }

            if has_artifact {
                div {
                    button {
                        style: "background: none; border: none; color: #92400E; cursor: pointer; \
                                font-size: 12px; padding: 0; text-decoration: underline;",
                        onmounted: move |e| opener.set(Some(e.data())),
                        onclick: move |_| popup_open.set(true),
                        "Search detail \u{2014} before and after reranking"
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
                    style: "font-size: 12px; font-style: italic; opacity: 0.75;",
                    "Nothing was stored for this call."
                }
            } else {
                pre {
                    style: "margin: 0; white-space: pre-wrap; word-break: break-word; \
                            font-family: ui-monospace, monospace; font-size: 11px; \
                            background: #FEE2E2; padding: 8px; border-radius: 6px; \
                            max-height: 320px; overflow: auto;",
                    "{raw}"
                }
            }
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
                    // The title is a link only when the URL is plainly http/https,
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
                class: "x-error-display",
                style: "padding: 20px; color: #991B1B;",
                "Could not load the search detail: {e}"
            }
        },
        Some(Ok(text)) => match serde_json::from_str::<serde_json::Value>(text) {
            Err(e) => rsx! {
                div {
                    class: "x-error-display",
                    style: "padding: 20px; color: #991B1B;",
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
                            padding: 12px 16px; border-bottom: 1px solid #E2E8F0;",
                    strong { style: "font-size: 14px;", "Search detail" }
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
