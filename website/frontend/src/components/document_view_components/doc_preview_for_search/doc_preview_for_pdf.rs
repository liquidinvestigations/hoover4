use common::document_text_sources::{
    DocumentTextSourceHit, DocumentTextSourceHitCount, DocumentTextSourceItem,
};
use common::pdf_to_html_conversion::PDFToHtmlConversionResponse;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use dioxus::logger::tracing;
use dioxus::prelude::*;

use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::raw_metadata_collector::RawMetadataCollector;
use crate::components::pdf_viewer::{PdfViewer, PdfViewerControllerDx, PdfViewerControllerJs, use_pdf_controller};
use crate::components::suspend_boundary::LoadingIndicator;

#[server]
pub async fn get_document_type_is_pdf(
    document_identifier: DocumentIdentifier,
) -> Result<(bool, u32), ServerFnError> {
    let (is_pdf, page_count) =
        backend::api::documents::get_pdf_to_html_conversion::get_document_type_is_pdf(
            document_identifier,
        )
        .await
        .map_err(|e| ServerFnError::from(e))?;
    Ok((is_pdf, page_count))
}

#[component]
pub fn DocumentPreviewForPdf(
    document_identifier: ReadSignal<DocumentIdentifier>,
    page_count: ReadSignal<u32>,
) -> Element {
    let pdf_url = use_memo(move || {
        let document_identifier = document_identifier.read().clone();
        let c = document_identifier.collection_dataset;
        let f = document_identifier.file_hash;
        format!("/_download_document/{c}/{f}")
    });


    let mut controller = use_signal(move || None);
    let mut on_document_loaded = Callback::new(move |x: PdfViewerControllerJs| {
        controller.set(Some(x));
    });


    rsx! {

        div {
            style: "display: flex; flex-direction: column; gap: 10px; width:100%;height:100%;align-items:center;justify-content:center;",

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
                if let Some(controller) = controller() {
                    PdfControllerButtons {controller }
                }

            }
            div {
                style:"height: calc(100% - 58px);width:100%;",
                PdfViewer { pdf_url, on_document_loaded }
                if let Some(controller) = controller() {
                    PdfControllerOverlay {controller }
                }
            }
        }
    }
}



#[component]
fn PdfControllerButtons(controller: PdfViewerControllerJs) -> Element {
    let controller = use_pdf_controller(controller);
    rsx! {
        PdfControllerButtons2 { controller }
    }
}

#[component]
fn PdfControllerOverlay(controller: PdfViewerControllerJs) -> Element {
    let controller = use_pdf_controller(controller);
    rsx! {
        PdfControllerOverlay2 { controller }
    }
}


#[component]

pub fn PdfControllerButtons2(controller: PdfViewerControllerDx) -> Element {
    let PdfViewerControllerDx {
        current_page,
        total_pages,
        set_page,
        search_query,
        set_search_query,
        search_hit_index,
        search_hit_count,
        set_search_idx,
        zoom_in,
        zoom_out,
        zoom_state,
        ..
    } = controller;

    rsx! {
        div {
            style: "
            flex-grow: 0;
            flex-shrink: 0;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: center;
            gap: 12px;
            padding: 12px;
        ",
            h1 {
                "PAGE {current_page()} / {total_pages()}"
            }
            button {
                onclick: move |_| {
                    set_page.call(current_page() - 1);
                },
                disabled: current_page() <= 1,
                "PREV PAGE"
            }
            button {
                onclick: move |_| {
                    set_page.call(current_page() + 1);
                },
                disabled: current_page() >= total_pages(),
                "NEXT PAGE"
            }
        }

        div {style: "flex-grow: 1;"}


        input {
            r#type: "text",
            placeholder: "Search in document",
            style: "
                        width: 100%;
                        height: 70%;
                        border: none;
                        outline: none;
                        background: white;
                        border: 1px solid rgba(0, 0, 0, 0.5);
                        border-radius: 14px;
                        padding: 8px 12px;
                        font-size: 14px;
                        font-weight: 400;
                        color: rgba(0, 0, 0, 0.8);
                        margin-left: 12px;
                        ",
            value: search_query(),
            oninput: move |e| {
                set_search_query.call(e.value());
            },
        }

        div {
            style: "
                flex-grow: 0;
                flex-shrink: 0;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 12px;
                padding: 12px;
            ",

            if search_hit_count() == 0 {
                h1 { "HIT - / -"}
            } else {
                h1 { "HIT {search_hit_index()+1} / {search_hit_count()}"}
            }
            button {
                onclick: move |_| {
                    set_search_idx.call(search_hit_index() - 1);
                },
                disabled: search_hit_index() <= 0,
                "PREV HIT"
            }
            button {
                onclick: move |_| {
                    set_search_idx.call(search_hit_index() + 1);
                },
                disabled: 1+search_hit_index() >= search_hit_count(),
                "NEXT HIT"
            }
        }
        div {style: "flex-grow: 1;"}

        div {
            style: "
                flex-grow: 0;
                flex-shrink: 0;
                display: flex;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                gap: 12px;
                padding: 12px;
            ",

            button {
                onclick: move |_| {
                    zoom_in.call(());
                },
                "ZOOM IN"
            }
            h1 {
                "ZOOM {zoom_state()}"
            }
            button {
                onclick: move |_| {
                    zoom_out.call(());
                },
                "ZOOM OUT"
            }
        }
    }
}


#[component]
fn PdfControllerOverlay2(controller: PdfViewerControllerDx) -> Element {
    let PdfViewerControllerDx {
        current_page,
        total_pages,
        set_page,
        zoom_in,
        zoom_out,
        zoom_state,
        ..
    } = controller;

    let mut current_page_input = use_signal(move || current_page());
    use_effect(move || {
        current_page_input.set(current_page());
    });

    rsx! {
        div {
            style: "position: relative; width: 0; height: 0; bottom: 0; right: 0; float: right; z-index: 100;",
            div {
                style: "position: absolute; bottom: 20px; right: 20px; background: white; border: 1px solid #ccc; border-radius: 8px; display: flex; flex-direction: column; align-items: center; padding: 4px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); width: 40px;",

                div {
                    style: "font-size: 14px; font-weight: bold; margin-bottom: 4px; padding: 4px; border-bottom: 1px solid #eee; width: 100%; text-align: center;",
                    input {
                        style: "width: 100%; text-align: center;",
                        r#type: "text",
                        value: current_page_input(),
                        oninput: move |e| {
                            current_page_input.set(e.value().parse::<i32>().unwrap_or_default());
                        },
                        onkeypress: move |e| {
                            if e.key() == Key::Enter {
                                e.prevent_default();
                                e.stop_propagation();
                                set_page.call(current_page_input());
                            }
                        },
                        onblur: move |_| {
                            set_page.call(current_page_input());
                        },
                    }
                }

                div {
                    style: "font-size: 14px; color: #666; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #eee; width: 100%; text-align: center;",
                    "{total_pages()}"
                }

                button {
                    style: "background: none; border: none; cursor: pointer; font-size: 20px; padding: 4px; margin: 2px 0;",
                    onclick: move |_| {
                        set_page.call(current_page() - 1);
                    },
                    disabled: current_page() <= 1,
                    "🔼"
                }

                button {
                    style: "background: none; border: none; cursor: pointer; font-size: 20px; padding: 4px; margin: 2px 0;",
                    onclick: move |_| {
                        set_page.call(current_page() + 1);
                    },
                    disabled: current_page() >= total_pages(),
                    "🔽"
                }

                button {
                    style: "background: none; border: none; cursor: default; font-size: 20px; padding: 4px; margin: 2px 0; opacity: 0.3;",
                    onclick: move |_| {
                        zoom_in.call(());
                    },
                    "➕"
                }
                div {"{zoom_state()}"}

                button {
                    style: "background: none; border: none; cursor: default; font-size: 20px; padding: 4px; margin: 2px 0; opacity: 0.3;",
                    onclick: move |_| {
                        zoom_out.call(());
                    },
                    "➖"
                }
            }
        }
    }
}
