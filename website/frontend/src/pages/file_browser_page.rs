//! File browser pages: collection list and folder listing for a collection.

use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use common::vfs::{PathDescriptor, VfsFileEntry, VfsListing};
use dioxus::prelude::*;

use crate::components::document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot;
use crate::components::document_view_components::doc_preview_for_search::no_document_selected::NoDocumentSelected;
use crate::components::search_components::card_action_buttons::{
    DocCardActionButtonMore, DocCardActionButtonOpenNewTab,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::data_definitions::doc_viewer_state::{DocViewerState, ViewerRightTabState};
use crate::data_definitions::url_param::UrlParam;
use crate::pages::search_page::DocViewerStateControl;
use crate::routes::Route;

// ---------- Style constants ----------

const PAGE_STYLE: &str = "
    background: #FFFFFF;
    color: #111827;
    font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
    height: 100%;
    width: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: row;
    overflow: hidden;
";

const SIDEBAR_STYLE: &str = "
    width: 240px;
    flex-shrink: 0;
    border-right: 1px solid #E5E7EB;
    background: #FAFBFC;
    display: flex;
    flex-direction: column;
    overflow: hidden;
";

const SIDEBAR_HEADER_STYLE: &str = "
    padding: 14px 16px;
    background: #F3F4F6;
    border-bottom: 1px solid #E5E7EB;
    color: #6B7280;
    font-size: 13px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.04em;
";

const SIDEBAR_LIST_STYLE: &str = "
    flex: 1 1 auto;
    overflow: auto;
    padding: 8px 0;
";

const SIDEBAR_ITEM_BASE: &str = "
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    text-decoration: none;
    color: #111827;
    font-size: 14px;
    border-left: 3px solid transparent;
";

const SIDEBAR_ITEM_CURRENT: &str = "
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 10px;
    padding: 10px 16px;
    text-decoration: none;
    color: #1D4ED8;
    font-size: 14px;
    background: #EEF2FF;
    border-left: 3px solid #4F46E5;
    font-weight: 500;
";

const MAIN_AREA_STYLE: &str = "
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    flex-direction: row;
    overflow: hidden;
";

const TABLE_PANE_STYLE: &str = "
    flex: 1 1 50%;
    min-width: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
";

const TABLE_SCROLL_STYLE: &str = "
    flex: 1 1 auto;
    overflow: auto;
";

const PREVIEW_PANE_STYLE: &str = "
    flex: 1 1 50%;
    min-width: 0;
    border-left: 1px solid #E5E7EB;
    background: #FFFFFF;
    overflow: hidden;
    display: flex;
    flex-direction: column;
";

const BREADCRUMB_BAR_STYLE: &str = "
    display: flex;
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    padding: 14px 20px;
    background: #F3F4F6;
    border-bottom: 1px solid #E5E7EB;
    font-size: 14px;
    color: #374151;
    flex-shrink: 0;
";

const CRUMB_LABEL_STYLE: &str = "color: #374151; font-weight: 500; text-decoration: none;";
const CRUMB_LINK_STYLE: &str = "color: #2563EB; text-decoration: none; font-weight: 500;";
const CRUMB_SEP_STYLE: &str = "color: #9CA3AF; font-size: 14px;";

const TABLE_STYLE: &str = "
    width: 100%;
    border-collapse: collapse;
    background: #FFFFFF;
    font-size: 14px;
";

const TH_NAME_STYLE: &str = "
    text-align: left;
    padding: 12px 20px;
    background: #F3F4F6;
    color: #6B7280;
    font-weight: 500;
    font-size: 13px;
    border-bottom: 1px solid #E5E7EB;
";

const TH_SIZE_STYLE: &str = "
    text-align: left;
    padding: 12px 20px;
    background: #F3F4F6;
    color: #6B7280;
    font-weight: 500;
    font-size: 13px;
    border-bottom: 1px solid #E5E7EB;
    width: 130px;
";

const TH_ACTIONS_STYLE: &str = "
    padding: 12px 20px;
    background: #F3F4F6;
    border-bottom: 1px solid #E5E7EB;
    width: 110px;
";

const ROW_CLICKABLE_STYLE: &str = "background: #FFFFFF; cursor: pointer;";
const ROW_SELECTED_STYLE: &str = "background: #EEF2FF; cursor: pointer;";
const ROW_HOVER_CLASS: &str = "hoover4-hover-shadow-background";

const TD_NAME_STYLE: &str = "
    padding: 14px 20px;
    border-bottom: 1px solid #E5E7EB;
    color: #111827;
    vertical-align: middle;
";

const TD_SIZE_STYLE: &str = "
    padding: 14px 20px;
    border-bottom: 1px solid #E5E7EB;
    color: #6B7280;
    font-size: 13px;
    vertical-align: middle;
";

const TD_ACTIONS_STYLE: &str = "
    padding: 10px 20px;
    border-bottom: 1px solid #E5E7EB;
    text-align: right;
    white-space: nowrap;
    vertical-align: middle;
";

const NAME_INNER_STYLE: &str = "
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 12px;
";

const ICON_STYLE: &str = "
    font-size: 18px;
    width: 22px;
    text-align: center;
    flex-shrink: 0;
    color: #4B5563;
";

const FOLDER_LINK_STYLE: &str = "
    color: #111827;
    text-decoration: none;
";

const FILE_NAME_STYLE: &str = "color: #111827;";

// ---------- Top-level "all collections" page (route: /file_browser) ----------

#[component]
pub fn FileBrowserCollectionsPage() -> Element {
    let collections_resource = use_resource(move || async move { list_collections().await });

    let body = match collections_resource.read().clone() {
        None => rsx! { div { padding: "20px", "Loading..." } },
        Some(Err(e)) => rsx! { div { padding: "20px", "Error: {e}" } },
        Some(Ok(collections)) => {
            if collections.is_empty() {
                rsx! { p { padding: "20px", "(no collections found)" } }
            } else {
                rsx! { CollectionsTable { collections } }
            }
        }
    };

    rsx! {
        Title { "Hoover Search - File Browser" }
        div {
            style: "
                background: #FFFFFF;
                color: #111827;
                font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
                min-height: 100%;
                width: 100%;
                box-sizing: border-box;
            ",
            div {
                style: BREADCRUMB_BAR_STYLE,
                span { style: CRUMB_LABEL_STYLE, "Browsing" }
                span { style: CRUMB_LABEL_STYLE, "Collections" }
            }
            {body}
        }
    }
}

#[component]
fn CollectionsTable(collections: Vec<String>) -> Element {
    rsx! {
        table {
            style: TABLE_STYLE,
            thead {
                tr {
                    th { style: TH_NAME_STYLE, "Name" }
                }
            }
            tbody {
                for collection in collections.iter() {
                    CollectionRow {
                        key: "collection-{collection}",
                        collection: collection.clone(),
                    }
                }
            }
        }
    }
}

#[component]
fn CollectionRow(collection: String) -> Element {
    let target_collection = collection.clone();
    rsx! {
        tr {
            style: ROW_CLICKABLE_STYLE,
            class: ROW_HOVER_CLASS,
            onclick: move |_| {
                navigator().push(Route::file_browser_page(
                    target_collection.clone(),
                    PathDescriptor::root(),
                ));
            },
            td {
                style: TD_NAME_STYLE,
                div {
                    style: NAME_INNER_STYLE,
                    span { style: ICON_STYLE, "🗄️" }
                    span { style: FOLDER_LINK_STYLE, "{collection}" }
                }
            }
        }
    }
}

// ---------- File browser inside a collection ----------

#[component]
pub fn FileBrowserPage(
    collection: String,
    path: UrlParam<PathDescriptor>,
    selected_result_hash: UrlParam<Option<DocumentIdentifier>>,
    doc_viewer_state: UrlParam<Option<DocViewerState>>,
) -> Element {
    rsx! {
        Title { "Hoover Search - File Browser" }
        FileBrowserContent {
            collection: collection,
            path: path.0,
            selected_result_hash: selected_result_hash.0,
            doc_viewer_state: doc_viewer_state.0,
        }
    }
}

#[component]
fn FileBrowserContent(
    collection: ReadSignal<String>,
    path: ReadSignal<PathDescriptor>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
    doc_viewer_state: ReadSignal<Option<DocViewerState>>,
) -> Element {
    let mut listing_resource = use_resource(move || {
        let collection = collection();
        let path = path();
        async move { list_folder_children(collection, path).await }
    });
    use_effect(move || {
        let _ = collection();
        let _ = path();
        listing_resource.clear();
        listing_resource.restart();
    });

    use_context_provider(move || DocViewerStateControl {
        doc_viewer_state: doc_viewer_state.into(),
        set_doc_viewer_state: Callback::new(move |state: DocViewerState| {
            let next = Route::FileBrowserPage {
                collection: collection.read().clone(),
                path: path.read().clone().into(),
                selected_result_hash: selected_result_hash.read().clone().into(),
                doc_viewer_state: Some(state.clone()).into(),
            };
            // if let Some(old_state) = doc_viewer_state.read().clone() {
            //     if old_state == state {
            //         return;
            //     }
            //     navigator().push(next);
            // } else {
                navigator().replace(next);
            // }
        }),
    });

    let on_file_click = Callback::new(move |doc_id: DocumentIdentifier| {
        // let already_selected = selected_result_hash
        //     .read()
        //     .as_ref()
        //     .is_some_and(|s| s == &doc_id);
        // if already_selected {
        //     return;
        // }
        dioxus::logger::tracing::info!("on_file_click2: {:?}", doc_id);
        navigator().replace(Route::FileBrowserPage {
            collection: collection.read().clone(),
            path: path.read().clone().into(),
            selected_result_hash: Some(doc_id).into(),
            doc_viewer_state: UrlParam::from(None),
        });
    });

    let collection_value = collection();
    let path_value = path();
    let selected_value = selected_result_hash.read().clone();
    dioxus::logger::tracing::info!("selected_value: {:?}", selected_value);

    let listing_view = match listing_resource.read().clone() {
        None => rsx! { div { padding: "20px", "Loading..." } },
        Some(Err(e)) => rsx! { div { padding: "20px", "Error: {e}" } },
        Some(Ok(listing)) => rsx! {
            ListingTable {
                collection: collection_value.clone(),
                listing,
                selected_file: selected_value.clone(),
                on_file_click,
            }
        },
    };

    rsx! {
        div {
            style: PAGE_STYLE,
            CollectionsSidebar { current_collection: collection_value.clone() }
            div {
                style: MAIN_AREA_STYLE,
                div {
                    style: TABLE_PANE_STYLE,
                    Breadcrumbs {
                        collection: collection_value.clone(),
                        path: path_value.clone(),
                    }
                    div {
                        style: TABLE_SCROLL_STYLE,
                        {listing_view}
                    }
                }
                div {
                    style: PREVIEW_PANE_STYLE,
                    PreviewPane { selected_file: selected_value }
                }
            }
        }
    }
}

#[component]
fn CollectionsSidebar(current_collection: String) -> Element {
    let collections_resource = use_resource(move || async move { list_collections().await });

    let body = match collections_resource.read().clone() {
        None => rsx! { div { padding: "10px 16px", color: "#6B7280", "Loading..." } },
        Some(Err(e)) => rsx! { div { padding: "10px 16px", color: "#B91C1C", "Error: {e}" } },
        Some(Ok(collections)) => {
            if collections.is_empty() {
                rsx! { div { padding: "10px 16px", color: "#6B7280", "(none)" } }
            } else {
                rsx! {
                    for collection in collections.iter() {
                        SidebarCollectionItem {
                            key: "side-coll-{collection}",
                            collection: collection.clone(),
                            is_current: collection == &current_collection,
                        }
                    }
                }
            }
        }
    };

    rsx! {
        div {
            style: SIDEBAR_STYLE,
            div { style: SIDEBAR_HEADER_STYLE, "Collections" }
            div { style: SIDEBAR_LIST_STYLE, {body} }
        }
    }
}

#[component]
fn SidebarCollectionItem(collection: String, is_current: bool) -> Element {
    let item_style = if is_current {
        SIDEBAR_ITEM_CURRENT
    } else {
        SIDEBAR_ITEM_BASE
    };
    rsx! {
        Link {
            to: Route::file_browser_page(collection.clone(), PathDescriptor::root()),
            style: item_style,
            class: ROW_HOVER_CLASS,
            span { style: ICON_STYLE, "🗄️" }
            span { "{collection}" }
        }
    }
}

#[component]
fn Breadcrumbs(collection: String, path: PathDescriptor) -> Element {
    let segments = path_segments(&path);
    let container_hash = path.container_hash.clone();
    rsx! {
        div {
            style: BREADCRUMB_BAR_STYLE,
            Link {
                to: Route::FileBrowserCollectionsPage {},
                style: CRUMB_LABEL_STYLE,
                "Browsing"
            }
            Link {
                to: Route::file_browser_page(collection.clone(), PathDescriptor::root()),
                style: CRUMB_LINK_STYLE,
                "{collection}"
            }
            if !container_hash.is_empty() {
                ContainerBreadcrumb {
                    collection: collection.clone(),
                    container_hash: container_hash.clone(),
                }
            }
            for (name, descriptor) in segments.iter() {
                span { style: CRUMB_SEP_STYLE, "›" }
                Link {
                    key: "crumb-{descriptor}",
                    to: Route::file_browser_page(collection.clone(), descriptor.clone()),
                    style: CRUMB_LINK_STYLE,
                    "{name}"
                }
            }
        }
    }
}

#[component]
fn ContainerBreadcrumb(collection: String, container_hash: String) -> Element {
    let collection_for_lookup = collection.clone();
    let container_hash_for_lookup = container_hash.clone();
    let descriptor_resource = use_resource(move || {
        let collection = collection_for_lookup.clone();
        let container_hash = container_hash_for_lookup.clone();
        async move {
            lookup_container_descriptor(DocumentIdentifier {
                collection_dataset: collection,
                file_hash: container_hash,
            })
            .await
        }
    });

    let descriptor = match descriptor_resource.read().clone() {
        Some(Ok(d)) => d,
        _ => {
            return rsx! {
                span { style: CRUMB_SEP_STYLE, "›" }
                span {
                    style: CRUMB_LABEL_STYLE,
                    "[{container_hash:.8}…]"
                }
            };
        }
    };
    let label = descriptor
        .path
        .rsplit('/')
        .find(|s| !s.is_empty())
        .unwrap_or("(container)")
        .to_string();
    let parent_descriptor = descriptor.parent();
    rsx! {
        span { style: CRUMB_SEP_STYLE, "›" }
        Link {
            to: Route::file_browser_page(collection.clone(), parent_descriptor),
            style: CRUMB_LINK_STYLE,
            title: "{descriptor.path}",
            "📦 {label}"
        }
    }
}

fn path_segments(path: &PathDescriptor) -> Vec<(String, PathDescriptor)> {
    let trimmed = path.path.trim_start_matches('/').trim_end_matches('/');
    if trimmed.is_empty() {
        return Vec::new();
    }
    let mut result = Vec::new();
    let mut current = String::new();
    for part in trimmed.split('/') {
        current.push('/');
        current.push_str(part);
        result.push((
            part.to_string(),
            PathDescriptor {
                container_hash: path.container_hash.clone(),
                path: current.clone(),
            },
        ));
    }
    result
}

fn format_size(bytes: u64) -> String {
    const KB: f64 = 1024.0;
    const MB: f64 = KB * 1024.0;
    const GB: f64 = MB * 1024.0;
    let b = bytes as f64;
    if b < KB {
        format!("{} B", bytes)
    } else if b < MB {
        format!("{:.0} KB", b / KB)
    } else if b < GB {
        format!("{:.1} MB", b / MB)
    } else {
        format!("{:.2} GB", b / GB)
    }
}

#[component]
fn ListingTable(
    collection: String,
    listing: VfsListing,
    selected_file: Option<DocumentIdentifier>,
    on_file_click: Callback<DocumentIdentifier>,
) -> Element {
    if listing.directories.is_empty() && listing.files.is_empty() {
        return rsx! { p { padding: "20px", color: "#6B7280", "(empty folder)" } };
    }
    rsx! {
        table {
            style: TABLE_STYLE,
            thead {
                tr {
                    th { style: TH_NAME_STYLE, "Name" }
                    th { style: TH_SIZE_STYLE, "Size" }
                    th { style: TH_ACTIONS_STYLE, "" }
                }
            }
            tbody {
                for dir in listing.directories.iter() {
                    DirRow {
                        key: "dir-{dir.path}",
                        collection: collection.clone(),
                        name: dir.name.clone(),
                        path: dir.path.clone(),
                    }
                }
                for file in listing.files.iter() {
                    FileRow {
                        key: "file-{file.path}-{file.hash}",
                        collection: collection.clone(),
                        file: file.clone(),
                        is_selected: selected_file.as_ref().is_some_and(|id| {
                            id.collection_dataset == collection && id.file_hash == file.hash
                        }),
                        on_file_click,
                    }
                }
            }
        }
    }
}

#[component]
fn DirRow(collection: String, name: String, path: PathDescriptor) -> Element {
    let target_path = path.clone();
    let target_collection = collection.clone();
    rsx! {
        tr {
            style: ROW_CLICKABLE_STYLE,
            class: ROW_HOVER_CLASS,
            onclick: move |_| {
                navigator().push(Route::file_browser_page(
                    target_collection.clone(),
                    target_path.clone(),
                ));
            },
            td {
                style: TD_NAME_STYLE,
                div {
                    style: NAME_INNER_STYLE,
                    span { style: ICON_STYLE, "📁" }
                    span { style: FOLDER_LINK_STYLE, "{name}" }
                }
            }
            td { style: TD_SIZE_STYLE, "" }
            td { style: TD_ACTIONS_STYLE, "" }
        }
    }
}

#[component]
fn FileRow(
    collection: String,
    file: VfsFileEntry,
    is_selected: bool,
    on_file_click: Callback<DocumentIdentifier>,
) -> Element {
    let row_style = if is_selected {
        ROW_SELECTED_STYLE
    } else {
        ROW_CLICKABLE_STYLE
    };
    let row_class = if is_selected { "" } else { ROW_HOVER_CLASS };
    let click_doc_id = DocumentIdentifier {
        collection_dataset: collection.clone(),
        file_hash: file.hash.clone(),
    };
    let click_doc_id = use_signal(move || click_doc_id.clone());
    rsx! {
        tr {
            style: row_style,
            class: row_class,
            onclick: move |_| {
                dioxus::logger::tracing::info!("FileRow onclick: {:?}", click_doc_id.read().clone());
                on_file_click.call(click_doc_id.read().clone());
            },
            td {
                style: TD_NAME_STYLE,
                div {
                    style: NAME_INNER_STYLE,
                    span { style: ICON_STYLE, "📄" }
                    span { style: FILE_NAME_STYLE, "{file.name}" }
                }
            }
            td { style: TD_SIZE_STYLE, "{format_size(file.file_size_bytes)}" }
            td {
                style: TD_ACTIONS_STYLE,
                div {
                    style: "display: flex; flex-direction: row; justify-content: flex-end; gap: 4px;",
                    DocCardActionButtonOpenNewTab {
                        document_identifier:click_doc_id
                    }
                    DocCardActionButtonMore {
                        document_identifier: click_doc_id
                    }
                }
            }
        }
    }
}

// ---------- Right-hand preview pane ----------

#[component]
fn PreviewPane(selected_file: ReadSignal<Option<DocumentIdentifier>>) -> Element {

    dioxus::logger::tracing::info!("PreviewPane selected_file: {:?}", selected_file);
    rsx! {
        DocumentPreviewForSearchRoot {
            query: SearchQuery::default(),
            selected_result_hash: selected_file,
        }
    }
}

// ---------- Server fns ----------

#[server]
async fn list_folder_children(
    collection_dataset: String,
    path: PathDescriptor,
) -> Result<VfsListing, ServerFnError> {
    backend::api::vfs::list_folder_children(collection_dataset, path)
        .await
        .map_err(|e| ServerFnError::ServerError {
            message: e.to_string(),
            code: 500,
            details: None,
        })
}

#[server]
async fn lookup_container_descriptor(
    document_identifier: DocumentIdentifier,
) -> Result<PathDescriptor, ServerFnError> {
    backend::api::vfs::get_first_vfs_path(document_identifier)
        .await
        .map_err(|e| ServerFnError::ServerError {
            message: e.to_string(),
            code: 500,
            details: None,
        })
}

#[server]
async fn list_collections() -> Result<Vec<String>, ServerFnError> {
    backend::api::list_datasets::list_dataset_ids()
        .await
        .map_err(|e| ServerFnError::ServerError {
            message: e.to_string(),
            code: 500,
            details: None,
        })
}
