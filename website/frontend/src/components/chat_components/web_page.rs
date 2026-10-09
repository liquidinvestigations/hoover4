//! Source cards and a preview of captured web page Markdown.

use common::chat_pages::{CapturedWebPage, ChatPageRef};
use dioxus::prelude::*;

use super::markdown_text::MarkdownishText;
use super::tool_cards::http_link;
use crate::api::chat_api::chat_artifact_detail;
use crate::data_definitions::doc_viewer_state::DocViewerStateControl;
use crate::components::search_components::search_result_item_card::ResultCardLabel;

#[derive(Clone, Copy)]
pub struct ChatWebOpen {
    pub open: Callback<(String, String)>,
}

#[component]
pub fn WebPageCard(page: ChatPageRef, #[props(default)] passages: Vec<ChatPageRef>) -> Element {
    let open = try_use_context::<ChatWebOpen>();
    let title = if page.title.trim().is_empty() { page.url.clone() } else { page.title.clone() };
    let href = http_link(if page.final_url.is_empty() { &page.url } else { &page.final_url });
    let domain = href.as_deref().unwrap_or_default().split("://").nth(1)
        .unwrap_or_default().split('/').next().unwrap_or_default().to_string();
    let target = (page.artifact_id.clone(), page.terms.first().cloned().unwrap_or_default());
    let passages = if passages.is_empty() { vec![page.clone()] } else { passages };
    let mut seen = std::collections::HashSet::new();
    let quotes = passages.iter().flat_map(|source| source.quotes.iter().map(move |quote| (source, quote)))
        .filter(|(source, quote)| seen.insert((source.version.clone(), (*quote).clone())))
        .map(|(source, quote)| {
            let find = source.terms.iter().find(|term| quote.contains(term.as_str())).cloned().unwrap_or_default();
            (source.clone(), quote.clone(), find)
        }).collect::<Vec<_>>();
    let control = try_use_context::<DocViewerStateControl>();
    let selected = control.is_some_and(|control| control.doc_viewer_state.read().as_ref()
        .and_then(|state| state.web_artifact_id.as_ref())
        .is_some_and(|artifact| passages.iter().any(|source| &source.artifact_id == artifact)));
    let background = if selected { "#4096FF33" } else { "white" };
    let border = if selected { "#367ED899" } else { "#AAAAAA33" };
    rsx! {
        div {
            "data-web-citation": "{page.handle}",
            "data-citation-select": "true",
            "data-selected": "{selected}",
            class: "x-result-item-card",
            style: "background-color: {background}; border: 3px solid; border-color: {border}; border-radius: 8px; \
                    display: flex; flex-direction: column; gap: 7px; width: calc(100% - 16px); \
                    padding: 12px 16px; margin: 8px; font-size: var(--x-text-md); cursor: pointer;",
            onclick: move |_| { if let Some(open) = open { open.open.call(target.clone()); } },
            // The title row, and the domain on its own line under it, so neither cuts the
            // other short.
            div {
                style: "display: flex; flex-direction: column; min-width: 0; flex-shrink: 0;",
                div {
                    style: "display: flex; align-items: center; gap: 12px; min-width: 0;",
                    ResultCardLabel { label: page.handle.clone() }
                    if let Some(href) = href {
                        a { href, target: "_blank", rel: "noopener noreferrer nofollow",
                            style: "color: #0000EE; font-size: 20px; line-height: 28px; text-decoration: none; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;",
                            onclick: move |event| event.stop_propagation(),
                            "{title}"
                        }
                    } else { div { style: "font-size: 20px; line-height: 28px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;", "{title}" } }
                }
                div {
                    "data-web-citation-domain": "true",
                    style: "color: #16713C; font-size: 13px; line-height: 18px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                    "{domain}"
                }
            }
            // One three-line limit for all quotes. A line clamp counts only lines in plain
            // block and inline children, so each quote is a `div` without vertical margin.
            // The box takes its content height and does not grow: a taller box would show
            // part of a fourth line below the clamp. Three 20 px lines fit under the title
            // and domain lines in the 148 px card.
            div {
                class: "x-card-text",
                style: "flex: 0 1 auto; min-height: 0; overflow: hidden; overflow-wrap: anywhere; line-height: 20px; \
                        display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical;",
                for (source, quote, find) in quotes {
                    {
                        let target = (source.artifact_id.clone(), find.clone());
                        let key_target = target.clone();
                        rsx! {
                            div { role: "button", tabindex: "0", style: "color: #111827; white-space: pre-wrap; cursor: pointer;",
                                onclick: move |event| {
                                    event.stop_propagation();
                                    if let Some(open) = open { open.open.call(target.clone()); }
                                },
                                onkeydown: move |event: Event<KeyboardData>| {
                                    if event.key() == Key::Enter || event.key() == Key::Character(" ".to_string()) {
                                        event.prevent_default();
                                        event.stop_propagation();
                                        if let Some(open) = open { open.open.call(key_target.clone()); }
                                    }
                                },
                                for (text, marked) in common::chat_pages::exact_quote_parts(&quote, &source.terms) {
                                    if marked { mark { style: "background: #EB3E014D; color: inherit;", "{text}" } }
                                    else { span { "{text}" } }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn find_in_page(query: &str, direction: i8) {
    let query = serde_json::to_string(query).unwrap_or_else(|_| "\"\"".to_string());
    let script = include_str!("../../../assets/web-preview-find.js");
    document::eval(&format!("({script})({query},{direction});"));
}

#[component]
pub fn WebPagePreview(artifact_id: ReadSignal<String>, find: ReadSignal<String>) -> Element {
    let control = use_context::<DocViewerStateControl>();
    let source_id = artifact_id();
    let source = use_resource(use_reactive!(|source_id| chat_artifact_detail(source_id)));
    let page = source.read().as_ref().and_then(|result| result.as_ref().ok())
        .and_then(|body| serde_json::from_str::<CapturedWebPage>(body).ok());
    let ready = page.is_some();
    use_effect(move || {
        let query = find();
        let _ = source.read();
        find_in_page(&query, 0);
    });
    let failed = source.read().as_ref().is_some_and(|result| result.is_err());
    rsx! {
        div { "data-web-preview": "true", style: "height: 100%; display: flex; flex-direction: column; background: #F5F6F8;",
            style { "::highlight(web-page-find) {{ background: #FFF176; }} ::highlight(web-page-current) {{ background: #FFB74D; }}" }
            div { style: "display: flex; align-items: center; gap: 8px; padding: 10px; border-bottom: 1px solid; border-bottom-color: var(--x-border);",
                input { placeholder: "Find exact text", value: "{find}",
                    style: "min-width: 0; flex: 1; border: 1px solid #AAAAAA; border-radius: 14px; padding: 8px 12px; background: white;",
                    oninput: move |event| {
                        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
                        state.find_query = event.value();
                        control.set_doc_viewer_state.call(state);
                    }
                }
                span { id: "web-page-find-count", style: "font-size: var(--x-text-sm); color: var(--x-ink-muted);", "0/0" }
                button { title: "Previous match", onclick: move |_| find_in_page(&find(), -1), "▲" }
                button { title: "Next match", onclick: move |_| find_in_page(&find(), 1), "▼" }
                button { title: "Close preview", onclick: move |_| {
                    let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
                    state.web_artifact_id = None;
                    control.set_doc_viewer_state.call(state);
                }, "×" }
            }
            if let Some(page) = page {
                div { style: "padding: 12px 16px; font-size: var(--x-text-xl); background: white; border-bottom: 1px solid; border-bottom-color: var(--x-border);", "{page.title}" }
                div { id: "web-page-preview-text", style: "overflow: auto; padding: 16px; flex: 1;",
                    onmounted: move |_| find_in_page(&find(), 0),
                    MarkdownishText { text: page.markdown, citation_links: false }
                }
            } else if failed || (source.read().is_some() && !ready) {
                div { style: "padding: 16px;", "The captured page could not be loaded." }
            } else {
                div { style: "padding: 16px;", "Loading…" }
            }
        }
    }
}
