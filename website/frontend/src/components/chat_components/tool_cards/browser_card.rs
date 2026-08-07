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
    artifact_refs, artifact_refs_from_text, artifact_url, http_link, json_str,
    strip_artifact_marker, tool_content,
    ArtifactRef, CardShell, ElapsedCounter,
};

/// Human phrasing per tool. Falls back to the raw name so a sidecar upgrade that adds a
/// tool still produces a readable card.
fn action_label(tool_name: &str, input: &serde_json::Value) -> String {
    let element = json_str(input, "element");
    let url = json_str(input, "url");
    let text = json_str(input, "text");
    match tool_name {
        "browser_navigate" if !url.is_empty() => format!("opened {url}"),
        "browser_navigate" => "opened a page".to_string(),
        "browser_navigate_back" => "went back".to_string(),
        "browser_snapshot" => "read the page".to_string(),
        "browser_take_screenshot" => "took a screenshot".to_string(),
        "browser_click" if !element.is_empty() => format!("clicked {element}"),
        "browser_click" => "clicked".to_string(),
        "browser_type" if !element.is_empty() => format!("typed into {element}"),
        "browser_type" if !text.is_empty() => format!("typed \u{201c}{text}\u{201d}"),
        "browser_type" => "typed".to_string(),
        "browser_fill_form" => "filled a form".to_string(),
        "browser_press_key" => format!("pressed {}", json_str(input, "key")),
        "browser_select_option" if !element.is_empty() => format!("chose an option in {element}"),
        "browser_hover" if !element.is_empty() => format!("hovered {element}"),
        "browser_wait_for" => "waited for the page".to_string(),
        "browser_tabs" => "managed tabs".to_string(),
        "browser_network_requests" => "listed network requests".to_string(),
        "browser_console_messages" => "read the console".to_string(),
        "browser_evaluate" => "ran a page expression".to_string(),
        other => other.trim_start_matches("browser_").replace('_', " "),
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
) -> Element {
    let expanded = use_signal(|| false);
    let mut popup: Signal<Option<ArtifactRef>> = use_signal(|| None);

    let input = serde_json::from_str::<serde_json::Value>(&tool_input)
        .unwrap_or(serde_json::Value::Null);
    let label = action_label(&tool_name, &input);

    if running {
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
                ElapsedCounter {}
            }
        };
    }

    let content = tool_content(&tool_output).unwrap_or(serde_json::Value::Null);
    // Look for the marker in the *extracted* text, not the raw value: a result that
    // arrived as content blocks would otherwise be searched as escaped JSON, where the
    // payload's quotes are backslashed and the parse silently fails.
    let raw_text = result_text(&content);
    let mut artifacts = artifact_refs(&content);
    if artifacts.is_empty() {
        artifacts = artifact_refs_from_text(&raw_text);
    }
    // The marker is bookkeeping between the router and this card. Showing it would be
    // showing the user a UUID they cannot use.
    let text = strip_artifact_marker(&raw_text);
    let url = json_str(&input, "url");
    let link = http_link(&url);
    // A refusal from urlcheck comes back as {"success": false, "error": "refused: …"}.
    let error = json_str(&content, "error");

    rsx! {
        CardShell {
            chip: tool_name.clone(),
            label: label.clone(),
            running: false,
            expanded,
            badges: rsx! {
                for a in artifacts.clone() {
                    {
                        let thumb = artifact_url(&a.artifact_id, "thumb.webp");
                        let entry = a.clone();
                        rsx! {
                            img {
                                key: "{a.artifact_id}",
                                src: "{thumb}",
                                alt: "page thumbnail",
                                title: "Open the archived page",
                                style: "height: 40px; width: 71px; object-fit: cover; \
                                        border-radius: 4px; border: 1px solid #FDE68A; \
                                        cursor: pointer; flex-shrink: 0;",
                                onclick: move |_| popup.set(Some(entry.clone())),
                            }
                        }
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
                CaptureBlock { key: "{a.artifact_id}", artifact: a.clone(), on_open: move |e| popup.set(Some(e)) }
            }

            if !text.is_empty() {
                PageText { text: text.clone() }
            }
        }

        if let Some(a) = popup.read().clone() {
            ArchivedPagePopup { artifact: a, on_close: move |_| popup.set(None) }
        }
    }
}

/// The thumbnail plus whatever the capture could not do, said out loud.
#[component]
fn CaptureBlock(artifact: ArtifactRef, on_open: EventHandler<ArtifactRef>) -> Element {
    let thumb = artifact_url(&artifact.artifact_id, "thumb.webp");
    let has_page = artifact.status == "ok";
    let entry = artifact.clone();
    rsx! {
        div {
            style: "display: flex; flex-direction: column; gap: 4px;",
            img {
                src: "{thumb}",
                alt: "screenshot of the page",
                style: "max-width: 100%; border-radius: 6px; border: 1px solid #FDE68A; \
                        cursor: pointer;",
                onclick: move |_| on_open.call(entry.clone()),
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

/// The archived page, in a sandboxed iframe.
///
/// `sandbox=""` — the empty value, not an omitted attribute — gives the document an opaque
/// origin with scripting disabled. The response also carries `default-src 'none'`, which
/// forbids every network fetch. Both are needed: the CSP alone still allows scripts, and
/// the sandbox alone still lets a stylesheet fetch leak that the capture was viewed.
#[component]
fn ArchivedPagePopup(artifact: ArtifactRef, on_close: EventHandler<()>) -> Element {
    let page = artifact_url(&artifact.artifact_id, "page.html");
    let link = http_link(&artifact.url);
    let openable = artifact.status == "ok";
    rsx! {
        div {
            style: "position: fixed; inset: 0; background: rgba(15,23,42,0.55); z-index: 900; \
                    display: flex; align-items: center; justify-content: center; padding: 24px;",
            onclick: move |_| on_close.call(()),
            // Escape closes, and the backdrop is focusable so the key event has somewhere
            // to land without stealing focus from the page behind.
            tabindex: "-1",
            autofocus: true,
            onkeydown: move |e| {
                if e.key() == Key::Escape {
                    on_close.call(());
                }
            },
            div {
                style: "background: white; border-radius: 12px; width: min(1300px, 96vw); \
                        height: min(86vh, 950px); display: flex; flex-direction: column; \
                        overflow: hidden; box-shadow: 0 20px 60px rgba(0,0,0,0.3);",
                onclick: move |e| e.stop_propagation(),
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
                    button {
                        style: "background: none; border: none; font-size: 20px; cursor: pointer; \
                                color: #64748B; line-height: 1; flex-shrink: 0;",
                        onclick: move |_| on_close.call(()),
                        "\u{00d7}"
                    }
                }
                if openable {
                    iframe {
                        src: "{page}",
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
}
