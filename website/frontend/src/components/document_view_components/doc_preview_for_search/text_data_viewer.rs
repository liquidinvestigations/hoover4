//! The text body of the shared text viewer, with the page controls at its end.
//!
//! It renders the page that [`DocumentViewerResultStore::displayed`] holds. Highlighted
//! and raw text come from the same page view, so both always show the selected page.

use common::document_text_pages::{TextPageBody, TextPageView};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::md_navigation_icons::{MdArrowBack, MdArrowForward},
};

use crate::components::{
    document_view_components::doc_preview_for_search::text_preview_with_search::DocumentViewerResultStore,
    error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator,
};

#[component]
pub fn TextDataViewer() -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    // In the flow layout the enclosing container scrolls, so the text takes its natural
    // height. Otherwise the text is its own scroll container.
    let viewer_style = if store.flow_layout {
        "width: 100%;"
    } else {
        "height: 100%; width: 100%; overflow-y: auto;"
    };
    let viewer_key = store.viewer_key;
    let view = store.displayed.read().clone();
    let error = store.request_error.read().clone();

    let Some(view) = view else {
        return match error {
            Some(error) => rsx! {
                div {
                    id: "x-document-text-viewer",
                    "data-text-viewer-key": "{viewer_key}",
                    style: "{viewer_style}",
                    ServerErrorDisplay { error }
                    div { style: "display: flex; justify-content: center;", RetryButton {} }
                }
            },
            None => rsx! { LoadingIndicator {} },
        };
    };

    rsx! {
        div {
            id: "x-document-text-viewer",
            "data-text-viewer-key": "{viewer_key}",
            style: "{viewer_style}",
            TextNotices { view: view.clone() }
            match view.body.clone() {
                TextPageBody::Text { page_id, spans, .. } => rsx! {
                    TextSpans { page_id, spans }
                },
                TextPageBody::Absent => rsx! {
                    p {
                        "data-text-absent": "true",
                        style: "margin: 0; padding: 12px 2px; color: var(--x-ink-muted);",
                        "No text is stored for {view.navigation.unit.label()} {view.navigation.requested_page.unwrap_or_default()}."
                    }
                },
                TextPageBody::EmptySource => rsx! {
                    p {
                        style: "margin: 0; padding: 12px 2px; color: var(--x-ink-muted);",
                        "This source has no stored text."
                    }
                },
            }
            if !matches!(view.body, TextPageBody::EmptySource) {
                ContentPageNavigation { view: view.clone() }
            }
        }
    }
}

/// One line for each failure that the displayed page carries, beside the content.
#[component]
fn TextNotices(view: TextPageView) -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let request_error = store.request_error.read().clone();
    let highlight_error = match &view.body {
        TextPageBody::Text { highlight_error, .. } => highlight_error.clone(),
        _ => None,
    };
    let unit = view.navigation.unit.label();
    let target = match store.request.read().page {
        Some(page) => format!("{unit} {page}"),
        None => "the text".to_string(),
    };
    let request_message = request_error.as_ref().map(crate::api::error_util::user_facing_message).unwrap_or_default();
    let shown_unit = unit.to_lowercase();
    rsx! {
        if request_error.is_some() {
            div {
                role: "alert",
                "data-text-request-error": "true",
                style: NOTICE_STYLE,
                span {
                    style: "flex: 1 1 auto; min-width: 0;",
                    "Could not load {target}: {request_message}"
                }
                RetryButton {}
            }
        }
        if view.source_changed {
            div {
                role: "status",
                style: NOTICE_STYLE,
                "This source changed after it was displayed. The page positions are refreshed."
            }
        }
        if let Some(error) = view.match_error {
            div {
                role: "alert",
                style: NOTICE_STYLE,
                title: "{error}",
                "The match search failed. The first stored {shown_unit} is shown."
            }
        }
        if let Some(error) = highlight_error {
            div {
                role: "alert",
                style: NOTICE_STYLE,
                title: "{error}",
                "Highlighting failed. The stored text is shown."
            }
        }
    }
}

const NOTICE_STYLE: &str = "display: flex; align-items: center; gap: 12px; padding: 6px 4px; margin-bottom: 6px; border-bottom: 1px solid; border-bottom-color: var(--x-border); color: var(--x-danger); font-size: var(--x-text-sm);";

#[component]
fn RetryButton() -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    rsx! {
        button {
            style: "flex: 0 0 auto; background-color: white; color: var(--x-ink-strong); border: 1px solid; border-color: var(--x-border-strong); border-radius: 16px; padding: 3px 12px; cursor: pointer; font: inherit;",
            onclick: move |_| store.retry.call(()),
            "Retry"
        }
    }
}

/// Previous and next stored page after the text, aligned to the start and the end. They
/// use the toolbar's targets, and the unavailable one stays in place, disabled.
#[component]
fn ContentPageNavigation(view: TextPageView) -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let unit = view.navigation.unit.label();
    let previous = view.navigation.previous_page;
    let next = view.navigation.next_page;
    // A disabled button is dimmed and shows the not-allowed cursor, so its state does not
    // depend on colour alone.
    let state_style = |enabled: bool| if enabled { "cursor: pointer; opacity: 1;" } else { "cursor: not-allowed; opacity: 0.45;" };
    let previous_style = format!("{CONTENT_BUTTON_STYLE} {}", state_style(previous.is_some()));
    let next_style = format!("{CONTENT_BUTTON_STYLE} {}", state_style(next.is_some()));
    rsx! {
        nav {
            "aria-label": "{unit} navigation at the end of the text",
            "data-text-content-navigation": "true",
            style: "display: flex; justify-content: space-between; gap: 12px; padding: 12px 0 4px 0;",
            button {
                style: "{previous_style}",
                disabled: previous.is_none(),
                onclick: move |_| if let Some(page) = previous { store.go_to_page.call(page) },
                Icon { icon: MdArrowBack, style: "width: 16px; height: 16px;" }
                "Previous {unit}"
            }
            button {
                style: "{next_style}",
                disabled: next.is_none(),
                onclick: move |_| if let Some(page) = next { store.go_to_page.call(page) },
                "Next {unit}"
                Icon { icon: MdArrowForward, style: "width: 16px; height: 16px;" }
            }
        }
    }
}

const CONTENT_BUTTON_STYLE: &str = "display: inline-flex; align-items: center; gap: 4px; background-color: white; color: var(--x-ink-strong); border: 1px solid; border-color: var(--x-border-strong); border-radius: 16px; padding: 3px 12px; font: inherit; font-size: var(--x-text-body);";

#[component]
fn TextSpans(page_id: u32, spans: Vec<common::text_highlight::HighlightTextSpan>) -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let request = store.request.read().clone();
    let onclick = Callback::new(move |clicked_index: u32| store.select_match.call(clicked_index));
    let spans = spans
        .into_iter()
        .enumerate()
        .map(|(nth, span)| {
            let index = span.index as u32;
            let key = format!("{:?}-{}-{nth}-{page_id}", request.document, request.extracted_by);
            rsx! {
                if span.is_highlighted {
                    TextDataSpan { key: "{key}", index, text: span.text, key2: key.clone(), onclick }
                } else {
                    TextDataSpanClean { key: "{key}", text: span.text, key2: key.clone() }
                }
            }
        })
        .collect::<Vec<_>>();
    rsx! {
        pre {
            style: "
                margin: 0;
                white-space: pre-wrap; word-wrap: break-word;
                font-size: var(--x-text-body);
                line-height: var(--x-line-body);
                font-weight: 400;
                color: rgb(0, 0, 0);
            ",
            {spans.into_iter()}
        }
    }
}

#[component]
fn TextDataSpan(index: u32, text: String, key2: String, onclick: Callback<u32>) -> Element {
    let current_match = use_context::<DocumentViewerResultStore>().current_match;
    let is_selected = index == *current_match.read();

    let text = text_to_span_html(text, true, is_selected);

    rsx! {
        span {
            key: "{key2}",
            "data-text-hit": "{index}",
            onclick: move |_| onclick.call(index),
            dangerous_inner_html: text,
        }
    }
}

#[component]
fn TextDataSpanClean(text: String, key2: String) -> Element {
    let text = text_to_span_html(text, false, false);

    rsx! {
        span {
            key: "{key2}-clean",
            dangerous_inner_html: text,
        }
    }
}

fn text_to_span_html(text: String, is_match: bool, is_active_match: bool) -> String {
    // the "b" bug #105 - dioxus bug where it doesn't encode/decode html
    // and markup breaks. instead, we generate our own html here.
    let class = if is_match {
        if is_active_match {
            "x-hit-span-active-match"
        } else {
            "x-hit-span-inacti-match"
        }
    } else {
        "x-hit-span-non-match"
    };

    let text = html_escape::encode_text(&text).to_string();

    format!(r#"<span class="{class}">{text}</span>"#)
}
