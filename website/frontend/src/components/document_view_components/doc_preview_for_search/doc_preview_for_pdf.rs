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
pub async fn get_document_type_is_pdf(document_identifier: DocumentIdentifier) -> Result<bool, ServerFnError> {
    let is_pdf = backend::api::documents::get_pdf_to_html_conversion::get_document_type_is_pdf(document_identifier).await.map_err(|e| ServerFnError::from(e));
    is_pdf
}


#[component]
pub fn DocumentPreviewForPdf(
    document_identifier: ReadSignal<DocumentIdentifier>,
) -> Element {
    let pdf_to_html_conversion = use_resource(move || {
        let document_identifier = document_identifier.read().clone();
        async move {
            let pdf_to_html_conversion = get_pdf_to_html_conversion(document_identifier).await;
            pdf_to_html_conversion
        }
    });
    match pdf_to_html_conversion.read().clone() {
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
                LoadingIndicator {  }
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
async fn get_pdf_to_html_conversion(document_identifier: DocumentIdentifier) -> Result<PDFToHtmlConversionResponse, ServerFnError> {
    let pdf_to_html_conversion = backend::api::documents::get_pdf_to_html_conversion::get_pdf_to_html_conversion(document_identifier).await.map_err(|e| ServerFnError::from(e));
    pdf_to_html_conversion
}
