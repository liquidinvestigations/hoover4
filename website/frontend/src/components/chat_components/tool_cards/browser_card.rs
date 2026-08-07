//! Cards for the browser router's Playwright tools.
//!
//! One family, two shapes. `browser_navigate` gets the full treatment — thumbnail, title,
//! the URL as a link, the page text, and a popup holding the archived page in a sandboxed
//! iframe. Every other action (`browser_click`, `browser_type`, …) gets a compact row:
//! what was done, to which element, and the resulting thumbnail. Read as a sequence, those
//! compact rows are a filmstrip of the navigation, which is the thing that makes a
//! multi-step browse legible at all.
//!
//! `status = 'too_large'` or `'failed'` renders as an **explicit line**, never as an
//! absent element: a capture that silently is not there looks identical to a tool that was
//! never called.

use dioxus::prelude::*;

use crate::components::chat_components::tool_cards::{
    artifact_refs, artifact_url, focus, http_link, json_str, result_marker_from_text,
    strip_artifact_marker, tool_content, tool_failure,
    ArtifactRef, CardShell, ElapsedCounter, FocusHandle, ModalCloseButton, ModalShell,
    ToolFailure,
};

/// Human phrasing per tool, in two tenses.
///
/// Two, not one, because the collapsed header is the only thing most readers see and it
/// has to be true: a `browser_navigate` that urlcheck refused used to read "opened
/// http://clickhouse:8123", describing the argument rather than the outcome. `done` is
/// what happened; `not_done` is what did not. Falls back to the raw name so a sidecar
/// upgrade that adds a tool still produces a readable card.
fn action_label(tool_name: &str, input: &serde_json::Value, failed: bool) -> String {
    let element = json_str(input, "element");
    let url = json_str(input, "url");
    let text = json_str(input, "text");
    let pick = |done: String, not_done: String| if failed { not_done } else { done };
    match tool_name {
        "browser_navigate" if !url.is_empty() => {
            pick(format!("opened {url}"), format!("could not open {url}"))
        }
        "browser_navigate" => pick("opened a page".into(), "could not open the page".into()),
        "browser_navigate_back" => pick("went back".into(), "could not go back".into()),
        "browser_snapshot" => pick("read the page".into(), "could not read the page".into()),
        "browser_take_screenshot" => {
            pick("took a screenshot".into(), "could not take a screenshot".into())
        }
        "browser_click" if !element.is_empty() => {
            pick(format!("clicked {element}"), format!("could not click {element}"))
        }
        "browser_click" => pick("clicked".into(), "could not click".into()),
        "browser_type" if !element.is_empty() => pick(
            format!("typed into {element}"),
            format!("could not type into {element}"),
        ),
        "browser_type" if !text.is_empty() => pick(
            format!("typed \u{201c}{text}\u{201d}"),
            format!("could not type \u{201c}{text}\u{201d}"),
        ),
        "browser_type" => pick("typed".into(), "could not type".into()),
        "browser_fill_form" => pick("filled a form".into(), "could not fill the form".into()),
        "browser_press_key" => {
            let key = json_str(input, "key");
            pick(format!("pressed {key}"), format!("could not press {key}"))
        }
        "browser_select_option" if !element.is_empty() => pick(
            format!("chose an option in {element}"),
            format!("could not choose an option in {element}"),
        ),
        "browser_hover" if !element.is_empty() => {
            pick(format!("hovered {element}"), format!("could not hover {element}"))
        }
        "browser_wait_for" => pick(
            "waited for the page".into(),
            "gave up waiting for the page".into(),
        ),
        "browser_tabs" => pick("managed tabs".into(), "could not manage tabs".into()),
        "browser_network_requests" => pick(
            "listed network requests".into(),
            "could not list network requests".into(),
        ),
        "browser_console_messages" => {
            pick("read the console".into(), "could not read the console".into())
        }
        "browser_evaluate" => pick(
            "ran a page expression".into(),
            "could not run the page expression".into(),
        ),
        other => {
            let bare = other.trim_start_matches("browser_").replace('_', " ");
            pick(bare.clone(), format!("{bare} \u{2014} failed"))
        }
    }
}

/// The text a Playwright tool returns.
///
/// It arrives in one of three shapes depending on how far up the stack it has travelled:
/// a bare string, MCP content blocks (`{"type":"text","text":…}`), or — the shape the
/// transcript actually stores — a **plain array of strings**, one per content block.
/// Missing that last case was worth a bug: `result_text` returned empty, the artifact
/// marker was never found, and the browser cards rendered with no thumbnail while the
/// captures existed and were correct.
fn result_text(content: &serde_json::Value) -> String {
    if let Some(s) = content.as_str() {
        return s.to_string();
    }
    if let Some(items) = content.as_array() {
        let joined: Vec<String> = items
            .iter()
            .filter_map(|i| {
                i.as_str()
                    .map(str::to_string)
                    .or_else(|| i.get("text").and_then(|t| t.as_str()).map(str::to_string))
            })
            .collect();
        if !joined.is_empty() {
            return joined.join("\n");
        }
    }
    // Structured payloads: prefer a text-ish field over dumping the whole object.
    for key in ["text", "result", "snapshot", "message"] {
        let value = json_str(content, key);
        if !value.is_empty() {
            return value;
        }
    }
    String::new()
}

#[component]
pub fn BrowserCard(
    tool_name: String,
    tool_input: String,
    tool_output: String,
    running: bool,
    elapsed_ms: Option<u32>,
) -> Element {
    let expanded = use_signal(|| false);
    let mut popup: Signal<Option<ArtifactRef>> = use_signal(|| None);
    // Whatever opened the popup, so focus can go back to it on close (plan §7.7). A
    // dialog that drops focus on the document body leaves a keyboard user at the top of
    // the page, having lost the card they were reading.
    let opener: FocusHandle = use_signal(|| None);

    let input = serde_json::from_str::<serde_json::Value>(&tool_input)
        .unwrap_or(serde_json::Value::Null);

    if running {
        let label = action_label(&tool_name, &input, false);
        return rsx! {
            div {
                style: "align-self: flex-start; max-width: 92%; background: #FFFBEB; \
                        border: 1px solid #FDE68A; border-radius: 10px; padding: 8px 12px; \
                        font-size: 13px; color: #78350F; display: flex; align-items: center; \
                        gap: 10px; flex-wrap: wrap;",
                span {
                    style: "flex-shrink: 0; background: #FDE68A; color: #78350F; \
                            border-radius: 999px; padding: 1px 8px; font-size: 11px; \
                            font-weight: 600; font-family: ui-monospace, monospace;",
                    "{tool_name}"
                }
                span { style: "flex: 1; min-width: 0;", "{label}" }
                ElapsedCounter { already_ms: elapsed_ms }
            }
        };
    }

    let content = tool_content(&tool_output).unwrap_or(serde_json::Value::Null);
    // Look for the marker in the *extracted* text, not the raw value: a result that
    // arrived as content blocks would otherwise be searched as escaped JSON, where the
    // payload's quotes are backslashed and the parse silently fails.
    let raw_text = result_text(&content);
    let marker = result_marker_from_text(&raw_text);
    let mut artifacts = artifact_refs(&content);
    if artifacts.is_empty() {
        artifacts = marker.artifacts.clone();
    }
    // Two independent accounts of the outcome, because neither is complete on its own: a
    // urlcheck refusal is a JSON body with no marker at all, and a Playwright failure is
    // prose the router flags for us because nothing in the text distinguishes it from the
    // page it was trying to fetch.
    let failure = tool_failure(&content).or_else(|| {
        marker.failed.then(|| ToolFailure {
            refused: false,
            message: "the browser could not complete this action".to_string(),
        })
    });
    // The marker is bookkeeping between the router and this card. Showing it would be
    // showing the user a UUID they cannot use.
    let text = strip_artifact_marker(&raw_text);
    let url = json_str(&input, "url");
    let link = http_link(&url);
    let label = action_label(&tool_name, &input, failure.is_some());
    let error = failure.as_ref().map(|f| f.message.clone()).unwrap_or_default();

    rsx! {
        CardShell {
            chip: tool_name.clone(),
            label: label.clone(),
            running: false,
            expanded,
            failure: failure.clone(),
            badges: rsx! {
                for a in artifacts.clone() {
                    ThumbnailButton {
                        key: "{a.artifact_id}",
                        artifact: a.clone(),
                        opener,
                        on_open: move |e| popup.set(Some(e)),
                        img_style: "height: 40px; width: 71px; object-fit: cover; \
                                    border-radius: 3px; display: block;".to_string(),
                        button_style: "padding: 0; border: 1px solid #FDE68A; background: none; \
                                       border-radius: 4px; cursor: pointer; flex-shrink: 0; \
                                       line-height: 0;".to_string(),
                    }
                }
            },

            if !error.is_empty() {
                div {
                    style: "background: #FEF2F2; color: #991B1B; border: 1px solid #FECACA; \
                            border-radius: 6px; padding: 6px 8px; font-size: 12px; \
                            word-break: break-word;",
                    "{error}"
                }
            }

            if let Some(href) = link.clone() {
                a {
                    href: "{href}",
                    target: "_blank",
                    rel: "noopener noreferrer nofollow",
                    style: "color: #1D4ED8; font-size: 12px; word-break: break-all;",
                    "{href}"
                }
            }

            for a in artifacts.clone() {
                CaptureBlock {
                    key: "{a.artifact_id}",
                    artifact: a.clone(),
                    opener,
                    on_open: move |e| popup.set(Some(e)),
                }
            }

            if !text.is_empty() {
                PageText { text: text.clone() }
            }
        }

        if let Some(a) = popup.read().clone() {
            ArchivedPagePopup {
                artifact: a,
                on_close: move |_| {
                    popup.set(None);
                    focus(opener);
                },
            }
        }
    }
}

/// A capture thumbnail that opens the archived page.
///
/// A button, not a bare `img onclick`: it opens a modal, so it must be reachable by
/// keyboard, and it must be the element focus returns to when that modal closes (§7.7).
/// It owns its own node handle and publishes it to the shared `opener` **on click** — a
/// card with three thumbnails would otherwise return focus to whichever mounted last.
#[component]
fn ThumbnailButton(
    artifact: ArtifactRef,
    opener: FocusHandle,
    on_open: EventHandler<ArtifactRef>,
    button_style: String,
    img_style: String,
) -> Element {
    let mut me: FocusHandle = use_signal(|| None);
    let mut opener = opener;
    let thumb = artifact_url(&artifact.artifact_id, "thumb.webp");
    let entry = artifact.clone();
    rsx! {
        button {
            title: "Open the archived page",
            "aria-label": "Open the archived page",
            style: "{button_style}",
            onmounted: move |e| me.set(Some(e.data())),
            onclick: move |_| {
                opener.set(me.read().clone());
                on_open.call(entry.clone());
            },
            img { src: "{thumb}", alt: "", style: "{img_style}" }
        }
    }
}

/// The thumbnail plus whatever the capture could not do, said out loud.
#[component]
fn CaptureBlock(
    artifact: ArtifactRef,
    on_open: EventHandler<ArtifactRef>,
    /// Set to this block's own trigger when it is clicked, so the popup returns focus
    /// here rather than to whichever thumbnail was mounted last.
    opener: FocusHandle,
) -> Element {
    let has_page = artifact.status == "ok";
    let entry = artifact.clone();
    rsx! {
        div {
            style: "display: flex; flex-direction: column; gap: 4px;",
            ThumbnailButton {
                artifact: entry.clone(),
                opener,
                on_open,
                img_style: "max-width: 100%; border-radius: 5px; display: block;".to_string(),
                button_style: "padding: 0; border: 1px solid #FDE68A; background: none; \
                               border-radius: 6px; cursor: pointer; line-height: 0; \
                               max-width: 100%;".to_string(),
            }
            if !artifact.title.is_empty() {
                div { style: "font-size: 12px; font-weight: 500;", "{artifact.title}" }
            }
            // Never an absent element: a capture that is not there must say why.
            if !has_page {
                div {
                    style: "font-size: 11px; color: #92400E; font-style: italic;",
                    if artifact.detail.is_empty() {
                        "The page itself was not archived (status: {artifact.status}). The screenshot above is what was kept."
                    } else {
                        "{artifact.detail}"
                    }
                }
            } else {
                div {
                    style: "font-size: 11px;",
                    "Click the screenshot to open the archived page."
                }
            }
        }
    }
}

/// The page text a Playwright tool returned, with a show-all toggle.
#[component]
fn PageText(text: String) -> Element {
    let mut show_all = use_signal(|| false);
    let full = *show_all.read();
    let clipped: String = if full || text.chars().count() <= 1200 {
        text.clone()
    } else {
        text.chars().take(1200).collect::<String>() + "\u{2026}"
    };
    let long = text.chars().count() > 1200;
    rsx! {
        div {
            pre {
                style: "margin: 0; white-space: pre-wrap; word-break: break-word; \
                        font-family: ui-monospace, monospace; font-size: 11px; \
                        background: #FEF3C7; padding: 8px; border-radius: 6px; \
                        max-height: 320px; overflow: auto;",
                "{clipped}"
            }
            if long {
                button {
                    style: "background: none; border: none; color: #92400E; cursor: pointer; \
                            font-size: 12px; padding: 2px 0 0 0; text-decoration: underline;",
                    onclick: move |_| {
                        let next = !*show_all.peek();
                        show_all.set(next);
                    },
                    if full { "Show less" } else { "Show all" }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_refused_navigation_does_not_claim_the_page_was_opened() {
        // Reproduced live: urlcheck refused `http://clickhouse:8123` and the collapsed
        // card read "opened http://clickhouse:8123".
        let input = serde_json::json!({"url": "http://clickhouse:8123"});
        assert_eq!(
            action_label("browser_navigate", &input, false),
            "opened http://clickhouse:8123"
        );
        assert_eq!(
            action_label("browser_navigate", &input, true),
            "could not open http://clickhouse:8123"
        );
    }

    #[test]
    fn every_action_has_a_failed_phrasing_that_is_not_the_succeeded_one() {
        let input = serde_json::json!({"element": "the Search button", "key": "Enter"});
        for tool in [
            "browser_navigate",
            "browser_navigate_back",
            "browser_snapshot",
            "browser_take_screenshot",
            "browser_click",
            "browser_type",
            "browser_fill_form",
            "browser_press_key",
            "browser_select_option",
            "browser_hover",
            "browser_wait_for",
            "browser_tabs",
            "browser_network_requests",
            "browser_console_messages",
            "browser_evaluate",
            // A tool the sidecar grew after this file was written.
            "browser_drag",
        ] {
            let done = action_label(tool, &input, false);
            let failed = action_label(tool, &input, true);
            assert_ne!(done, failed, "{tool} says the same thing either way");
            assert!(!done.is_empty() && !failed.is_empty(), "{tool} has no label");
        }
    }

    #[test]
    fn the_result_text_of_a_content_block_list_is_joined() {
        // The shape the transcript actually stores.
        let content = serde_json::json!(["### Page\n- Page URL: https://x.example/", "second"]);
        assert_eq!(result_text(&content), "### Page\n- Page URL: https://x.example/\nsecond");
    }
}

/// The archived page, in a sandboxed iframe.
///
/// `sandbox=""` — the empty value, not an omitted attribute — gives the document an opaque
/// origin with scripting disabled. The response also carries `default-src 'none'`, which
/// forbids every network fetch. Both are needed: the CSP alone still allows scripts, and
/// the sandbox alone still lets a stylesheet fetch leak that the capture was viewed.
///
/// Escape, the focus trap and the announced role all come from [`ModalShell`].
#[component]
fn ArchivedPagePopup(artifact: ArtifactRef, on_close: EventHandler<()>) -> Element {
    let page = artifact_url(&artifact.artifact_id, "page.html");
    let link = http_link(&artifact.url);
    let openable = artifact.status == "ok";
    rsx! {
        ModalShell {
            label: "Archived page".to_string(),
            on_close,
            pane_size: "width: min(1300px, 96vw); height: min(86vh, 950px);".to_string(),
            header: rsx! {
                div {
                    style: "display: flex; align-items: center; gap: 12px; padding: 10px 14px; \
                            border-bottom: 1px solid #E2E8F0; font-size: 12px;",
                    strong { style: "flex-shrink: 0;", "Archived page" }
                    if let Some(href) = link.clone() {
                        a {
                            href: "{href}",
                            target: "_blank",
                            rel: "noopener noreferrer nofollow",
                            style: "flex: 1; min-width: 0; color: #1D4ED8; overflow: hidden; \
                                    text-overflow: ellipsis; white-space: nowrap;",
                            "{href}"
                        }
                    } else {
                        span { style: "flex: 1; min-width: 0; opacity: 0.7;", "{artifact.url}" }
                    }
                    if openable {
                        a {
                            href: "{page}",
                            download: "page.html",
                            style: "flex-shrink: 0; color: #4F46E5;",
                            "Download"
                        }
                    }
                    ModalCloseButton { on_close }
                }
            },

            if openable {
                iframe {
                    src: "{page}",
                    title: "Archived copy of {artifact.url}",
                    // Quoted because dioxus_elements has no typed `sandbox` on
                    // iframe. The EMPTY value is the strict one — an omitted
                    // attribute means no sandbox at all, which is the opposite.
                    "sandbox": "",
                    style: "flex: 1; width: 100%; border: none; background: white;",
                }
            } else {
                div {
                    style: "flex: 1; display: flex; align-items: center; justify-content: center; \
                            padding: 30px; text-align: center; color: #92400E; font-size: 13px;",
                    if artifact.detail.is_empty() {
                        "This page was not archived (status: {artifact.status})."
                    } else {
                        "{artifact.detail}"
                    }
                }
            }
        }
    }
}
