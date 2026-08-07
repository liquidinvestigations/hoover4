//! The VFS tree, shared by the storage sidebar and the filter pane's folder picker.
//!
//! One component, two skins. Both lazily expand one node at a time against the
//! structure index, and both obey the same layout rule:
//!
//! **No horizontal scrolling, ever.** These corpora contain a folder named `A`×200 and
//! trees forty levels deep. A row that lays out at its natural width turns the sidebar
//! into a horizontal scroller and the labels into something you have to drag to read. So
//! every row is `flex; min-width: 0` with a single-line ellipsised label, the indent is
//! `padding-left` capped at [`MAX_VISUAL_DEPTH`] (past which a depth badge carries the
//! information the indent no longer can), and the full path is always in `title`.
//!
//! **No unbounded row counts, ever, either.** The same corpora contain
//! `many-children/deep-stuff`, a 42-level chain, and `many-children/the-directory`, 334
//! sibling folders. Three independent caps keep the rendered row count bounded, and they
//! are deliberately separate because they answer different questions:
//!
//! * [`MAX_CHILDREN_PER_NODE`] caps what is FETCHED. Its overflow row raises the limit
//!   and refetches.
//! * [`MAX_SIBLINGS_EACH_SIDE`] caps what is RENDERED per level, once the level has been
//!   fetched — centred on the node you are on when the level contains it, from the top
//!   otherwise. Its overflow rows are client-side only.
//! * [`MAX_VISIBLE_ANCESTORS`] caps how many levels of the path to the current node are
//!   rendered at all — the middle of a 42-deep chain is scrollbar, not information.
//!
//! Only one of the first two ever shows at a time: while a sibling window is active the
//! fetch row is suppressed, so "34 more…" never sits next to "126 more…" meaning two
//! different things.

use std::collections::BTreeSet;

use common::vfs::{VfsNodeKind, VfsTreeNode, dataset_root_key};
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

/// Children fetched per expansion. Past this the tree shows a "N more…" row rather than
/// rendering forty thousand siblings and freezing the tab.
pub const MAX_CHILDREN_PER_NODE: u64 = 500;

/// Indent stops growing here, and the depth badge takes over.
///
/// The arithmetic is against the 240 px storage sidebar, which is the narrowest place
/// this tree lives: 4 levels x 16 px of indent, ~40 px of chevron and folder icon and
/// ~60 px of depth badge leaves about 76 px for the label. At the previous value of 12
/// the indent alone was 192 px and every row past depth 12 rendered as a chevron, a
/// folder icon and nothing else -- visible the moment a 42-level fixture existed to
/// render, and invisible before that.
pub const MAX_VISUAL_DEPTH: usize = 4;

/// Ancestor rows rendered on the path to the focused node before the middle is elided.
/// Design §6.3. `deep-stuff` is 42 levels; all 42 rendered is a scrollbar in which the
/// thing you are looking at is off-screen.
pub const MAX_VISIBLE_ANCESTORS: usize = 8;

/// How many of those always come from the TOP of the chain. The design's rule is "the
/// dataset/collection root and the last folder always render", and the tail is where you
/// are — but one top row is a single name with no context above the `N more levels…`
/// row, and in a 42-level chain that name is as likely to be `1` as anything else. Two
/// says where the chain STARTED as well as where it goes.
pub const ANCESTORS_SHOWN_AT_TOP: usize = 2;

/// Siblings rendered either side of the focused node in one level. Design §6.3.
pub const MAX_SIBLINGS_EACH_SIDE: usize = 10;

/// Pixels of indent per level, below the cap.
const INDENT_PX: usize = 16;

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

/// The label. Single line, shrinks rather than wraps or scrolls — see the module docs.
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
    /// Levels this tree is nested under, for indent purposes only.
    ///
    /// The unified storage tree puts two synthetic rows (the collection and the dataset)
    /// above every folder, and their indent has to come out of the same budget — see
    /// [`MAX_VISUAL_DEPTH`]. It is deliberately NOT added to `depth`, which is an index
    /// into the focus chain: ancestor elision and sibling capping are defined in terms of
    /// the dataset's own tree and must not shift because of what is above it.
    pub indent_offset: usize,
    /// Selected node keys. The `Picker` filter. Unused by `Sidebar`, which highlights
    /// [`TreeContext::focus_key`] instead — one node, always the one the URL names.
    pub selected: Signal<BTreeSet<String>>,
    pub on_activate: Callback<VfsTreeNode>,
    /// The node the tree is centred on, or empty.
    pub focus_key: ReadSignal<String>,
    /// Node keys from the dataset root down to the focused node, root first. Empty when
    /// nothing is focused, in which case neither elision nor sibling capping applies —
    /// they are both defined relative to "the node you are on".
    pub focus_chain: Signal<Vec<String>>,
    /// Parent keys whose elision gap or sibling window the user has clicked open.
    pub unfolded: Signal<BTreeSet<String>>,
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
    /// The node the tree should reveal and centre its caps on — the folder the storage
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
        }
    });
    let expanded = use_signal(|| initially_expanded.iter().cloned().collect::<BTreeSet<String>>());
    use_context_provider(|| expanded);

    let chain = use_resource({
        let collection_dataset = collection_dataset.clone();
        move || {
            let collection_dataset = collection_dataset.clone();
            // Read OUTSIDE the async block: that read is the subscription.
            let key = focus_key();
            async move {
                if key.is_empty() {
                    return Vec::new();
                }
                vfs_tree_path_to(collection_dataset, key).await.unwrap_or_default()
            }
        }
    });

    let mut chain_signal = focus_chain;
    let mut expanded_signal = expanded;
    use_effect(move || {
        let Some(nodes) = chain.read().clone() else {
            return;
        };
        let keys: Vec<String> = nodes.iter().map(|node| node.node_key.clone()).collect();
        // Every ancestor is expanded, including the ones elision will hide: unfolding the
        // gap must reveal an already-open path rather than a column of collapsed rows.
        let mut open = expanded_signal.write();
        for key in &keys {
            open.insert(key.clone());
        }
        drop(open);
        if *chain_signal.peek() != keys {
            chain_signal.set(keys);
        }
    });

    rsx! {
        div {
            // The container scrolls VERTICALLY only. `overflow-x: hidden` is the second
            // half of the no-horizontal-scrolling rule: without it a row that somehow
            // overflows makes the whole panel scrollable sideways.
            style: "width: 100%; min-width: 0; overflow-x: hidden; overflow-y: auto;",
            VfsTreeLevel { parent_key: root_key, depth: 0 }
        }
    }
}

/// One level of the tree: either the elision gap, or the level itself.
///
/// The split is not cosmetic. Deciding elision needs the focus chain, and fetching the
/// children needs a resource — putting both in one component would mean a `use_resource`
/// that sometimes runs and sometimes does not, which is a hook-order violation and also
/// a wasted query against a level nobody is going to see.
#[component]
fn VfsTreeLevel(parent_key: String, depth: usize) -> Element {
    let context = use_context::<TreeContext>();
    let mut unfolded = context.unfolded;

    // Is this level on the path to the focused node, and if so which of its children is
    // the next step? Everything below keys off these two answers.
    let chain = context.focus_chain.read().clone();
    let on_focus_path = chain.get(depth).is_some_and(|key| *key == parent_key);
    let next_on_path = if on_focus_path { chain.get(depth + 1).cloned() } else { None };
    let chain_rows = chain.len().saturating_sub(1);
    let is_unfolded = unfolded.read().contains(&parent_key);

    // The elision gap. Rendered by the level whose children start the hidden run, which
    // then hands off to the level the chain resumes at.
    if let Some(elision) = elide_ancestors(chain_rows)
        && on_focus_path
        && depth == elision.head
        && !is_unfolded
    {
        let resume_key = chain[elision.resume_depth].clone();
        let hidden = elision.hidden;
        let gap_indent = indent_px(depth + context.indent_offset);
        let unfold_key = parent_key.clone();
        return rsx! {
            button {
                style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {gap_indent}px;",
                class: "x-facet-list-item",
                title: "Show the {hidden} folder levels between here and the one you are in",
                onclick: move |_| { unfolded.write().insert(unfold_key.clone()); },
                Icon { icon: MdMoreHoriz, style: "width: 18px; height: 18px; flex-shrink: 0;" }
                div { style: "{LABEL_STYLE}", "{hidden} more levels…" }
            }
            VfsTreeLevel { parent_key: resume_key, depth: elision.resume_depth }
        };
    }

    rsx! {
        VfsTreeLevelBody { parent_key, depth, focus_child: next_on_path, unfolded: is_unfolded }
    }
}

#[component]
fn VfsTreeLevelBody(
    parent_key: String,
    depth: usize,
    /// The child of this level that lies on the path to the focused node, if any. The
    /// sibling window is centred on it.
    focus_child: Option<String>,
    /// The user clicked one of this level's "more" rows, so nothing is windowed.
    unfolded: bool,
) -> Element {
    let context = use_context::<TreeContext>();
    let expanded = use_context::<Signal<BTreeSet<String>>>();
    let mut unfolded_set = context.unfolded;
    let mut limit = use_signal(|| MAX_CHILDREN_PER_NODE);

    let children = use_resource({
        let dataset = context.collection_dataset.clone();
        let parent = parent_key.clone();
        move || {
            let dataset = dataset.clone();
            let parent = parent.clone();
            let limit = *limit.read();
            async move { vfs_tree_children(dataset, parent, limit, 0).await }
        }
    });

    let value = children.read().clone();
    let Some(value) = value else {
        return rsx! {
            div {
                style: "padding: 4px 8px; font-size: 14px; color: rgba(0,0,0,0.5);",
                "Loading…"
            }
        };
    };
    let listing = match value {
        Err(error) => {
            return rsx! {
                div {
                    class: "x-error-display",
                    style: "padding: 4px 8px; font-size: 14px; color: rgb(160,30,30);",
                    "Could not load this folder: {error}"
                }
            };
        }
        Ok(listing) => listing,
    };

    // Only folder-like nodes are navigable, in both skins: you filter by folder and you
    // browse into folders. Plain files are listed in the content pane, not the tree.
    let nodes: Vec<VfsTreeNode> = listing
        .nodes
        .into_iter()
        .filter(|node| node.kind.is_folder_like())
        .collect();

    if nodes.is_empty() && depth == 0 {
        return rsx! {
            div {
                style: "padding: 6px 8px; font-size: 14px; color: rgba(0,0,0,0.5);",
                "No folders in this dataset."
            }
        };
    }

    let focus_index = focus_child
        .as_ref()
        .and_then(|key| nodes.iter().position(|node| node.node_key == *key));
    let window = if unfolded {
        SiblingWindow::everything(nodes.len())
    } else {
        window_siblings(nodes.len(), focus_index)
    };

    let shown = nodes.len() as u64;
    // The fetch row and the window rows both mean "more siblings", so only one of them is
    // ever on screen. While the window is capping, the window's own row is the honest
    // one: raising the fetch limit would not reveal anything the window is hiding.
    let more = if window.is_capping() { 0 } else { listing.total.saturating_sub(shown) };
    let more_indent = indent_px(depth + context.indent_offset);
    let visible: Vec<VfsTreeNode> = nodes[window.start..window.end].to_vec();
    let unfold_before = parent_key.clone();
    let unfold_after = parent_key.clone();

    rsx! {
        if window.hidden_before > 0 {
            button {
                style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {more_indent}px;",
                class: "x-facet-list-item",
                title: "Show all {nodes.len()} folders here",
                onclick: move |_| { unfolded_set.write().insert(unfold_before.clone()); },
                Icon { icon: MdMoreHoriz, style: "width: 18px; height: 18px; flex-shrink: 0;" }
                div { style: "{LABEL_STYLE}", "{window.hidden_before} more above…" }
            }
        }
        for node in visible {
            {
                let node_key = node.node_key.clone();
                let is_expanded = expanded.read().contains(&node_key);
                rsx! {
                    div {
                        key: "{node_key}",
                        VfsTreeRow { node: node.clone(), depth, is_expanded }
                        if is_expanded {
                            VfsTreeLevel { parent_key: node_key.clone(), depth: depth + 1 }
                        }
                    }
                }
            }
        }
        if window.hidden_after > 0 {
            button {
                style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {more_indent}px;",
                class: "x-facet-list-item",
                title: "Show all {nodes.len()} folders here",
                onclick: move |_| { unfolded_set.write().insert(unfold_after.clone()); },
                Icon { icon: MdMoreHoriz, style: "width: 18px; height: 18px; flex-shrink: 0;" }
                div { style: "{LABEL_STYLE}", "{window.hidden_after} more below…" }
            }
        }
        if more > 0 {
            button {
                style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {more_indent}px;",
                class: "x-facet-list-item",
                onclick: move |_| {
                    let current = *limit.read();
                    limit.set(current + MAX_CHILDREN_PER_NODE);
                },
                "{more} more…"
            }
        }
    }
}

/// Indent in pixels, capped. See [`MAX_VISUAL_DEPTH`].
pub(crate) fn indent_px(depth: usize) -> usize {
    depth.min(MAX_VISUAL_DEPTH) * INDENT_PX
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
/// `chain_rows` is the number of ancestor ROWS — one less than the chain length, because
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
/// still applies, from the top — the level below the folder you are in is exactly the
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
fn VfsTreeRow(node: VfsTreeNode, depth: usize, is_expanded: bool) -> Element {
    let context = use_context::<TreeContext>();
    let mut expanded = use_context::<Signal<BTreeSet<String>>>();
    let node_key = node.node_key.clone();
    let check_state = tri_state(&node_key, &context.selected.read());
    // The sidebar highlights the one folder the URL names; the picker highlights what is
    // ticked. Two different questions, deliberately not sharing a signal — the sidebar's
    // answer changes on every navigation and the picker's does not.
    let is_selected = match context.skin {
        TreeSkin::Sidebar => *context.focus_key.read() == node_key,
        TreeSkin::Picker => check_state == TriState::Checked,
    };
    let visual_depth = depth + context.indent_offset;
    let indent = indent_px(visual_depth);
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
            style: "{ROW_STYLE} padding-left: {indent}px; background: {row_background};",
            class: "x-facet-list-item",
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

            // Past the indent cap the depth is no longer legible from the layout, so it
            // is stated. Below the cap this is absent rather than always-on noise. The
            // number is the row's depth in the tree on screen — which now starts at the
            // collection, so it counts the two synthetic levels the indent also spends.
            if visual_depth > MAX_VISUAL_DEPTH {
                div {
                    style: "flex-shrink: 0; font-size: 11px; color: rgba(0,0,0,0.45); border: 1px solid rgba(0,0,0,0.2); border-radius: 8px; padding: 0 5px;",
                    "depth {visual_depth}"
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

/// The string every descendant key of `node_key` starts with.
///
/// A separator has to be appended so that `/ab` is not read as a child of `/a` — except
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
/// Selecting a folder covers everything below it — the filter it becomes is one
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

    #[test]
    fn the_indent_stops_growing_at_the_cap() {
        assert_eq!(indent_px(0), 0);
        assert_eq!(indent_px(2), 2 * INDENT_PX);
        assert_eq!(indent_px(MAX_VISUAL_DEPTH), MAX_VISUAL_DEPTH * INDENT_PX);
        // A 40-deep tree indents no further than one at the cap, or the label has no
        // width left at all. The sidebar is 240 px; this has to leave room for a name.
        assert_eq!(indent_px(40), indent_px(MAX_VISUAL_DEPTH));
        assert!(indent_px(usize::MAX) + 100 < 240, "the deepest indent must leave room for a label");
    }

    #[test]
    fn the_synthetic_levels_do_not_eat_the_indent_budget() {
        // The unified tree renders folders under two synthetic rows, so every folder's
        // indent is computed at `depth + 2`. The cap is what keeps that from spending
        // the label's width, and it has to bind at the OFFSET depth, not the raw one.
        use crate::components::search_components::storage_tree::SYNTHETIC_LEVELS;
        for depth in 0..64 {
            assert!(
                indent_px(depth + SYNTHETIC_LEVELS) <= MAX_VISUAL_DEPTH * INDENT_PX,
                "depth {depth} under the synthetic levels must still be capped"
            );
        }
        // Deepest possible row in the 240 px sidebar, with room left for a name.
        assert!(indent_px(usize::MAX) + 100 < 240);
    }

    #[test]
    fn the_dataset_root_is_a_prefix_of_its_own_folders() {
        // Its key ends in `/`, so appending another one matches nothing — and the
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
}
