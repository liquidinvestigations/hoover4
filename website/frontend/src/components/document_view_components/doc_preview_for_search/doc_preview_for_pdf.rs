use common::{document_sources::DocumentPdfSourceItem, search_result::DocumentIdentifier};
use dioxus::prelude::*;
use dioxus_free_icons::icons::md_navigation_icons::{MdArrowDownward, MdArrowUpward};

use crate::{components::{document_view_components::doc_preview_shared::PreviewWrapper, pdf_viewer::{PdfViewer, PdfViewerControllerDx, PdfViewerControllerJs, use_pdf_controller}, search_components::search_result_list_controls::NavigationButton}, pages::search_page::DocViewerStateControl};

#[component]
pub fn DocumentPreviewForPdf(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentPdfSourceItem>,
) -> Element {
    let pdf_url = use_memo(move || {
        let document_identifier = document_identifier.read().clone();
        document_identifier.get_absolute_url_path()
    });

    let mut controller = use_signal(move || None);
    let on_document_loaded = Callback::new(move |x: PdfViewerControllerJs| {
        controller.set(Some(x));
    });


    rsx! {
        PreviewWrapper {
            controls: rsx! {
                if let Some(controller) = controller() {
                    PdfControllerButtons {controller }
                }
            },
            page: rsx! {
                PdfViewer { pdf_url, on_document_loaded, document_identifier: document_identifier() }
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
        // current_page,
        // total_pages,
        // set_page,
        // search_query,
        set_search_query,
        search_hit_index,
        search_hit_count,
        set_search_idx,
        // zoom_in,
        // zoom_out,
        // zoom_state,
        ..
    } = controller;


    let global_control = use_context::<DocViewerStateControl>();
    let global_search_query = use_memo(move || {
            let global_state = global_control.doc_viewer_state.read().clone().unwrap_or_default();
            global_state.find_query.clone()
    });
    use_effect(move || {
        set_search_query.call(global_search_query.read().clone());
    });


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


            NavigationButton {
                icon: MdArrowUpward,
                onclick: move |_| {
                    set_search_idx.call(search_hit_index() - 1);
                },
                disabled: search_hit_index() <= 0,
                label: "Previous Hit"
            }

            div {
                style: "
                    min-width: 60px;
                    font-size: 20px;
                    line-height: 28px;
                ",
                if search_hit_count() == 0 {
                    h1 { "- / -"}
                } else {
                    h1 { "{search_hit_index()+1} / {search_hit_count()}"}
                }
            }

            NavigationButton {
                icon: MdArrowDownward, label: "Next Hit",
                onclick: move |_| {
                    set_search_idx.call(search_hit_index() + 1);
                },
                disabled: 1+search_hit_index() >= search_hit_count(),
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
