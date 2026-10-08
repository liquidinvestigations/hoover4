//! Shared document preview layout + dispatch (used by search preview and full-page viewer).

// TODO: This is a workaround to avoid the warning about the function pointer being unpredictable.
// We should find a better way to do this (trait + dyn dispatch).
#![allow(unpredictable_function_pointer_comparisons)]

use common::document_sources::DocumentSourceItem;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::{
    doc_preview_for_email::DocumentPreviewForEmail, doc_preview_for_pdf::DocumentPreviewForPdf,
    doc_preview_for_table::DocumentPreviewForTable,
    doc_preview_for_text::DocumentPreviewForTextWithSearch,
};

#[derive(Clone, Copy)]
pub struct PreviewExtraSections {
    pub find_query: ReadSignal<Element>,
    pub preview_selector: ReadSignal<Element>,
    pub wrapper_fn: fn(Element, Element) -> Element,
}

#[component]
pub fn ProvidePreviewExtraSections(
    find_query_input_box: Element,
    preview_selector: Element,
    children: Element,
    wrapper_fn: fn(Element, Element) -> Element,
) -> Element {
    let find_query = use_signal(move || find_query_input_box);
    let preview_selector = use_signal(move || preview_selector);
    use_context_provider(move || PreviewExtraSections {
        find_query: find_query.into(),
        preview_selector: preview_selector.into(),
        wrapper_fn: wrapper_fn.into(),
    });
    rsx! { {children} }
}

#[component]
pub fn PreviewWrapper(controls: Element, page: Element) -> Element {
    let extra = use_context::<PreviewExtraSections>();
    let wrapper_fn = extra.wrapper_fn;
    wrapper_fn(controls, page)
}

#[component]
pub fn DocSourceDispatch(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentSourceItem>,
) -> Element {
    match source.read().clone() {
        DocumentSourceItem::Pdf(pdf) => rsx! {
            DocumentPreviewForPdf { document_identifier, source: pdf }
        },
        DocumentSourceItem::Email(email) => rsx! {
            DocumentPreviewForEmail { document_identifier, source: email }
        },
        DocumentSourceItem::Table(table) => rsx! {
            DocumentPreviewForTable { document_identifier, source: table }
        },
        DocumentSourceItem::Text(text) => rsx! {
            DocumentPreviewForTextWithSearch { document_identifier, source: text }
        },
        DocumentSourceItem::Image(image) => rsx! {
            PreviewWrapper {
                controls: rsx! {"Image; {image.width}x{image.height}"},
                page: rsx! { ImagePreview { url: document_identifier().get_absolute_url_path() } }
            },
        },
        DocumentSourceItem::Audio(audio) => rsx! {
            PreviewWrapper {
                controls: rsx! {"Audio; {audio.duration_seconds} seconds"},
                page: rsx! {
                    audio {
                        src: "{document_identifier().get_absolute_url_path()}",
                        alt: "audio preview",
                        controls: true
                    }
                }
            },
        },
        DocumentSourceItem::Video(video) => rsx! {
            PreviewWrapper {
                controls: rsx! {"Video; {video.width}x{video.height} - {video.duration_seconds} seconds"},
                page: rsx! {
                    video {
                        src: "{document_identifier().get_absolute_url_path()}",
                        alt: "video preview",
                        controls: true,
                        style: "max-width: 100%; max-height: 100%;",
                    }
                }
            },
        },
        // A source this build has no viewer for. It is not an error (an older bookmark
        // or a newer indexer can both produce one), so it says so plainly and carries no
        // error marker, and in particular it never prints the variant at a reader.
        _ => rsx! {
            PreviewWrapper {
                controls: rsx! {"Preview"},
                page: rsx! {
                    div {
                        style: "padding: 12px; color: rgba(0,0,0,0.6);",
                        "There is no preview for this source. Pick another one from the list."
                    }
                }
            },
        },
    }
}

/// The original image file. Some formats, such as HEIC, have no decoder in most
/// browsers, so a failed load shows a note and a download link in place of the alt text.
#[component]
fn ImagePreview(url: String) -> Element {
    let mut failed = use_signal(|| false);
    if failed() {
        return rsx! {
            p {
                id: "x-image-preview-failed",
                style: "margin: 0; padding: 12px; color: var(--x-ink-muted);",
                "This browser cannot show this image format. "
                a { href: "{url}", download: "", "Download the file" }
            }
        };
    }
    rsx! {
        img {
            src: "{url}",
            style: "max-width: 100%; max-height: 100%;",
            alt: "image preview",
            onerror: move |_| failed.set(true),
        }
    }
}

/// One row above the viewer when a source query failed. The sources that loaded still
/// show below it.
#[component]
pub fn SourceLoadNotice(error: String, on_retry: Callback<()>) -> Element {
    rsx! {
        div {
            id: "x-source-load-notice",
            role: "alert",
            style: "flex: 0 0 auto; display: flex; align-items: center; gap: 12px; padding: 6px 12px; border-bottom: 1px solid; border-bottom-color: var(--x-border); color: var(--x-danger); font-size: var(--x-text-sm);",
            span { style: "flex: 1 1 auto; min-width: 0;", "Could not load all document sources: {error}" }
            button {
                style: "flex: 0 0 auto; background-color: white; color: var(--x-ink-strong); border: 1px solid; border-color: var(--x-border-strong); border-radius: 16px; padding: 3px 12px; cursor: pointer; font: inherit;",
                onclick: move |_| on_retry.call(()),
                "Retry"
            }
        }
    }
}
