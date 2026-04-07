//! Shared document preview layout + dispatch (used by search preview and full-page viewer).

use common::document_sources::DocumentSourceItem;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::{
    doc_preview_for_email::DocumentPreviewForEmail,
    doc_preview_for_pdf::DocumentPreviewForPdf,
    doc_preview_for_text::DocumentPreviewForTextWithSearch,
};
use crate::components::document_view_components::raw_metadata_collector::RawMetadataCollector;

#[derive(Clone, Copy)]
pub struct PreviewExtraSections {
    pub find_query: ReadSignal<Element>,
    pub preview_selector: ReadSignal<Element>,
}

#[component]
pub fn ProvidePreviewExtraSections(
    find_query_input_box: Element,
    preview_selector: Element,
    children: Element,
) -> Element {
    let find_query = use_signal(move || find_query_input_box);
    let preview_selector = use_signal(move || preview_selector);
    use_context_provider(move || PreviewExtraSections {
        find_query: find_query.into(),
        preview_selector: preview_selector.into(),
    });
    rsx! { {children} }
}

#[component]
pub fn PreviewControlsSection(children: Element) -> Element {
    let sections = use_context::<PreviewExtraSections>();
    rsx! {
        PreviewSubtitleBar {
            find_query_input_box: sections.find_query.read().clone(),
            preview_selector: sections.preview_selector.read().clone(),
            control: children,
        }
    }
}

#[component]
pub fn PreviewPageSection(children: Element) -> Element {
    rsx! {
        div {
            style: "
                width: 100%;
                height: calc(100% - 110px);
                padding: 10px;
            ",
            {children}
        }
    }
}

#[component]
fn PreviewSubtitleBar(find_query_input_box: Element, preview_selector: Element, control: Element) -> Element {
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: row;
                gap: 12px;
                align-items: center;
                justify-content: space-between;
                height: 48px;
                width: 100%;
                background-color:rgba(0, 0, 0, 0.04);
                flex-shrink: 0;
                flex-grow: 0;
                border: 1px solid rgba(0, 0, 0, 0.3); border-top: none;
            ",
            {find_query_input_box}
            div { style:"flex-grow: 1;" }
            div {
                style:"flex-grow: 13; flex-shrink: 1; height: 90%;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 4px;
                ",
                {control}
            }
            div { style:"flex-grow: 1;" }
            {preview_selector}
        }
    }
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
            PreviewControlsSection { "Image; {image.width}x{image.height}" }
            PreviewPageSection {
                img {
                    src: "{document_identifier().get_absolute_url_path()}",
                    style: "max-width: 100%; max-height: 100%;",
                    alt: "image preview"
                }
            }
        },
        DocumentSourceItem::Audio(audio) => rsx! {
            PreviewControlsSection { "Audio; {audio.duration_seconds} seconds" }
            PreviewPageSection {
                audio {
                    src: "{document_identifier().get_absolute_url_path()}",
                    alt: "audio preview",
                    controls: true
                }
            }
        },
        DocumentSourceItem::Video(video) => rsx! {
            PreviewControlsSection { "Video; {video.width}x{video.height} - {video.duration_seconds} seconds" }
            PreviewPageSection {
                video {
                    src: "{document_identifier().get_absolute_url_path()}",
                    alt: "video preview",
                    controls: true,
                    style: "max-width: 100%; max-height: 100%;",
                }
            }
        },
        DocumentSourceItem::Metadata => rsx! {
            PreviewControlsSection { "Metadata" }
            PreviewPageSection { RawMetadataCollector { document_identifier } }
        },
        other => rsx! {
            PreviewControlsSection { "TODO CONTROLS: {other:?}" }
            PreviewPageSection { "TODO PAGE: {other:?}" }
        },
    }
}

