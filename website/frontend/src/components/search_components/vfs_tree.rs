//! The VFS tree, shared by the storage sidebar and the filter pane's folder picker.
//!
//! One component, two skins. Both lazily expand one node at a time against the
//! structure index, and both obey the same layout rule:
//!
//! **No horizontal scrolling, ever.** These corpora contain a folder named `A`×200 and
//! trees forty levels deep. A row that lays out at its natural width turns the sidebar
//! into a horizontal scroller and the labels into something you have to drag to read. So
//! every row is `flex; min-width: 0` with a single-line ellipsised label, the full path is
//! always in `title`, and the indent is bounded. See [`indent_style`].
//!
//! **No unbounded row counts, ever, either.** The same corpora contain
//! `many-children/deep-stuff`, a 42-level chain, and `many-children/the-directory`, 334
//! sibling folders. Three independent caps keep the rendered row count bounded, and they
//! are deliberately separate because they answer different questions:
//!
//! * [`CHILDREN_PAGE_SIZE`] caps what is FETCHED per request. Its overflow row asks for
//!   the NEXT page and appends it.
//! * [`MAX_SIBLINGS_EACH_SIDE`] caps what is RENDERED per level, once the level has been
//!   fetched, centred on the node you are on when the level contains it, from the top
//!   otherwise. Its overflow rows are client-side only.
//! * [`MAX_VISIBLE_ANCESTORS`] caps how many levels of the path to the current node are
//!   rendered at all. The middle of a 42-deep chain is scrollbar, not information.
//!
//! Only one of the first two ever shows at a time: while a sibling window is active the
//! fetch row is suppressed, so "34 more…" never sits next to "126 more…" meaning two
//! different things.
//!
//! **The indent counts RUNGS, not depth**, and that is what lets the two rules above pay
//! for each other. A row's `rung` is its position in the ladder actually on screen; its
//! `depth` is its position in the tree. Ancestor elision makes the first much smaller than
//! the second (the deepest folder in a 42-level chain sits on rung 11), so indenting by
//! rung means every row on the path the tree opens for you is indented strictly more than
//! the row it hangs off, at every width the sidebar can be dragged to, in a total the
//! sidebar can afford. Indenting by depth is what forced the old flat cap: it had to stop
//! at four levels or spend the whole pane, and once it stopped, ten nested folders
//! rendered as ten siblings.
//!
//! Three things hold that up together, and dropping any one of them brings the flat list
//! back: [`indent_style`] scales its pane-relative ceiling by the rung so a narrow pane
//! keeps the steps instead of collapsing them; [`expansion_after_refocus`] closes the
//! subtree below the focus so no automatic ladder ever runs past what elision bounds; and
//! [`MAX_INDENT_PX`] is the backstop for a user who opens twenty chevrons by hand, past
//! which the depth badge is what carries the number.

use std::collections::{BTreeMap, BTreeSet};

use common::vfs::{VfsNodeKind, VfsTreeChildren, VfsTreeNode, dataset_root_key};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        go_icons::GoFileZip,
        md_file_icons::{MdFolder, MdFolderOpen},
        md_navigation_icons::{MdChevronRight, MdExpandMore, MdMoreHoriz},
        md_toggle_icons::{MdCheckBox, MdCheckBoxOutlineBlank, MdIndeterminateCheckBox},
    },
};

use crate::api::vfs_api::{vfs_tree_children, vfs_tree_path_to};

/// Children fetched per request. Past this the tree shows a "N more…" row rather than
/// rendering forty thousand siblings and freezing the tab; clicking it fetches the next
/// page at the offset the level has already loaded and APPENDS it.
///
/// Strictly smaller than the server's own page cap, and that is the point: while the two
/// numbers were equal, a client asking for more than one page had its request clamped
/// back to the page it already had, and the row could never resolve.
pub const CHILDREN_PAGE_SIZE: u64 = 500;
/// The mounted-tree cache lifetime in milliseconds.
///
/// A route change reuses child pages during this interval. The next access refreshes a
/// retained page in place, so ingestion changes become visible without removing the
/// ancestor rows that establish the user's location.
pub(crate) const CHILDREN_CACHE_TTL_MS: f64 = 5_000.0;

pub(crate) fn browser_now_ms() -> f64 {
    web_sys::window()
        .and_then(|window| window.performance())
        .map(|performance| performance.now())
        .unwrap_or(0.0)
}

/// One structure-index response, for tests that must not confuse it with a browser request.
#[derive(Clone, PartialEq)]
pub(crate) struct TreeQueryEvent {
    pub kind: &'static str,
    pub from_cache: bool,
    pub datastore_queries: u64,
    pub took_ms: u64,
}

pub(crate) static TREE_QUERY_LOG: GlobalSignal<Vec<TreeQueryEvent>> = Signal::global(Vec::new);

pub(crate) fn record_tree_query(kind: &'static str, from_cache: bool, datastore_queries: u64, took_ms: u64) {
    TREE_QUERY_LOG.write().push(TreeQueryEvent { kind, from_cache, datastore_queries, took_ms });
}

pub(crate) fn tree_query_log_json(events: &[TreeQueryEvent]) -> String {
    let parts: Vec<String> = events
        .iter()
        .map(|event| {
            format!(
                "{{\"kind\":\"{}\",\"from_cache\":{},\"datastore_queries\":{},\"took_ms\":{}}}",
                event.kind, event.from_cache, event.datastore_queries, event.took_ms
            )
        })
        .collect();
    format!("[{}]", parts.join(","))
}

/// Rungs that get the full [`INDENT_PX`] step. Past this the step shrinks to
/// [`DEEP_INDENT_PX`]; it never stops.
///
/// The arithmetic is against the narrowest pane this tree lives in: four rungs at 16 px is
/// 64 px, and with ~40 px of chevron and folder icon and ~56 px of depth badge that is
/// most of a 240 px sidebar already. A tree forty levels deep cannot spend 16 px a level,
/// but stopping the indent outright made ten nested folders render as ten siblings
/// distinguishable only by a badge you have to read, which is the defect this shape
/// replaces.
pub const FULL_STEP_RUNGS: usize = 4;

/// Ancestor rows rendered on the path to the focused node before the middle is elided.
/// `deep-stuff` is 42 levels; all 42 rendered is a scrollbar in which the thing you are
/// looking at is off-screen.
pub const MAX_VISIBLE_ANCESTORS: usize = 8;

/// How many of those always come from the TOP of the chain. The rule is "the
/// dataset/collection root and the last folder always render", and the tail is where you
/// are, but one top row is a single name with no context above the `N more levels…`
/// row, and in a 42-level chain that name is as likely to be `1` as anything else. Two
/// says where the chain STARTED as well as where it goes.
pub const ANCESTORS_SHOWN_AT_TOP: usize = 2;

/// Siblings rendered either side of the focused node in one level.
pub const MAX_SIBLINGS_EACH_SIDE: usize = 10;

/// Pixels of indent per rung, for the first [`FULL_STEP_RUNGS`] of them.
const INDENT_PX: usize = 16;

/// Pixels of indent per rung past [`FULL_STEP_RUNGS`].
///
/// Small, but not as small as it looks: the app lays out at a 1920 px design width and
/// `zoom`s to the window (`assets/main.css`), so at a 1280 px window this is 5 device
/// pixels. 4 px would be 2.5, which is not a step anyone can see, and an indent nobody can
/// see is the flat cap again under another name.
const DEEP_INDENT_PX: usize = 8;

/// The indent may never grow past this, however many rungs there are.
///
/// Ancestor elision bounds the rungs on the path to the focused node, but a user
/// disclosing rows by chevron alone is not on any focus path and can nest as far as the
/// corpus goes. This is the backstop for that, and past it the depth badge is the only
/// thing still carrying the number.
const MAX_INDENT_PX: usize = 160;

/// The share of the pane the indent may take before it stops growing.
///
/// The pixel ceiling above is chosen against a comfortable pane; this one holds when the
/// pane is not, and it is the only guard that follows the user dragging the sidebar
/// narrower. Expressed as a CSS `min()` so the browser re-evaluates it on every resize
/// rather than the tree re-rendering to keep up.
const MAX_INDENT_PERCENT: usize = 40;

pub(crate) const ROW_STYLE: &str = "
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
    width: 100%;
    padding: 3px 6px;
    border-radius: 6px;
    cursor: pointer;
    box-sizing: border-box;
";

/// The label. Single line, shrinks rather than wraps or scrolls. See the module docs.
pub(crate) const LABEL_STYLE: &str = "
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 15px;
    line-height: 22px;
";

/// The shared look of every "there is more here" row: the elision rows and the fetch row.
pub(crate) const MORE_ROW_STYLE: &str = "
    border: none; background: none; color: rgba(0,0,0,0.6); font-size: 14px;
    text-align: left;
";

/// Which skin the tree is wearing.
#[derive(Clone, Copy, PartialEq)]
pub enum TreeSkin {
    /// Storage page: clicking a row navigates into it. No checkboxes.
    Sidebar,
    /// Filter pane: clicking a row selects it. Checkboxes, no navigation.
    Picker,
}

#[derive(Clone)]
pub struct TreeContext {
    pub skin: TreeSkin,
    pub collection_dataset: String,
    /// Rows rendered above this tree by whoever mounted it, the collection and dataset
    /// rows of the unified storage tree. It seeds the root level's rung and it is what the
    /// depth badge adds, so the number a row states is its depth in the tree on screen
    /// rather than in the dataset's own.
    ///
    /// Deliberately NOT added to `depth`, which is an index into the focus chain: ancestor
    /// elision and sibling capping are defined in terms of the dataset's own tree and must
    /// not shift because of what is above it.
    pub indent_offset: usize,
    /// Selected node keys. The `Picker` filter. Unused by `Sidebar`, which highlights
    /// [`TreeContext::focus_key`] instead, one node, always the one the URL names.
    pub selected: Signal<BTreeSet<String>>,
    pub on_activate: Callback<VfsTreeNode>,
    /// The node the tree is centred on, or empty.
    pub focus_key: ReadSignal<String>,
    /// Node keys from the dataset root down to the focused node, root first. Empty when
    /// nothing is focused, in which case neither elision nor sibling capping applies.
    /// They are both defined relative to "the node you are on".
    pub focus_chain: Signal<Vec<String>>,
    /// Parent keys whose elision gap or sibling window the user has clicked open.
    pub unfolded: Signal<BTreeSet<String>>,
    /// Child pages retained for this mounted dataset tree, keyed by parent and offset.
    child_pages: Signal<BTreeMap<(String, u64), CachedChildren>>,
    /// Next children offset the level is asking for. Zero until the user pages.
    page_offsets: Signal<BTreeMap<String, u64>>,
    /// Fetch errors keyed by parent, so a failed page stays a row rather than a blank.
    fetch_errors: Signal<BTreeMap<String, String>>,
}

/// The tree rooted at one dataset.
#[component]
pub fn VfsTree(
    collection_dataset: String,
    skin: TreeSkin,
    selected: Signal<BTreeSet<String>>,
    on_activate: Callback<VfsTreeNode>,
    /// Expanded from the start, e.g. the chain down to the current folder.
    initially_expanded: Vec<String>,
    /// The node the tree should reveal and centre its caps on, the folder the storage
    /// page is showing. Empty in the picker, where there is no single "here".
    ///
    /// A SIGNAL, not a `String`. Component props are not reactive in Dioxus: a
    /// `use_resource` captures its closure once, and a changed prop does not re-run it.
    /// Reading a signal inside the closure is what subscribes it. Passing the plain value
    /// left the tree showing the folder you navigated AWAY from, on every in-app
    /// navigation, while a fresh page load looked perfect.
    focus_key: ReadSignal<String>,
    /// See [`TreeContext::indent_offset`]. Zero when this tree is the whole tree.
    indent_offset: usize,
) -> Element {
    let root_key = dataset_root_key(&collection_dataset);
    let focus_chain = use_signal(Vec::<String>::new);
    let unfolded = use_signal(BTreeSet::<String>::new);
    let child_pages = use_signal(BTreeMap::<(String, u64), CachedChildren>::new);
    let page_offsets = use_signal(BTreeMap::<String, u64>::new);
    let fetch_errors = use_signal(BTreeMap::<String, String>::new);
    use_context_provider({
        let collection_dataset = collection_dataset.clone();
        move || TreeContext {
            skin,
            collection_dataset: collection_dataset.clone(),
            indent_offset,
            selected,
            on_activate,
            focus_key,
            focus_chain,
            unfolded,
            child_pages,
            page_offsets,
            fetch_errors,
        }
    });
    let expanded = use_signal(|| initially_expanded.iter().cloned().collect::<BTreeSet<String>>());
    use_context_provider(|| expanded);

    let shared_path = use_hook(try_consume_context::<crate::api::vfs_api::ResolvedVfsPath>);
    let mut cached_paths = use_signal(BTreeMap::<String, (f64, Vec<VfsTreeNode>)>::new);
    let chain = use_resource({
        let collection_dataset = collection_dataset.clone();
        move || {
            let collection_dataset = collection_dataset.clone();
            // Read OUTSIDE the async block: that read is the subscription.
            let key = focus_key();
            let cached = cached_paths.peek().get(&key).cloned();
            let shared = shared_path
                .filter(|shared| (shared.dataset)() == collection_dataset)
                .map(|shared| shared.chain.read().clone());
            async move {
                if let Some(shared) = shared {
                    return shared.unwrap_or(Ok(None));
                }
                if key.is_empty() {
                    return Ok::<_, ServerFnError>(None);
                }
                if let Some((fetched_at, nodes)) = cached
                    && browser_now_ms() - fetched_at < CHILDREN_CACHE_TTL_MS
                {
                    record_tree_query("path", true, 0, 0);
                    return Ok(Some((key, nodes)));
                }
                let nodes = vfs_tree_path_to(collection_dataset, key.clone()).await?;
                record_tree_query("path", false, nodes.datastore_queries, nodes.took_ms);
                cached_paths.write().insert(key.clone(), (browser_now_ms(), nodes.nodes.clone()));
                Ok(Some((key, nodes.nodes)))
            }
        }
    });

    let mut chain_signal = focus_chain;
    let mut expanded_signal = expanded;
    use_effect(move || {
        let Some(Ok(Some((key, nodes)))) = chain.read().clone() else {
            return;
        };
        if key != *focus_key.peek() {
            return;
        }
        let keys: Vec<String> = nodes.iter().map(|node| node.node_key.clone()).collect();
        // Open the path to the focus and close everything under it. See
        // [`expansion_after_refocus`]. Written only when it changes: this effect re-runs
        // on every chain read, and an unconditional `write()` on a signal the tree
        // renders from is a re-render per run.
        let next = expansion_after_refocus(&expanded_signal.peek(), &keys);
        if *expanded_signal.peek() != next {
            expanded_signal.set(next);
        }
        if *chain_signal.peek() != keys {
            chain_signal.set(keys);
        }
    });

    let pages_now = child_pages();
    let expanded_now = expanded();
    let unfolded_now = unfolded();
    let chain_now = focus_chain();
    let errors_now = fetch_errors();
    let items = visible_items(
        &root_key,
        indent_offset,
        &chain_now,
        &unfolded_now,
        &expanded_now,
        &pages_now,
        &errors_now,
    );
    let fetches = needed_parents(
        &root_key,
        &chain_now,
        &unfolded_now,
        &expanded_now,
        &pages_now,
    );

    rsx! {
        div {
            // The container scrolls VERTICALLY only. `overflow-x: hidden` is the second
            // half of the no-horizontal-scrolling rule: without it a row that somehow
            // overflows makes the whole panel scrollable sideways.
            style: "width: 100%; min-width: 0; overflow-x: hidden; overflow-y: auto;",
            if let Some(Err(error)) = chain.read().as_ref() {
                div { class: "x-error-display", "Could not load the folder path: {error}" }
            }
            // Fetch components emit no row. They sit in a separate parent so a change
            // in the fetch list cannot replace keyed folder rows.
            div {
                key: "fetches",
                style: "display: none;",
                for parent in fetches {
                    VfsTreeLevelFetch { key: "fetch-{parent}", parent_key: parent.clone() }
                }
            }
            // Dioxus diffs a sibling list by position when the first sibling has no
            // key. These rows must be the only children of this parent, or a resume
            // shift recreates every folder after the elision slot.
            div {
                key: "visible-rows",
                style: "min-width: 0; width: 100%;",
                for item in items {
                    VisibleTreeRow { key: "{item.row_key()}", item: item.clone() }
                }
            }
        }
    }
}

/// Everything one level has fetched so far, and what the server says is there in total.
///
/// Keyed by `parent_key` so a page that arrives for a folder the tree is no longer
/// showing is discarded rather than appended to the visible sequence.
#[derive(Clone, PartialEq, Default)]
struct LoadedChildren {
    parent_key: String,
    nodes: Vec<VfsTreeNode>,
    /// Folder-like children this node has, as the server counts them. `nodes.len()` is
    /// how many of those are loaded; the difference is what the "N more…" row states.
    total: u64,
}

/// One retained VFS response. The key that owns it includes the page offset.
#[derive(Clone, PartialEq)]
struct CachedChildren {
    nodes: Vec<VfsTreeNode>,
    total: u64,
    fetched_at_ms: f64,
}

/// A child page together with the time its server response was received.
#[derive(Clone)]
struct ChildPageResult {
    page: VfsTreeChildren,
    fetched_at_ms: f64,
    from_cache: bool,
    offset: u64,
}

/// Restore every cached page that starts at the next unloaded offset.
fn loaded_pages_for_parent(
    pages: &BTreeMap<(String, u64), CachedChildren>,
    parent_key: &str,
) -> LoadedChildren {
    let mut result = LoadedChildren { parent_key: parent_key.to_string(), ..Default::default() };
    loop {
        let offset = result.nodes.len() as u64;
        let Some(page) = pages.get(&(parent_key.to_string(), offset)) else {
            break;
        };
        if page.nodes.is_empty() {
            result.total = page.total;
            break;
        }
        let previous_offset = offset;
        result.nodes.extend(page.nodes.clone());
        result.total = page.total;
        if result.nodes.len() as u64 == previous_offset {
            break;
        }
    }
    result
}


/// One visible row in the shared keyed sequence.
///
/// Folder rows use the node key. Elision and overflow rows use a synthetic key that
/// cannot collide with a node key, because node keys contain a unit separator.
#[derive(Clone, PartialEq, Debug)]
enum VisibleItem {
    Folder { node: VfsTreeNode, depth: usize, rung: usize, is_expanded: bool },
    Elision { parent_key: String, hidden: usize, rung: usize },
    MoreSiblings { parent_key: String, hidden: usize, rung: usize, above: bool, fetched: usize },
    FetchMore { parent_key: String, more: u64, total: u64, rung: usize, loaded: u64 },
    Loading { parent_key: String, rung: usize },
    Error { parent_key: String, message: String, rung: usize },
    EmptyRoot,
}

impl VisibleItem {
    fn row_key(&self) -> String {
        match self {
            Self::Folder { node, .. } => node.node_key.clone(),
            Self::Elision { .. } => "elision".to_string(),
            Self::MoreSiblings { parent_key, above, .. } => {
                format!("more-{}:{parent_key}", if *above { "before" } else { "after" })
            }
            Self::FetchMore { parent_key, .. } => format!("fetch:{parent_key}"),
            Self::Loading { parent_key, .. } => format!("loading:{parent_key}"),
            Self::Error { parent_key, .. } => format!("error:{parent_key}"),
            Self::EmptyRoot => "empty-root".to_string(),
        }
    }
}

fn visible_items(
    root_key: &str,
    indent_offset: usize,
    focus_chain: &[String],
    unfolded: &BTreeSet<String>,
    expanded: &BTreeSet<String>,
    pages: &BTreeMap<(String, u64), CachedChildren>,
    errors: &BTreeMap<String, String>,
) -> Vec<VisibleItem> {
    let mut items = Vec::new();
    walk_visible(
        root_key,
        0,
        indent_offset,
        focus_chain,
        unfolded,
        expanded,
        pages,
        errors,
        &mut items,
    );
    items
}

fn walk_visible(
    parent_key: &str,
    depth: usize,
    rung: usize,
    focus_chain: &[String],
    unfolded: &BTreeSet<String>,
    expanded: &BTreeSet<String>,
    pages: &BTreeMap<(String, u64), CachedChildren>,
    errors: &BTreeMap<String, String>,
    items: &mut Vec<VisibleItem>,
) {
    if focus_chain.get(depth).is_some_and(|key| *key == parent_key) {
        let elision = elide_ancestors(focus_chain.len().saturating_sub(1));
        if let Some(elision) = elision
            && elision.head == depth
            && !unfolded.contains(parent_key)
        {
            items.push(VisibleItem::Elision {
                parent_key: parent_key.to_string(),
                hidden: elision.hidden,
                rung,
            });
            if let Some(resume) = focus_chain.get(elision.resume_depth) {
                let resume_cached = pages.keys().any(|(parent, _)| parent == resume);
                if resume_cached {
                    walk_visible(
                        resume,
                        elision.resume_depth,
                        rung + 1,
                        focus_chain,
                        unfolded,
                        expanded,
                        pages,
                        errors,
                        items,
                    );
                } else if let Some((cached_depth, cached_key)) = (elision.resume_depth..focus_chain.len()).find_map(|depth| {
                    let key = focus_chain.get(depth)?;
                    pages.keys().any(|(parent, _)| parent == key).then_some((depth, key.clone()))
                }) {
                    // The new resume parent is still loading. Keep already-cached
                    // tail folders mounted instead of replacing them with a loading row.
                    walk_visible(
                        &cached_key,
                        cached_depth,
                        rung + 1,
                        focus_chain,
                        unfolded,
                        expanded,
                        pages,
                        errors,
                        items,
                    );
                } else {
                    items.push(VisibleItem::Loading {
                        parent_key: resume.clone(),
                        rung: rung + 1,
                    });
                }
            }
            return;
        }
    }

    if let Some(message) = errors.get(parent_key) {
        items.push(VisibleItem::Error {
            parent_key: parent_key.to_string(),
            message: message.clone(),
            rung,
        });
        return;
    }

    let listing = loaded_pages_for_parent(pages, parent_key);
    let has_page = pages.keys().any(|(parent, _)| parent == parent_key);
    if !has_page {
        items.push(VisibleItem::Loading { parent_key: parent_key.to_string(), rung });
        return;
    }
    if listing.nodes.is_empty() && depth == 0 {
        items.push(VisibleItem::EmptyRoot);
        return;
    }

    let on_path = focus_chain.get(depth).is_some_and(|key| *key == parent_key);
    let focus_child = if on_path { focus_chain.get(depth + 1).cloned() } else { None };
    let focus_index = focus_child
        .as_ref()
        .and_then(|key| listing.nodes.iter().position(|node| node.node_key == *key));
    let window = if unfolded.contains(parent_key) {
        SiblingWindow::everything(listing.nodes.len())
    } else {
        window_siblings(listing.nodes.len(), focus_index)
    };
    let fetched = listing.nodes.len() as u64;
    let more = if window.is_capping() { 0 } else { listing.total.saturating_sub(fetched) };

    if window.hidden_before > 0 {
        items.push(VisibleItem::MoreSiblings {
            parent_key: parent_key.to_string(),
            hidden: window.hidden_before,
            rung,
            above: true,
            fetched: listing.nodes.len(),
        });
    }
    for node in &listing.nodes[window.start..window.end] {
        let is_expanded = expanded.contains(&node.node_key);
        items.push(VisibleItem::Folder {
            node: node.clone(),
            depth,
            rung,
            is_expanded,
        });
        if is_expanded {
            walk_visible(
                &node.node_key,
                depth + 1,
                rung + 1,
                focus_chain,
                unfolded,
                expanded,
                pages,
                errors,
                items,
            );
        }
    }
    if window.hidden_after > 0 {
        items.push(VisibleItem::MoreSiblings {
            parent_key: parent_key.to_string(),
            hidden: window.hidden_after,
            rung,
            above: false,
            fetched: listing.nodes.len(),
        });
    }
    if more > 0 {
        items.push(VisibleItem::FetchMore {
            parent_key: parent_key.to_string(),
            more,
            total: listing.total,
            rung,
            loaded: fetched,
        });
    }
}

fn needed_parents(
    root_key: &str,
    focus_chain: &[String],
    unfolded: &BTreeSet<String>,
    expanded: &BTreeSet<String>,
    pages: &BTreeMap<(String, u64), CachedChildren>,
) -> Vec<String> {
    let mut out = Vec::new();
    collect_needed(root_key, 0, focus_chain, unfolded, expanded, pages, &mut out);
    out
}

fn collect_needed(
    parent_key: &str,
    depth: usize,
    focus_chain: &[String],
    unfolded: &BTreeSet<String>,
    expanded: &BTreeSet<String>,
    pages: &BTreeMap<(String, u64), CachedChildren>,
    out: &mut Vec<String>,
) {
    if focus_chain.get(depth).is_some_and(|key| *key == parent_key) {
        let elision = elide_ancestors(focus_chain.len().saturating_sub(1));
        if let Some(elision) = elision
            && elision.head == depth
            && !unfolded.contains(parent_key)
        {
            if let Some(resume) = focus_chain.get(elision.resume_depth) {
                collect_needed(resume, elision.resume_depth, focus_chain, unfolded, expanded, pages, out);
            }
            // The next shallower resume parent sits in the elision gap. Fetch it
            // so a parent click does not replace the visible tail with a loading row.
            if elision.resume_depth > elision.head + 1
                && let Some(next_up) = focus_chain.get(elision.resume_depth - 1)
                && !out.iter().any(|key| key == next_up)
            {
                out.push(next_up.clone());
            }
            return;
        }
    }
    if out.iter().any(|key| key == parent_key) {
        return;
    }
    out.push(parent_key.to_string());
    let listing = loaded_pages_for_parent(pages, parent_key);
    if listing.nodes.is_empty() && !pages.keys().any(|(parent, _)| parent == parent_key) {
        return;
    }
    let on_path = focus_chain.get(depth).is_some_and(|key| *key == parent_key);
    let focus_child = if on_path { focus_chain.get(depth + 1).cloned() } else { None };
    let focus_index = focus_child
        .as_ref()
        .and_then(|key| listing.nodes.iter().position(|node| node.node_key == *key));
    let window = if unfolded.contains(parent_key) {
        SiblingWindow::everything(listing.nodes.len())
    } else {
        window_siblings(listing.nodes.len(), focus_index)
    };
    for node in &listing.nodes[window.start..window.end] {
        if expanded.contains(&node.node_key) {
            collect_needed(&node.node_key, depth + 1, focus_chain, unfolded, expanded, pages, out);
        }
    }
}

/// Fetch one parent's current page into the shared cache. Renders nothing.
#[component]
fn VfsTreeLevelFetch(parent_key: String) -> Element {
    let context = use_context::<TreeContext>();
    let parent = use_memo(use_reactive!(|parent_key| parent_key));
    let children = use_resource({
        let dataset = context.collection_dataset.clone();
        let child_pages = context.child_pages;
        let page_offsets = context.page_offsets;
        move || {
            let dataset = dataset.clone();
            let parent = parent();
            let offset = page_offsets.read().get(&parent).copied().unwrap_or(0);
            let _focus = (context.focus_key)();
            let cached = child_pages.peek().get(&(parent.clone(), offset)).cloned();
            async move {
                if let Some(cached) = cached
                    && browser_now_ms() - cached.fetched_at_ms < CHILDREN_CACHE_TTL_MS
                {
                    record_tree_query("children", true, 0, 0);
                    return Ok(ChildPageResult {
                        page: VfsTreeChildren {
                            parent_key: parent,
                            nodes: cached.nodes,
                            total: cached.total,
                            datastore_queries: 0,
                            took_ms: 0,
                        },
                        fetched_at_ms: cached.fetched_at_ms,
                        from_cache: true,
                        offset,
                    });
                }
                vfs_tree_children(dataset, parent, CHILDREN_PAGE_SIZE, offset, true)
                    .await
                    .map(|page| {
                        record_tree_query("children", false, page.datastore_queries, page.took_ms);
                        ChildPageResult {
                            page,
                            fetched_at_ms: browser_now_ms(),
                            from_cache: false,
                            offset,
                        }
                    })
            }
        }
    });

    let mut child_pages_signal = context.child_pages;
    let mut fetch_errors = context.fetch_errors;
    use_effect(move || {
        match children.read().clone() {
            Some(Ok(result)) => {
                let page = result.page.clone();
                let asked_parent = parent();
                let asked_offset = context.page_offsets.peek().get(&asked_parent).copied().unwrap_or(0);
                if page.parent_key != asked_parent || result.offset != asked_offset {
                    return;
                }
                let mut pages = child_pages_signal.write();
                if asked_offset == 0 && !result.from_cache {
                    pages.retain(|(parent, offset), _| parent != &asked_parent || *offset == 0);
                }
                pages.insert(
                    (asked_parent.clone(), asked_offset),
                    CachedChildren {
                        nodes: page.nodes,
                        total: page.total,
                        fetched_at_ms: result.fetched_at_ms,
                    },
                );
                fetch_errors.write().remove(&asked_parent);
            }
            Some(Err(error)) => {
                fetch_errors.write().insert(parent(), error.to_string());
            }
            None => {}
        }
    });

    rsx! {}
}

#[component]
fn VisibleTreeRow(item: VisibleItem) -> Element {
    let context = use_context::<TreeContext>();
    let mut unfolded_set = context.unfolded;
    let mut page_offsets = context.page_offsets;
    match item {
        VisibleItem::Folder { node, depth, rung, is_expanded } => rsx! {
            VfsTreeRow { node, depth, rung, is_expanded }
        },
        VisibleItem::Elision { parent_key, hidden, rung } => {
            let gap_indent = indent_style(rung);
            let unfold_key = parent_key.clone();
            rsx! {
                button {
                    style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {gap_indent};",
                    class: "x-facet-list-item",
                    title: "Show the {hidden} folder levels between here and the one you are in",
                    onclick: move |_| { unfolded_set.write().insert(unfold_key.clone()); },
                    Icon { icon: MdMoreHoriz, style: "width: 18px; height: 18px; flex-shrink: 0;" }
                    div { style: "{LABEL_STYLE}", "{hidden} more levels…" }
                }
            }
        }
        VisibleItem::MoreSiblings { parent_key, hidden, rung, above, fetched } => {
            let more_indent = indent_style(rung);
            let unfold_key = parent_key.clone();
            let direction = if above { "above" } else { "below" };
            rsx! {
                button {
                    style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {more_indent};",
                    class: "x-facet-list-item",
                    title: "Show all {fetched} folders here",
                    onclick: move |_| { unfolded_set.write().insert(unfold_key.clone()); },
                    Icon { icon: MdMoreHoriz, style: "width: 18px; height: 18px; flex-shrink: 0;" }
                    div { style: "{LABEL_STYLE}", "{hidden} more {direction}…" }
                }
            }
        }
        VisibleItem::FetchMore { parent_key, more, total, rung, loaded } => {
            let more_indent = indent_style(rung);
            rsx! {
                button {
                    style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {more_indent};",
                    class: "x-facet-list-item",
                    title: "Load the next {CHILDREN_PAGE_SIZE.min(more)} of the {total} folders here",
                    onclick: move |_| {
                        page_offsets.write().insert(parent_key.clone(), loaded);
                    },
                    "{more} more…"
                }
            }
        }
        VisibleItem::Loading { rung, .. } => {
            let pad = indent_style(rung);
            rsx! {
                div {
                    style: "padding: 4px 8px; padding-left: {pad}; font-size: 14px; color: rgba(0,0,0,0.5);",
                    "Loading…"
                }
            }
        }
        VisibleItem::Error { message, rung, .. } => {
            let pad = indent_style(rung);
            rsx! {
                div {
                    class: "x-error-display",
                    style: "padding: 4px 8px; padding-left: {pad}; font-size: 14px; color: rgb(160,30,30);",
                    "Could not load this folder: {message}"
                }
            }
        }
        VisibleItem::EmptyRoot => rsx! {
            div {
                style: "padding: 6px 8px; font-size: 14px; color: rgba(0,0,0,0.5);",
                "No folders in this dataset."
            }
        },
    }
}

/// Indent in pixels for a row on ladder rung `rung`. See the module docs for `rung`.
///
/// Full steps for the first few rungs, a reduced step for every rung after them, and a
/// ceiling. The reduced step is the point: a ladder that keeps stepping stays a ladder,
/// and the alternative (an indent that stops) turns a chain into a list.
pub(crate) fn indent_px(rung: usize) -> usize {
    let full = rung.min(FULL_STEP_RUNGS) * INDENT_PX;
    let deep = rung.saturating_sub(FULL_STEP_RUNGS).saturating_mul(DEEP_INDENT_PX);
    full.saturating_add(deep).min(MAX_INDENT_PX)
}

/// The share of [`MAX_INDENT_PX`] that rung `rung` has reached, in `0.0..=1.0`.
///
/// This is what makes the pane-relative ceiling keep its steps. A flat
/// `min(Npx, {MAX_INDENT_PERCENT}%)` collapses every rung whose pixel indent is past the
/// percentage into one value, so at the narrowest pane the drag offers, four to five
/// consecutive levels render at pixel-identical indent, which is the flattening the rung
/// ladder exists to prevent, reachable by dragging the sidebar to its floor. Scaling the
/// percentage by the rung's own share instead means the narrow-pane branch is a
/// proportional copy of the wide-pane one: it is bounded by the same
/// [`MAX_INDENT_PERCENT`] of the pane, and it still steps at every rung the pixel ladder
/// steps at.
fn indent_fraction(rung: usize) -> f64 {
    indent_px(rung) as f64 / MAX_INDENT_PX as f64
}

/// The `padding-left` value for a row on rung `rung`.
///
/// Two ceilings, because they guard different things: [`indent_px`] is what the layout was
/// designed against, and [`MAX_INDENT_PERCENT`] is what keeps a row readable in a pane the
/// user has dragged narrow. The percentage resolves against the pane, so it tracks the
/// drag with no re-render. Both are scaled by the rung's [`indent_fraction`], so whichever
/// binds, the ladder still steps.
pub(crate) fn indent_style(rung: usize) -> String {
    format!(
        "min({}px, calc({MAX_INDENT_PERCENT}% * {:.4}))",
        indent_px(rung),
        indent_fraction(rung)
    )
}

/// What [`indent_style`] resolves to, in pixels, in a tree `container_px` wide.
///
/// The CSS is what the browser evaluates; this is the same arithmetic written twice on
/// purpose, so the ladder's one required property (a step at every width) is a test
/// rather than a measurement taken by hand at three widths. It has to move whenever the
/// format string above does.
#[cfg(test)]
pub(crate) fn indent_resolved_px(rung: usize, container_px: f64) -> f64 {
    let percentage = container_px * MAX_INDENT_PERCENT as f64 / 100.0 * indent_fraction(rung);
    (indent_px(rung) as f64).min(percentage)
}

/// Where the middle of a deep ancestor chain is replaced by one row.
///
/// `head` is the depth of the level that renders the gap; `resume_depth` is the depth the
/// tree picks up again at. Both are indices into the chain returned by `vfs_tree_path_to`,
/// where `chain[d]` is the parent of the rows rendered by the level at depth `d`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AncestorElision {
    pub head: usize,
    pub hidden: usize,
    pub resume_depth: usize,
}

/// Elide the middle of the ancestor chain, or `None` when it is short enough to render.
///
/// `chain_rows` is the number of ancestor ROWS, one less than the chain length, because
/// the dataset root is the tree container rather than a row in it.
pub fn elide_ancestors(chain_rows: usize) -> Option<AncestorElision> {
    if chain_rows <= MAX_VISIBLE_ANCESTORS {
        return None;
    }
    let head = ANCESTORS_SHOWN_AT_TOP;
    let tail = MAX_VISIBLE_ANCESTORS - head;
    let resume_depth = chain_rows - tail;
    Some(AncestorElision { head, hidden: resume_depth - head, resume_depth })
}

/// The slice of one level's siblings that renders, and how many are hidden either side.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SiblingWindow {
    pub start: usize,
    pub end: usize,
    pub hidden_before: usize,
    pub hidden_after: usize,
}

impl SiblingWindow {
    /// The whole level, nothing hidden.
    pub fn everything(len: usize) -> Self {
        SiblingWindow { start: 0, end: len, hidden_before: 0, hidden_after: 0 }
    }

    pub fn is_capping(&self) -> bool {
        self.hidden_before > 0 || self.hidden_after > 0
    }
}

/// Render at most `2 * MAX_SIBLINGS_EACH_SIDE + 1` of a level's siblings.
///
/// Centred on the focused child when the level has one. When it does not, the window
/// still applies, from the top. The level below the folder you are in is exactly the
/// 334-row case, and "there is no centre" is not a reason to render eight screens of
/// folders into a 240 px sidebar. Nothing is lost either way: the overflow rows say how
/// many are hidden and reveal them on click.
pub fn window_siblings(len: usize, focus_index: Option<usize>) -> SiblingWindow {
    let span = 2 * MAX_SIBLINGS_EACH_SIDE + 1;
    if len <= span {
        return SiblingWindow::everything(len);
    }
    let (start, end) = match focus_index {
        Some(focus) => (
            focus.saturating_sub(MAX_SIBLINGS_EACH_SIDE),
            len.min(focus + MAX_SIBLINGS_EACH_SIDE + 1),
        ),
        None => (0, span),
    };
    SiblingWindow { start, end, hidden_before: start, hidden_after: len - end }
}

#[component]
fn VfsTreeRow(node: VfsTreeNode, depth: usize, rung: usize, is_expanded: bool) -> Element {
    let context = use_context::<TreeContext>();
    let mut expanded = use_context::<Signal<BTreeSet<String>>>();
    let node_key = node.node_key.clone();
    let check_state = tri_state(&node_key, &context.selected.read());
    // The sidebar highlights the one folder the URL names; the picker highlights what is
    // ticked. Two different questions, deliberately not sharing a signal, the sidebar's
    // answer changes on every navigation and the picker's does not.
    let is_selected = match context.skin {
        TreeSkin::Sidebar => *context.focus_key.read() == node_key,
        TreeSkin::Picker => check_state == TriState::Checked,
    };
    // Two different numbers on purpose: the ladder position the row is drawn at, and the
    // depth in the tree it actually has. Elision is what pulls them apart.
    let tree_depth = depth + context.indent_offset;
    let indent = indent_style(rung);
    let row_background = if is_selected { "rgba(243,140,104,0.16)" } else { "transparent" };
    let label = if node.name.is_empty() {
        node.path.clone()
    } else {
        node.name.clone()
    };

    let toggle_key = node_key.clone();
    let toggle = move |event: Event<MouseData>| {
        event.stop_propagation();
        let mut set = expanded.write();
        if set.contains(&toggle_key) {
            set.remove(&toggle_key);
        } else {
            set.insert(toggle_key.clone());
        }
    };

    let mut selected = context.selected;
    let select_key = node_key.clone();
    let activate_node = node.clone();
    let on_activate = context.on_activate;
    let skin = context.skin;

    rsx! {
        div {
            style: "{ROW_STYLE} padding-left: {indent}; background: {row_background};",
            class: "x-facet-list-item",
            "data-node-key": "{node_key}",
            "aria-current": if is_selected { "location" } else { "false" },
            // The full path, always. It is the only place a truncated label can be read
            // in full, and truncation is the normal case here rather than the exception.
            title: "{node.path}",
            onclick: move |_| {
                if skin == TreeSkin::Picker {
                    toggle_selection(&select_key, &mut selected.write());
                }
                on_activate.call(activate_node.clone());
            },

            // Disclosure. Always present, even for a leaf, so the labels of siblings
            // line up rather than jittering by 18 px.
            button {
                style: "border: none; background: none; cursor: pointer; padding: 0; display: flex; align-items: center; flex-shrink: 0;",
                "aria-expanded": if is_expanded { "true" } else { "false" },
                onclick: toggle,
                if is_expanded {
                    Icon { icon: MdExpandMore, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.6);" }
                } else {
                    Icon { icon: MdChevronRight, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.6);" }
                }
            }

            if skin == TreeSkin::Picker {
                div {
                    style: "display: flex; align-items: center; flex-shrink: 0;",
                    {tri_state_icon(check_state)}
                }
            }

            div {
                style: "display: flex; align-items: center; flex-shrink: 0;",
                if node.kind == VfsNodeKind::Container {
                    Icon { icon: GoFileZip, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.7);" }
                } else if is_expanded {
                    Icon { icon: MdFolderOpen, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.7);" }
                } else {
                    Icon { icon: MdFolder, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.7);" }
                }
            }

            div { style: "{LABEL_STYLE}", "{label}" }

            // Past the full-step rungs the indent still steps but no longer counts, and
            // once ancestors are elided the ladder is shorter than the path anyway, so
            // the depth is stated. Above the shallow rows it is absent rather than
            // always-on noise. The number is the row's depth in the tree on screen, which
            // starts at the collection, so it counts the synthetic levels too.
            if tree_depth > FULL_STEP_RUNGS {
                div {
                    style: "flex-shrink: 0; font-size: 11px; color: rgba(0,0,0,0.45); border: 1px solid rgba(0,0,0,0.2); border-radius: 8px; padding: 0 5px;",
                    "depth {tree_depth}"
                }
            }
        }
    }
}

/// Tri-state for a node given the selection set alone.
///
/// From the SELECTION, never from the loaded children: the tree is lazy, so "are all my
/// descendants selected" is a question about nodes that may not be loaded, and answering
/// it from what happens to be in memory makes the checkbox flicker as the user scrolls.
pub fn tri_state(node_key: &str, selected: &BTreeSet<String>) -> TriState {
    if selected.contains(node_key) {
        return TriState::Checked;
    }
    // A descendant is selected iff some selected key is under this node's path. Node
    // keys share a prefix exactly when one node is under the other, which is a property
    // of the key format, not a coincidence.
    let prefix = descendant_prefix(node_key);
    if selected.iter().any(|key| key.starts_with(&prefix)) {
        TriState::Partial
    } else {
        TriState::Unchecked
    }
}

/// The expansion set the tree holds once it has refocused on the end of `chain`.
///
/// Two rules, and the second is the one that is commonly missed. Every ancestor of the
/// focused node is expanded, including the ones elision will hide, so unfolding the gap
/// reveals an already-open path rather than a column of collapsed rows. And every strict
/// DESCENDANT of the focused node is collapsed, because the chain you walked down is not
/// the chain you are on any more.
///
/// Leaving descendants expanded is what turned navigating *up* into a flat list: elision
/// only shortens the ladder on the path to the focus, so rows below it keep taking a rung
/// each until the indent ceiling swallows them. Going up from a 44-deep folder to a
/// 26-deep one left twenty-one consecutive rows at identical indent, twenty-one nested
/// levels rendered as twenty-one siblings.
///
/// An empty chain is not a focus: the picker skin has none, and collapsing everything
/// there would fight the user's own chevrons.
pub fn expansion_after_refocus(
    expanded: &BTreeSet<String>,
    chain: &[String],
) -> BTreeSet<String> {
    let Some(focus) = chain.last() else {
        return expanded.clone();
    };
    let below_focus = descendant_prefix(focus);
    let mut next: BTreeSet<String> = expanded
        .iter()
        .filter(|key| !key.starts_with(&below_focus))
        .cloned()
        .collect();
    next.extend(chain.iter().cloned());
    next
}

/// The string every descendant key of `node_key` starts with.
///
/// A separator has to be appended so that `/ab` is not read as a child of `/a`, except
/// when the key already ends in one, which the DATASET ROOT does: its path is `"/"`, and
/// `"{root}/"` matches nothing at all. That row is a real, tickable row in the unified
/// tree, so getting this wrong showed a dataset as unticked while folders under it were
/// ticked.
fn descendant_prefix(node_key: &str) -> String {
    if node_key.ends_with('/') {
        node_key.to_string()
    } else {
        format!("{node_key}/")
    }
}

/// Tick or untick a node in a picker selection.
///
/// Selecting a folder covers everything below it. The filter it becomes is one
/// ancestor-closure term id, and `file_paths IN (parent)` already matches every document
/// under `parent`. So a descendant that was ticked separately is now redundant, and
/// leaving it in the set would render the parent as Partial while it is in fact fully
/// selected. Unticking removes only the node itself: the descendants are gone already.
pub fn toggle_selection(node_key: &str, selected: &mut BTreeSet<String>) {
    if selected.remove(node_key) {
        return;
    }
    let prefix = descendant_prefix(node_key);
    selected.retain(|key| !key.starts_with(&prefix));
    selected.insert(node_key.to_string());
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TriState {
    Unchecked,
    Partial,
    Checked,
}

/// The icon for a tri-state checkbox.
pub fn tri_state_icon(state: TriState) -> Element {
    match state {
        TriState::Checked => rsx! {
            Icon { icon: MdCheckBox, style: "width: 20px; height: 20px; color: rgb(28,33,45);" }
        },
        TriState::Partial => rsx! {
            Icon { icon: MdIndeterminateCheckBox, style: "width: 20px; height: 20px; color: rgb(28,33,45);" }
        },
        TriState::Unchecked => rsx! {
            Icon { icon: MdCheckBoxOutlineBlank, style: "width: 20px; height: 20px; color: rgba(0,0,0,0.6);" }
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cached_node(key: &str) -> VfsTreeNode {
        VfsTreeNode {
            collection_dataset: "testdata_shapes".into(), node_key: key.into(),
            parent_key: "parent".into(), container_hash: String::new(),
            path: format!("/{key}"), name: key.into(), kind: VfsNodeKind::Dir,
            file_hash: String::new(), file_size_bytes: 0, depth: 1,
        }
    }

    #[test]
    fn restored_child_pages_stop_at_a_gap_and_exclude_other_parents() {
        let pages = BTreeMap::from([
            (("parent".into(), 0), CachedChildren { nodes: vec![cached_node("one")], total: 4, fetched_at_ms: 0.0 }),
            (("parent".into(), 1), CachedChildren { nodes: vec![cached_node("two")], total: 4, fetched_at_ms: 0.0 }),
            (("parent".into(), 3), CachedChildren { nodes: vec![cached_node("four")], total: 4, fetched_at_ms: 0.0 }),
            (("other".into(), 2), CachedChildren { nodes: vec![cached_node("other")], total: 3, fetched_at_ms: 0.0 }),
        ]);
        let restored = loaded_pages_for_parent(&pages, "parent");
        assert_eq!(restored.nodes.iter().map(|node| node.node_key.as_str()).collect::<Vec<_>>(), vec!["one", "two"]);
        assert_eq!(restored.total, 4);
    }

    #[test]
    fn an_empty_cached_page_terminates_restoration() {
        let pages = BTreeMap::from([(("parent".into(), 0), CachedChildren {
            nodes: Vec::new(), total: 0, fetched_at_ms: 0.0,
        })]);
        let restored = loaded_pages_for_parent(&pages, "parent");
        assert!(restored.nodes.is_empty());
        assert_eq!(restored.parent_key, "parent");
    }

    #[test]
    fn the_indent_keeps_stepping_past_the_full_step_rungs() {
        assert_eq!(indent_px(0), 0);
        assert_eq!(indent_px(2), 2 * INDENT_PX);
        assert_eq!(indent_px(FULL_STEP_RUNGS), FULL_STEP_RUNGS * INDENT_PX);
        // The defect this guards: an indent that stops past the fourth rung renders a
        // deep chain as a flat list. Every rung up to the ceiling must be wider than
        // the one above it, or the parent-child relationship is not on screen at all.
        let ceiling_rung = (0..)
            .find(|rung| indent_px(*rung) == MAX_INDENT_PX)
            .expect("the indent reaches its ceiling");
        for rung in 1..ceiling_rung {
            assert!(
                indent_px(rung) > indent_px(rung - 1),
                "rung {rung} must be indented past rung {}",
                rung - 1
            );
        }
        // And it is bounded, so no depth can spend the pane.
        assert_eq!(indent_px(usize::MAX), MAX_INDENT_PX);
        assert!(ceiling_rung > 12, "the ceiling must be past any elided ladder");
    }

    /// The rung the deepest row of a `chain_rows`-long path renders on, once ancestor
    /// elision has trimmed the middle out of it. This is the number the indent budget is
    /// actually spent against. The tree's depth is not.
    fn deepest_visible_rung(chain_rows: usize) -> usize {
        use crate::components::search_components::storage_tree::SYNTHETIC_LEVELS;
        let Some(elision) = elide_ancestors(chain_rows) else {
            return SYNTHETIC_LEVELS + chain_rows;
        };
        // Rung by rung: the synthetic rows, the ancestors kept at the top, one rung for
        // the gap row, the tail, and then the level of children below the focused node.
        let tail = chain_rows - elision.resume_depth;
        SYNTHETIC_LEVELS + elision.head + 1 + tail
    }

    #[test]
    fn trimming_the_ancestors_is_what_pays_for_the_indent() {
        // `deep-stuff` is 42 numbered folders under `/deep-stuff`, so the deepest path is
        // 43 rows below the dataset root and reaches depth 45 on screen. Elision renders
        // it on a rung in the low teens, which is the entire reason the ladder can keep
        // stepping at all.
        let rung = deepest_visible_rung(43);
        assert!(rung <= 12, "a 43-row path must fit a short ladder, not a 43-rung one");
        assert!(
            indent_px(rung) < MAX_INDENT_PX,
            "the deep fixture must be inside the ceiling, not sitting on it"
        );

        // At the default pane width the deepest row still has a real label. The row also
        // spends a chevron, a folder icon, their gaps and the depth badge.
        let furniture = 18 + 18 + 24 + 56;
        let label = crate::components::resizable_sidebar::DEFAULT_SIDEBAR_PX as usize
            - indent_px(rung)
            - furniture;
        assert!(label >= 90, "the deepest visible row has only {label} px of label");
    }

    #[test]
    fn the_indent_never_takes_most_of_a_narrow_pane() {
        // The pixel ceiling is chosen against a comfortable pane; the percentage is what
        // holds when the user drags the sidebar in, and the browser re-evaluates it with
        // no re-render. It has to bind at the narrowest pane the drag allows, or the
        // ceiling is the only guard there and it is the wrong one.
        assert_eq!(indent_style(0), format!("min(0px, calc({MAX_INDENT_PERCENT}% * 0.0000))"));
        assert_eq!(
            indent_style(usize::MAX),
            format!("min({MAX_INDENT_PX}px, calc({MAX_INDENT_PERCENT}% * 1.0000))")
        );
        assert!(MAX_INDENT_PERCENT < 50, "the indent may never outweigh the label");
        let narrowest = crate::components::resizable_sidebar::MIN_SIDEBAR_PX as usize;
        assert!(
            narrowest * MAX_INDENT_PERCENT / 100 < MAX_INDENT_PX,
            "at the narrowest pane the percentage must be the binding guard"
        );
        // And whichever guard binds, no rung may take more than the stated share.
        for rung in 0..40 {
            assert!(
                indent_resolved_px(rung, narrowest as f64)
                    <= narrowest as f64 * MAX_INDENT_PERCENT as f64 / 100.0 + 0.001,
                "rung {rung} takes more than {MAX_INDENT_PERCENT}% of the narrowest pane"
            );
        }
    }

    /// The property the whole ladder exists for, asserted at the widths the drag offers.
    ///
    /// A pane-relative ceiling that is not scaled by the rung collapses every rung above
    /// it onto one value: at the 240 px floor the drag allows, five consecutive levels
    /// then render at pixel-identical indent and a deep chain reads as a flat list,
    /// which is exactly the defect the ladder replaced, reached from the other direction.
    /// The tree also scrolls, which takes a further ~13 px off the containing block, so
    /// the narrow case is checked below the pane width as well as at it.
    #[test]
    fn every_rung_still_steps_at_every_pane_width() {
        let widths = [
            crate::components::resizable_sidebar::MIN_SIDEBAR_PX as f64 - 13.0,
            crate::components::resizable_sidebar::MIN_SIDEBAR_PX as f64,
            crate::components::resizable_sidebar::DEFAULT_SIDEBAR_PX as f64,
            crate::components::resizable_sidebar::MAX_SIDEBAR_PX as f64,
        ];
        // Up to the rung where the pixel ladder itself stops; past that the depth badge
        // carries the number and [`MAX_INDENT_PX`] is doing what it is there for.
        let last_stepping_rung = (0..usize::MAX)
            .find(|rung| indent_px(*rung) == MAX_INDENT_PX)
            .expect("the ladder reaches its ceiling");
        for width in widths {
            for rung in 1..=last_stepping_rung {
                let previous = indent_resolved_px(rung - 1, width);
                let current = indent_resolved_px(rung, width);
                assert!(
                    current > previous,
                    "at {width}px, rung {rung} indents {current} and rung {} indents {previous}",
                    rung - 1
                );
            }
        }
    }

    /// Navigating up must not leave the chain you came from hanging off the new focus.
    ///
    /// Elision shortens the ladder only above the focus, so an expanded descendant chain
    /// keeps taking a rung each until the indent ceiling absorbs it: going up from a
    /// 44-deep folder to a 26-deep one left twenty-one consecutive rows at the same
    /// indent, which is the flat list the ladder exists to prevent.
    #[test]
    fn refocusing_closes_the_subtree_below_the_new_focus() {
        let root = "ds\u{1f}\u{1f}/";
        let chain_down: Vec<String> = (0..6)
            .map(|d| format!("ds\u{1f}\u{1f}/{}", (0..=d).map(|i| i.to_string()).collect::<Vec<_>>().join("/")))
            .collect();
        let mut expanded: BTreeSet<String> = chain_down.iter().cloned().collect();
        expanded.insert(root.to_string());
        // A sibling branch the user opened by hand, which has nothing to do with the walk.
        expanded.insert("ds\u{1f}\u{1f}/9".to_string());

        // Back up to the third folder in the chain.
        let mut chain_up = vec![root.to_string()];
        chain_up.extend(chain_down[..3].iter().cloned());
        let after = expansion_after_refocus(&expanded, &chain_up);

        for key in &chain_up {
            assert!(after.contains(key), "the path to the focus stays open: {key}");
        }
        for key in &chain_down[3..] {
            assert!(!after.contains(key), "the chain below the focus is closed: {key}");
        }
        assert!(after.contains("ds\u{1f}\u{1f}/9"), "a branch elsewhere is untouched");
    }

    #[test]
    fn a_tree_with_no_focus_keeps_every_chevron_the_user_opened() {
        // The picker skin has no focus at all, and an empty chain must not be read as
        // "focused on the root", which would collapse the whole tree on every render.
        let expanded = BTreeSet::from([
            "ds\u{1f}\u{1f}/a".to_string(),
            "ds\u{1f}\u{1f}/a/b".to_string(),
        ]);
        assert_eq!(expansion_after_refocus(&expanded, &[]), expanded);
    }

    #[test]
    fn the_dataset_root_is_a_prefix_of_its_own_folders() {
        // Its key ends in `/`, so appending another one matches nothing, and the
        // dataset row would render unticked with every folder under it ticked.
        let root = common::vfs::dataset_root_key("testdata_zips");
        let folder = common::vfs::make_node_key("testdata_zips", "", "/location-1");
        let selected = BTreeSet::from([folder.clone()]);
        assert_eq!(tri_state(&root, &selected), TriState::Partial);

        let mut selected = selected;
        toggle_selection(&root, &mut selected);
        assert_eq!(selected, BTreeSet::from([root.clone()]), "the folder is absorbed");
        assert_eq!(tri_state(&root, &selected), TriState::Checked);
    }

    #[test]
    fn tri_state_comes_from_the_selection_alone() {
        let mut selected = BTreeSet::new();
        selected.insert("ds\u{1f}\u{1f}/a/b".to_string());
        assert_eq!(tri_state("ds\u{1f}\u{1f}/a/b", &selected), TriState::Checked);
        assert_eq!(tri_state("ds\u{1f}\u{1f}/a", &selected), TriState::Partial);
        assert_eq!(tri_state("ds\u{1f}\u{1f}/c", &selected), TriState::Unchecked);
    }

    #[test]
    fn a_sibling_with_a_shared_name_prefix_is_not_a_descendant() {
        // `/ab` is not under `/a`, and a naive `starts_with(node_key)` would say it is.
        let mut selected = BTreeSet::new();
        selected.insert("ds\u{1f}\u{1f}/ab".to_string());
        assert_eq!(tri_state("ds\u{1f}\u{1f}/a", &selected), TriState::Unchecked);
    }

    #[test]
    fn ticking_a_parent_absorbs_its_descendants() {
        // Otherwise the parent renders Partial while every document under it is in fact
        // selected, because `file_paths IN (parent)` already covers the subtree.
        let mut selected = BTreeSet::from([
            "ds\u{1f}\u{1f}/a/b".to_string(),
            "ds\u{1f}\u{1f}/a/c/d".to_string(),
            "ds\u{1f}\u{1f}/ab".to_string(),
        ]);
        toggle_selection("ds\u{1f}\u{1f}/a", &mut selected);
        assert_eq!(
            selected,
            BTreeSet::from(["ds\u{1f}\u{1f}/a".to_string(), "ds\u{1f}\u{1f}/ab".to_string()]),
            "the sibling `/ab` is not under `/a` and must survive"
        );
        assert_eq!(tri_state("ds\u{1f}\u{1f}/a", &selected), TriState::Checked);

        toggle_selection("ds\u{1f}\u{1f}/a", &mut selected);
        assert_eq!(selected, BTreeSet::from(["ds\u{1f}\u{1f}/ab".to_string()]));
    }

    #[test]
    fn a_shallow_chain_is_not_elided() {
        for rows in 0..=MAX_VISIBLE_ANCESTORS {
            assert_eq!(elide_ancestors(rows), None, "{rows} rows fit");
        }
    }

    #[test]
    fn elision_keeps_the_top_and_the_tail_and_counts_the_gap_exactly() {
        // `many-children/deep-stuff` is 42 levels deep. That is the case this exists for.
        let elision = elide_ancestors(42).expect("42 rows must elide");
        assert_eq!(elision.head, ANCESTORS_SHOWN_AT_TOP);
        assert_eq!(elision.resume_depth, 42 - (MAX_VISIBLE_ANCESTORS - ANCESTORS_SHOWN_AT_TOP));
        // Rows rendered: the head levels, then the tail levels. Rows hidden: the gap.
        let tail = 42 - elision.resume_depth;
        assert_eq!(elision.head + tail, MAX_VISIBLE_ANCESTORS);
        assert_eq!(elision.head + elision.hidden + tail, 42, "every row is shown or counted");
    }

    #[test]
    fn elision_is_off_by_one_free_at_the_boundary() {
        assert_eq!(elide_ancestors(MAX_VISIBLE_ANCESTORS), None);
        let first = elide_ancestors(MAX_VISIBLE_ANCESTORS + 1).expect("one over must elide");
        assert_eq!(first.hidden, 1, "the first elided chain hides exactly one row");
    }

    #[test]
    fn a_level_with_no_focus_is_still_windowed() {
        // The children of the folder you are in have no focused sibling, and that level
        // is exactly the 334-row case. Rendering it whole put eight screens of identical
        // folders into a 240 px sidebar.
        let window = window_siblings(334, None);
        assert_eq!(window.start, 0);
        assert_eq!(window.end, 2 * MAX_SIBLINGS_EACH_SIDE + 1);
        assert_eq!(window.hidden_after, 334 - window.end);
        assert!(window.is_capping());

        // A level that fits is never touched, focus or no focus.
        assert_eq!(window_siblings(5, None), SiblingWindow::everything(5));
        assert_eq!(
            window_siblings(2 * MAX_SIBLINGS_EACH_SIDE + 1, None),
            SiblingWindow::everything(2 * MAX_SIBLINGS_EACH_SIDE + 1)
        );
    }

    #[test]
    fn a_level_windows_around_the_focused_sibling() {
        let window = window_siblings(334, Some(200));
        assert_eq!(window.start, 200 - MAX_SIBLINGS_EACH_SIDE);
        assert_eq!(window.end, 200 + MAX_SIBLINGS_EACH_SIDE + 1);
        assert_eq!(window.end - window.start, 2 * MAX_SIBLINGS_EACH_SIDE + 1);
        assert_eq!(window.hidden_before, 190);
        assert_eq!(window.hidden_after, 334 - 211);
        // Nothing is lost: shown + hidden is the whole level.
        assert_eq!(window.hidden_before + (window.end - window.start) + window.hidden_after, 334);
    }

    #[test]
    fn windowing_clamps_at_both_ends_without_underflow() {
        let first = window_siblings(334, Some(0));
        assert_eq!(first.start, 0);
        assert_eq!(first.hidden_before, 0);
        assert_eq!(first.end, MAX_SIBLINGS_EACH_SIDE + 1);

        let last = window_siblings(334, Some(333));
        assert_eq!(last.end, 334);
        assert_eq!(last.hidden_after, 0);

        // A level small enough to fit is never capped, so the two "more" rows and the
        // fetch row can never all appear at once on an ordinary folder.
        let small = window_siblings(5, Some(2));
        assert!(!small.is_capping());
        assert_eq!(small, SiblingWindow::everything(5));
    }

    fn chain_pages(keys: &[&str]) -> (Vec<String>, BTreeMap<(String, u64), CachedChildren>) {
        let chain: Vec<String> = keys.iter().map(|key| key.to_string()).collect();
        let mut pages = BTreeMap::new();
        for window in chain.windows(2) {
            let parent = window[0].clone();
            let child = window[1].clone();
            pages.insert(
                (parent.clone(), 0),
                CachedChildren {
                    nodes: vec![cached_node(&child)],
                    total: 1,
                    fetched_at_ms: 0.0,
                },
            );
        }
        let last = chain.last().unwrap().clone();
        pages.insert(
            (last, 0),
            CachedChildren { nodes: Vec::new(), total: 0, fetched_at_ms: 0.0 },
        );
        (chain, pages)
    }

    fn folder_keys(items: &[VisibleItem]) -> Vec<String> {
        items
            .iter()
            .filter_map(|item| match item {
                VisibleItem::Folder { node, .. } => Some(node.node_key.clone()),
                _ => None,
            })
            .collect()
    }

    #[test]
    fn visible_rows_elide_the_middle_and_keep_unique_keys() {
        let (chain, pages) = chain_pages(&(0..21).map(|i| format!("n{i}")).map(|s| Box::leak(s.into_boxed_str()) as &str).collect::<Vec<_>>());
        let expanded: BTreeSet<String> = chain.iter().cloned().collect();
        let items = visible_items(&chain[0], 2, &chain, &BTreeSet::new(), &expanded, &pages, &BTreeMap::new());
        let keys: Vec<String> = items.iter().map(|item| item.row_key()).collect();
        let unique = BTreeSet::from_iter(keys.iter().cloned());
        assert_eq!(keys.len(), unique.len(), "visible row keys must be unique: {keys:?}");
        assert!(items.iter().any(|item| matches!(item, VisibleItem::Elision { hidden: 12, .. })), "{items:?}");
        let folders = folder_keys(&items);
        assert!(folders.contains(&chain[1]));
        assert!(folders.contains(&chain[20]));
        assert!(!folders.contains(&chain[5]), "elided ancestors are not mounted: {folders:?}");
    }

    #[test]
    fn common_visible_folder_keys_survive_an_elision_resume_shift() {
        let labels: Vec<String> = (0..21).map(|i| format!("n{i}")).collect();
        let leaked: Vec<&str> = labels.iter().map(|s| Box::leak(s.clone().into_boxed_str()) as &str).collect();
        let (chain_deep, pages) = chain_pages(&leaked);
        let expanded: BTreeSet<String> = chain_deep.iter().cloned().collect();
        let deep_items = visible_items(&chain_deep[0], 2, &chain_deep, &BTreeSet::new(), &expanded, &pages, &BTreeMap::new());
        let chain_up = chain_deep[..20].to_vec();
        let up_items = visible_items(&chain_up[0], 2, &chain_up, &BTreeSet::new(), &expanded, &pages, &BTreeMap::new());
        let deep_keys: BTreeSet<String> = folder_keys(&deep_items).into_iter().collect();
        let up_keys: BTreeSet<String> = folder_keys(&up_items).into_iter().collect();
        let common: BTreeSet<String> = deep_keys.intersection(&up_keys).cloned().collect();
        assert!(common.contains(&chain_deep[1]));
        assert!(common.contains(&chain_deep[19]));
        assert!(!common.is_empty());
        let deep_row_keys: Vec<String> = deep_items.iter().map(|item| item.row_key()).collect();
        let up_row_keys: Vec<String> = up_items.iter().map(|item| item.row_key()).collect();
        assert_eq!(deep_row_keys.iter().filter(|k| *k == "elision").count(), 1);
        assert_eq!(up_row_keys.iter().filter(|k| *k == "elision").count(), 1);
        let deep_elision = deep_row_keys.iter().position(|k| k == "elision").expect("deep elision");
        let up_elision = up_row_keys.iter().position(|k| k == "elision").expect("up elision");
        assert_ne!(
            deep_row_keys.get(deep_elision + 1),
            up_row_keys.get(up_elision + 1),
            "a resume shift inserts a new folder immediately after the elision slot"
        );
        let common_order_deep: Vec<String> =
            deep_row_keys.iter().filter(|k| common.contains(*k)).cloned().collect();
        let common_order_up: Vec<String> =
            up_row_keys.iter().filter(|k| common.contains(*k)).cloned().collect();
        assert_eq!(
            common_order_deep, common_order_up,
            "shared visible folders keep the same keys and order when the resume parent moves"
        );
    }

    #[test]
    fn needed_parents_skip_elided_levels() {
        let labels: Vec<String> = (0..21).map(|i| format!("n{i}")).collect();
        let leaked: Vec<&str> = labels.iter().map(|s| Box::leak(s.clone().into_boxed_str()) as &str).collect();
        let (chain, pages) = chain_pages(&leaked);
        let expanded: BTreeSet<String> = chain.iter().cloned().collect();
        let needed = needed_parents(&chain[0], &chain, &BTreeSet::new(), &expanded, &pages);
        assert!(!needed.contains(&chain[5]), "elided parents are not fetched: {needed:?}");
        assert!(needed.contains(&chain[0]));
        let elision = elide_ancestors(chain.len().saturating_sub(1)).expect("deep chain elides");
        let next_up = &chain[elision.resume_depth - 1];
        assert!(needed.contains(next_up), "the next shallower resume parent is fetched: {needed:?}");
    }
}
