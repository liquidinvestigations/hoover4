//! Every place a document's bytes sit, as breadcrumb chains into the storage browser.
//!
//! A file hash is content, not a location. The same bytes can be at two paths of one
//! dataset, inside two different archives, or attached to two different emails, and the
//! title bar only ever shows the first of those. This panel is the place that says so.

use common::search_result::DocumentIdentifier;
use common::vfs::{PathDescriptor, VfsFileLocation, VfsFileLocations, VfsNodeKind};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{go_icons::GoFileZip, md_file_icons::MdFolder},
};

use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::components::error_boundary::ComponentErrorDisplay;
use crate::components::suspend_boundary::LoadingIndicator;
use crate::pages::file_browser_page::{
    CRUMB_LINK_STYLE, CRUMB_SEP_STYLE, Crumb, collapse_duplicate_crumbs, path_segments,
};
use crate::routes::Route;

const LOCATION_ROW_STYLE: &str = "
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px;
    padding: 10px 12px;
    border: 1px solid rgba(0,0,0,0.15);
    border-radius: 12px;
    font-size: 15px;
    line-height: 22px;
";

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
            return rsx! {
                PreviewWrapper { controls: rsx! { "File locations" }, page: rsx! { LoadingIndicator {} } }
            };
        }
        Some(Err(error)) => {
            return rsx! {
                PreviewWrapper {
                    controls: rsx! { "File locations" },
                    page: rsx! { ComponentErrorDisplay { error_txt: format!("{error:#?}") } }
                }
            };
        }
        Some(Ok(value)) => value,
    };

    let shown = value.locations.len() as u64;
    let hidden = value.total.saturating_sub(shown);
    let controls = rsx! {
        if value.total == 1 {
            "1 location"
        } else {
            "{value.total} locations"
        }
    };

    let page = if value.locations.is_empty() {
        // Not an error: a document can be known to the index while its VFS rows are not
        // there yet, and the reader is owed that sentence rather than an empty box.
        rsx! {
            div {
                style: "padding: 12px; color: rgba(0,0,0,0.6);",
                "This document is not recorded at any path in "
                b { "{document_identifier().collection_dataset}" }
                " — nothing to browse to."
            }
        }
    } else {
        rsx! {
            div {
                style: "display: flex; flex-direction: column; gap: 10px; padding: 4px; \
                        height: 100%; overflow-y: auto;",
                for (index , location) in value.locations.iter().enumerate() {
                    LocationRow {
                        key: "{location.container_hash}-{location.path}",
                        index: index + 1,
                        location: location.clone(),
                        document_identifier: document_identifier(),
                    }
                }
                if hidden > 0 {
                    div {
                        style: "padding: 4px 12px; color: rgba(0,0,0,0.6); font-size: 14px;",
                        "…and {hidden} more. Use Storage to browse the rest."
                    }
                }
            }
        }
    };

    rsx! {
        PreviewWrapper { controls, page }
    }
}

/// One location: the dataset, the folders and containers above the file, then the file.
///
/// The crumbs come from the resolved chain when there is one — that is the only thing
/// that knows an archive was crossed — and from splitting the raw path when there is not.
#[component]
fn LocationRow(
    index: usize,
    location: VfsFileLocation,
    document_identifier: DocumentIdentifier,
) -> Element {
    let dataset = location.collection_dataset.clone();
    let chain_len = location.chain.len();
    let crumbs: Vec<Crumb> = if chain_len > 1 {
        // `skip(1)` drops the dataset root, which renders as the dataset chip; `take` to
        // the second-to-last drops the file node, which renders as the last crumb.
        location.chain[..chain_len - 1]
            .iter()
            .skip(1)
            .map(|node| {
                (
                    node.display_name().to_string(),
                    node.descriptor(),
                    node.kind == VfsNodeKind::Container,
                )
            })
            .collect()
    } else {
        let descriptor = PathDescriptor {
            container_hash: location.container_hash.clone(),
            path: location.path.clone(),
        };
        let mut segments = path_segments(&descriptor);
        segments.pop();
        segments
            .into_iter()
            .map(|(name, descriptor)| (name, descriptor, false))
            .collect()
    };
    let crumbs = collapse_duplicate_crumbs(crumbs);

    let file_name = location.file_name().to_string();
    let parent = location.parent_descriptor();

    rsx! {
        div {
            style: LOCATION_ROW_STYLE,
            class: "x-file-location",
            span {
                style: "color: rgba(0,0,0,0.45); font-variant-numeric: tabular-nums;",
                "{index}."
            }
            Link {
                to: Route::file_browser_page(dataset.clone(), PathDescriptor::root(), None),
                style: CRUMB_LINK_STYLE,
                "{dataset}"
            }
            for (name , descriptor , is_container) in crumbs.iter() {
                span { key: "sep-{descriptor}", style: CRUMB_SEP_STYLE, "›" }
                Link {
                    to: Route::file_browser_page(dataset.clone(), descriptor.clone(), None),
                    style: CRUMB_LINK_STYLE,
                    title: "{descriptor.path}",
                    span {
                        style: "display: inline-flex; align-items: center; gap: 4px;",
                        if *is_container {
                            Icon { icon: GoFileZip, style: "width: 15px; height: 15px;" }
                        } else {
                            Icon { icon: MdFolder, style: "width: 15px; height: 15px; color: rgba(0,0,0,0.55);" }
                        }
                        "{name}"
                    }
                }
            }
            span { style: CRUMB_SEP_STYLE, "›" }
            // The file itself opens the folder that holds it WITH the document selected,
            // which is the browser state a reader arriving from here wants.
            Link {
                to: Route::file_browser_page(dataset.clone(), parent, Some(document_identifier.clone())),
                style: "{CRUMB_LINK_STYLE} font-weight: 600;",
                title: "{location.path}",
                "{file_name}"
            }
        }
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
