//! Shared document preview layout + dispatch (used by search preview and full-page viewer).

// TODO: This is a workaround to avoid the warning about the function pointer being unpredictable.
// We should find a better way to do this (trait + dyn dispatch).
#![allow(unpredictable_function_pointer_comparisons)]

use common::document_sources::DocumentSourceItem;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::{
    doc_preview_for_email::DocumentPreviewForEmail, doc_preview_for_pdf::DocumentPreviewForPdf,
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
        DocumentSourceItem::Text(text) => rsx! {
            DocumentPreviewForTextWithSearch { document_identifier, source: text }
        },
        DocumentSourceItem::Image(image) => rsx! {
            PreviewWrapper {
                controls: rsx! {"Image; {image.width}x{image.height}"},
                page: rsx! {
                    img {
                        src: "{document_identifier().get_absolute_url_path()}",
                        style: "max-width: 100%; max-height: 100%;",
                        alt: "image preview"
                    }
                }
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
        DocumentSourceItem::Metadata => rsx! {
            PreviewWrapper {
                controls: rsx! {"Metadata"},
                page: rsx! { "METADATA HIDDEN FROM PREVIEW"}
            },
        },
        other => rsx! {
            PreviewWrapper {
                controls: rsx! {"TODO CONTROLS: {other:?}"},
                page: rsx! {"TODO PAGE: {other:?}"}
            },
        },
    }
}
