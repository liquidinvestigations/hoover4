//! Every place a document's bytes sit, as one full path per row.
//!
//! A file hash is content, not a location. The same bytes can be at two paths of one
//! dataset, inside two different archives, or attached to two different emails, and the
//! title bar only ever shows the first of those. This panel is the place that says so.
//!
//! It is the viewer's `File Locations` tab and nothing else: it is not a preview source,
//! because a list of paths is a description of the document rather than a rendering of it.

use common::search_result::DocumentIdentifier;
use common::vfs::{VfsFileLocation, VfsFileLocations};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{md_content_icons::MdContentPaste, md_file_icons::MdFolderOpen},
};

use wasm_bindgen::JsCast;

use crate::components::error_boundary::ServerErrorDisplay;
use crate::components::suspend_boundary::LoadingIndicator;
use crate::routes::Route;

const PANEL_STYLE: &str = "
    display: flex;
    flex-direction: column;
    gap: 2px;
    height: 100%;
    overflow-y: auto;
    padding: 12px;
";

const HEADER_STYLE: &str = "
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 17px;
    font-weight: 700;
    padding: 4px 2px 10px 2px;
";

const LOCATION_ROW_STYLE: &str = "
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 10px;
    padding: 10px 2px;
    font-size: 15px;
    line-height: 22px;
";

/// The path itself. `overflow-wrap: anywhere` rather than a scrollbar: a path with no
/// spaces in it would otherwise push the whole tab sideways.
const PATH_STYLE: &str = "
    flex: 1 1 auto;
    min-width: 0;
    overflow-wrap: anywhere;
    color: rgb(17, 17, 17);
";

const ICON_BUTTON_STYLE: &str = "
    flex: 0 0 auto;
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: rgb(28, 33, 45);
    cursor: pointer;
    padding: 0;
    border-radius: 8px;
";

/// The path a reader would write down, built from the resolved chain when there is one.
///
/// The chain is the only thing that knows an archive was crossed, so a file inside a zip
/// reads `/folder/archive.zip/inner/file.txt` (one path, containers included), instead of
/// the bare in-container path, which on its own says nothing about where the archive is.
fn display_path(location: &VfsFileLocation) -> String {
    if location.chain.len() > 1 {
        let segments: Vec<&str> = location
            .chain
            .iter()
            .skip(1) // the dataset root renders as "/", not as a segment
            .map(|node| node.display_name().trim_matches('/'))
            .filter(|name| !name.is_empty())
            .collect();
        if !segments.is_empty() {
            return format!("/{}", segments.join("/"));
        }
    }
    location.path.clone()
}

#[component]
pub fn DocumentFileLocationsPanel(
    document_identifier: ReadSignal<DocumentIdentifier>,
) -> Element {
    let document_identifier_value = document_identifier();
    // ONE resource for the whole panel, and by value through `use_reactive`: the chains
    // are resolved server-side precisely so a document at N paths is one request rather
    // than N. A `ReadSignal` prop is a fresh signal on every parent render, so a resource
    // subscribed to it would never re-run when the document changes.
    let locations = use_resource(use_reactive!(|document_identifier_value| {
        async move { get_file_locations(document_identifier_value).await }
    }));

    let value: VfsFileLocations = match locations.read().clone() {
        None => {
            return rsx! { LoadingIndicator {} };
        }
        Some(Err(error)) => {
            return rsx! { ServerErrorDisplay { error: error.clone() } };
        }
        Some(Ok(value)) => value,
    };

    let shown = value.locations.len() as u64;
    let hidden = value.total.saturating_sub(shown);

    rsx! {
        div {
            style: PANEL_STYLE,
            class: "x-file-locations-panel",
            div {
                style: HEADER_STYLE,
                Icon { icon: MdFolderOpen, style: "width: 22px; height: 22px;" }
                "Document locations"
            }
            if value.locations.is_empty() {
                // Not an error: a document can be known to the index while its VFS rows
                // are not there yet, and the reader is owed that sentence rather than an
                // empty box.
                div {
                    style: "padding: 4px 2px; color: rgba(0,0,0,0.6);",
                    "This document is not recorded at any path in "
                    b { "{document_identifier().collection_dataset}" }
                    ", so there is nothing to browse to."
                }
            }
            for location in value.locations.iter() {
                LocationRow {
                    key: "{location.container_hash}-{location.path}",
                    location: location.clone(),
                    document_identifier: document_identifier(),
                }
            }
            if hidden > 0 {
                div {
                    style: "padding: 8px 2px; color: rgba(0,0,0,0.6); font-size: 14px;",
                    "…and {hidden} more. Use Storage to browse the rest."
                }
            }
        }
    }
}

/// One location: the full path, an open-in-the-file-browser button and a copy button.
#[component]
fn LocationRow(location: VfsFileLocation, document_identifier: DocumentIdentifier) -> Element {
    let dataset = location.collection_dataset.clone();
    let parent = location.parent_descriptor();
    let path_text = display_path(&location);
    let copy_text = path_text.clone();

    // A real navigation into a new tab, so an `<a href target="_blank">` rather than a
    // `Link`: the router cannot open a second tab, and the browser already can.
    let browse_href =
        Route::file_browser_page(dataset, parent, Some(document_identifier.clone())).to_string();

    let do_copy = use_callback(move |_: ()| {
        let text = copy_text.clone();
        let toast_api = dioxus_primitives::toast::consume_toast();
        // `navigator.clipboard` does not exist outside a secure context (plain http on a
        // host that is not `localhost`), and reaching for it there throws rather than
        // failing. `document.execCommand('copy')` still works there, so it is the
        // fallback, chosen on the context rather than on an error that never arrives.
        let secure = web_sys::window()
            .map(|window| window.is_secure_context())
            .unwrap_or(false);
        if secure {
            if let Some(window) = web_sys::window() {
                let promise = window.navigator().clipboard().write_text(&text);
                // The promise is AWAITED, not dropped: `writeText` rejects when the
                // document is not focused, and a dropped rejected promise is an
                // "Uncaught (in promise) NotAllowedError" in the console, a real error
                // in the release build, from a button that otherwise worked.
                wasm_bindgen_futures::spawn_local(async move {
                    let _ = wasm_bindgen_futures::JsFuture::from(promise).await;
                });
            }
        } else {
            copy_via_exec_command(&text);
        }
        toast_api.info(
            "Path copied to clipboard.".to_string(),
            dioxus_primitives::toast::ToastOptions::new()
                .description(text)
                .duration(std::time::Duration::from_secs(7))
                .permanent(false),
        );
    });

    rsx! {
        div {
            style: LOCATION_ROW_STYLE,
            class: "x-file-location",
            div {
                style: PATH_STYLE,
                class: "x-file-location-path",
                title: "{path_text}",
                "{path_text}"
            }
            a {
                style: ICON_BUTTON_STYLE,
                class: "x-file-location-open hoover4-hover-shadow-background",
                href: "{browse_href}",
                target: "_blank",
                title: "Open the containing folder in the file browser",
                Icon { icon: MdFolderOpen, style: "width: 22px; height: 22px;" }
            }
            button {
                style: ICON_BUTTON_STYLE,
                class: "x-file-location-copy hoover4-hover-shadow-background",
                title: "Copy this path",
                onclick: move |event| {
                    event.prevent_default();
                    event.stop_propagation();
                    do_copy.call(());
                },
                Icon { icon: MdContentPaste, style: "width: 22px; height: 22px;" }
            }
        }
    }
}

/// Clipboard write for a non-secure context, where `navigator.clipboard` does not exist.
fn copy_via_exec_command(text: &str) {
    let Some(window) = web_sys::window() else {
        return;
    };
    let Some(document) = window.document() else {
        return;
    };
    let Ok(element) = document.create_element("textarea") else {
        return;
    };
    let _ = element.set_attribute("style", "position: fixed; top: -1000px; opacity: 0;");
    element.set_text_content(Some(text));
    if let Some(body) = document.body() {
        let _ = body.append_child(&element);
        if let Some(area) = element.dyn_ref::<web_sys::HtmlTextAreaElement>() {
            area.select();
        }
        if let Some(html_document) = document.dyn_ref::<web_sys::HtmlDocument>() {
            let _ = html_document.exec_command("copy");
        }
        let _ = body.remove_child(&element);
    }
}

#[server]
async fn get_file_locations(
    document_identifier: DocumentIdentifier,
) -> Result<VfsFileLocations, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_file_path::get_file_locations(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}
