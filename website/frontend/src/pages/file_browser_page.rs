//! File browser pages: collection list and folder listing for a collection.

use common::search_query::SearchQuery;
use common::search_result::DocumentIdentifier;
use common::storage_tree::{DatasetAggregates, format_size, percent_of};
use common::vfs::{PathDescriptor, SubtreeStats, VfsFileEntry, VfsListing};
use dioxus::prelude::*;
use dioxus_free_icons::Icon;
use dioxus_free_icons::icons::go_icons::GoDatabase;
use dioxus_free_icons::icons::go_icons::GoFileZip;
use dioxus_free_icons::icons::md_action_icons::MdOpenInNew;
use dioxus_free_icons::icons::md_device_icons::MdStorage;
use dioxus_free_icons::icons::md_file_icons::MdFolder;

use crate::components::document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot;
use crate::components::resizable_sidebar::ResizableSidebar;
use crate::api::storage_api::{collection_overview, collections_overview};
use crate::api::vfs_api::{vfs_node_term_id, vfs_search_datasets, vfs_search_in_folder};
use crate::components::search_components::card_action_buttons::{
    DocCardActionButtonMore, DocCardActionButtonOpenNewTab,
};
use crate::components::search_components::storage_tree::{StorageRow, StorageTree};
use crate::components::search_components::vfs_tree::{TreeSkin, browser_now_ms, CHILDREN_CACHE_TTL_MS};
use common::search_result::FacetOriginalValue;
use common::vfs::{VFS_SEARCH_PAGE_SIZE, VfsNodeKind, VfsTreeNode, make_node_key};
use crate::data_definitions::doc_viewer_state::DocViewerState;
use crate::data_definitions::url_param::UrlParam;
use crate::pages::search_page::DocViewerStateControl;
use crate::pages::uploads::upload_button::UploadButton;
use crate::routes::Route;
use crate::tr;

// ---------- Style constants ----------

const PAGE_STYLE: &str = "
    background: #FFFFFF;
    color: var(--x-ink);
    font-family: var(--x-font);
    height: 100%;
    width: 100%;
    box-sizing: border-box;
    display: flex;
    flex-direction: row;
    overflow: hidden;
";

/// The container-root lookup and the descriptor it answered for.
///
/// A container-root URL identifies bytes and its inner path. It has no outer-location
/// field, so duplicate archive bytes resolve by the endpoint's stable path order.
#[derive(Clone)]
struct ContainerFocus {
    collection: String,
    descriptor: PathDescriptor,
    node: Option<VfsTreeNode>,
}

/// The inside of the storage pane. Its WIDTH belongs to [`ResizableSidebar`], which owns
/// the drag handle and the remembered value; putting a width here as well would fight it.
const SIDEBAR_STYLE: &str = "
    flex: 1 1 auto;
    min-width: 0;
    background: #FAFBFC;
    display: flex;
    flex-direction: column;
    overflow: hidden;
";

const SIDEBAR_HEADER_STYLE: &str = "
    padding: 14px 16px;
    background: #F3F4F6;
    border-bottom: 1px solid #E5E7EB;
    color: var(--x-ink-muted);
    font-size: var(--x-text-sm);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.04em;
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

/// The content box of the resizable preview pane. Its width belongs to the pane.
const PREVIEW_PANE_STYLE: &str = "background: #FFFFFF;";

const BREADCRUMB_BAR_STYLE: &str = "
    display: flex;
    flex-direction: row;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    padding: 14px 20px;
    background: #F3F4F6;
    border-bottom: 1px solid #E5E7EB;
    font-size: var(--x-text-md);
    color: var(--x-ink);
    flex-shrink: 0;
";

const CRUMB_LABEL_STYLE: &str = "color: var(--x-ink); font-weight: 500; text-decoration: none;";
pub(crate) const CRUMB_LINK_STYLE: &str = "color: var(--x-link); text-decoration: none; font-weight: 500;";
pub(crate) const CRUMB_SEP_STYLE: &str = "color: var(--x-ink-faint); font-size: var(--x-text-md);";

const TABLE_STYLE: &str = "
    width: 100%;
    border-collapse: collapse;
    background: #FFFFFF;
    font-size: var(--x-text-body);
";

const TH_NAME_STYLE: &str = "
    text-align: left;
    padding: 8px 11px;
    background: #F3F4F6;
    color: var(--x-ink-muted);
    font-weight: 500;
    font-size: var(--x-text-sm);
    border-bottom: 1px solid #E5E7EB;
";

/// The header over the `View Details` column. It has no label, and it gives the column
/// the same width as its cells.
const TH_DETAILS_STYLE: &str = "
    padding: 8px 8px;
    background: #F3F4F6;
    border-bottom: 1px solid #E5E7EB;
    width: 96px;
";

const TH_SIZE_STYLE: &str = "
    text-align: left;
    padding: 8px 8px;
    background: #F3F4F6;
    color: var(--x-ink-muted);
    font-weight: 500;
    font-size: var(--x-text-sm);
    border-bottom: 1px solid #E5E7EB;
    width: 80px;
";

const TH_ACTIONS_STYLE: &str = "
    padding: 8px 8px;
    background: #F3F4F6;
    border-bottom: 1px solid #E5E7EB;
    width: 88px;
";

const ROW_CLICKABLE_STYLE: &str = "background: #FFFFFF; cursor: pointer;";
const ROW_SELECTED_STYLE: &str = "background: #EEF2FF; cursor: pointer;";
const ROW_HOVER_CLASS: &str = "hoover4-hover-shadow-background";

const TD_NAME_STYLE: &str = "
    padding: 8px 11px;
    border-bottom: 1px solid #E5E7EB;
    color: var(--x-ink-strong);
    vertical-align: middle;
";

const TD_SIZE_STYLE: &str = "
    padding: 8px 8px;
    border-bottom: 1px solid #E5E7EB;
    color: var(--x-ink-muted);
    font-size: var(--x-text-sm);
    vertical-align: middle;
";

/// The mid-row cell holding `View Details`. It carries the row's rule like every other
/// cell: with `border-collapse: collapse` the rule is drawn per cell, so one styleless
/// cell punches a hole in it, and under the last row of a listing the remaining segments
/// read as the top edge of an empty row that is not there.
const TD_DETAILS_STYLE: &str = "
    width: 96px;
    border-bottom: 1px solid #E5E7EB;
    vertical-align: middle;
";

const TD_ACTIONS_STYLE: &str = "
    padding: 8px 8px;
    border-bottom: 1px solid #E5E7EB;
    text-align: right;
    white-space: nowrap;
    vertical-align: middle;
";

const NAME_INNER_STYLE: &str = "
    display: flex;
    flex-direction: row;
    align-items: center;
    gap: 8px;
";

const ICON_STYLE: &str = "
    font-size: var(--x-text-xl);
    width: 19px;
    text-align: center;
    flex-shrink: 0;
    color: var(--x-ink);
";

const FOLDER_LINK_STYLE: &str = "
    color: var(--x-ink-strong);
    text-decoration: none;
";

const FILE_NAME_STYLE: &str = "color: var(--x-ink-strong);";

// ---------- Top-level "all collections" page (route: /file_browser) ----------

/// The storage root. The sidebar is the same unified tree every storage surface has;
/// the pane names the collections, because a collection page is a real page now.
///
/// With a query in `q`, a list of matching names in every readable dataset replaces the
/// cards. `page` is the result page.
#[component]
pub fn FileBrowserCollectionsPage(q: String, page: u64) -> Element {
    // No dataset and no folder: the tree shows collections and their datasets only.
    let nothing = use_memo(String::new);
    let q = use_memo(use_reactive!(|q| q));
    let page = use_memo(use_reactive!(|page| page));
    let overview = use_resource(move || async move { collections_overview().await });

    let body = match overview.read().clone() {
        None => rsx! { div { padding: "20px", {tr!("file-browser-loading")} } },
        Some(Err(e)) => rsx! { div { class: "x-error-display", padding: "20px", {tr!("file-browser-error", e: e.to_string())} } },
        Some(Ok(collections)) => {
            if collections.is_empty() {
                rsx! { p { padding: "20px", {tr!("file-browser-no-collections-are-available-to")} } }
            } else {
                rsx! {
                    div {
                        style: CARD_GRID_STYLE,
                        for collection in collections.iter() {
                            StatsCard {
                                key: "collection-{collection.collectionname}",
                                to: Route::storage_collection(collection.collectionname.clone()),
                                title: collection.collectionname.clone(),
                                tooltip: collection.collectionname.clone(),
                                is_collection: true,
                                dataset_count: Some(collection.dataset_count),
                                stats: (collection.counted_dataset_count > 0).then(|| collection.as_dataset_aggregates()),
                                incomplete: !collection.is_complete(),
                            }
                        }
                    }
                }
            }
        }
    };

    rsx! {
        Title { {tr!("file-browser-hoover-search-file-browser")} }
        div {
            style: PAGE_STYLE,
            StorageSidebar { current_dataset: nothing, focus_key: nothing }
            div {
                style: "flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; overflow: auto;",
                div {
                    style: BREADCRUMB_BAR_STYLE,
                    span { style: CRUMB_LABEL_STYLE, {tr!("file-browser-browsing")} }
                    span { style: CRUMB_LABEL_STYLE, {tr!("file-browser-collections")} }
                    StorageSearchInput { collection: nothing, q }
                    UploadButton { dataset: String::new(), folder: String::new() }
                }
                if q().trim().is_empty() {
                    {body}
                } else {
                    StorageSearchResults { collection: nothing, q, page }
                }
            }
        }
    }
}

#[component]
fn dataset_icon() -> Element {
    rsx! {
        Icon {
            icon: GoDatabase,
            style: "width: 18px; height: 18px;"
        }
    }
}

#[component]
fn collection_icon() -> Element {
    rsx! {
        Icon {
            icon: MdStorage,
            style: "width: 18px; height: 18px;"
        }
    }
}

// ---------- Collection landing page (route: /file_browser/c/:collectionname) ----------

const CARD_GRID_STYLE: &str = "
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 16px;
    padding: 20px;
";

const CARD_STYLE: &str = "
    display: flex; flex-direction: column; gap: 10px;
    padding: 16px 18px; min-width: 0;
    border: 1px solid; border-color: var(--x-border); border-radius: var(--x-radius); background: white;
    cursor: pointer; text-decoration: none; color: var(--x-ink);
";

const CARD_STAT_ROW: &str = "
    display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
    font-size: var(--x-text-sm); color: var(--x-ink-muted);
";

const CARD_VALUE_STYLE: &str = "color: var(--x-ink-strong); font-weight: 500;";

const CARD_BADGE_STYLE: &str = "
    flex-shrink: 0; padding: 1px 8px; border-radius: 10px;
    font-size: var(--x-text-xs); font-weight: 500;
    color: var(--x-link); border: 1px solid; border-color: var(--x-link);
";

/// The tooltip of the Indexed share.
fn indexed_share_help() -> String {
    tr!("file-browser-the-share-of-documents-that")
}
/// The tooltip of the Processing errors share.
fn error_share_help() -> String {
    tr!("file-browser-the-share-of-documents-with")
}
/// The tooltip of the count date.
fn updated_on_help() -> String {
    tr!("file-browser-the-date-when-these-numbers")
}

/// One storage card: a collection on the root page, or a dataset on a collection page.
///
/// `stats` is `None` when the pipeline has not counted the dataset yet, and the card then
/// says so instead of showing zeros. `incomplete` marks a collection sum that leaves out
/// such datasets.
#[component]
fn StatsCard(
    to: Route,
    title: String,
    tooltip: String,
    is_collection: bool,
    dataset_count: Option<u64>,
    stats: Option<DatasetAggregates>,
    #[props(default)] incomplete: bool,
) -> Element {
    rsx! {
        Link {
            to: to,
            style: CARD_STYLE,
            class: ROW_HOVER_CLASS,
            title: "{tooltip}",
            div {
                style: "display: flex; align-items: center; gap: 10px; min-width: 0;",
                span { style: ICON_STYLE, if is_collection { {collection_icon()} } else { {dataset_icon()} } }
                span {
                    style: "flex: 1 1 auto; font-size: var(--x-text-lg); font-weight: 600; color: var(--x-ink-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                    "{title}"
                }
                if stats.as_ref().is_some_and(|s| s.processing) {
                    span { class: "x-storage-card-processing", style: CARD_BADGE_STYLE, {tr!("file-browser-processing")} }
                }
            }
            if let Some(count) = dataset_count {
                div { style: CARD_STAT_ROW,
                    span { {tr!("file-browser-datasets")} }
                    span { style: CARD_VALUE_STYLE, "{count}" }
                }
            }
            match stats {
                None => rsx! {
                    div { style: CARD_STAT_ROW, span { {tr!("file-browser-not-counted-yet")} } }
                },
                Some(aggregates) => rsx! {
                    div { style: CARD_STAT_ROW,
                        span { {tr!("file-browser-documents")} }
                        span { style: CARD_VALUE_STYLE, "{aggregates.document_count}" }
                    }
                    div { style: CARD_STAT_ROW,
                        span { {tr!("file-browser-total-size")} }
                        span { style: CARD_VALUE_STYLE, "{format_size(aggregates.total_size_bytes)}" }
                    }
                    div { style: CARD_STAT_ROW, title: "{indexed_share_help()}",
                        span { {tr!("file-browser-indexed")} }
                        span { style: CARD_VALUE_STYLE, "{percent_of(aggregates.indexed_count, aggregates.document_count)}" }
                    }
                    if aggregates.error_documents_counted {
                        div { style: CARD_STAT_ROW, title: "{error_share_help()}",
                            span { {tr!("file-browser-processing-errors")} }
                            span {
                                style: if aggregates.error_document_count > 0 { "color: var(--x-warning); font-weight: 500;" } else { CARD_VALUE_STYLE },
                                "{percent_of(aggregates.error_document_count, aggregates.document_count)}"
                            }
                        }
                    }
                    if !aggregates.updated_on.is_empty() {
                        div { style: CARD_STAT_ROW, title: "{updated_on_help()}",
                            span { {tr!("file-browser-updated-on", aggregates_updated_on: aggregates.updated_on.to_string())} }
                        }
                    }
                    if incomplete {
                        div { style: CARD_STAT_ROW, span { {tr!("file-browser-some-datasets-are-not-counted")} } }
                    }
                },
            }
        }
    }
}

/// The datasets of one collection, as cards with their cached statistics.
///
/// With a query in `q`, a list of matching names in the readable datasets of this
/// collection replaces the cards. `page` is the result page.
#[component]
pub fn FileBrowserCollectionPage(collectionname: String, q: String, page: u64) -> Element {
    // The signal, read inside the closure: that read is the subscription, and this page
    // is reachable from a sidebar row on another collection's page.
    let name = use_memo(use_reactive!(|collectionname| collectionname));
    let q = use_memo(use_reactive!(|q| q));
    let page = use_memo(use_reactive!(|page| page));
    let nothing = use_memo(String::new);
    let overview = use_resource(move || async move { collection_overview(name()).await });

    let body = match overview.read().clone() {
        None => rsx! { div { padding: "20px", {tr!("file-browser-loading")} } },
        Some(Err(e)) => rsx! { div { class: "x-error-display", padding: "20px", {tr!("file-browser-error", e: e.to_string())} } },
        Some(Ok(overview)) => rsx! {
            div {
                style: CARD_GRID_STYLE,
                for dataset in overview.datasets.iter() {
                    {
                        let aggregates = overview.aggregates_for(&dataset.collection_dataset).cloned();
                        rsx! {
                            StatsCard {
                                key: "{dataset.collection_dataset}",
                                to: Route::file_browser_page(
                                    dataset.collection_dataset.clone(),
                                    PathDescriptor::root(),
                                    None,
                                ),
                                title: dataset.label().to_string(),
                                tooltip: dataset.collection_dataset.clone(),
                                is_collection: false,
                                dataset_count: None,
                                stats: aggregates,
                            }
                        }
                    }
                }
            }
        },
    };

    rsx! {
        Title { {tr!("file-browser-hoover-search-file-browser")} }
        div {
            style: PAGE_STYLE,
            StorageSidebar { current_dataset: nothing, focus_key: nothing }
            div {
                style: "flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; overflow: auto;",
                div {
                    style: BREADCRUMB_BAR_STYLE,
                    Link { to: Route::storage_root(), style: CRUMB_LABEL_STYLE, {tr!("file-browser-browsing")} }
                    span { style: CRUMB_SEP_STYLE, "›" }
                    span { style: CRUMB_LABEL_STYLE, "{name}" }
                    StorageSearchInput { collection: name, q }
                    UploadButton { dataset: String::new(), folder: String::new() }
                }
                if q().trim().is_empty() {
                    {body}
                } else {
                    StorageSearchResults { collection: name, q, page }
                }
            }
        }
    }
}

// ---------- File-browser search on the root and collection pages ----------

/// The address of a storage search: the root page for an empty `collection`, the
/// collection page otherwise.
fn storage_search_route(collection: &str, q: String, page: u64) -> Route {
    if collection.is_empty() {
        Route::FileBrowserCollectionsPage { q, page }
    } else {
        Route::FileBrowserCollectionPage { collectionname: collection.to_string(), q, page }
    }
}

/// The search box of the root and collection pages. The query lives in the address.
///
/// Typing changes the address 300 ms after the last key. The first query after an empty
/// box adds a history entry, so Back returns to the cards. Later changes replace it.
/// `sent` holds the last query this box wrote, so an address that it wrote itself does
/// not overwrite keys typed after it. Back and links set the box to their query.
#[component]
fn StorageSearchInput(collection: ReadSignal<String>, q: ReadSignal<String>) -> Element {
    let mut needle = use_signal(|| q.peek().clone());
    let mut sent = use_signal(|| q.peek().clone());
    use_effect(move || {
        let current = q();
        if *sent.peek() != current {
            sent.set(current.clone());
            needle.set(current);
        }
    });
    let mut go = move |pattern: String| {
        if *sent.peek() == pattern {
            return;
        }
        let was_empty = sent.peek().trim().is_empty();
        sent.set(pattern.clone());
        let route = storage_search_route(&collection.peek(), pattern, 0);
        if was_empty {
            navigator().push(route);
        } else {
            navigator().replace(route);
        }
    };
    rsx! {
        div {
            style: "flex: 1 1 260px; min-width: 200px; max-width: 520px;",
            crate::components::search_input::SearchInput {
                value: needle,
                placeholder: if collection().is_empty() { {tr!("file-browser-search-names-in-all-collections")}.to_string() } else { {tr!("file-browser-search-names-in-this-collection")}.to_string() },
                on_change: move |value: String| {
                    needle.set(value.clone());
                    spawn(async move {
                        n0_future::time::sleep(std::time::Duration::from_millis(300)).await;
                        if *needle.peek() == value {
                            go(value);
                        }
                    });
                },
                on_submit: move |_| go(needle.peek().clone()),
            }
        }
    }
}

/// The result list that replaces the cards while a storage search has a query.
///
/// The resource returns the request it answered, and the list renders only the answer
/// to the current address. A failed request shows its error. Matches after the reachable
/// range are counted and named, and cannot be opened.
#[component]
fn StorageSearchResults(collection: ReadSignal<String>, q: ReadSignal<String>, page: ReadSignal<u64>) -> Element {
    let results = use_resource(move || {
        let request = (collection(), q(), page());
        async move {
            let (collection, q, page) = request.clone();
            let offset = page.saturating_mul(VFS_SEARCH_PAGE_SIZE);
            let answer = vfs_search_datasets(collection, q, VFS_SEARCH_PAGE_SIZE, offset).await;
            (request, answer)
        }
    });
    let current = (collection(), q(), page());
    let answer = match results.read().as_ref() {
        Some((request, answer)) if *request == current => Some(answer.clone()),
        _ => None,
    };
    let body = match answer {
        None => rsx! { div { class: "x-storage-search-loading", padding: "20px", {tr!("file-browser-searching")} } },
        Some(Err(e)) => rsx! { div { class: "x-error-display x-storage-search-error", padding: "20px", {tr!("file-browser-the-search-failed", e: e.to_string())} } },
        Some(Ok(found)) => {
            let collection_value = collection();
            let q_value = q();
            let page_value = page();
            if found.total == 0 {
                let short = q_value.trim().chars().count() < 3;
                rsx! {
                    div { class: "x-storage-search-empty", style: STORAGE_SEARCH_NOTE_STYLE,
                        p { {tr!("file-browser-no-file-or-folder-name", q_value_trim: q_value.trim().to_string())} }
                        if short {
                            p { {tr!("file-browser-type-at-least-3-characters")} }
                        }
                    }
                }
            } else if found.nodes.is_empty() {
                rsx! {
                    div { class: "x-storage-search-out-of-range", style: STORAGE_SEARCH_NOTE_STYLE,
                        p { {tr!("file-browser-this-page-is-after-the")} }
                        Link {
                            to: storage_search_route(&collection_value, q_value.clone(), 0),
                            style: CRUMB_LINK_STYLE,
                            {tr!("file-browser-go-to-page-1")}
                        }
                    }
                }
            } else {
                let first = found.offset + 1;
                let last = found.offset + found.nodes.len() as u64;
                let pages = found.page_count();
                let total_label = if found.total_exact { found.total.to_string() } else { format!("{}+", found.total) };
                let previous = (page_value > 0).then(|| storage_search_route(&collection_value, q_value.clone(), page_value - 1));
                let next = (page_value + 1 < pages).then(|| storage_search_route(&collection_value, q_value.clone(), page_value + 1));
                rsx! {
                    div { class: "x-storage-search-summary", style: STORAGE_SEARCH_SUMMARY_STYLE,
                        span { {tr!("file-browser-matches-of-page-of", first: first.to_string(), last: last.to_string(), total_label: total_label.to_string(), page_value_1: (page_value + 1).to_string(), pages: pages)} }
                        if found.total > found.reachable {
                            span { {tr!("file-browser-only-the-first-matches-can", found_reachable: found.reachable.to_string())} }
                        }
                    }
                    table {
                        style: TABLE_STYLE,
                        thead {
                            tr {
                                th { style: TH_NAME_STYLE, {tr!("file-browser-name")} }
                                th { style: TH_NAME_STYLE, {tr!("file-browser-dataset")} }
                                th { style: TH_NAME_STYLE, {tr!("file-browser-path")} }
                                th { style: TH_SIZE_STYLE, {tr!("file-browser-size")} }
                            }
                        }
                        tbody {
                            for node in found.nodes.iter() {
                                StorageSearchRow {
                                    key: "{node.node_key}",
                                    node: node.clone(),
                                    dataset_label: found.dataset_labels.get(&node.collection_dataset).cloned().unwrap_or_else(|| node.collection_dataset.clone()),
                                }
                            }
                        }
                    }
                    div { style: STORAGE_SEARCH_PAGER_STYLE,
                        if let Some(route) = previous {
                            Link { to: route, class: "x-storage-search-previous", style: CRUMB_LINK_STYLE, {tr!("file-browser-previous-page")} }
                        }
                        if let Some(route) = next {
                            Link { to: route, class: "x-storage-search-next", style: CRUMB_LINK_STYLE, {tr!("file-browser-next-page")} }
                        }
                    }
                }
            }
        }
    };
    rsx! {
        div { class: "x-storage-search-results", style: "display: flex; flex-direction: column; min-width: 0;", {body} }
    }
}

const STORAGE_SEARCH_NOTE_STYLE: &str = "padding: 20px; color: var(--x-ink-muted); display: flex; flex-direction: column; gap: 8px; align-items: flex-start;";
const STORAGE_SEARCH_SUMMARY_STYLE: &str = "padding: 8px 14px; font-size: var(--x-text-md); color: rgba(0,0,0,0.7); border-bottom: 1px solid #E5E7EB; display: flex; flex-direction: column; gap: 2px;";
const STORAGE_SEARCH_PAGER_STYLE: &str = "display: flex; gap: 16px; padding: 12px 14px;";

/// The route that a storage search result opens.
///
/// A folder opens itself. A container opens at its root and selects itself, as a tree
/// row does. A file opens its folder with the file selected.
fn storage_search_target(node: &VfsTreeNode) -> Route {
    let dataset = node.collection_dataset.clone();
    let selected = (!node.file_hash.is_empty() && node.kind != VfsNodeKind::Dir).then(|| DocumentIdentifier {
        collection_dataset: dataset.clone(),
        file_hash: node.file_hash.clone(),
    });
    Route::file_browser_page(dataset, node.open_descriptor(), selected)
}

/// One row of the storage search result list.
#[component]
fn StorageSearchRow(node: VfsTreeNode, dataset_label: String) -> Element {
    let target = storage_search_target(&node);
    let size = if node.file_size_bytes >= 0 && node.kind != VfsNodeKind::Dir {
        format_size(node.file_size_bytes as u64)
    } else {
        String::new()
    };
    rsx! {
        tr {
            class: "x-storage-search-row",
            td {
                style: TD_NAME_STYLE,
                Link {
                    to: target.clone(),
                    style: "{NAME_INNER_STYLE} color: var(--x-ink-strong); text-decoration: none;",
                    span {
                        style: ICON_STYLE,
                        if node.kind == VfsNodeKind::Container { {container_icon()} }
                        else if node.kind == VfsNodeKind::Dir { {folder_icon()} }
                        else { {file_icon(String::new())} }
                    }
                    span { style: FILE_NAME_STYLE, "{node.display_name()}" }
                }
            }
            td {
                style: "padding: 6px 10px; font-size: var(--x-text-sm); white-space: nowrap;",
                title: "{node.collection_dataset}",
                "{dataset_label}"
            }
            td {
                style: "padding: 6px 10px; color: var(--x-ink-muted); font-size: var(--x-text-sm); max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                title: "{node.path}",
                "{node.path}"
            }
            td { style: TD_SIZE_STYLE, "{size}" }
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
        Title { {tr!("file-browser-hoover-search-file-browser")} }
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
    // The signals are read OUTSIDE the async block, which is what subscribes the
    // resource to them, so it already re-runs on every navigation. The `use_effect`
    // that used to `clear()` and `restart()` it here fired on mount as well, which meant
    // every folder listing was fetched twice.
    let listing_resource = use_resource(move || {
        let collection = collection();
        let path = path();
        async move { list_folder_children(collection, path).await }
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
        navigator().replace(Route::FileBrowserPage {
            collection: collection.read().clone(),
            path: path.read().clone().into(),
            selected_result_hash: Some(doc_id).into(),
            doc_viewer_state: UrlParam::from(None),
        });
    });

    // `Some(nodes)` means the in-folder search box has a query and its matches replace
    // the plain listing; `None` means the box is empty and the listing is showing.
    let folder_matches = use_signal(|| None::<Vec<VfsTreeNode>>);

    // The node the URL is pointing at, as a MEMO over the route signals. Ancestor
    // elision, sibling capping and the highlighted row are all defined relative to it,
    // and all three have to follow an in-app navigation, which a plain prop does not.
    let descriptor_focus = use_memo(move || {
        let path = path();
        make_node_key(&collection(), &path.container_hash, &path.path)
    });
    let mut cached_containers = use_signal(std::collections::BTreeMap::<(String, String), (f64, Option<VfsTreeNode>)>::new);
    let container_focus = use_resource(move || {
        let collection = collection();
        let descriptor = path();
        let cache_key = (collection.clone(), descriptor.container_hash.clone());
        let cached = cached_containers.peek().get(&cache_key).cloned();
        async move {
            if descriptor.container_hash.is_empty() || descriptor.path != "/" {
                return Ok::<ContainerFocus, ServerFnError>(ContainerFocus { collection, descriptor, node: None });
            }
            if let Some((fetched_at, node)) = cached
                && browser_now_ms() - fetched_at < CHILDREN_CACHE_TTL_MS
            {
                return Ok(ContainerFocus { collection, descriptor, node });
            }
            let node = crate::api::vfs_api::vfs_tree_container_node(
                collection.clone(),
                descriptor.container_hash.clone(),
            )
            .await?;
            cached_containers.write().insert(cache_key, (
                browser_now_ms(), node.clone(),
            ));
            Ok::<ContainerFocus, ServerFnError>(ContainerFocus { collection, descriptor, node })
        }
    });
    let focus_key = use_memo(move || match container_focus.read().clone() {
        Some(Ok(resolved)) if resolved.collection == collection() && resolved.descriptor == path() => resolved
            .node
            .map(|node| node.node_key)
            .unwrap_or_else(|| descriptor_focus()),
        _ if !path().container_hash.is_empty() && path().path == "/" => String::new(),
        _ => descriptor_focus(),
    });

    let mut cached_paths = use_signal(std::collections::BTreeMap::<String, (f64, Vec<VfsTreeNode>)>::new);
    let resolved_path = use_resource(move || {
        let dataset = collection();
        let key = focus_key();
        let cached = cached_paths.peek().get(&key).cloned();
        async move {
            if key.is_empty() {
                return Ok::<_, ServerFnError>(None);
            }
            if let Some((fetched_at, nodes)) = cached
                && browser_now_ms() - fetched_at < CHILDREN_CACHE_TTL_MS
            {
                crate::components::search_components::vfs_tree::record_tree_query("path", true, 0, 0);
                return Ok(Some((key, nodes)));
            }
            let path = crate::api::vfs_api::vfs_tree_path_to(dataset, key.clone()).await?;
            crate::components::search_components::vfs_tree::record_tree_query(
                "path", false, path.datastore_queries, path.took_ms,
            );
            cached_paths.write().insert(key.clone(), (
                browser_now_ms(), path.nodes.clone(),
            ));
            Ok(Some((key, path.nodes)))
        }
    });
    use_context_provider(move || crate::api::vfs_api::ResolvedVfsPath { dataset: collection, chain: resolved_path });

    let collection_value = collection();
    let path_value = path();
    let selected_value = selected_result_hash.read().clone();

    let listing_view = match listing_resource.read().clone() {
        None => rsx! { div { padding: "20px", {tr!("file-browser-loading")} } },
        Some(Err(e)) => rsx! { div { class: "x-error-display", padding: "20px", {tr!("file-browser-error", e: e.to_string())} } },
        Some(Ok(listing)) => rsx! {
            ListingTable {
                collection: collection_value.clone(),
                listing,
                selected_file: selected_result_hash,
                on_file_click,
            }
        },
    };

    rsx! {
        div {
            style: PAGE_STYLE,
            // The SIGNALS, not their current values: the tree has to follow an in-app
            // navigation, and only a signal read inside a resource makes that happen.
            StorageSidebar { current_dataset: collection, focus_key }
            div {
                style: MAIN_AREA_STYLE,
                div {
                    style: TABLE_PANE_STYLE,
                    Breadcrumbs { collection, path, focus_key }
                    FolderToolbar {
                        key: descriptor_focus(),
                        collection: collection_value.clone(),
                        path: path_value.clone(),
                        matches: folder_matches,
                    }
                    div {
                        style: TABLE_SCROLL_STYLE,
                        match folder_matches.read().clone() {
                            Some(nodes) => rsx! {
                                FolderSearchResults {
                                    collection: collection_value.clone(),
                                    nodes,
                                    on_file_click,
                                }
                            },
                            None => listing_view,
                        }
                    }
                }
                crate::components::resizable_sidebar::ResizablePane {
                    storage_key: "hoover4.storage-preview-width-css-px",
                    default_px: 480,
                    min_px: 300,
                    max_px: 1400,
                    side: crate::components::resizable_sidebar::PaneSide::Right,
                    handle_id: "x-storage-preview-resize",
                    max_share: "65%",
                    pane_style: PREVIEW_PANE_STYLE.to_string(),
                    PreviewPane { selected_file: selected_value }
                }
            }
        }
    }
}

/// The one storage sidebar: collections > datasets > folders, on every storage page.
///
/// It replaced a COLLECTIONS list stacked on a FOLDERS tree of whichever dataset the URL
/// happened to name. That arrangement showed the same data as two unrelated widgets and
/// could not say which collection a dataset belonged to at all.
///
/// The pane is resizable and remembers its width. That is not cosmetic here: a corpus with
/// a 42-level chain in it spends most of a narrow pane on indent, chevron, icon and depth
/// badge, and the width the tree needs is a property of the corpus rather than of the app.
#[component]
fn StorageSidebar(current_dataset: ReadSignal<String>, focus_key: ReadSignal<String>) -> Element {
    // The picker's selection set. Unused by the sidebar skin, which highlights the node
    // the URL names instead, one row, always the one the URL names.
    let selected = use_signal(std::collections::BTreeSet::<String>::new);

    rsx! {
        ResizableSidebar {
            div {
                style: SIDEBAR_STYLE,
                div { style: SIDEBAR_HEADER_STYLE, {tr!("file-browser-storage")} }
                div {
                    // `overflow-x: hidden` here as well as inside the tree: nothing in the
                    // pane may make the page scroll sideways, however long a folder name
                    // is and however narrow the user has dragged it.
                    style: "flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 4px 2px;",
                    StorageTree {
                        skin: TreeSkin::Sidebar,
                        selected,
                        current_dataset,
                        focus_key,
                        on_activate: Callback::new(move |row: StorageRow| {
                            let target = match row {
                                StorageRow::Collection(name) => {
                                    Route::storage_collection(name)
                                }
                                StorageRow::Dataset(dataset) => {
                                    Route::file_browser_page(dataset, PathDescriptor::root(), None)
                                }
                                // A container is a file as well as a folder (a PDF or an
                                // archive), so entering it selects it too. Without that,
                                // a container whose children are not indexed (most PDFs)
                                // browsed to an `(empty folder)` and the document the
                                // row names was nowhere on the page.
                                StorageRow::Folder(dataset, node) => {
                                    let selected = (node.kind == VfsNodeKind::Container
                                        && !node.file_hash.is_empty())
                                    .then(|| DocumentIdentifier {
                                        collection_dataset: dataset.clone(),
                                        file_hash: node.file_hash.clone(),
                                    });
                                    Route::file_browser_page(dataset, node.descriptor(), selected)
                                }
                            };
                            navigator().push(target);
                        }),
                    }
                }
            }
        }
    }
}

/// Crumbs rendered before the trail collapses into a `…` chip.
pub const MAX_CRUMBS_SHOWN: usize = 3;

const CRUMB_CHIP_STYLE: &str = "
    display: inline-flex; align-items: center; justify-content: center;
    width: 26px; height: 22px; border-radius: 100px;
    border: 1px solid rgba(0,0,0,0.25); background: white;
    cursor: pointer; padding: 0; color: var(--x-ink);
";

const CRUMB_POPUP_STYLE: &str = "
    position: absolute; top: 26px; left: 0;
    min-width: 240px; max-width: min(520px, 80vw);
    max-height: 320px; overflow-y: auto; overflow-x: hidden;
    background: white; border: 1px solid rgba(0,0,0,0.25); border-radius: 10px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.18);
    z-index: 1200; padding: 6px 0;
";

const CRUMB_POPUP_ITEM_STYLE: &str = "
    display: flex; align-items: center; gap: 8px;
    padding: 6px 12px; font-size: var(--x-text-md); line-height: 20px;
    text-decoration: none; color: var(--x-link);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
";

/// How many leading crumbs collapse into the `…` chip.
///
/// The dataset root is a crumb of its own outside this trail and always renders, so the
/// rule here is only about the folders: keep the last [`MAX_CRUMBS_SHOWN`], hide the rest.
fn elide_crumbs(len: usize) -> usize {
    len.saturating_sub(MAX_CRUMBS_SHOWN)
}

/// One crumb: what it says, where it goes, and whether to draw an archive icon.
pub(crate) type Crumb = (String, PathDescriptor, bool);

/// Drop crumbs that navigate to the place the previous one already navigates to.
///
/// Entering a container produces TWO chain entries with the same destination: the
/// container file (`/location-1/parent.zip`, kind `container`) and the container's own
/// root (`/` inside it), because `VfsTreeNode::descriptor` turns a container into
/// `{container_hash: its own hash, path: "/"}`, which is exactly what that root already
/// is. Rendering both gives `… › parent.zip › /`: two links to one folder, and (because
/// the crumbs are keyed by descriptor) a duplicate Dioxus key that drops hops out of the
/// bar entirely. The first of the pair is the one worth keeping: it is named after the
/// archive, the second is named `/`.
pub(crate) fn collapse_duplicate_crumbs(crumbs: Vec<Crumb>) -> Vec<Crumb> {
    let mut result: Vec<Crumb> = Vec::with_capacity(crumbs.len());
    for crumb in crumbs {
        if result.last().is_some_and(|(_, previous, _)| *previous == crumb.1) {
            continue;
        }
        result.push(crumb);
    }
    result
}

/// The path bar, resolved through the structure index so nested containers show as a
/// chain rather than as one hop.
///
/// `PathDescriptor` carries a single `container_hash`, so an archive inside an archive
/// used to render as "collection › inner.zip › …" with the outer one missing entirely.
/// `vfs_tree_path_to` walks `parent_key`, which crosses container boundaries, so the
/// chain it returns is the real ancestry. It falls back to splitting the descriptor's
/// path while that round trip is in flight, or if the node is not in the index, a
/// breadcrumb bar that blinks empty on every navigation is worse than one that is briefly
/// missing a container hop.
#[component]
fn Breadcrumbs(collection: ReadSignal<String>, path: ReadSignal<PathDescriptor>, focus_key: ReadSignal<String>) -> Element {
    let mut popup_open = use_signal(|| false);
    let shared = use_context::<crate::api::vfs_api::ResolvedVfsPath>();

    // `(label, descriptor, is_container)` for every crumb after the dataset root. From
    // the index when it answers, from the raw path while it has not.
    let crumbs: Vec<Crumb> = match shared.chain.read().clone() {
        Some(Ok(Some((key, nodes)))) if key == focus_key() && nodes.len() > 1 => nodes
            .iter()
            .skip(1)
            .map(|node| {
                (
                    node.display_name().to_string(),
                    node.descriptor(),
                    node.kind == VfsNodeKind::Container,
                )
            })
            .collect(),
        _ => path_segments(&path())
            .into_iter()
            .map(|(name, descriptor)| (name, descriptor, false))
            .collect(),
    };
    let crumbs = collapse_duplicate_crumbs(crumbs);

    let hidden = elide_crumbs(crumbs.len());
    // The upload page opens at this folder only outside archives and emails.
    let upload_folder = if path().container_hash.is_empty() { path().path } else { String::new() };
    let collapsed: Vec<Crumb> = crumbs[..hidden].to_vec();
    let visible: Vec<Crumb> = crumbs[hidden..].to_vec();

    rsx! {
        div {
            style: BREADCRUMB_BAR_STYLE,
            Link {
                to: Route::storage_root(),
                style: CRUMB_LABEL_STYLE,
                {tr!("file-browser-browsing")}
            }
            Link {
                to: Route::file_browser_page(collection(), PathDescriptor::root(), None),
                style: CRUMB_LINK_STYLE,
                "{collection}"
            }
        if hidden > 0 {
            span { style: CRUMB_SEP_STYLE, "›" }
            div {
                style: "position: relative; display: inline-flex;",
                button {
                    // Named so a test or a script can find exactly this control. The
                    // tree has a gap row whose title begins the same way.
                    id: "x-breadcrumb-more",
                    style: CRUMB_CHIP_STYLE,
                    class: "hoover4-hover-shadow-background",
                    title: tr!("file-browser-show-the-folders-above", hidden: hidden.to_string()),
                    onclick: move |event: Event<MouseData>| {
                        event.stop_propagation();
                        let open = *popup_open.read();
                        popup_open.set(!open);
                    },
                    "…"
                }
                if *popup_open.read() {
                    // Click-away layer, below the popup and above everything else.
                    div {
                        style: "position: fixed; inset: 0; z-index: 1100;",
                        onclick: move |_| popup_open.set(false),
                    }
                    div {
                        style: CRUMB_POPUP_STYLE,
                        for (name, descriptor, is_container) in collapsed.iter() {
                            Link {
                                key: "{descriptor}",
                                to: Route::file_browser_page(collection(), descriptor.clone(), None),
                                style: CRUMB_POPUP_ITEM_STYLE,
                                class: "x-facet-list-item",
                                title: "{descriptor.path}",
                                onclick: move |_| popup_open.set(false),
                                if *is_container {
                                    Icon { icon: GoFileZip, style: "width: 16px; height: 16px; flex-shrink: 0;" }
                                } else {
                                    Icon { icon: MdFolder, style: "width: 16px; height: 16px; flex-shrink: 0; color: rgba(0,0,0,0.6);" }
                                }
                                "{name}"
                            }
                        }
                    }
                }
            }
        }
        for (name, descriptor, is_container) in visible.iter() {
            span { key: "crumb-{descriptor}", style: CRUMB_SEP_STYLE, "›" }
            Link {
                to: Route::file_browser_page(collection(), descriptor.clone(), None),
                style: "{CRUMB_LINK_STYLE} max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                title: "{descriptor.path}",
                span {
                    style: "display: inline-flex; align-items: center; gap: 4px;",
                    if *is_container {
                        Icon { icon: GoFileZip, style: "width: 16px; height: 16px;" }
                    }
                    "{name}"
                }
            }
        }
        UploadButton { dataset: collection(), folder: upload_folder }
        }
    }
}

pub(crate) fn path_segments(path: &PathDescriptor) -> Vec<(String, PathDescriptor)> {
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

#[component]
fn ListingTable(
    collection: String,
    listing: VfsListing,
    selected_file: ReadSignal<Option<DocumentIdentifier>>,
    on_file_click: Callback<DocumentIdentifier>,
) -> Element {
    if listing.directories.is_empty() && listing.files.is_empty() {
        return rsx! { p { padding: "20px", color: "var(--x-ink-muted)", {tr!("file-browser-empty-folder")} } };
    }
    let mut mounts = use_signal(move || std::collections::HashMap::new());
    let onmounted = Callback::new(move |(_id, _d): (DocumentIdentifier, Event<MountedData>)| {
        mounts.write().insert(_id, _d.data());
    });
    use_effect(move || {
        let selected = selected_file.read().clone();
        let dict = mounts.read().clone();
        if let Some(selected) = selected {
            if let Some(data) = dict.get(&selected) {
                let _x = data.scroll_to_with_options(ScrollToOptions {
                    behavior: ScrollBehavior::Smooth,
                    vertical: ScrollLogicalPosition::Center,
                    horizontal: ScrollLogicalPosition::Center,
                });
                spawn(async move {
                    let _r_ = _x.await;
                });
            }
        }
    });

    rsx! {
        table {
            style: TABLE_STYLE,
            thead {
                tr {
                    th { style: TH_NAME_STYLE, {tr!("file-browser-name")} }
                    th { style: TH_DETAILS_STYLE, "" }
                    th { style: TH_SIZE_STYLE, {tr!("file-browser-files")} }
                    th { style: TH_SIZE_STYLE, {tr!("file-browser-size")} }
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
                        stats: dir.stats,
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
                        onmounted: onmounted,
                        is_container: file.is_container,
                    }
                }
            }
        }
    }
}

#[component]
fn DirRow(collection: String, name: String, path: PathDescriptor, stats: Option<SubtreeStats>) -> Element {
    // Unknown values leave both cells empty.
    let (files, size) = match stats {
        Some(stats) => (stats.file_count.to_string(), format_size(stats.size_bytes)),
        None => (String::new(), String::new()),
    };
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
                    None,
                ));
            },
            td {
                style: TD_NAME_STYLE,
                div {
                    style: NAME_INNER_STYLE,
                    span { style: ICON_STYLE, {folder_icon()}}
                    span { style: FOLDER_LINK_STYLE, "{name}" }
                }
            }
            td {
                // no container for dir
                style: TD_DETAILS_STYLE,
            }
            td {
                style: TD_SIZE_STYLE,
                title: tr!("file-browser-files-below-this-folder-with"),
                "{files}"
            }
            td {
                style: TD_SIZE_STYLE,
                title: tr!("file-browser-stored-size-of-the-files"),
                "{size}"
            }
            td { style: TD_ACTIONS_STYLE, "" }
        }
    }
}

#[component]
fn folder_icon() -> Element {
    rsx! {
        Icon {
            icon: MdFolder,
            style: "width: 19px; height: 19px;"
        }
    }
}

#[component]
fn container_icon() -> Element {
    rsx! {
        Icon {
            icon: GoFileZip,
            style: "width: 19px; height: 19px;"
        }
    }
}

/// Not a `#[component]`: it is called as a plain function from two row renderers, the way
/// `container_icon` and `folder_icon` beside it are.
fn file_icon(file_type: String) -> Element {
    rsx! {
        crate::components::file_type_icon::FileTypeGlyphIcon { file_type, size: 19 }
    }
}

#[component]
fn FileRow(
    collection: String,
    file: VfsFileEntry,
    is_selected: bool,
    on_file_click: Callback<DocumentIdentifier>,
    onmounted: Callback<(DocumentIdentifier, Event<MountedData>)>,
    is_container: bool,
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
    let container_path = PathDescriptor {
        container_hash: file.hash.clone(),
        path: "/".to_string(),
    };
    let enter_collection = collection.clone();
    // 0 for a plain file. An unknown container value leaves the cell empty.
    let file_count = file.file_count.map(|count| count.to_string()).unwrap_or_default();
    rsx! {
        tr {
            onmounted: move |_d| onmounted.call((click_doc_id.read().clone(), _d)),
            style: row_style,
            class: row_class,
            onclick: move |_| {
                if is_container {
                    // Enter it, exactly like a directory row: history `push`, so Back
                    // comes out of the container rather than off the page.
                    navigator().push(Route::file_browser_page(
                        enter_collection.clone(),
                        container_path.clone(),
                        None,
                    ));
                } else {
                    on_file_click.call(click_doc_id.read().clone());
                }
            },
            td {
                style: TD_NAME_STYLE,
                div {
                    style: NAME_INNER_STYLE,
                    span {
                        style: ICON_STYLE,
                        if is_container { {container_icon()} } else { {file_icon(file.file_type.clone())} }
                    }
                    span { style: FILE_NAME_STYLE, "{file.name}" }
                }
            }
            td {
                style: TD_DETAILS_STYLE,
                if is_container {
                    ViewDetailsButton {
                        doc_id: click_doc_id,
                        on_file_click,
                    }
                }
            }
            td {
                style: TD_SIZE_STYLE,
                title: if is_container { tr!("file-browser-files-inside-this-archive-or") } else { "" },
                "{file_count}"
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
                        document_identifier: click_doc_id,
                        show_finder: false,
                    }
                }
            }
        }
    }
}

/// The in-row button on a CONTAINER file.
///
/// The row itself now navigates INTO the container. An archive and an email with
/// attachments are folders as far as browsing is concerned, and making the user find a
/// pill to enter one was the odd part of the old design. What the pill used to do
/// (enter the container) is now the row; what the row used to do for a plain file
/// (select it into the preview pane) is now this button, because a container is still a
/// document you may want to look at.
#[component]
fn ViewDetailsButton(
    doc_id: ReadSignal<DocumentIdentifier>,
    on_file_click: Callback<DocumentIdentifier>,
) -> Element {
    rsx! {
        button {
            style: "
                padding: 4px 8px; border: 1px solid rgba(0,0,0,0.4); border-radius: 16px;
                background: white; cursor: pointer; font-size: var(--x-text-sm);
                white-space: nowrap; display: inline-flex; align-items: center;
            ",
            class: ROW_HOVER_CLASS,
            title: tr!("file-browser-show-this-container-in-the"),
            onclick: move |event: Event<MouseData>| {
                // Without this the row's own onclick fires too, and the row now
                // navigates into the container, so the preview would open and be
                // replaced by a folder listing in the same click.
                event.stop_propagation();
                on_file_click.call(doc_id.read().clone());
            },
            {tr!("file-browser-view-details")}
        }
    }
}



// ---------- Folder tree sidebar, in-folder search, Open in Search ----------

static FOLDER_SEARCHES: GlobalSignal<std::collections::BTreeMap<String, String>> = Signal::global(std::collections::BTreeMap::new);

/// `[Search in folder…]` on the left, `Open in Search` on the right.
#[component]
fn FolderToolbar(
    collection: String,
    path: PathDescriptor,
    matches: Signal<Option<Vec<VfsTreeNode>>>,
) -> Element {
    let node_key = make_node_key(&collection, &path.container_hash, &path.path);
    let initial_key = node_key.clone();
    let mut needle = use_signal(move || FOLDER_SEARCHES.peek().get(&initial_key).cloned().unwrap_or_default());
    let remembered_key = node_key.clone();
    use_effect(move || {
        FOLDER_SEARCHES.write().insert(remembered_key.clone(), needle());
    });

    // The Open in Search href needs the folder's term id, which is a round trip. Fetched
    // once per folder rather than per keystroke.
    let term_id = use_resource({
        let collection = collection.clone();
        let node_key = node_key.clone();
        move || {
            let collection = collection.clone();
            let node_key = node_key.clone();
            async move { vfs_node_term_id(collection, node_key).await }
        }
    });

    // Debounced 250 ms. Without it every keystroke is a Manticore query, and the
    // structure index is deliberately uncached.
    use_effect({
        let collection = collection.clone();
        let node_key = node_key.clone();
        move || {
            let pattern = needle.read().clone();
            let collection = collection.clone();
            let node_key = node_key.clone();
            spawn(async move {
                n0_future::time::sleep(std::time::Duration::from_millis(250)).await;
                if *needle.peek() != pattern {
                    return;
                }
                if pattern.trim().is_empty() {
                    matches.set(None);
                    return;
                }
                match vfs_search_in_folder(collection, node_key, pattern, 500).await {
                    Ok(children) => matches.set(Some(children.nodes)),
                    Err(error) => {
                        dioxus::logger::tracing::warn!("in-folder search failed: {error}");
                        matches.set(Some(Vec::new()));
                    }
                }
            });
        }
    });

    let open_in_search_route = use_memo(move || {
        let mut query = SearchQuery {
            query_string: needle.read().clone(),
            ..Default::default()
        };
        if let Some(Ok(Some(id))) = term_id.read().as_ref() {
            query.facet_filters.insert(
                "file_paths".to_string(),
                std::collections::BTreeSet::from([FacetOriginalValue::Int(*id)]),
            );
        }
        Route::search_page_from_query(query)
    });

    let match_count = use_memo(move || matches.read().as_ref().map(|m| m.len()));

    rsx! {
        div {
            style: "
                display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
                padding: 8px 14px; border-bottom: 1px solid #E5E7EB;
            ",
            div {
                style: "flex: 1 1 260px; min-width: 0;",
                crate::components::search_input::SearchInput {
                    value: needle,
                    placeholder: tr!("file-browser-search-in-folder"),
                    on_change: move |value: String| {
                        needle.set(value);
                        if needle.peek().is_empty() { matches.set(None); }
                    },
                }
            }

            // Keep the folder view available while the corpus search opens in a new tab.
            Link {
                to: open_in_search_route(),
                new_tab: true,
                style: "
                    display: inline-flex; align-items: center; gap: 6px;
                    padding: 5px 12px; border: 1px solid rgba(0,0,0,0.35); border-radius: 100px;
                    text-decoration: none; color: var(--x-ink-strong); font-size: var(--x-text-md); white-space: nowrap;
                ",
                class: ROW_HOVER_CLASS,
                title: tr!("file-browser-search-the-whole-corpus-filtered"),
                Icon { icon: MdOpenInNew, style: "width: 16px; height: 16px;" }
                {tr!("file-browser-open-in-search")}
            }
        }
        if let Some(count) = match_count() {
            div {
                style: "padding: 6px 14px; font-size: var(--x-text-md); color: rgba(0,0,0,0.7); border-bottom: 1px solid #E5E7EB;",
                {tr!("file-browser-matches-in-this-folder-and", count: count)}
            }
        }
    }
}

/// The in-folder search result list. Folders AND files, because "where is that thing"
/// is as often a folder as a file.
#[component]
fn FolderSearchResults(
    collection: String,
    nodes: Vec<VfsTreeNode>,
    on_file_click: Callback<DocumentIdentifier>,
) -> Element {
    if nodes.is_empty() {
        return rsx! { p { padding: "20px", color: "var(--x-ink-muted)", {tr!("file-browser-no-matches-in-this-folder")} } };
    }
    rsx! {
        table {
            style: TABLE_STYLE,
            thead {
                tr {
                    th { style: TH_NAME_STYLE, {tr!("file-browser-name")} }
                    th { style: TH_NAME_STYLE, {tr!("file-browser-path")} }
                    th { style: TH_SIZE_STYLE, {tr!("file-browser-size")} }
                }
            }
            tbody {
                for node in nodes {
                    {
                        let target_collection = collection.clone();
                        let descriptor = node.descriptor();
                        let is_folder = node.kind.is_folder_like();
                        let doc_id = DocumentIdentifier {
                            collection_dataset: collection.clone(),
                            file_hash: node.file_hash.clone(),
                        };
                        let size = if node.file_size_bytes >= 0 {
                            format_size(node.file_size_bytes as u64)
                        } else {
                            String::new()
                        };
                        rsx! {
                            tr {
                                key: "{node.node_key}",
                                style: ROW_CLICKABLE_STYLE,
                                class: ROW_HOVER_CLASS,
                                onclick: move |_| {
                                    if is_folder {
                                        navigator().push(Route::file_browser_page(
                                            target_collection.clone(), descriptor.clone(), None,
                                        ));
                                    } else {
                                        on_file_click.call(doc_id.clone());
                                    }
                                },
                                td {
                                    style: TD_NAME_STYLE,
                                    div {
                                        style: NAME_INNER_STYLE,
                                        span {
                                            style: ICON_STYLE,
                                            if node.kind == VfsNodeKind::Container { {container_icon()} }
                                            else if node.kind == VfsNodeKind::Dir { {folder_icon()} }
                                            // The tree search returns VFS nodes, which carry no
                                            // canonical type, so the generic glyph is what it gets.
                                            else { {file_icon(String::new())} }
                                        }
                                        span { style: FILE_NAME_STYLE, "{node.display_name()}" }
                                    }
                                }
                                td {
                                    style: "padding: 6px 10px; color: var(--x-ink-muted); font-size: var(--x-text-sm); max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                                    title: "{node.path}",
                                    "{node.path}"
                                }
                                td { style: TD_SIZE_STYLE, "{size}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

// ---------- Right-hand preview pane ----------

#[component]
fn PreviewPane(selected_file: ReadSignal<Option<DocumentIdentifier>>) -> Element {
    rsx! {
        DocumentPreviewForSearchRoot {
            query: SearchQuery::default(),
            selected_result_hash: selected_file,
            show_finder: false,
        }
    }
}

// ---------- Server fns ----------

#[server]
async fn list_folder_children(
    collection_dataset: String,
    path: PathDescriptor,
) -> Result<VfsListing, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::vfs::list_folder_children(&user, collection_dataset, path)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_short_trail_is_not_collapsed() {
        for len in 0..=MAX_CRUMBS_SHOWN {
            assert_eq!(elide_crumbs(len), 0, "{len} crumbs fit");
        }
    }

    #[test]
    fn a_long_trail_keeps_the_last_crumbs_and_hides_the_rest() {
        // `deep-stuff` is 42 folders deep; the bar shows the last three and a chip.
        assert_eq!(elide_crumbs(42), 42 - MAX_CRUMBS_SHOWN);
        assert_eq!(elide_crumbs(MAX_CRUMBS_SHOWN + 1), 1);
        // Nothing is lost: hidden + shown is the whole trail.
        for len in [4_usize, 9, 42] {
            let hidden = elide_crumbs(len);
            assert_eq!(hidden + MAX_CRUMBS_SHOWN, len);
        }
    }

    #[test]
    fn entering_a_container_is_one_crumb_not_two() {
        // The chain hands back the container file and then the container's own root, and
        // `descriptor()` maps both to the same place. Keeping both renders two links to
        // one folder and collides the Dioxus keys.
        let inside = PathDescriptor { container_hash: "abc".to_string(), path: "/".to_string() };
        let crumbs = vec![
            ("location-1".to_string(), PathDescriptor { container_hash: String::new(), path: "/location-1".to_string() }, false),
            ("parent.zip".to_string(), inside.clone(), true),
            ("/".to_string(), inside.clone(), false),
            ("inner".to_string(), PathDescriptor { container_hash: "abc".to_string(), path: "/inner".to_string() }, false),
        ];
        let collapsed = collapse_duplicate_crumbs(crumbs);
        let names: Vec<&str> = collapsed.iter().map(|(name, _, _)| name.as_str()).collect();
        assert_eq!(names, ["location-1", "parent.zip", "inner"], "the named one survives");
        assert!(collapsed[1].2, "and it keeps its archive icon");
    }

    #[test]
    fn collapsing_only_removes_adjacent_duplicates() {
        // A trail that legitimately returns to the same descriptor later is not a
        // duplicate hop; only the container pair is, and it is always adjacent.
        let a = PathDescriptor { container_hash: String::new(), path: "/a".to_string() };
        let b = PathDescriptor { container_hash: String::new(), path: "/b".to_string() };
        let crumbs = vec![
            ("a".to_string(), a.clone(), false),
            ("b".to_string(), b.clone(), false),
            ("a again".to_string(), a.clone(), false),
        ];
        assert_eq!(collapse_duplicate_crumbs(crumbs).len(), 3);
    }

    #[test]
    fn path_segments_accumulate_prefixes_and_carry_the_container() {
        let path = PathDescriptor { container_hash: "abc".to_string(), path: "/a/b/c".to_string() };
        let segments = path_segments(&path);
        let names: Vec<&str> = segments.iter().map(|(name, _)| name.as_str()).collect();
        assert_eq!(names, ["a", "b", "c"]);
        assert_eq!(segments[1].1.path, "/a/b");
        assert!(segments.iter().all(|(_, d)| d.container_hash == "abc"));
        assert!(path_segments(&PathDescriptor::root()).is_empty());
    }
}
