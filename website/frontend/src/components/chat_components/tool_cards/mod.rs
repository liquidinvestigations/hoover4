//! Per-tool cards, dispatched from a registry keyed on the tool's name.
//!
//! Do not fold this back into one `match` in `tool_disclosure.rs` that grows a branch
//! per tool. That shape has a specific failure: the generic branch collects the *newest*
//! tools, which are the ones whose output is least readable as flat key/value rows. With
//! the dispatch here the generic card is a deliberate fallback rather than the default —
//! an MCP server that adds a tool tomorrow still renders, just plainly.
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
/// which is what lets a card show the query while the search is still running.
#[component]
pub fn ToolCard(
    tool_name: String,
    tool_input: String,
    tool_output: String,
    content_summary: String,
    running: Option<bool>,
    /// How long a still-running call has been going, from the server. See
    /// [`ElapsedCounter`].
    elapsed_ms: Option<u32>,
) -> Element {
    let running = running.unwrap_or(false);
    match tool_name.as_str() {
        "web_search" => rsx! {
            web_search_card::WebSearchCard {
                tool_input: tool_input.clone(),
                tool_output: tool_output.clone(),
                running,
                elapsed_ms,
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
                elapsed_ms,
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

/// What a tool result says went wrong, if anything.
///
/// A card that reads only the tool's *arguments* describes what was attempted, not what
/// happened: a `browser_navigate` refused by urlcheck rendered, collapsed, as "opened
/// http://clickhouse:8123", and a `web_search` that errored read "0 results · 0 sources"
/// with no pip. Both are the demo telling the user something it knows to be false. Every
/// card asks this before it writes its header.
#[derive(Debug, Clone, PartialEq)]
pub struct ToolFailure {
    /// The tool declined the call outright — urlcheck, a rejected argument — rather than
    /// trying and failing. Worth distinguishing because a refusal is the system working.
    pub refused: bool,
    /// The message as the model saw it.
    pub message: String,
}

impl ToolFailure {
    /// One word for the header pip.
    pub fn verb(&self) -> &'static str {
        if self.refused {
            "refused"
        } else {
            "failed"
        }
    }
}

fn failure_from_object(v: &serde_json::Value) -> Option<ToolFailure> {
    let error = json_str(v, "error");
    let is_error = json_bool(v, "is_error");
    let success_false = v.get("success").and_then(|s| s.as_bool()) == Some(false);
    // Only the words that can only mean failure. A bare `status` key is common on healthy
    // payloads (an artifact entry's `status: "too_large"` is not a failed tool call), so
    // this does not treat "anything but ok" as broken.
    let bad_status = matches!(
        json_str(v, "status").as_str(),
        "error" | "failed" | "failure" | "refused"
    );
    if error.is_empty() && !is_error && !success_false && !bad_status {
        return None;
    }
    let message = if !error.is_empty() {
        error
    } else {
        let m = json_str(v, "message");
        if m.is_empty() {
            "the tool reported an error".to_string()
        } else {
            m
        }
    };
    let refused = message.to_ascii_lowercase().starts_with("refused");
    Some(ToolFailure { refused, message })
}

/// Playwright's own failures arrive as prose, and only as prose: the sidecar's `is_error`
/// is carried separately (see [`result_marker_from_text`]). Only the **first** line is
/// examined — for a browser tool the rest of the text is the fetched page, and a page that
/// happens to contain "Error: …" is not a failed tool call.
fn failure_from_text(text: &str) -> Option<ToolFailure> {
    let first = text.trim_start().lines().next()?.trim();
    let rest = first.strip_prefix("Error:").or_else(|| first.strip_prefix("error:"))?;
    Some(ToolFailure {
        refused: false,
        message: rest.trim().to_string(),
    })
}

/// Read a tool result's own account of whether it worked.
///
/// Handles the three shapes a result reaches the transcript in: the object itself, a list
/// of MCP content blocks (`{"type":"text","text": …}` — where `text` may already have been
/// JSON-decoded into an object by the agent), and a bare string.
pub fn tool_failure(content: &serde_json::Value) -> Option<ToolFailure> {
    match content {
        serde_json::Value::Object(_) => failure_from_object(content),
        serde_json::Value::Array(items) => items.iter().find_map(|item| {
            let inner = item.get("text").unwrap_or(item);
            tool_failure(inner)
        }),
        serde_json::Value::String(s) => {
            // A block whose text is still an unparsed JSON document.
            if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(s) {
                if let Some(f) = tool_failure(&parsed) {
                    return Some(f);
                }
            }
            failure_from_text(s)
        }
        _ => None,
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

/// Is this the shape `artifacts.new_id()` produces — a plain UUIDv4?
///
/// The id is interpolated straight into `/_chat_artifact/<id>/<asset>`, so it must be a
/// lookup key and nothing else. Anything else is refused rather than escaped: an id that
/// is not a UUID did not come from the artifact writer, and there is no legitimate value
/// for this field that this rejects.
fn is_artifact_id(id: &str) -> bool {
    let bytes = id.as_bytes();
    if bytes.len() != 36 {
        return false;
    }
    bytes.iter().enumerate().all(|(i, b)| match i {
        8 | 13 | 18 | 23 => *b == b'-',
        _ => b.is_ascii_hexdigit(),
    })
}

fn parse_entries(entries: &[serde_json::Value]) -> Vec<ArtifactRef> {
    entries
        .iter()
        .filter_map(|e| {
            let id = json_str(e, "artifact_id");
            if !is_artifact_id(&id) {
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
///
/// **Only the last line counts, and only if it is the marker.** For a browser tool the
/// text is the fetched page's own content, so anything found in the middle of it was
/// written by whoever wrote the page: a hostile site that plants
/// `[hoover4:artifacts] [...]` in its body got an attacker-chosen title and URL rendered
/// inside the trusted "Archived page" chrome, with `/_chat_artifact/<their string>/…`
/// probed as an image URL. No script ran — everything stays a text node — but it is UI
/// spoofing on a surface the design explicitly treats as attacker-controlled.
///
/// The router appends its marker as the final content block of *every* browser tool
/// result, including when nothing was captured (`[hoover4:artifacts] {"artifacts": []}`),
/// precisely so this position check has something to anchor on. A planted marker is
/// therefore always followed by the genuine one and never wins; a result that does not end
/// with a marker carries no artifacts at all rather than whatever its body happens to
/// contain.
pub fn artifact_refs_from_text(text: &str) -> Vec<ArtifactRef> {
    result_marker_from_text(text).artifacts
}

/// Everything the router's trailing marker says about a call.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct ResultMarker {
    pub artifacts: Vec<ArtifactRef>,
    /// The sidecar reported `is_error` for this call. Playwright says so only in prose,
    /// and by the time a result reaches the transcript that prose is indistinguishable
    /// from the page it fetched — so the router writes the flag down here instead.
    pub failed: bool,
    /// A marker was found at all. A browser result without one is either older than this
    /// mechanism or not from the router; either way `failed: false` means "unknown", not
    /// "fine", and the caller should fall back to reading the payload.
    pub present: bool,
}

/// Parse the trailing marker line.
///
/// Two payload shapes, because the marker predates the failure flag: the object form
/// `{"artifacts": [...], "failed": true}` written today, and the bare array `[...]`
/// already sitting in transcripts. Both are read; only the object form can say `failed`.
pub fn result_marker_from_text(text: &str) -> ResultMarker {
    let Some(line) = text.trim_end().lines().next_back() else {
        return ResultMarker::default();
    };
    let Some(payload) = line.trim().strip_prefix(ARTIFACT_MARKER) else {
        return ResultMarker::default();
    };
    let Ok(value) = serde_json::from_str::<serde_json::Value>(payload.trim()) else {
        return ResultMarker::default();
    };
    match &value {
        serde_json::Value::Array(entries) => ResultMarker {
            artifacts: parse_entries(entries),
            failed: false,
            present: true,
        },
        serde_json::Value::Object(_) => ResultMarker {
            artifacts: value
                .get("artifacts")
                .and_then(|a| a.as_array())
                .map(|e| parse_entries(e))
                .unwrap_or_default(),
            failed: json_bool(&value, "failed"),
            present: true,
        },
        _ => ResultMarker::default(),
    }
}

/// The tool's text with the artifact marker removed.
///
/// The marker is bookkeeping between the router and this card; showing it to the user
/// would be showing them a UUID they cannot use.
///
/// Only a *trailing* marker line is removed, matching `artifact_refs_from_text`. Cutting
/// at the last occurrence anywhere would let a page that plants the marker in its own body
/// truncate everything the user would otherwise see after it.
pub fn strip_artifact_marker(text: &str) -> String {
    let trimmed = text.trim_end();
    match trimmed.lines().next_back() {
        Some(last) if last.trim().starts_with(ARTIFACT_MARKER) => {
            trimmed[..trimmed.len() - last.len()].trim_end().to_string()
        }
        _ => text.to_string(),
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
    /// Set when the call did not do what its label says. The card turns red and grows a
    /// pip **collapsed**, which is the state a reader who is skimming actually sees; an
    /// error visible only after clicking Expand is an error nobody reads.
    failure: Option<ToolFailure>,
) -> Element {
    let (background, border, ink) = match failure {
        Some(_) => ("#FEF2F2", "#FECACA", "#991B1B"),
        None => ("#FFFBEB", "#FDE68A", "#78350F"),
    };
    let chip_bg = if failure.is_some() { "#FECACA" } else { "#FDE68A" };
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
                {badges}
                if running {
                    span {
                        style: "flex-shrink: 0; font-size: 12px; font-style: italic; color: #B45309;",
                        "running\u{2026}"
                    }
                } else {
                    button {
                        style: "background: none; border: none; color: {ink}; cursor: pointer; \
                                font-size: 12px; padding: 0; white-space: nowrap; \
                                text-decoration: underline;",
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

/// A mounted element we may want to move focus to later.
pub type FocusHandle = Signal<Option<std::rc::Rc<MountedData>>>;

/// Move focus to an element mounted earlier, if it is still there.
pub fn focus(handle: FocusHandle) {
    let Some(node) = handle.read().clone() else {
        return;
    };
    spawn(async move {
        let _ = node.set_focus(true).await;
    });
}

/// The chrome every tool-card popup shares: backdrop, pane, and the keyboard contract.
///
/// It is not decoration. A popup that covers the page cannot be closed or navigated
/// without a mouse unless it carries all of this: a `role`, so a screen reader announces
/// it; a focus move, so Tab does not carry on through the transcript *behind* the
/// overlay; and an Escape handler.
///
/// The trap is two focus guards rather than a DOM query for focusable descendants — there
/// is no DOM to query from here. Tab off either end lands on a guard, which bounces focus
/// back to the pane, and tabbing resumes inside. `on_close` is expected to refocus
/// whatever opened the popup; see [`focus`].
#[component]
pub fn ModalShell(
    /// Announced as the dialog's name.
    label: String,
    on_close: EventHandler<()>,
    /// Header row, inside the pane, above the body.
    header: Element,
    /// Width/height of the pane, as a CSS fragment.
    pane_size: String,
    children: Element,
) -> Element {
    let mut pane: FocusHandle = use_signal(|| None);
    let bounce = move |_| focus(pane);
    rsx! {
        div {
            style: "position: fixed; inset: 0; background: rgba(15,23,42,0.55); z-index: 900; \
                    display: flex; align-items: center; justify-content: center; padding: 24px;",
            onclick: move |_| on_close.call(()),
            div { tabindex: "0", onfocus: bounce }
            div {
                role: "dialog",
                "aria-modal": "true",
                "aria-label": "{label}",
                // Focused on mount so the keyboard is inside the dialog from the first
                // key, and `-1` so it is reachable programmatically without joining the
                // tab order itself.
                tabindex: "-1",
                onmounted: move |e| {
                    pane.set(Some(e.data()));
                    focus(pane);
                },
                onkeydown: move |e| {
                    if e.key() == Key::Escape {
                        e.stop_propagation();
                        on_close.call(());
                    }
                },
                style: "background: white; border-radius: 12px; {pane_size} \
                        display: flex; flex-direction: column; overflow: hidden; \
                        box-shadow: 0 20px 60px rgba(0,0,0,0.3); outline: none;",
                // Clicks inside the pane must not reach the backdrop's close handler.
                onclick: move |e| e.stop_propagation(),
                {header}
                {children}
            }
            div { tabindex: "0", onfocus: bounce }
        }
    }
}

/// The close button every popup header ends with.
#[component]
pub fn ModalCloseButton(on_close: EventHandler<()>) -> Element {
    rsx! {
        button {
            "aria-label": "Close",
            style: "background: none; border: none; font-size: 20px; cursor: pointer; \
                    color: #64748B; line-height: 1; flex-shrink: 0;",
            onclick: move |_| on_close.call(()),
            "\u{00d7}"
        }
    }
}

/// Seconds since a running call started, ticking once a second.
///
/// A pending search with no elapsed counter is indistinguishable from a wedged one, which
/// is the state this whole card family exists to make visible.
///
/// `already_ms` seeds it from the server's own measurement of how long the call has been
/// running. Without it, refreshing the page mid-call restarted the count at 0 and a
/// two-minute browse read as having just begun — the counter saying the reassuring thing
/// exactly when the worrying one is true. The seed is read once, at mount; the tick then
/// runs locally so the number moves between polls.
#[component]
pub fn ElapsedCounter(already_ms: Option<u32>) -> Element {
    let mut seconds = use_signal(|| already_ms.unwrap_or(0) / 1000);
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

    /// A real `artifacts.new_id()` — a UUIDv4, which is the only id shape accepted.
    const ID_A: &str = "6f1a3c2e-9b4d-4a71-8e0f-2c5d7a9b1e33";
    const ID_B: &str = "0b7e5d41-2f68-4c93-a0d5-9e1b6c84f207";

    #[test]
    fn artifacts_are_read_from_the_structured_key_when_it_survived() {
        let v = serde_json::json!({
            "_hoover4_artifacts": [
                {"artifact_id": ID_A, "kind": "page_capture", "status": "ok",
                 "url": "https://x.example/", "title": "X"}
            ]
        });
        let refs = artifact_refs(&v);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].artifact_id, ID_A);
        assert_eq!(refs[0].url, "https://x.example/");
    }

    fn marker_line(id: &str, title: &str) -> String {
        format!(
            "[hoover4:artifacts] [{{\"artifact_id\":\"{id}\",\"kind\":\"page_capture\",\
             \"status\":\"ok\",\"url\":\"https://x.example/\",\"title\":\"{title}\"}}]"
        )
    }

    #[test]
    fn artifacts_are_read_from_the_text_marker_when_it_did_not() {
        // The real transcript path: LangGraph hands the backend the text blocks and
        // nothing else, so the structured key is gone by the time a card renders.
        let text = format!(
            "### Page\n- Page URL: https://x.example/\n\n\
             [hoover4:artifacts] [{{\"artifact_id\":\"{ID_A}\",\"kind\":\"page_capture\",\
             \"status\":\"too_large\",\"url\":\"https://x.example/\",\"title\":\"X\",\
             \"detail\":\"snapshot is 9000 kB\"}}]"
        );
        let refs = artifact_refs_from_text(&text);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].artifact_id, ID_A);
        assert_eq!(refs[0].status, "too_large");
        assert_eq!(refs[0].detail, "snapshot is 9000 kB");
    }

    #[test]
    fn a_marker_planted_by_the_page_never_wins() {
        // The attack: a browser tool's text IS the fetched page, so a hostile site can
        // write the marker into its own body and get its own title and URL rendered in
        // the trusted "Archived page" chrome. The router's genuine marker is always the
        // final block, so only the final line is honoured.
        let text = format!(
            "### Page\n{}\nsome more page text\n{}",
            marker_line(ID_B, "Your bank"),
            marker_line(ID_A, "Real capture"),
        );
        let refs = artifact_refs_from_text(&text);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].artifact_id, ID_A);
        assert_eq!(refs[0].title, "Real capture");
    }

    #[test]
    fn a_page_marker_alone_yields_nothing() {
        // The router appends `[hoover4:artifacts] []` even when it captured nothing, so a
        // result whose last line is not a marker cannot have come from it.
        let text = format!("### Page\n{}\ntrailing page text", marker_line(ID_B, "Your bank"));
        assert!(artifact_refs_from_text(&text).is_empty());
    }

    #[test]
    fn an_empty_trailing_marker_is_the_no_artifacts_case() {
        let text = "### Console\nnothing to report\n[hoover4:artifacts] []";
        assert!(artifact_refs_from_text(text).is_empty());
        assert_eq!(strip_artifact_marker(text), "### Console\nnothing to report");
    }

    #[test]
    fn an_id_that_is_not_a_uuid_is_refused() {
        // The id is interpolated into `/_chat_artifact/<id>/<asset>`; nothing but a
        // lookup key belongs there.
        for bad in ["abc", "../../etc/passwd", "", "6f1a3c2e9b4d4a718e0f2c5d7a9b1e33"] {
            let text = format!(
                "x\n[hoover4:artifacts] [{{\"artifact_id\":\"{bad}\",\"kind\":\"page_capture\"}}]"
            );
            assert!(artifact_refs_from_text(&text).is_empty(), "accepted {bad:?}");
        }
        assert!(is_artifact_id(ID_A));
    }

    #[test]
    fn the_marker_is_stripped_before_the_text_is_shown() {
        let text = "### Page\n- Page URL: https://x.example/\n\n[hoover4:artifacts] [{}]";
        let shown = strip_artifact_marker(text);
        assert!(!shown.contains("hoover4:artifacts"));
        assert!(shown.ends_with("https://x.example/"));
    }

    #[test]
    fn stripping_does_not_let_a_page_hide_its_own_content() {
        // Cutting at the last occurrence anywhere would let a planted marker truncate
        // everything after it out of the user's view.
        let text = "### Page\n[hoover4:artifacts] [{}]\nthe part they wanted hidden";
        assert_eq!(strip_artifact_marker(text), text);
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

    // ---------------------------------------------------------------- failure detection

    #[test]
    fn a_urlcheck_refusal_is_read_as_a_refusal() {
        // The real stored shape: the agent JSON-decoded the block's text, so the payload
        // arrives as a *content block list* whose `text` is already an object.
        let raw = r#"[{"text":{"error":"refused: 'clickhouse' is an internal service and must not be fetched","success":false},"type":"text"}]"#;
        let v: serde_json::Value = serde_json::from_str(raw).unwrap();
        let f = tool_failure(&v).expect("a refusal must be visible to the card");
        assert!(f.refused, "a refusal is the system working, not a crash");
        assert_eq!(f.verb(), "refused");
        assert!(f.message.contains("internal service"));
    }

    #[test]
    fn a_bare_refusal_object_is_read_too() {
        let v = serde_json::json!({"success": false, "error": "refused: no"});
        assert_eq!(tool_failure(&v).unwrap().verb(), "refused");
    }

    #[test]
    fn success_false_without_a_message_still_fails_loudly() {
        let v = serde_json::json!({"success": false});
        let f = tool_failure(&v).unwrap();
        assert_eq!(f.verb(), "failed");
        assert!(!f.message.is_empty(), "a pip with no tooltip explains nothing");
    }

    #[test]
    fn a_web_search_error_is_a_failure_not_a_count_of_zero() {
        // "0 results · 0 sources" phrased a dead search as if the web had nothing to say.
        let v = serde_json::json!({"success": false, "query": "x", "error": "upstream timeout"});
        assert_eq!(tool_failure(&v).unwrap().message, "upstream timeout");
    }

    #[test]
    fn a_healthy_result_is_not_dressed_up_as_broken() {
        let v = serde_json::json!({"success": true, "results": [], "sources_used": ["ddg"]});
        assert!(tool_failure(&v).is_none());
        // An artifact whose *capture* was too large is not a failed tool call.
        let v = serde_json::json!({"status": "too_large", "artifact_id": ID_A});
        assert!(tool_failure(&v).is_none());
        // Neither is an empty error string.
        assert!(tool_failure(&serde_json::json!({"error": ""})).is_none());
    }

    #[test]
    fn playwright_prose_is_only_read_on_the_first_line() {
        // The rest of a browser result IS the fetched page. A page that says "Error: 404"
        // in its body has not failed the tool call, and treating it as one would put a
        // red card over a perfectly good capture.
        let v = serde_json::json!("Error: page.goto: net::ERR_PROXY_CONNECTION_FAILED");
        assert_eq!(
            tool_failure(&v).unwrap().message,
            "page.goto: net::ERR_PROXY_CONNECTION_FAILED"
        );
        let page = serde_json::json!("### Page\n- Page URL: https://x.example/\nError: 404 not found");
        assert!(tool_failure(&page).is_none());
    }

    // ------------------------------------------------------------------- result marker

    #[test]
    fn the_marker_carries_the_routers_failure_flag() {
        // Playwright's `is_error` does not survive to the transcript; this is how the card
        // learns that "opened http://clickhouse:8123" did not happen.
        let text = format!(
            "Error: refused\n[hoover4:artifacts] {{\"artifacts\": [], \"failed\": true}}"
        );
        let m = result_marker_from_text(&text);
        assert!(m.present && m.failed);
        assert!(m.artifacts.is_empty());
    }

    #[test]
    fn the_object_marker_still_yields_artifacts() {
        let text = format!(
            "### Page\n[hoover4:artifacts] {{\"artifacts\": [{{\"artifact_id\":\"{ID_A}\",\
             \"kind\":\"page_capture\",\"status\":\"ok\"}}]}}"
        );
        let m = result_marker_from_text(&text);
        assert_eq!(m.artifacts.len(), 1);
        assert_eq!(m.artifacts[0].artifact_id, ID_A);
        assert!(!m.failed);
    }

    #[test]
    fn the_legacy_array_marker_is_still_read() {
        // Transcripts already hold thousands of these; the shape changed, the history did
        // not. An array cannot say `failed`, which is exactly why the shape changed.
        let text = format!("### Page\n{}", marker_line(ID_A, "Real capture"));
        let m = result_marker_from_text(&text);
        assert_eq!(m.artifacts.len(), 1);
        assert!(m.present && !m.failed);
    }

    #[test]
    fn no_marker_means_unknown_rather_than_fine() {
        let m = result_marker_from_text("### Page\njust a page");
        assert!(!m.present, "absence must not read as a successful call");
        assert!(!m.failed);
    }

    #[test]
    fn a_page_planted_object_marker_still_never_wins() {
        // Same position rule as before — the flag rides in the same line, so it inherits
        // the same authentication. A page cannot mark its own capture as failed either.
        let planted = "[hoover4:artifacts] {\"artifacts\": [], \"failed\": true}";
        let text = format!("### Page\n{planted}\nmore page text\n{}", marker_line(ID_A, "Real"));
        let m = result_marker_from_text(&text);
        assert!(!m.failed);
        assert_eq!(m.artifacts[0].title, "Real");
    }

    #[test]
    fn artifact_urls_point_at_the_acl_checked_route() {
        assert_eq!(artifact_url(ID_A, "thumb.webp"), format!("/_chat_artifact/{ID_A}/thumb.webp"));
        assert_eq!(artifact_url(ID_A, "page.html"), format!("/_chat_artifact/{ID_A}/page.html"));
    }
}
