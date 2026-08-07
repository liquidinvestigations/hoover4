//! Per-tool cards, dispatched from a registry keyed on the tool's name.
//!
//! `tool_disclosure.rs` used to be one `match` that grew a branch per tool, and that
//! shape has a specific failure: the generic branch got the *newest* tools, which are the
//! ones whose output is least readable as flat key/value rows. So the dispatch now lives
//! here and the generic card is the deliberate fallback rather than the default — an MCP
//! server that adds a tool tomorrow still renders, just plainly.
//!
//! ## The rule every card follows
//!
//! **Tool payloads are never rendered as HTML.** Titles, snippets and page text come from
//! the open web and are attacker-controlled; every one of them is a Dioxus text node, and
//! a URL becomes a link only after [`http_link`] has confirmed it is `http`/`https`.

pub mod browser_card;
pub mod web_search_card;

use dioxus::prelude::*;

use crate::components::chat_components::tool_disclosure::ToolCallDisclosure;

/// Route one tool call to its card.
///
/// `running` is true between `start_tool` and `end_tool`, when there is no output yet —
/// the whole reason Phase 1 exists is that a card can now show the query while the search
/// is still running.
#[component]
pub fn ToolCard(
    tool_name: String,
    tool_input: String,
    tool_output: String,
    content_summary: String,
    running: Option<bool>,
) -> Element {
    let running = running.unwrap_or(false);
    match tool_name.as_str() {
        "web_search" => rsx! {
            web_search_card::WebSearchCard {
                tool_input: tool_input.clone(),
                tool_output: tool_output.clone(),
                running,
            }
        },
        // Every Playwright tool the browser router forwards. Matching on the prefix
        // rather than listing two dozen names keeps a sidecar upgrade from silently
        // dropping new tools into the generic card.
        name if name.starts_with("browser_") => rsx! {
            browser_card::BrowserCard {
                tool_name: tool_name.clone(),
                tool_input: tool_input.clone(),
                tool_output: tool_output.clone(),
                running,
            }
        },
        _ => rsx! {
            ToolCallDisclosure {
                tool_name: tool_name.clone(),
                tool_input: tool_input.clone(),
                tool_output: tool_output.clone(),
                content_summary: content_summary.clone(),
                running,
            }
        },
    }
}

/// The tool's own result object, dug out of the LangGraph event envelope.
///
/// End events arrive as `{"output": {"content": …, "name": …}}` and the content is
/// sometimes a JSON string rather than an object (the agent's `recurse_json_decode`
/// usually unwraps it, but a payload truncated at `TOOL_PAYLOAD_CHARS` may not survive
/// that). Both shapes are handled, because a card that renders nothing for a real result
/// looks exactly like a tool that returned nothing.
pub fn tool_content(tool_output: &str) -> Option<serde_json::Value> {
    let root: serde_json::Value = serde_json::from_str(tool_output).ok()?;
    let content = root
        .get("output")
        .and_then(|o| o.get("content"))
        .or_else(|| root.get("content"))
        .unwrap_or(&root)
        .clone();
    if let serde_json::Value::String(s) = &content {
        if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(s) {
            return Some(parsed);
        }
    }
    Some(content)
}

pub fn json_str(v: &serde_json::Value, key: &str) -> String {
    v.get(key).and_then(|x| x.as_str()).unwrap_or("").to_string()
}

pub fn json_u64(v: &serde_json::Value, key: &str) -> u64 {
    v.get(key).and_then(|x| x.as_u64()).unwrap_or(0)
}

pub fn json_f64(v: &serde_json::Value, key: &str) -> Option<f64> {
    v.get(key).and_then(|x| x.as_f64())
}

pub fn json_bool(v: &serde_json::Value, key: &str) -> bool {
    v.get(key).and_then(|x| x.as_bool()).unwrap_or(false)
}

pub fn json_strings(v: &serde_json::Value, key: &str) -> Vec<String> {
    v.get(key)
        .and_then(|x| x.as_array())
        .map(|a| a.iter().filter_map(|i| i.as_str().map(str::to_string)).collect())
        .unwrap_or_default()
}

/// A URL that may become an `href`, or `None`.
///
/// The check is the point: a result's URL is attacker-controlled, and `javascript:` in an
/// `href` is script execution in the site's own origin. Anything that is not plainly
/// `http`/`https` is rendered as text instead of as a link.
pub fn http_link(url: &str) -> Option<String> {
    let trimmed = url.trim();
    let lowered = trimmed.to_ascii_lowercase();
    if lowered.starts_with("http://") || lowered.starts_with("https://") {
        Some(trimmed.to_string())
    } else {
        None
    }
}

/// The artifacts a tool result carries, from the reserved `_hoover4_artifacts` key.
#[derive(Debug, Clone, PartialEq)]
pub struct ArtifactRef {
    pub artifact_id: String,
    pub kind: String,
    pub status: String,
    pub url: String,
    pub title: String,
    pub detail: String,
}

/// Marker the browser router appends to a tool result's **text**.
///
/// `_hoover4_artifacts` in `structured_content` is the right place for this, and the
/// router puts it there too — but it does not survive the path to the transcript.
/// LangGraph's `on_tool_end` hands the backend a ToolMessage whose `content` is the text
/// blocks and nothing else, so a card reading only the structured key finds nothing and
/// renders no thumbnail. Verified against a real stored `tool_output`.
pub const ARTIFACT_MARKER: &str = "[hoover4:artifacts]";

fn parse_entries(entries: &[serde_json::Value]) -> Vec<ArtifactRef> {
    entries
        .iter()
        .filter_map(|e| {
            let id = json_str(e, "artifact_id");
            if id.is_empty() {
                return None;
            }
            Some(ArtifactRef {
                artifact_id: id,
                kind: json_str(e, "kind"),
                status: json_str(e, "status"),
                url: json_str(e, "url"),
                title: json_str(e, "title"),
                detail: json_str(e, "detail"),
            })
        })
        .collect()
}

pub fn artifact_refs(content: &serde_json::Value) -> Vec<ArtifactRef> {
    // The structured key first: a client that preserved it gives us richer data with no
    // parsing at all.
    if let Some(entries) = content.get("_hoover4_artifacts").and_then(|x| x.as_array()) {
        let refs = parse_entries(entries);
        if !refs.is_empty() {
            return refs;
        }
    }
    // Otherwise the text marker.
    match content {
        serde_json::Value::String(s) => artifact_refs_from_text(s),
        other => artifact_refs_from_text(&other.to_string()),
    }
}

/// Pull the marker's JSON out of a tool result's text.
pub fn artifact_refs_from_text(text: &str) -> Vec<ArtifactRef> {
    let Some(start) = text.rfind(ARTIFACT_MARKER) else {
        return Vec::new();
    };
    let rest = text[start + ARTIFACT_MARKER.len()..].trim_start();
    // The payload is one JSON array on one line. Take to the end of the line so trailing
    // content (there should be none, but a stored payload can be truncated mid-way)
    // cannot swallow the parse.
    let line = rest.split('\n').next().unwrap_or("").trim_end();
    serde_json::from_str::<Vec<serde_json::Value>>(line)
        .map(|entries| parse_entries(&entries))
        .unwrap_or_default()
}

/// The tool's text with the artifact marker removed.
///
/// The marker is bookkeeping between the router and this card; showing it to the user
/// would be showing them a UUID they cannot use.
pub fn strip_artifact_marker(text: &str) -> String {
    match text.rfind(ARTIFACT_MARKER) {
        Some(i) => text[..i].trim_end().to_string(),
        None => text.to_string(),
    }
}

pub fn artifact_url(artifact_id: &str, asset: &str) -> String {
    format!("/_chat_artifact/{artifact_id}/{asset}")
}

/// Shared card chrome, so every tool card looks like the same family.
#[component]
pub fn CardShell(
    chip: String,
    label: String,
    running: bool,
    /// Rendered on the header row, right of the label — counts, warning pips.
    badges: Element,
    /// Rendered when the card is expanded.
    children: Element,
    expanded: Signal<bool>,
) -> Element {
    rsx! {
        div {
            style: "align-self: flex-start; max-width: 92%; background: #FFFBEB; \
                    border: 1px solid #FDE68A; border-radius: 10px; padding: 8px 12px; \
                    font-size: 13px; color: #78350F;",
            div {
                style: "display: flex; align-items: center; gap: 10px; flex-wrap: wrap;",
                span {
                    style: "flex-shrink: 0; background: #FDE68A; color: #78350F; \
                            border-radius: 999px; padding: 1px 8px; font-size: 11px; \
                            font-weight: 600; font-family: ui-monospace, monospace;",
                    "{chip}"
                }
                span { style: "flex: 1; min-width: 0;", "{label}" }
                {badges}
                if running {
                    span {
                        style: "flex-shrink: 0; font-size: 12px; font-style: italic; color: #B45309;",
                        "running\u{2026}"
                    }
                } else {
                    button {
                        style: "background: none; border: none; color: #92400E; cursor: pointer; \
                                font-size: 12px; padding: 0; white-space: nowrap;",
                        onclick: move |_| {
                            let next = !*expanded.peek();
                            expanded.set(next);
                        },
                        if *expanded.read() { "Hide" } else { "Expand" }
                    }
                }
            }
            if *expanded.read() && !running {
                div {
                    style: "margin-top: 8px; display: flex; flex-direction: column; gap: 8px;",
                    {children}
                }
            }
        }
    }
}

/// Seconds since a running call started, ticking once a second.
///
/// A pending search with no elapsed counter is indistinguishable from a wedged one, which
/// is the state this whole card family exists to make visible.
#[component]
pub fn ElapsedCounter() -> Element {
    let mut seconds = use_signal(|| 0_u32);
    use_future(move || async move {
        loop {
            // `n0_future::time::sleep`, never `gloo_timers`: gloo's futures feature is
            // wasm-only, so the same file fails to build server-side and the whole site
            // serves 500. This cost a session once already.
            n0_future::time::sleep(std::time::Duration::from_millis(1000)).await;
            seconds += 1;
        }
    });
    let n = *seconds.read();
    rsx! {
        span {
            style: "flex-shrink: 0; font-size: 11px; color: #B45309; \
                    font-variant-numeric: tabular-nums;",
            "{n}s"
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_url_becomes_a_link_only_when_it_is_plainly_http() {
        assert_eq!(http_link("https://a.example/x"), Some("https://a.example/x".into()));
        assert_eq!(http_link(" http://a.example "), Some("http://a.example".into()));
        // The whole point: an href from the open web must not be able to run script.
        assert!(http_link("javascript:alert(1)").is_none());
        assert!(http_link("data:text/html,<script>x</script>").is_none());
        assert!(http_link("file:///etc/passwd").is_none());
        assert!(http_link("").is_none());
    }

    #[test]
    fn artifacts_are_read_from_the_structured_key_when_it_survived() {
        let v = serde_json::json!({
            "_hoover4_artifacts": [
                {"artifact_id": "abc", "kind": "page_capture", "status": "ok",
                 "url": "https://x.example/", "title": "X"}
            ]
        });
        let refs = artifact_refs(&v);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].artifact_id, "abc");
        assert_eq!(refs[0].url, "https://x.example/");
    }

    #[test]
    fn artifacts_are_read_from_the_text_marker_when_it_did_not() {
        // The real transcript path: LangGraph hands the backend the text blocks and
        // nothing else, so the structured key is gone by the time a card renders.
        let text = "### Page\n- Page URL: https://x.example/\n\n\
                    [hoover4:artifacts] [{\"artifact_id\":\"def\",\"kind\":\"page_capture\",\
                    \"status\":\"too_large\",\"url\":\"https://x.example/\",\"title\":\"X\",\
                    \"detail\":\"snapshot is 9000 kB\"}]";
        let refs = artifact_refs_from_text(text);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].artifact_id, "def");
        assert_eq!(refs[0].status, "too_large");
        assert_eq!(refs[0].detail, "snapshot is 9000 kB");
    }

    #[test]
    fn the_marker_is_stripped_before_the_text_is_shown() {
        let text = "### Page\n- Page URL: https://x.example/\n\n[hoover4:artifacts] [{}]";
        let shown = strip_artifact_marker(text);
        assert!(!shown.contains("hoover4:artifacts"));
        assert!(shown.ends_with("https://x.example/"));
    }

    #[test]
    fn text_with_no_marker_is_untouched_and_yields_nothing() {
        let text = "### Page\n- Page URL: https://x.example/";
        assert_eq!(strip_artifact_marker(text), text);
        assert!(artifact_refs_from_text(text).is_empty());
    }

    #[test]
    fn a_truncated_marker_payload_is_ignored_rather_than_panicking() {
        // tool_output is clipped at TOOL_PAYLOAD_CHARS, so a marker can arrive half-written.
        let text = "x\n[hoover4:artifacts] [{\"artifact_id\":\"gh";
        assert!(artifact_refs_from_text(text).is_empty());
    }

    #[test]
    fn tool_content_unwraps_the_langgraph_envelope() {
        let raw = r#"{"output":{"content":{"success":true,"results":[]},"name":"web_search"}}"#;
        let v = tool_content(raw).unwrap();
        assert_eq!(json_bool(&v, "success"), true);
    }

    #[test]
    fn tool_content_parses_a_content_that_arrived_as_a_json_string() {
        // A payload truncated at TOOL_PAYLOAD_CHARS may not have been decoded by the
        // agent's recurse_json_decode; a card that rendered nothing here would look
        // exactly like a tool that returned nothing.
        let raw = r#"{"output":{"content":"{\"success\":true}","name":"web_search"}}"#;
        let v = tool_content(raw).unwrap();
        assert_eq!(json_bool(&v, "success"), true);
    }

    #[test]
    fn artifact_urls_point_at_the_acl_checked_route() {
        assert_eq!(artifact_url("abc", "thumb.webp"), "/_chat_artifact/abc/thumb.webp");
        assert_eq!(artifact_url("abc", "page.html"), "/_chat_artifact/abc/page.html");
    }
}
