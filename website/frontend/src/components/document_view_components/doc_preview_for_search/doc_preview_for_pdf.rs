use common::document_text_sources::{DocumentTextSourceHit, DocumentTextSourceHitCount, DocumentTextSourceItem};
use common::pdf_to_html_conversion::PDFToHtmlConversionResponse;
use dioxus::logger::tracing;
use dioxus::prelude::*;
use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;

use crate::components::document_view_components::doc_title_bar::DocTitleBar;
use crate::components::document_view_components::raw_metadata_collector::RawMetadataCollector;
use crate::components::suspend_boundary::LoadingIndicator;
use crate::pages::search_page::DocViewerStateControl;



#[server]
pub async fn get_document_type_is_pdf(document_identifier: DocumentIdentifier) -> Result<(bool, u32), ServerFnError> {
    let (is_pdf, page_count) = backend::api::documents::get_pdf_to_html_conversion::get_document_type_is_pdf(document_identifier).await.map_err(|e| ServerFnError::from(e))?;
    Ok((is_pdf, page_count))
}


#[component]
pub fn DocumentPreviewForPdf(
    document_identifier: ReadSignal<DocumentIdentifier>,
    page_count: ReadSignal<u32>,
) -> Element {
    let current_page_index = use_signal(move || 0_u32);
    let pdf_to_html_conversion = use_resource(move || {
        let document_identifier = document_identifier.read().clone();
        let current_page_index = current_page_index.read().clone();
        async move {
            let pdf_to_html_conversion = get_pdf_to_html_single_page(document_identifier, current_page_index).await;
            pdf_to_html_conversion
        }
    });
    let data_viewer = match pdf_to_html_conversion.read().clone() {
        Some(Ok(pdf_to_html_conversion)) => {
            rsx! {
                PDFDataViewer { pdf_to_html_conversion }
            }
        }
        Some(Err(e)) => {
            return rsx! {
                pre {
                    style: "color:red; font-size: 26px; border: 1px solid red; padding: 10px; border-radius: 5px; margin: 15px;",
                    "{e:#?}"
                }
            }
        }
        None => {
            return rsx! {
                div {
                    style: "width: 90%; height: 60px;",
                    LoadingIndicator {  }
                }
            }
        }
    };
    rsx! {
        {data_viewer}
        PdfControllerOverlay { page_count, current_page_index }
    }
}

#[component]
fn PdfControllerOverlay(page_count: ReadSignal<u32>, current_page_index: Signal<u32>) -> Element {
    let mut current_page = current_page_index;
    let page_count = page_count();

    rsx! {
        div {
            style: "position: relative; width: 0; height: 0; bottom: 0; right: 0; float: right; z-index: 100;",
            div {
                style: "position: absolute; bottom: 20px; right: 20px; background: white; border: 1px solid #ccc; border-radius: 8px; display: flex; flex-direction: column; align-items: center; padding: 4px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); width: 40px;",

                div {
                    style: "font-size: 14px; font-weight: bold; margin-bottom: 4px; padding: 4px; border-bottom: 1px solid #eee; width: 100%; text-align: center;",
                    "{current_page() + 1}"
                }

                div {
                    style: "font-size: 14px; color: #666; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #eee; width: 100%; text-align: center;",
                    "{page_count}"
                }

                button {
                    style: "background: none; border: none; cursor: pointer; font-size: 20px; padding: 4px; margin: 2px 0;",
                    onclick: move |_| {
                        if current_page() > 0 {
                            current_page -= 1;
                        }
                    },
                    "🔼"
                }

                button {
                    style: "background: none; border: none; cursor: pointer; font-size: 20px; padding: 4px; margin: 2px 0;",
                    onclick: move |_| {
                        if current_page() < page_count - 1 {
                            current_page += 1;
                        }
                    },
                    "🔽"
                }

                button {
                    style: "background: none; border: none; cursor: default; font-size: 20px; padding: 4px; margin: 2px 0; opacity: 0.3;",
                    disabled: true,
                    "➕"
                }

                button {
                    style: "background: none; border: none; cursor: default; font-size: 20px; padding: 4px; margin: 2px 0; opacity: 0.3;",
                    disabled: true,
                    "➖"
                }
            }
        }
    }
}
#[component]
fn PDFDataViewer(pdf_to_html_conversion: ReadSignal<PDFToHtmlConversionResponse>) -> Element {
    let page_width_px = use_memo(move || {
        pdf_to_html_conversion.read().page_width_px
    });
    let page_height_px = use_memo(move || {
        pdf_to_html_conversion.read().page_height_px
    });
    let aspect_ratio = use_memo(move || {
        page_width_px() / page_height_px()
    });

    let html_content = use_memo(move || {
        let styles = pdf_to_html_conversion.read().clone().styles.join("\n");
        let page_idx = 0;
        let page_content = pdf_to_html_conversion.read().clone().pages[page_idx].clone();
        let page_content = format!("{styles}\n{page_content}");

        rsx! {
            iframe {
                srcdoc: "{page_content}",
                style: "width: {page_width_px+60.0}px; height: {page_height_px+60.0}px;  aspect-ratio: {aspect_ratio};",
            }
        }
    });

    let mut resize_info = use_signal(move || (page_width_px(), page_height_px()));
    let mut scale_factor = use_memo(move || {
        let rx = resize_info.read().0 / (page_width_px() + 60.0);
        let ry = resize_info.read().1 / (page_height_px() + 60.0);
        let min_scale_factor = rx.min(ry);
        min_scale_factor
    });



    rsx! {
        div {
            style: "height: 50px; font-size: 40px;",
            "TODO HEADER"
        }
        div {
            style: "aspect-ratio: {aspect_ratio};width: 100%;height: calc(100% - 50px);",
            onresize: move |e| {
                let Ok(size) = e.data().clone().get_border_box_size() else {
                    tracing::error!("Failed to get border box size: {:#?}", e.data());
                    return;
                };
                // tracing::info!("Border box size: {:#?}", size);

                resize_info.set((size.width as f32, size.height as f32));
            },

            div {
                style: "transform: scale({scale_factor}); transform-origin: top left;",
                {html_content()}
            }
        }
    }
}

#[server]
async fn get_pdf_to_html_single_page(document_identifier: DocumentIdentifier, page_index: u32) -> Result<PDFToHtmlConversionResponse, ServerFnError> {
    let pdf_to_html_conversion = backend::api::documents::get_pdf_to_html_conversion::
    get_pdf_to_html_single_page(document_identifier, page_index).await.map_err(|e| ServerFnError::from(e));
    pdf_to_html_conversion
}
