use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::{md_action_icons::MdOpenInNew, md_editor_icons::MdInsertLink, md_file_icons::MdFileDownload, md_navigation_icons::MdMoreVert}};

use crate::routes::Route;

#[component]
pub fn DocCardActionButtonOpenNewTab(document_identifier:ReadSignal<DocumentIdentifier>) -> Element {
    rsx! {
        a {
            style: "
                width: 40px;
                height: 40px;
                cursor: pointer;
                border: 1px solid #000;
                border-radius: 8px;
                background: white;
                color: black;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 24px;
                padding: 1px;
                margin: 1px;
            ",
            target: "_blank",
            class: "hoover4-hover-shadow-background",
            href: Route::ViewDocumentPage { document_identifier: document_identifier.read().clone().into() }.to_string(),
            // onclick: move |_e| {
            //     _e.prevent_default();
            //     _e.stop_propagation();
            //     navigator().push(Route::ViewDocumentPage { document_identifier: document_identifier.read().clone().into() });
            // },
            Icon {
                icon: MdOpenInNew,
                style: "width: 24px; height: 24px;"
            }
        }
    }
}

#[component]
pub fn DocCardActionButtonMore(document_identifier:ReadSignal<DocumentIdentifier>) -> Element {
    let mut is_expanded = use_signal(|| false);
    let do_copy_link = use_callback(move |_:()| {
        let url = web_sys::window().unwrap().location().href().unwrap();
        let _r = web_sys::window().unwrap().navigator().clipboard().write_text(&url);
        dioxus::logger::tracing::info!("Link copied to clipboard: {:#?}", url);
        // toastr().success("Link copied to clipboard");
    });
    let do_download_document = use_callback(move |_:()| {

    });
    rsx! {
        div {

            style: "",

            button {
                style: "
                    width: 40px;
                    height: 40px;
                    cursor: pointer;
                    border: 1px solid #000;
                    border-radius: 8px;
                    background: white;
                    color: black;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 24px;
                    padding: 1px;
                    margin: 1px;
                ",
                class: "hoover4-hover-shadow-background",
                onclick: move |_e| {
                    _e.prevent_default();
                    _e.stop_propagation();
                    *is_expanded.write() ^= true;
                },
                Icon {
                    icon: MdMoreVert,
                    style: "width: 24px; height: 24px;"
                }
            }

            if is_expanded() {
                div {
                    style: "
                    position: absolute;
                    top: 0px;
                    left: 0px;
                    width: 100vw;
                    height: 100vh;
                    padding: 0px;
                    margin: 0px;
                    overflow: hidden;
                    background: rgba(0, 0, 0, 0.05);
                    z-index: 1000;
                    ",
                    onclick: move |_e| {
                        _e.prevent_default();
                        _e.stop_propagation();
                        *is_expanded.write() = false;
                    },
                }
                div {
                    style: "
                    position: relative;
                    width: 0px;
                    height: 0px;
                    top: 0px;
                    left: -262px;
                    padding: 0px;
                    margin: 0px;
                    ",
                    div {
                        style: "
                        position: absolute;
                        position-anchor: --more-menu-anchor;
                        left: anchor(right);
                        top: anchor(bottom);

                        width: 300px;
                        background-color: white;
                        border: 1px solid rgba(0, 0, 0, 0.5);
                        box-shadow: 0 0 10px 0 rgba(0, 0, 0, 0.5);
                        border-radius: 4px;
                        padding: 5px;
                        margin: 2px;
                        gap: 5px;
                        z-index: 1001;
                        flex-direction: column;
                        display: flex;
                        font-size: 20px;
                        line-height: 28px;
                        ",
                        onscroll: move |_e| {
                            _e.prevent_default();
                            _e.stop_propagation();
                        },

                        div {
                            style: "
                            padding: 2px;
                            padding-left: 10px;
                            margin: 2px;
                            cursor: pointer;
                            display: flex;
                            flex-direction: row;
                            // justify-content: center;
                            align-items: center;
                            gap: 10px;
                            ",
                            class: "hoover4-hover-shadow-background",
                            onclick: move |_e| {
                                _e.prevent_default();
                                _e.stop_propagation();
                                do_copy_link.call(());
                                *is_expanded.write() = false;
                            },

                            Icon {
                                icon: MdInsertLink,
                                style: "width: 20px; height: 20px;"
                            },
                            "Copy Document Link"
                        },
                        div {
                            style: "width: 100%; border-bottom: 1px solid rgba(0, 0, 0, 0.5);",
                        }
                        div {
                            style: "
                            padding: 2px;
                            padding-left: 10px;
                            margin: 2px;
                            cursor: pointer;
                            display: flex;
                            flex-direction: row;
                            // justify-content: center;
                            align-items: center;
                            gap: 10px;
                            ",
                            class: "hoover4-hover-shadow-background",
                            onclick: move |_e| {
                                _e.prevent_default();
                                _e.stop_propagation();
                                do_download_document.call(());
                                *is_expanded.write() = false;
                            },

                            Icon {
                                icon: MdFileDownload,
                                style: "width: 20px; height: 20px;"
                            },
                            "Download Document"
                        },
                    }
                }
            }
        }
    }
}