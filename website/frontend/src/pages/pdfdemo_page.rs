use dioxus::prelude::*;

use crate::components::pdf_viewer::{
    PdfViewer, PdfViewerControllerDx, PdfViewerControllerJs, use_pdf_controller,
};

#[used]
static EMBED_PDF_FOLDER: Asset = asset!(
    "/assets/embed-pdf/_viewer/",
    AssetOptions::folder().with_hash_suffix(false)
);

#[component]
pub fn PdfDemoPage() -> Element {
    let mut pdf_url = use_signal(move || "".to_string());
    // let mut controller = use_signal(move || None);
    let mut on_document_loaded = Callback::new(move |x: PdfViewerControllerJs| {
        // controller.set(Some(x));
    });
    rsx! {
        script {
            src: "/assets/_viewer/embed-demo.js",
            r#type: "module",
        }

        div {
            style: "height: 10%; width: 90%; border: 1px solid black;padding:10px;margin:10px;
            display:flex;flex-direction:row;gap:10px;align-items:center;justify-content:center;",

            div {style: "flex-grow: 1;"}


            button {
                onclick: move |_| {
                    // controller.set(None);
                    pdf_url.set("https://snippet.embedpdf.com/ebook.pdf".to_string());
                },
                "DOCUMENT 1"
            }
            button {
                onclick: move |_| {
                    // controller.set(None);
                    pdf_url.set("http://localhost:8080/_download_document/testdata/a0d06de0243c63497070c77e9bb6cab5a2d0bda5564daa03a37987a4f1640fd3".to_string());
                },
                "DOCUMENT 2"
            }
            div {style: "flex-grow: 1;"}

            // if let Some(controller) = controller() {
            //     PdfControllerButtons { controller }
            // }
            div {style: "flex-grow: 1;"}


        }

        div {
            style: "width:90%;height:80%;",
            // PdfViewer {pdf_url, on_document_loaded}
            div {
                id: "x-demo-pdf-viewer",
                style: "width:100%;height:100%;",
            }
        }



    }
}

#[component]
pub fn PdfControllerButtons(controller: PdfViewerControllerJs) -> Element {
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
    } = use_pdf_controller(controller);

    rsx! {
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

        div {style: "flex-grow: 1;"}


        input {
            r#type: "text",
            placeholder: "Search for a word",
            value: search_query(),
            oninput: move |e| {
                set_search_query.call(e.value());
            },
        }


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
        div {style: "flex-grow: 1;"}

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
