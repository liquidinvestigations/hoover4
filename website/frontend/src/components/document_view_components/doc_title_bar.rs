//! Title bar for document viewer.

use dioxus::prelude::*;

use common::search_result::DocumentIdentifier;
use dioxus_free_icons::{
    Icon,
    icons::{go_icons::GoDatabase, md_editor_icons::MdInsertDriveFile},
};

use crate::components::search_components::card_action_buttons::{
    DocCardActionButtonMore, DocCardActionButtonOpenNewTab,
};

#[component]
pub fn DocTitleBar(
    document_identifier: ReadSignal<DocumentIdentifier>,
    show_new_tab_button: bool,
    show_finder: bool,
) -> Element {
    rsx! {
        div {
            style: "
                display: flex;
                flex-direction: row;
                gap: 12px;
                padding-right: 6px;
                padding-left: 0px;
                align-items: center;
                justify-content: space-between;
                height: 54px;
                width: 100%;
                background-color:#F8FCFF;
                flex-shrink: 0;
                flex-grow: 0;
                border: 1px solid rgba(0, 0, 0, 0.3);
            ",

            // COLLECTION AND FILENAME
            CollectionAndFilenameSection {document_identifier: document_identifier()}
            // SPACER
            div {
                style:"flex-grow: 1;"
            }
            // ACTION BUTTONS
            div {
                style: "
                    display: flex;
                    flex-direction: row;
                    gap: 6px;
                    align-items: center;
                    justify-content: center;
                ",
                if show_new_tab_button {
                    DocCardActionButtonOpenNewTab {document_identifier: document_identifier()}
                }
                DocCardActionButtonMore {document_identifier: document_identifier(), show_finder}
            }

        }
    }
}

#[component]
fn CollectionAndFilenameSection(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let collection_dataset = document_identifier.read().clone().collection_dataset;
    rsx! {
        div {
            style: "
                flex-grow: 0;
                flex-shrink: 0;
                max-width: calc(100% - 120px);
                display: flex;
                flex-direction: row;
                align-items: center;
                gap: 12px;
                padding-left: 12px;
                font-size: 20px;
                font-weight: 400;
            ",

            CollectionIcon {  }
            div {
                style: "color: rgba(0, 0, 0, 0.8); font-style: italic;",
                "{collection_dataset}"
            }
            div {
            "/"
            }
            FileTypeIcon {}
            FilenameText {document_identifier: document_identifier()}
        }
    }
}

#[component]
fn CollectionIcon() -> Element {
    rsx! {
        div {
            style: "
                width: 21px;
                height: 21px;
                background: transparent;
                color: rgba(0, 0, 0, 0.8);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                border-radius: 4px;
                flex-shrink: 0;
            ",
            Icon {
                icon: GoDatabase,
                style: "width: 18px; height: 18px;"
            }
        }
    }
}

#[component]
fn FilenameText(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let document_identifier_value = document_identifier();
    let file_path_resource = use_resource(use_reactive!(|document_identifier_value| {
        get_file_path(document_identifier_value)
    }));
    let file_path = match file_path_resource.read().clone() {
        Some(Ok(Some(path))) => path.split("/").last().unwrap_or("").to_string(),
        // The identifier resolves to no file: a bookmark that outlived its ingest, or a
        // hand-edited URL. A neutral name, not an error marker — the rest of the viewer
        // still has something to show, and there is nothing here for the user to fix.
        Some(Ok(None)) => {
            return rsx! { div {
                style: "display: block; overflow:hidden;text-overflow: ellipsis; white-space: nowrap;color:rgba(0,0,0,0.45); font-style: italic;",
                title: "This document is not at any path in its dataset",
                "Unknown file"
            }};
        }
        Some(Err(e)) => {
            return rsx! { div {
                class: "x-error-display",
                "error! {e}"
            }};
        }
        None => {
            return rsx! { div {
                "..."
            }};
        }
    };
    rsx! {
        div {
            style: "display: block; overflow:hidden;text-overflow: ellipsis; white-space: nowrap;color:rgba(0,0,0,0.75)",

            "{file_path}"
        }
    }
}

#[component]
fn FileTypeIcon() -> Element {
    rsx! {
        div {
            style: "
                width: 24px;
                height: 24px;
                background: transparent;
                color: rgba(0, 0, 0, 0.9);
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 16px;
                font-weight: 600;
                border-radius: 4px;
                flex-shrink: 0;
            ",
            Icon {
                icon: MdInsertDriveFile,
                style: "width: 18px; height: 18px;"
            }
        }
    }
}

/// `Ok(None)` is "this dataset has no file with that hash" — a dead bookmark, not a
/// failure. See the backend fn.
#[server]
async fn get_file_path(
    document_identifier: DocumentIdentifier,
) -> Result<Option<String>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_file_path::get_file_path(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}
