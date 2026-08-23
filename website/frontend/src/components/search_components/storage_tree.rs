//! One tree for the whole corpus: collections > datasets > folders.
//!
//! One tree rather than two lists. A flat COLLECTIONS list plus a separate folder tree
//! for whichever dataset the URL names says the same thing twice, forces the user to pick
//! a dataset before any folder tree appears, and never shows the corpus as it is.
//!
//! **The two upper levels are synthetic.** VFS node keys are dataset-scoped by
//! construction (`common::vfs::make_node_key`), so the structure index cannot produce a
//! cross-dataset tree and is not asked to. The collection and dataset rows come from the
//! dataset registry in ONE call ([`list_storage_tree`]); a dataset's folders are fetched
//! by an embedded [`VfsTree`] only once its row is expanded. A corpus of N collections x
//! M datasets therefore costs one request on mount, not N x M.
//!
//! Everything below a dataset row (ancestor elision, sibling capping, the indent ladder,
//! the tri-state checkbox) is the existing per-dataset tree, unchanged. The only thing
//! this level hands it is [`SYNTHETIC_LEVELS`], which is the ladder rung its folders start
//! on, so the two rows above a folder are paid for out of the same indent budget rather
//! than being added on top of it.

use std::collections::BTreeSet;

use common::storage_tree::CollectionNode;
use common::vfs::{VfsTreeNode, dataset_root_key, node_key_is_in_dataset};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        go_icons::GoDatabase,
        md_device_icons::MdStorage,
        md_navigation_icons::{MdChevronRight, MdExpandMore, MdMoreHoriz},
    },
};

use crate::api::storage_api::list_storage_tree;
use crate::components::search_components::vfs_tree::{
    LABEL_STYLE, MORE_ROW_STYLE, ROW_STYLE, SiblingWindow, TreeSkin, TriState, VfsTree,
    indent_style, tri_state_icon, window_siblings,
};

/// Rows above a folder: the collection and the dataset. Folders indent from here.
pub const SYNTHETIC_LEVELS: usize = 2;

/// Which row the user activated. The two surfaces answer this very differently (the
/// sidebar navigates, the picker ticks), so the tree reports rather than decides.
#[derive(Debug, Clone, PartialEq)]
pub enum StorageRow {
    Collection(String),
    Dataset(String),
    /// `(collection_dataset, node)`. The node alone does not say which dataset it is in
    /// once the tree spans all of them.
    Folder(String, VfsTreeNode),
}

/// One synthetic level's rows: the window plus what it hides either side.
///
/// The same cap the folder levels obey ([`window_siblings`]). A deployment with two
/// hundred datasets in a collection is not a reason to put two hundred rows in a sidebar,
/// and the overflow rows say exactly how many are hidden and reveal them.
#[derive(Debug, Clone, PartialEq)]
pub struct SyntheticLevel<T> {
    pub hidden_before: usize,
    pub items: Vec<T>,
    pub hidden_after: usize,
}

/// Window one synthetic level around `focus`, or from the top when it has none.
pub fn flatten_level<T: Clone>(
    items: &[T],
    focus: Option<usize>,
    unfolded: bool,
) -> SyntheticLevel<T> {
    let window = if unfolded {
        SiblingWindow::everything(items.len())
    } else {
        window_siblings(items.len(), focus)
    };
    SyntheticLevel {
        hidden_before: window.hidden_before,
        items: items[window.start..window.end].to_vec(),
        hidden_after: window.hidden_after,
    }
}

/// The tri-state of a DATASET row, from the selection alone.
///
/// Not the folder rule: a dataset covers everything scoped to it, including nodes inside
/// archives and emails, whose keys carry a different container field and so are not
/// under the root by any path comparison. Dataset scope is the exact question, and the
/// key's first field answers it.
pub fn dataset_tri_state(collection_dataset: &str, selected: &BTreeSet<String>) -> TriState {
    let root = dataset_root_key(collection_dataset);
    if selected.contains(&root) {
        return TriState::Checked;
    }
    if selected
        .iter()
        .any(|key| node_key_is_in_dataset(key, collection_dataset))
    {
        TriState::Partial
    } else {
        TriState::Unchecked
    }
}

/// The tri-state of a COLLECTION row: the aggregate of its datasets'.
///
/// Checked only when every dataset is fully checked, so the box never claims more than
/// the filter does. A collection with no datasets is Unchecked rather than vacuously
/// Checked. An empty tick is a filter that matches nothing.
pub fn collection_tri_state(dataset_ids: &[String], selected: &BTreeSet<String>) -> TriState {
    if dataset_ids.is_empty() {
        return TriState::Unchecked;
    }
    let states: Vec<TriState> = dataset_ids
        .iter()
        .map(|id| dataset_tri_state(id, selected))
        .collect();
    if states.iter().all(|s| *s == TriState::Checked) {
        TriState::Checked
    } else if states.iter().all(|s| *s == TriState::Unchecked) {
        TriState::Unchecked
    } else {
        TriState::Partial
    }
}

/// Tick or untick a whole dataset.
///
/// Ticking selects the dataset's ROOT NODE KEY, which is a `file_paths` term exactly
/// like a folder's (the ancestor closure of every document in the dataset contains it)
/// so the filter machinery downstream needs to know nothing about datasets. Everything
/// else scoped to the dataset is absorbed, for the same reason ticking a folder absorbs
/// its subtree: the parent term already covers them, and leaving them in would render
/// the row Partial while it is fully selected.
pub fn toggle_dataset(collection_dataset: &str, selected: &mut BTreeSet<String>) {
    let root = dataset_root_key(collection_dataset);
    let was_checked = selected.contains(&root);
    selected.retain(|key| !node_key_is_in_dataset(key, collection_dataset));
    if !was_checked {
        selected.insert(root);
    }
}

/// Tick or untick every dataset of a collection at once.
///
/// Anything short of fully checked ticks the lot; fully checked unticks it. That is the
/// rule a tri-state box has to follow to be reversible in one click from any state.
pub fn toggle_collection(dataset_ids: &[String], selected: &mut BTreeSet<String>) {
    let checked = collection_tri_state(dataset_ids, selected) == TriState::Checked;
    for id in dataset_ids {
        selected.retain(|key| !node_key_is_in_dataset(key, id));
        if !checked {
            selected.insert(dataset_root_key(id));
        }
    }
}

/// Expansion keys for the synthetic rows. Prefixed so a collection named like a dataset
/// id cannot collide with it in the one set that holds both.
fn collection_expansion_key(collectionname: &str) -> String {
    format!("c\u{1f}{collectionname}")
}

fn dataset_expansion_key(collection_dataset: &str) -> String {
    format!("d\u{1f}{collection_dataset}")
}

/// The unified tree. Both surfaces mount exactly this.
#[component]
pub fn StorageTree(
    skin: TreeSkin,
    /// The picker's selection: node keys, dataset roots included. Ignored by `Sidebar`.
    selected: Signal<BTreeSet<String>>,
    /// The dataset the storage page is inside, or empty. A SIGNAL: the tree has to
    /// follow an in-app navigation, and a plain prop does not re-run anything.
    current_dataset: ReadSignal<String>,
    /// The folder node key the storage page is showing, or empty.
    focus_key: ReadSignal<String>,
    on_activate: Callback<StorageRow>,
) -> Element {
    // One request for every collection and dataset the user may read. Nothing below is
    // fetched until a dataset row is expanded.
    let tree = use_resource(move || async move { list_storage_tree().await });
    let mut expanded = use_signal(BTreeSet::<String>::new);
    let unfolded = use_signal(BTreeSet::<String>::new);

    // Open the collections as soon as they arrive, and the chain down to the dataset the
    // URL names. Expanding a collection costs NOTHING (its datasets came with the one
    // request), so the level that tells you what exists is open by default; the dataset
    // level, which does cost a request, is not.
    //
    // An effect that only INSERTS. It must never clear the set: a user who collapsed a
    // row would see it spring open again on the next render, and clearing plus restarting
    // a resource here is the pattern that doubles every request in this codebase.
    //
    // Built from `peek()` and written only when it CHANGES. `write()` marks the signal
    // dirty whether or not the value moved, and this effect re-runs on every read of the
    // resource, so an unconditional write here was a re-render of every collection row,
    // every dataset row and every mounted `VfsTree` per run. The same reasoning as the
    // sibling effect in `vfs_tree.rs`.
    use_effect(move || {
        let Some(Ok(nodes)) = tree.read().clone() else {
            return;
        };
        let dataset = current_dataset();
        let mut next = expanded.peek().clone();
        for node in &nodes {
            next.insert(collection_expansion_key(&node.collectionname));
        }
        if !dataset.is_empty() {
            next.insert(dataset_expansion_key(&dataset));
        }
        if *expanded.peek() != next {
            expanded.set(next);
        }
    });

    let body = match tree.read().clone() {
        None => rsx! {
            div { style: "padding: 8px 10px; font-size: 14px; color: rgba(0,0,0,0.5);", "Loading…" }
        },
        Some(Err(error)) => rsx! {
            div {
                class: "x-error-display",
                style: "padding: 8px 10px; font-size: 14px; color: rgb(160,30,30);",
                "Could not load the collections: {error}"
            }
        },
        Some(Ok(nodes)) if nodes.is_empty() => rsx! {
            div { style: "padding: 8px 10px; font-size: 14px; color: rgba(0,0,0,0.5);", "No collections." }
        },
        Some(Ok(nodes)) => {
            let focus = current_dataset();
            let focus_index = nodes
                .iter()
                .position(|node| node.datasets.iter().any(|d| d.collection_dataset == focus));
            let level = flatten_level(&nodes, focus_index, unfolded.read().contains("collections"));
            rsx! {
                MoreRow {
                    hidden: level.hidden_before,
                    depth: 0,
                    label: "collections",
                    unfold_key: "collections".to_string(),
                    unfolded,
                    above: true,
                }
                for node in level.items {
                    CollectionBranch {
                        key: "{node.collectionname}",
                        node: node.clone(),
                        skin,
                        selected,
                        current_dataset,
                        focus_key,
                        on_activate,
                        expanded,
                        unfolded,
                    }
                }
                MoreRow {
                    hidden: level.hidden_after,
                    depth: 0,
                    label: "collections",
                    unfold_key: "collections".to_string(),
                    unfolded,
                    above: false,
                }
            }
        }
    };

    rsx! {
        div {
            // Named so a script can scope a click to the tree. Dataset and folder names
            // appear on the result cards behind the filter modal as well, and a
            // document-wide search clicks straight through the overlay.
            id: "x-storage-tree",
            // Vertical scrolling only, like the folder tree it contains: a long dataset
            // name may not make the sidebar scroll sideways, at any width.
            style: "width: 100%; min-width: 0; overflow-x: hidden;",
            {body}
        }
    }
}

#[component]
fn CollectionBranch(
    node: CollectionNode,
    skin: TreeSkin,
    selected: Signal<BTreeSet<String>>,
    current_dataset: ReadSignal<String>,
    focus_key: ReadSignal<String>,
    on_activate: Callback<StorageRow>,
    expanded: Signal<BTreeSet<String>>,
    unfolded: Signal<BTreeSet<String>>,
) -> Element {
    let expansion_key = collection_expansion_key(&node.collectionname);
    let is_expanded = expanded.read().contains(&expansion_key);
    let dataset_ids = node.dataset_ids();
    let check_state = collection_tri_state(&dataset_ids, &selected.read());
    let name = node.collectionname.clone();

    let level = {
        let focus = current_dataset();
        let focus_index = node
            .datasets
            .iter()
            .position(|d| d.collection_dataset == focus);
        flatten_level(
            &node.datasets,
            focus_index,
            unfolded.read().contains(&expansion_key),
        )
    };
    let unfold_key = expansion_key.clone();

    rsx! {
        SyntheticRow {
            depth: 0,
            label: name.clone(),
            title: name.clone(),
            skin,
            check_state,
            is_expanded,
            is_current: false,
            expansion_key: expansion_key.clone(),
            expanded,
            icon: SyntheticIcon::Collection,
            on_click: Callback::new({
                let name = name.clone();
                let dataset_ids = dataset_ids.clone();
                move |_| {
                    if skin == TreeSkin::Picker {
                        toggle_collection(&dataset_ids, &mut selected.write());
                    }
                    on_activate.call(StorageRow::Collection(name.clone()));
                }
            }),
        }
        if is_expanded {
            MoreRow {
                hidden: level.hidden_before,
                depth: 1,
                label: "datasets",
                unfold_key: unfold_key.clone(),
                unfolded,
                above: true,
            }
            for dataset in level.items {
                DatasetBranch {
                    key: "{dataset.collection_dataset}",
                    collection_dataset: dataset.collection_dataset.clone(),
                    label: dataset.label().to_string(),
                    skin,
                    selected,
                    current_dataset,
                    focus_key,
                    on_activate,
                    expanded,
                }
            }
            MoreRow {
                hidden: level.hidden_after,
                depth: 1,
                label: "datasets",
                unfold_key: unfold_key.clone(),
                unfolded,
                above: false,
            }
        }
    }
}

#[component]
fn DatasetBranch(
    collection_dataset: String,
    label: String,
    skin: TreeSkin,
    selected: Signal<BTreeSet<String>>,
    current_dataset: ReadSignal<String>,
    focus_key: ReadSignal<String>,
    on_activate: Callback<StorageRow>,
    expanded: Signal<BTreeSet<String>>,
) -> Element {
    let expansion_key = dataset_expansion_key(&collection_dataset);
    let is_expanded = expanded.read().contains(&expansion_key);
    let check_state = dataset_tri_state(&collection_dataset, &selected.read());

    // The focus belongs to ONE dataset's tree. Handing it to the others would make every
    // mounted tree run `vfs_tree_path_to` for a key that is not in it. A memo, not a
    // value: it has to follow an in-app navigation.
    let dataset_focus = use_memo({
        let collection_dataset = collection_dataset.clone();
        move || {
            if current_dataset() == collection_dataset {
                focus_key()
            } else {
                String::new()
            }
        }
    });
    let is_current = use_memo({
        let collection_dataset = collection_dataset.clone();
        move || skin == TreeSkin::Sidebar && current_dataset() == collection_dataset
    });

    rsx! {
        SyntheticRow {
            depth: 1,
            label: label.clone(),
            title: collection_dataset.clone(),
            skin,
            check_state,
            is_expanded,
            // The dataset row is the "you are here" row only while the page is showing
            // the dataset's own root; below that the folder row carries the highlight.
            is_current: is_current() && focus_key() == dataset_root_key(&collection_dataset),
            expansion_key: expansion_key.clone(),
            expanded,
            icon: SyntheticIcon::Dataset,
            on_click: Callback::new({
                let collection_dataset = collection_dataset.clone();
                move |_| {
                    if skin == TreeSkin::Picker {
                        toggle_dataset(&collection_dataset, &mut selected.write());
                    }
                    on_activate.call(StorageRow::Dataset(collection_dataset.clone()));
                }
            }),
        }
        if is_expanded {
            VfsTree {
                collection_dataset: collection_dataset.clone(),
                skin,
                selected,
                initially_expanded: Vec::new(),
                focus_key: dataset_focus,
                indent_offset: SYNTHETIC_LEVELS,
                on_activate: Callback::new({
                    let collection_dataset = collection_dataset.clone();
                    move |node: VfsTreeNode| {
                        on_activate.call(StorageRow::Folder(collection_dataset.clone(), node))
                    }
                }),
            }
        }
    }
}

#[derive(Clone, Copy, PartialEq)]
enum SyntheticIcon {
    Collection,
    Dataset,
}

/// A collection or dataset row. Deliberately the same shape as a folder row, same
/// height, same disclosure slot, same checkbox slot, same ellipsised label, because a
/// tree in which one level looks like a heading and the next like a list reads as two
/// widgets stacked, which is what this replaced.
#[component]
fn SyntheticRow(
    depth: usize,
    label: String,
    title: String,
    skin: TreeSkin,
    check_state: TriState,
    is_expanded: bool,
    is_current: bool,
    expansion_key: String,
    expanded: Signal<BTreeSet<String>>,
    icon: SyntheticIcon,
    on_click: Callback<()>,
) -> Element {
    let indent = indent_style(depth);
    // Named so a script can expand exactly this row. Clicking the row itself ticks it in
    // the picker, which is not the same gesture. The disclosure is the only way to open
    // a row without also selecting it, and a test that cannot tell them apart tests
    // neither. Both parts of the id are validated slugs, so it is a usable selector.
    let toggle_id = match icon {
        SyntheticIcon::Collection => format!("x-tree-c-{title}"),
        SyntheticIcon::Dataset => format!("x-tree-d-{title}"),
    };
    let selected_here = match skin {
        TreeSkin::Sidebar => is_current,
        TreeSkin::Picker => check_state == TriState::Checked,
    };
    let background = if selected_here { "rgba(243,140,104,0.16)" } else { "transparent" };
    let weight = if depth == 0 { 600 } else { 500 };

    let mut expanded_set = expanded;
    let toggle_key = expansion_key.clone();
    let toggle = move |event: Event<MouseData>| {
        event.stop_propagation();
        let mut set = expanded_set.write();
        if set.contains(&toggle_key) {
            set.remove(&toggle_key);
        } else {
            set.insert(toggle_key.clone());
        }
    };

    rsx! {
        div {
            style: "{ROW_STYLE} padding-left: {indent}; background: {background};",
            class: "x-facet-list-item",
            title: "{title}",
            onclick: move |_| on_click.call(()),

            button {
                id: "{toggle_id}",
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
                match icon {
                    SyntheticIcon::Collection => rsx! {
                        Icon { icon: MdStorage, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.7);" }
                    },
                    SyntheticIcon::Dataset => rsx! {
                        Icon { icon: GoDatabase, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.7);" }
                    },
                }
            }

            div { style: "{LABEL_STYLE} font-weight: {weight};", "{label}" }
        }
    }
}

/// The "N more…" row of a synthetic level. Renders nothing when nothing is hidden.
#[component]
fn MoreRow(
    hidden: usize,
    depth: usize,
    label: &'static str,
    unfold_key: String,
    unfolded: Signal<BTreeSet<String>>,
    above: bool,
) -> Element {
    if hidden == 0 {
        return rsx! {};
    }
    let indent = indent_style(depth);
    let mut unfolded_set = unfolded;
    let direction = if above { "above" } else { "below" };
    rsx! {
        button {
            style: "{ROW_STYLE} {MORE_ROW_STYLE} padding-left: {indent};",
            class: "x-facet-list-item",
            title: "Show all {label} here",
            onclick: move |_| { unfolded_set.write().insert(unfold_key.clone()); },
            Icon { icon: MdMoreHoriz, style: "width: 18px; height: 18px; flex-shrink: 0;" }
            div { style: "{LABEL_STYLE}", "{hidden} more {label} {direction}…" }
        }
    }
}

/// The keys a `file_paths` selection resolves to when it is seeded back from term ids.
///
/// `fetch_db_terms_for_ints` answers with `id -> term value`, and a `vfs_node` term
/// value IS the node key, so seeding is a filter for the values that look like one, not
/// a parse. Values from another term field (a stale query, an id collision) are dropped
/// rather than shown as a tick on nothing.
pub fn node_keys_from_terms(terms: impl IntoIterator<Item = String>) -> BTreeSet<String> {
    terms
        .into_iter()
        .filter(|value| common::vfs::dataset_of_node_key(value).is_some_and(|d| d != *value))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::components::search_components::vfs_tree::{
        MAX_SIBLINGS_EACH_SIDE, toggle_selection,
    };
    use common::vfs::make_node_key;

    fn ids(names: &[&str]) -> Vec<String> {
        names.iter().map(|n| n.to_string()).collect()
    }

    #[test]
    fn a_short_level_renders_whole() {
        let items = ids(&["a", "b", "c"]);
        let level = flatten_level(&items, None, false);
        assert_eq!(level.items, items);
        assert_eq!((level.hidden_before, level.hidden_after), (0, 0));
    }

    #[test]
    fn a_long_level_windows_around_the_dataset_you_are_in() {
        let items: Vec<String> = (0..200).map(|i| format!("ds{i}")).collect();
        let level = flatten_level(&items, Some(120), false);
        assert_eq!(level.items.len(), 2 * MAX_SIBLINGS_EACH_SIDE + 1);
        assert_eq!(level.items[MAX_SIBLINGS_EACH_SIDE], "ds120");
        // Nothing is lost: shown plus hidden is the whole level.
        assert_eq!(
            level.hidden_before + level.items.len() + level.hidden_after,
            items.len()
        );
        // And unfolding it shows everything.
        let all = flatten_level(&items, Some(120), true);
        assert_eq!(all.items.len(), items.len());
        assert_eq!((all.hidden_before, all.hidden_after), (0, 0));
    }

    #[test]
    fn a_dataset_is_partial_when_a_folder_under_it_is_ticked() {
        let mut selected = BTreeSet::new();
        selected.insert(make_node_key("testdata_zips", "", "/location-1"));
        assert_eq!(dataset_tri_state("testdata_zips", &selected), TriState::Partial);
        assert_eq!(dataset_tri_state("testdata_shapes", &selected), TriState::Unchecked);

        // Including a folder INSIDE a container, whose key shares no path prefix with
        // the dataset root at all.
        let mut in_container = BTreeSet::new();
        in_container.insert(make_node_key("testdata_zips", "ziphash", "/inner"));
        assert_eq!(dataset_tri_state("testdata_zips", &in_container), TriState::Partial);
    }

    #[test]
    fn ticking_a_dataset_absorbs_everything_scoped_to_it() {
        let mut selected = BTreeSet::from([
            make_node_key("testdata_zips", "", "/location-1"),
            make_node_key("testdata_zips", "ziphash", "/inner"),
            make_node_key("testdata_shapes", "", "/shapes"),
        ]);
        toggle_dataset("testdata_zips", &mut selected);
        assert_eq!(
            selected,
            BTreeSet::from([
                dataset_root_key("testdata_zips"),
                make_node_key("testdata_shapes", "", "/shapes"),
            ]),
            "the other dataset's selection survives"
        );
        assert_eq!(dataset_tri_state("testdata_zips", &selected), TriState::Checked);

        // And unticking it leaves nothing behind.
        toggle_dataset("testdata_zips", &mut selected);
        assert_eq!(dataset_tri_state("testdata_zips", &selected), TriState::Unchecked);
        assert_eq!(selected.len(), 1);
    }

    #[test]
    fn a_collection_aggregates_its_datasets() {
        let datasets = ids(&["testdata_shapes", "testdata_zips"]);
        let mut selected = BTreeSet::new();
        assert_eq!(collection_tri_state(&datasets, &selected), TriState::Unchecked);

        toggle_dataset("testdata_shapes", &mut selected);
        assert_eq!(collection_tri_state(&datasets, &selected), TriState::Partial);

        toggle_dataset("testdata_zips", &mut selected);
        assert_eq!(collection_tri_state(&datasets, &selected), TriState::Checked);

        // A folder tick under one of them is Partial, not Checked: the box may never
        // claim more than the filter does.
        let mut partial = BTreeSet::new();
        partial.insert(make_node_key("testdata_shapes", "", "/a"));
        partial.insert(dataset_root_key("testdata_zips"));
        assert_eq!(collection_tri_state(&datasets, &partial), TriState::Partial);

        // An empty collection is not vacuously checked.
        assert_eq!(collection_tri_state(&[], &selected), TriState::Unchecked);
    }

    #[test]
    fn a_collection_ticks_and_unticks_in_one_click_from_any_state() {
        let datasets = ids(&["testdata_shapes", "testdata_zips"]);
        let mut selected = BTreeSet::from([make_node_key("testdata_shapes", "", "/a")]);

        toggle_collection(&datasets, &mut selected);
        assert_eq!(collection_tri_state(&datasets, &selected), TriState::Checked);
        assert_eq!(
            selected,
            BTreeSet::from([
                dataset_root_key("testdata_shapes"),
                dataset_root_key("testdata_zips"),
            ]),
            "the half-selected folder is absorbed by its dataset's root"
        );

        toggle_collection(&datasets, &mut selected);
        assert!(selected.is_empty());
    }

    #[test]
    fn a_folder_tick_inside_a_ticked_dataset_is_absorbed() {
        // The folder rows go through `toggle_selection`, which absorbs descendants of
        // the key it ticks. The dataset root has to be a real ancestor for that, which
        // is what the trailing-separator case in `descendant_prefix` is about.
        let mut selected = BTreeSet::from([dataset_root_key("testdata_zips")]);
        toggle_selection(&make_node_key("testdata_zips", "", "/location-1"), &mut selected);
        assert_eq!(selected.len(), 2, "a narrower tick under a ticked dataset is additive");

        let mut selected = BTreeSet::from([make_node_key("testdata_zips", "", "/location-1")]);
        toggle_selection(&dataset_root_key("testdata_zips"), &mut selected);
        assert_eq!(selected, BTreeSet::from([dataset_root_key("testdata_zips")]));
    }

    #[test]
    fn seeding_keeps_node_keys_and_drops_everything_else() {
        let key = make_node_key("testdata_zips", "", "/location-1");
        let seeded = node_keys_from_terms([key.clone(), "application/pdf".to_string()]);
        assert_eq!(seeded, BTreeSet::from([key]));
    }
}
