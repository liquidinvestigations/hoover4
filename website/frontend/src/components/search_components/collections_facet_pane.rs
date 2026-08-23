//! The Collections pane of the filter modal: a two-level collection → dataset tree.
//!
//! The filter itself is unchanged: `facet_filters["collection_dataset"]` is still a flat
//! set of dataset ids, which is the only thing the backend has ever understood. What is
//! composed here is the level ABOVE it: the buckets come back per dataset, the dataset
//! registry says which collection each belongs to, and a collection's hit count is the
//! sum of its datasets'. A reader picks whole collections first and only expands when
//! they want one dataset out of one of them.
//!
//! **Expanding fetches nothing.** Both halves (the buckets and the collection → dataset
//! map) are already in hand before a row is drawn, so an expand is a pure render with no
//! resource, no suspense and no loading state behind it. Expansion state also lives in a
//! signal that only the individual rows read, through a `Memo` of their own key, so
//! opening one collection wakes that one row instead of redrawing the pane.

use std::collections::{BTreeMap, BTreeSet};

use common::search_query::SearchQuery;
use common::search_result::{FacetOriginalValue, SearchResultFacetItem};
use common::storage_tree::CollectionNode;
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        go_icons::GoDatabase,
        md_action_icons::MdSearch,
        md_navigation_icons::{MdChevronRight, MdExpandMore},
    },
};

use crate::api::search_api::search_string_facet;
use crate::api::storage_api::list_storage_tree;
use crate::components::error_boundary::ServerErrorDisplay;
use crate::components::search_components::vfs_tree::{TriState, tri_state_icon};
use crate::components::suspend_boundary::LoadingIndicator;

pub const FACET_FIELD: &str = "collection_dataset";

const INPUT_STYLE: &str = "
    padding: 6px 10px; border: 1px solid rgba(0,0,0,0.25); border-radius: 8px;
    font-size: 15px; background: white; color: black; min-width: 0;
";

const ROW_STYLE: &str = "
    display: flex; flex-direction: row; align-items: center; gap: 10px;
    cursor: pointer; padding: 4px; margin: 2px 4px; accent-color: #ffffff;
";

const LABEL_STYLE: &str = "
    flex: 1 1 auto; min-width: 0; font-size: 20px; line-height: 28px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
";

const COUNT_STYLE: &str = "
    flex-shrink: 0; font-size: 20px; line-height: 28px;
    color: rgba(28, 33, 45, 0.7); white-space: nowrap;
";

/// One dataset row's data: what it is called, what it filters on, how many hits.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DatasetBucket {
    pub collection_dataset: String,
    pub label: String,
    pub count: u64,
}

/// One collection row and the datasets under it, both already sorted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CollectionGroup {
    pub collectionname: String,
    pub count: u64,
    pub datasets: Vec<DatasetBucket>,
}

impl CollectionGroup {
    pub fn dataset_ids(&self) -> Vec<String> {
        self.datasets
            .iter()
            .map(|d| d.collection_dataset.clone())
            .collect()
    }
}

/// Group the flat buckets into collections, count-descending at both levels.
///
/// A bucket whose dataset is not in the storage tree (permissions changed mid-session, or
/// the registry row is gone) becomes its own single-dataset collection rather than being
/// dropped: dropping it would hide a filter the user can still apply and, worse, one they
/// may already have applied. For the same reason a selected dataset that came back in no
/// bucket at all is added with a count of zero, so the tick can always be undone.
pub fn group_buckets(
    buckets: &[SearchResultFacetItem],
    tree: &[CollectionNode],
    selected: &BTreeSet<String>,
) -> Vec<CollectionGroup> {
    let mut collection_of: BTreeMap<&str, &str> = BTreeMap::new();
    let mut label_of: BTreeMap<&str, &str> = BTreeMap::new();
    for node in tree {
        for dataset in &node.datasets {
            collection_of.insert(
                dataset.collection_dataset.as_str(),
                node.collectionname.as_str(),
            );
            label_of.insert(dataset.collection_dataset.as_str(), dataset.label());
        }
    }

    let mut groups: BTreeMap<String, CollectionGroup> = BTreeMap::new();
    let mut seen: BTreeSet<String> = BTreeSet::new();
    let push = |groups: &mut BTreeMap<String, CollectionGroup>, id: &str, count: u64| {
        let collectionname = collection_of.get(id).map(|c| c.to_string()).unwrap_or_else(|| id.to_string());
        let label = label_of.get(id).map(|l| l.to_string()).unwrap_or_else(|| id.to_string());
        let group = groups
            .entry(collectionname.clone())
            .or_insert_with(|| CollectionGroup {
                collectionname,
                count: 0,
                datasets: Vec::new(),
            });
        group.count += count;
        group.datasets.push(DatasetBucket {
            collection_dataset: id.to_string(),
            label,
            count,
        });
    };

    for bucket in buckets {
        let FacetOriginalValue::String(id) = &bucket.original_value else {
            // `collection_dataset` is a text field, never a term id. An Int here means
            // the mapping changed under us; skipping it is better than inventing a name.
            continue;
        };
        if !seen.insert(id.clone()) {
            continue;
        }
        push(&mut groups, id, bucket.count);
    }
    for id in selected {
        if seen.insert(id.clone()) {
            push(&mut groups, id, 0);
        }
    }

    let mut groups: Vec<CollectionGroup> = groups.into_values().collect();
    for group in groups.iter_mut() {
        // Count descending, then name, so equal counts keep a stable order instead of
        // shuffling every time the query changes.
        group
            .datasets
            .sort_by(|a, b| b.count.cmp(&a.count).then(a.label.cmp(&b.label)));
    }
    groups.sort_by(|a, b| {
        b.count
            .cmp(&a.count)
            .then(a.collectionname.cmp(&b.collectionname))
    });
    groups
}

/// The tri-state of a collection row, over the flat set of selected dataset ids.
///
/// Not `storage_tree::collection_tri_state`: that one answers over VFS node keys, where a
/// dataset is selected by its root key and a folder inside it makes the dataset partial.
/// Here the selection is the facet filter itself (plain dataset ids), and a dataset is
/// either in it or not, so only the collection level can be indeterminate.
pub fn collection_facet_tri_state(dataset_ids: &[String], selected: &BTreeSet<String>) -> TriState {
    if dataset_ids.is_empty() {
        return TriState::Unchecked;
    }
    let checked = dataset_ids.iter().filter(|id| selected.contains(*id)).count();
    if checked == 0 {
        TriState::Unchecked
    } else if checked == dataset_ids.len() {
        TriState::Checked
    } else {
        TriState::Partial
    }
}

/// The dataset ids currently in the filter, as plain strings.
fn selected_ids(query: &SearchQuery) -> BTreeSet<String> {
    query
        .facet_filters
        .get(FACET_FIELD)
        .map(|values| {
            values
                .iter()
                .filter_map(|v| match v {
                    FacetOriginalValue::String(s) => Some(s.clone()),
                    FacetOriginalValue::Int(_) => None,
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Tick or untick a set of datasets in one write.
fn set_selection(query: &mut SearchQuery, ids: &[String], select: bool) {
    let entry = query
        .facet_filters
        .entry(FACET_FIELD.to_string())
        .or_default();
    for id in ids {
        let value = FacetOriginalValue::String(id.clone());
        if select {
            entry.insert(value);
        } else {
            entry.remove(&value);
        }
    }
    if entry.is_empty() {
        query.facet_filters.remove(FACET_FIELD);
    }
}

#[component]
pub fn CollectionsFacetPane(
    original_query: ReadSignal<SearchQuery>,
    pending: Signal<SearchQuery>,
) -> Element {
    let mut needle = use_signal(String::new);
    // Which collections are open. Only the ROWS read this, each through a memo of its own
    // name, so a toggle re-renders one row and never this component.
    let expanded = use_signal(BTreeSet::<String>::new);

    let mut facets = use_resource(move || {
        let q = original_query.read().clone();
        search_string_facet(q, FACET_FIELD.to_string(), None, None)
    });
    // One call for the whole registry, on mount, exactly as the storage tree does it.
    let tree = use_resource(move || async move { list_storage_tree().await });

    let (facets_value, tree_value) = match (facets.read().clone(), tree.read().clone()) {
        (Some(Ok(f)), Some(Ok(t))) => (f, t),
        (Some(Err(e)), _) => {
            // The retry is a BUTTON and never automatic: the failure this pane is most
            // likely to show is the search running out of its time budget, and retrying
            // that by itself doubles the load on a Manticore that was already too slow.
            return rsx! {
                ServerErrorDisplay { error: e }
                div {
                    style: "display: flex; justify-content: center; margin: 8px 0;",
                    button {
                        style: "
                            border: 1px solid rgba(0,0,0,0.3); background: white;
                            border-radius: 100px; padding: 6px 16px; cursor: pointer;
                            font-size: 15px;
                        ",
                        class: "hoover4-hover-shadow-background",
                        onclick: move |_| facets.restart(),
                        "Retry"
                    }
                }
            };
        }
        (_, Some(Err(e))) => {
            return rsx! { ServerErrorDisplay { error: e } };
        }
        _ => {
            return rsx! { LoadingIndicator {} };
        }
    };

    let selected = selected_ids(&pending.read());
    let groups = group_buckets(&facets_value.facet_values, &tree_value, &selected);
    let partial = facets_value.partial;

    let needle_text = needle.read().trim().to_lowercase();
    // Narrowing happens on the labels, which are what is on screen. A collection matches
    // when its own name matches OR one of its datasets does, and in the second case it
    // opens itself while the box is non-empty. A hidden match is the same as no match.
    let visible: Vec<(CollectionGroup, bool)> = if needle_text.is_empty() {
        groups.into_iter().map(|g| (g, false)).collect()
    } else {
        groups
            .into_iter()
            .filter_map(|group| {
                let name_hit = group.collectionname.to_lowercase().contains(&needle_text);
                let dataset_hit = group
                    .datasets
                    .iter()
                    .any(|d| d.label.to_lowercase().contains(&needle_text));
                match (name_hit, dataset_hit) {
                    (false, false) => None,
                    (_, dataset_hit) => Some((group, dataset_hit)),
                }
            })
            .collect()
    };
    let no_matches = visible.is_empty() && !needle_text.is_empty();

    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 6px; margin-bottom: 8px;",
            Icon { icon: MdSearch, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.5);" }
            input {
                r#type: "text",
                style: "{INPUT_STYLE} flex: 1 1 auto;",
                placeholder: "Search collections and datasets…",
                value: "{needle}",
                oninput: move |event| needle.set(event.value()),
            }
        }
        if partial {
            div {
                style: "
                    width: 100%; padding: 6px 10px; margin-bottom: 4px;
                    border: 1px solid rgba(200, 120, 0, 0.6); border-radius: 6px;
                    background-color: rgba(255, 180, 60, 0.15); color: rgb(120, 70, 0);
                    font-size: 13px;
                ",
                "Some collections could not be searched, so facet counts may be incomplete."
            }
        }
        if no_matches {
            div {
                style: "padding: 8px 10px; font-size: 14px; color: rgba(0,0,0,0.55);",
                "Nothing here matches \"{needle_text}\"."
            }
        }
        ul {
            style: "list-style: none; margin: 0; padding: 0;",
            for (group , force_open) in visible {
                li {
                    key: "{group.collectionname}",
                    CollectionFacetRow {
                        group: group.clone(),
                        pending,
                        expanded,
                        force_open,
                    }
                }
            }
        }
    }
}

#[component]
fn CollectionFacetRow(
    group: CollectionGroup,
    pending: Signal<SearchQuery>,
    expanded: Signal<BTreeSet<String>>,
    force_open: bool,
) -> Element {
    let name = group.collectionname.clone();
    let dataset_ids = group.dataset_ids();

    // A memo of THIS row's key. `expanded` changing for another collection produces the
    // same boolean here, so the memo does not fire and this row is not re-rendered. That
    // is the whole reason expansion cannot turn into a redraw of the pane.
    let is_open_key = name.clone();
    let is_open = use_memo(move || expanded.read().contains(&is_open_key));
    let open = force_open || is_open();

    let check_ids = dataset_ids.clone();
    let toggle_selection = move |_event: Event<MouseData>| {
        let selected = selected_ids(&pending.read());
        let all_on =
            collection_facet_tri_state(&check_ids, &selected) == TriState::Checked;
        set_selection(&mut pending.write(), &check_ids, !all_on);
    };

    let toggle_key = name.clone();
    let toggle_open = move |event: Event<MouseData>| {
        // The chevron and the label are separate hit targets: clicking the row selects,
        // clicking the chevron only expands. Conflating them is the usual way this
        // pattern goes wrong, every expand would also change the filter.
        event.stop_propagation();
        let mut set = expanded.write();
        if !set.remove(&toggle_key) {
            set.insert(toggle_key.clone());
        }
    };

    let selected = selected_ids(&pending.read());
    let check_state = collection_facet_tri_state(&dataset_ids, &selected);

    rsx! {
        div {
            class: "x-facet-list-item x-collection-facet-row",
            style: ROW_STYLE,
            onclick: toggle_selection,
            {tri_state_icon(check_state)}
            // The chevron sits between the tick and the database glyph, where a tree
            // control belongs: it is what opens the row's children, and reading a row
            // left to right should reach "open me" before it reaches what is being
            // opened. At the far end it read as part of the count.
            button {
                class: "x-collection-facet-expand",
                style: "
                    flex-shrink: 0; border: none; background: transparent; padding: 0;
                    margin: 0; cursor: pointer; display: inline-flex; align-items: center;
                ",
                title: if open { "Collapse" } else { "Expand" },
                onclick: toggle_open,
                if open {
                    Icon { icon: MdExpandMore, style: "width: 22px; height: 22px; color: rgba(0,0,0,0.6);" }
                } else {
                    Icon { icon: MdChevronRight, style: "width: 22px; height: 22px; color: rgba(0,0,0,0.6);" }
                }
            }
            Icon { icon: GoDatabase, style: "width: 20px; height: 20px; flex-shrink: 0; color: rgb(28,33,45);" }
            div { style: LABEL_STYLE, title: "{group.collectionname}", "{group.collectionname}" }
            div { style: COUNT_STYLE, "{group.count}" }
        }
        if open {
            ul {
                style: "list-style: none; margin: 0; padding: 0 0 0 26px;",
                for dataset in group.datasets.iter() {
                    li {
                        key: "{dataset.collection_dataset}",
                        DatasetFacetRow { dataset: dataset.clone(), pending }
                    }
                }
            }
        }
    }
}

#[component]
fn DatasetFacetRow(dataset: DatasetBucket, pending: Signal<SearchQuery>) -> Element {
    let id = dataset.collection_dataset.clone();
    let is_checked_id = id.clone();
    let is_checked = use_memo(move || selected_ids(&pending.read()).contains(&is_checked_id));
    let click_id = id.clone();
    rsx! {
        div {
            class: "x-facet-list-item x-dataset-facet-row",
            style: ROW_STYLE,
            onclick: move |_event| {
                let on = selected_ids(&pending.read()).contains(&click_id);
                set_selection(&mut pending.write(), std::slice::from_ref(&click_id), !on);
            },
            {tri_state_icon(if is_checked() { TriState::Checked } else { TriState::Unchecked })}
            div {
                style: LABEL_STYLE,
                title: "{dataset.collection_dataset}",
                "{dataset.label}"
            }
            div { style: COUNT_STYLE, "{dataset.count}" }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::storage_tree::DatasetSummary;

    fn bucket(id: &str, count: u64) -> SearchResultFacetItem {
        SearchResultFacetItem {
            display_string: id.to_string(),
            original_value: FacetOriginalValue::String(id.to_string()),
            count,
        }
    }

    fn tree() -> Vec<CollectionNode> {
        vec![
            CollectionNode {
                collectionname: "enron".to_string(),
                datasets: vec![
                    DatasetSummary {
                        collection_dataset: "enron_kaminski".to_string(),
                        collectionname: "enron".to_string(),
                        dataset_name: "kaminski".to_string(),
                        dataset_display_name: "".to_string(),
                    },
                    DatasetSummary {
                        collection_dataset: "enron_maildir".to_string(),
                        collectionname: "enron".to_string(),
                        dataset_name: "maildir".to_string(),
                        dataset_display_name: "Mail Dir".to_string(),
                    },
                ],
            },
            CollectionNode {
                collectionname: "testdata".to_string(),
                datasets: vec![DatasetSummary {
                    collection_dataset: "testdata_zips".to_string(),
                    collectionname: "testdata".to_string(),
                    dataset_name: "zips".to_string(),
                    dataset_display_name: "".to_string(),
                }],
            },
        ]
    }

    #[test]
    fn a_collections_count_is_the_sum_of_its_datasets() {
        let buckets = vec![
            bucket("enron_kaminski", 28448),
            bucket("testdata_zips", 29),
            bucket("enron_maildir", 27850),
            bucket("orphan_dataset", 5),
            bucket("testdata_missing_from_tree", 0),
        ];
        let groups = group_buckets(&buckets, &tree(), &BTreeSet::new());
        // Collections count-descending: enron 56298, orphan 5, testdata 29 ... and the
        // bucket with no registry row is its own collection rather than dropped.
        let names: Vec<&str> = groups.iter().map(|g| g.collectionname.as_str()).collect();
        assert_eq!(
            names,
            vec![
                "enron",
                "testdata",
                "orphan_dataset",
                "testdata_missing_from_tree"
            ]
        );
        assert_eq!(groups[0].count, 56298);
        assert_eq!(groups[1].count, 29);
        // Datasets inside a collection are count-descending too, and labelled from the
        // registry (display name when set).
        let enron: Vec<(&str, u64)> = groups[0]
            .datasets
            .iter()
            .map(|d| (d.label.as_str(), d.count))
            .collect();
        assert_eq!(enron, vec![("kaminski", 28448), ("Mail Dir", 27850)]);
    }

    #[test]
    fn a_selected_dataset_with_no_bucket_is_still_listed_so_it_can_be_unticked() {
        let selected: BTreeSet<String> = ["enron_kaminski".to_string()].into_iter().collect();
        let groups = group_buckets(&[], &tree(), &selected);
        assert_eq!(groups.len(), 1);
        assert_eq!(groups[0].collectionname, "enron");
        assert_eq!(groups[0].datasets.len(), 1);
        assert_eq!(groups[0].datasets[0].count, 0);
    }

    #[test]
    fn the_collection_box_is_indeterminate_only_in_the_middle() {
        let ids = vec![
            "enron_kaminski".to_string(),
            "enron_maildir".to_string(),
        ];
        let none: BTreeSet<String> = BTreeSet::new();
        assert_eq!(collection_facet_tri_state(&ids, &none), TriState::Unchecked);

        let some: BTreeSet<String> = ["enron_kaminski".to_string()].into_iter().collect();
        assert_eq!(collection_facet_tri_state(&ids, &some), TriState::Partial);

        let all: BTreeSet<String> = ids.iter().cloned().collect();
        assert_eq!(collection_facet_tri_state(&ids, &all), TriState::Checked);

        // An empty collection is unchecked, not vacuously checked: an empty tick is a
        // filter that matches nothing.
        assert_eq!(collection_facet_tri_state(&[], &all), TriState::Unchecked);
    }

    #[test]
    fn ticking_and_unticking_a_collection_writes_plain_dataset_ids() {
        let mut query = SearchQuery::default();
        let ids = vec![
            "enron_kaminski".to_string(),
            "enron_maildir".to_string(),
        ];
        set_selection(&mut query, &ids, true);
        assert_eq!(selected_ids(&query), ids.iter().cloned().collect());

        // Unticking one dataset leaves the collection indeterminate.
        set_selection(&mut query, &ids[..1], false);
        assert_eq!(
            collection_facet_tri_state(&ids, &selected_ids(&query)),
            TriState::Partial
        );

        // Emptying the set removes the key entirely, so the query carries no filter at
        // all rather than an empty one.
        set_selection(&mut query, &ids, false);
        assert!(!query.facet_filters.contains_key(FACET_FIELD));
    }
}
