//! The workspace pane of a conversation: the files that the agent wrote, and the content
//! of one file version. It is read-only. The URL holds the file and the version
//! (`DocViewerState::workspace_file`), so a link opens the same view.
//!
//! The pane lists the files at their current versions. An answer of the transcript opens
//! its pinned version, which a later edit does not change.

use dioxus::prelude::*;

use crate::api::chat_api::{
    chat_workspace_capture, chat_workspace_captures, chat_workspace_file, chat_workspace_files,
};
use crate::components::chat_components::markdown_text::MarkdownishText;
use crate::data_definitions::doc_viewer_state::{DocViewerState, DocViewerStateControl};
use crate::tr;

/// Opens the workspace pane at a file version: `(name, version)`. An empty name opens the
/// file list, and a `None` version the current version.
#[derive(Clone, Copy)]
pub struct ChatWorkspaceOpen {
    pub open: Callback<(String, Option<u32>)>,
}

/// The text of a file length in characters.
fn length_text(chars: u32) -> String {
    if chars == 1 { "1 character".to_string() } else { tr!("chat-workspace-pane-characters", chars: chars.to_string()) }
}

#[component]
pub fn WorkspacePane(
    session_id: ReadSignal<String>,
    file: ReadSignal<String>,
    version: ReadSignal<Option<u32>>,
) -> Element {
    let control = use_context::<DocViewerStateControl>();
    let files = use_resource(move || chat_workspace_files(session_id()));
    let mut capture_offset = use_signal(|| (String::new(), 0));
    let capture = use_resource(move || async move {
        let path = file();
        let (selected, offset) = capture_offset();
        if !is_capture(&path) {
            return None;
        }
        Some(chat_workspace_capture(session_id(), path.clone(), if selected == path { offset } else { 0 }).await)
    });
    let content = use_resource(move || async move {
        let name = file();
        if name.is_empty() || is_capture(&name) {
            return None;
        }
        Some(chat_workspace_file(session_id(), name, version()).await)
    });
    let open = move |name: String, version: Option<u32>| {
        control.set_doc_viewer_state.call(DocViewerState::for_workspace(name, version));
    };
    let close = move |_| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.workspace_file = None;
        state.workspace_version = None;
        control.set_doc_viewer_state.call(state);
    };
    let listed = files.read().clone();
    let shown = content.read().clone().flatten();
    let current = file();
    let shown_capture = capture.read().clone().flatten();
    rsx! {
        div { "data-workspace-pane": "true",
            style: "height: 100%; display: flex; flex-direction: column; background: #F5F6F8;",
            div { style: "display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: white; \
                          border-bottom: 1px solid; border-bottom-color: var(--x-border);",
                span { style: "flex: 1; font-size: var(--x-text-md); font-weight: 600; color: var(--x-ink-strong);",
                    {tr!("chat-workspace-pane-workspace")}
                }
                button { title: tr!("chat-workspace-pane-close-the-workspace"), onclick: close, {tr!("chat-workspace-pane-close")} }
            }
            div { "data-workspace-files": "true",
                style: "padding: 8px 14px; display: flex; flex-direction: column; gap: 4px; \
                        border-bottom: 1px solid; border-bottom-color: var(--x-border); max-height: 35%; overflow: auto;",
                match listed {
                    None => rsx! { span { style: "color: var(--x-ink-muted);", {tr!("chat-workspace-pane-loading-the-files-u")} } },
                    Some(Err(error)) => rsx! { span { style: "color: var(--x-danger);", {tr!("chat-workspace-pane-the-files-could-not-be", error: error.to_string())} } },
                    Some(Ok(list)) if list.is_empty() => rsx! {
                        span { style: "color: var(--x-ink-muted);", {tr!("chat-workspace-pane-this-conversation-has-no-files")} }
                    },
                    Some(Ok(list)) => rsx! {
                        for entry in list {
                            button {
                                key: "{entry.name}",
                                "data-workspace-file": "{entry.name}",
                                style: if entry.name == current {
                                    "text-align: left; border: 1px solid; border-color: var(--x-link); border-radius: 6px; \
                                     background-color: white; padding: 4px 8px; cursor: pointer;"
                                } else {
                                    "text-align: left; border: 1px solid; border-color: transparent; border-radius: 6px; \
                                     background-color: transparent; padding: 4px 8px; cursor: pointer;"
                                },
                                onclick: {
                                    let name = entry.name.clone();
                                    move |_| open(name.clone(), None)
                                },
                                span { style: "font-weight: 600;", "{entry.name}" }
                                span { style: "margin-left: 8px; font-size: var(--x-text-sm); color: var(--x-ink-muted);",
                                    {tr!("chat-workspace-pane-version", entry_version: entry.version.to_string(), length_text_entry_chars: (length_text(entry.chars)).to_string())}
                                }
                            }
                        }
                    },
                }
                CaptureList { session_id: session_id(), sources: true, open: move |path| open(path, None) }
                CaptureList { session_id: session_id(), sources: false, open: move |path| open(path, None) }
            }
            div { "data-workspace-content": "true", style: "overflow: auto; padding: 16px; flex: 1;",
                if current.is_empty() {
                    span { style: "color: var(--x-ink-muted);", {tr!("chat-workspace-pane-choose-a-file-to-read")} }
                } else if is_capture(&current) {
                    match shown_capture {
                        None => rsx! { span { {tr!("chat-workspace-pane-loading-the-file-u")} } },
                        Some(Err(error)) => rsx! { span { style: "color: var(--x-danger);",
                            {tr!("chat-workspace-pane-the-file-could-not-be", error: error.to_string())}
                        } },
                        Some(Ok(found)) => rsx! {
                            pre { style: "white-space: pre-wrap; overflow-wrap: anywhere;", "{found.text}" }
                            if let Some(offset) = found.next_offset {
                                button { onclick: move |_| capture_offset.set((found.path.clone(), offset)), "Next part" }
                            }
                        },
                    }
                } else {
                    match shown {
                        None => rsx! { span { style: "color: var(--x-ink-muted);", {tr!("chat-workspace-pane-loading-the-file-u")} } },
                        Some(Err(error)) => rsx! { span { style: "color: var(--x-danger);", {tr!("chat-workspace-pane-the-file-could-not-be", error: error.to_string())} } },
                        Some(Ok(found)) => rsx! {
                            div { style: "margin-bottom: 10px; font-size: var(--x-text-sm); color: var(--x-ink-muted);",
                                {tr!("chat-workspace-pane-version-2", found_name: found.name.to_string(), found_version: found.version.to_string())}
                            }
                            MarkdownishText { text: found.content }
                        },
                    }
                }
            }
        }
    }
}


fn is_capture(path: &str) -> bool {
    path.starts_with("sources/") || path.starts_with("results/")
}

#[component]
fn CaptureList(session_id: String, sources: bool, open: Callback<String>) -> Element {
    let mut expanded = use_signal(|| false);
    let mut cursor = use_signal(String::new);
    let page = use_resource(move || {
        let session = session_id.clone();
        async move {
            if !expanded() {
                return None;
            }
            Some(chat_workspace_captures(session, sources, cursor()).await)
        }
    });
    let listed = page.read().clone().flatten();
    rsx! {
        details {
            ontoggle: move |_| expanded.set(true),
            summary { if sources { "Sources" } else { "Results" } }
            match listed {
                Some(Ok(page)) => rsx! {
                    for entry in page.entries {
                        button {
                            key: "{entry.path}",
                            style: "display: block; text-align: left;",
                            onclick: move |_| open.call(entry.path.clone()),
                            "{entry.title}"
                        }
                    }
                    if let Some(next) = page.next_cursor {
                        button { onclick: move |_| cursor.set(next.clone()), "More" }
                    }
                },
                Some(Err(error)) => rsx! { span { style: "color: var(--x-danger);",
                    {tr!("chat-workspace-pane-the-files-could-not-be", error: error.to_string())}
                } },
                None => rsx! { span { {tr!("chat-workspace-pane-loading-the-files-u")} } },
            }
        }
    }
}
