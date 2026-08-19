//! The reusable pieces of a checkbox facet list.
//!
//! There is no pill strip here — every facet is a pane inside the "All filters" modal
//! (`filter_modal.rs`), because a strip of buttons does not scale past four facets and
//! has nowhere to put a filter that is not a checkbox list. Do not add mime/extension/path
//! buttons either: `file_paths` is a folder TREE, and a flat list of hashed path ids is
//! not usable.
//!
//! What stayed is the part the modal reuses verbatim: the list itself, its hit counts,
//! its partial-shard notice, and `ResolveMissingItems`.

use std::collections::BTreeSet;

use common::{search_query::SearchQuery, search_result::FacetOriginalValue};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::md_toggle_icons::{MdCheckBox, MdCheckBoxOutlineBlank},
};

use crate::{
    api::search_api::{fetch_db_terms_for_ints, search_string_facet},
    components::error_boundary::ServerErrorDisplay,
};

#[component]
pub fn FacetSelectorList(
    original_query: ReadSignal<SearchQuery>,
    modified_search_query: Signal<SearchQuery>,
    facet_field_name: ReadSignal<String>,
    map_string_terms: ReadSignal<Option<String>>,
    /// Substring the rendered buckets are narrowed to, case-insensitively.
    ///
    /// It filters what is RENDERED, never what is fetched: the server returns the top
    /// buckets for the query and re-running that fan-out per keystroke would cost one
    /// search per character on an index that already fails on its time budget. Empty
    /// means no narrowing, which is why the default renders every bucket.
    #[props(default)]
    needle: ReadSignal<String>,
) -> Element {
    let mut facet_request = use_resource(move || {
        let q = original_query.read().clone();
        search_string_facet(
            q,
            facet_field_name.read().clone(),
            map_string_terms.read().clone(),
        )
    });
    let search_result = facet_request.suspend()?.cloned();
    let search_result = match search_result {
        // The retry is a BUTTON and never automatic. This pane is one of four rendered
        // at once, and the failure it is most likely to show is the search running out
        // of its time budget — retrying that by itself doubles the load on a Manticore
        // that was already too slow to answer, four times over.
        Err(e) => {
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
                        onclick: move |_| facet_request.restart(),
                        "Retry"
                    }
                }
            };
        }
        Ok(s) => s,
    };
    let originally_filtered_values = original_query
        .read()
        .facet_filters
        .get(&facet_field_name.read().clone())
        .unwrap_or(&BTreeSet::new())
        .clone();
    let returned_values = search_result
        .facet_values
        .iter()
        .map(|v| v.original_value.clone())
        .collect::<BTreeSet<_>>();
    // Narrowing happens on the label the user can actually read. `original_value` is a
    // term id for the mapped fields, so matching against it would search text that is
    // never on screen and miss the text that is.
    let needle_text = needle.read().trim().to_lowercase();
    let visible_values: Vec<_> = if needle_text.is_empty() {
        search_result.facet_values
    } else {
        search_result
            .facet_values
            .into_iter()
            .filter(|v| v.display_string.to_lowercase().contains(&needle_text))
            .collect()
    };
    // A narrowing that matches nothing has to say so. Rendering an empty list under a box
    // the user just typed into is indistinguishable from the list having failed to load.
    let no_matches = visible_values.is_empty() && !needle_text.is_empty();
    let missing_values = originally_filtered_values
        .difference(&returned_values)
        .cloned()
        .collect::<Vec<_>>();

    rsx! {
        // Partial-results notice: one or more shards could not be searched, so these
        // buckets and counts may be missing the failed shard's contribution.
        if search_result.partial {
            div {
                style: "
                    width: 100%;
                    padding: 6px 10px;
                    margin-bottom: 4px;
                    border: 1px solid rgba(200, 120, 0, 0.6);
                    border-radius: 6px;
                    background-color: rgba(255, 180, 60, 0.15);
                    color: rgb(120, 70, 0);
                    font-size: 13px;
                ",
                "Some collections could not be searched — facet counts may be incomplete."
            }
        }
        if no_matches {
            div {
                style: "padding: 8px 10px; font-size: 14px; color: rgba(0,0,0,0.55);",
                "Nothing here matches \"{needle_text}\"."
            }
        }
        ul {
            for result in visible_values {
                li {
                    key: "{result.display_string}-{result.count}-{result.original_value:?}",
                    FacetCheckbox {
                        query: modified_search_query,
                        facet_name: facet_field_name.clone(),
                        facet_value: result.original_value.clone(),
                        result_count: result.count,
                        result_display_string: result.display_string.clone(),
                    }
                }
            }
            ResolveMissingItems {
                modified_search_query,
                missing_values,
                facet_field_name,
                map_string_terms,
            }
        }
    }
}

#[component]
pub fn ResolveMissingItems(
    modified_search_query: Signal<SearchQuery>,
    missing_values: ReadSignal<Vec<FacetOriginalValue>>,
    facet_field_name: ReadSignal<String>,
    map_string_terms: ReadSignal<Option<String>>,
) -> Element {
    // **Every hook runs before the first early return, unconditionally.** Dioxus
    // identifies a hook by its call ORDER, so a `use_memo` behind an `if` panics with
    // "Unable to retrieve the hook that was initialized at this index" the first time
    // that condition flips — and it flips constantly here, because whether a filtered
    // value is missing from the returned buckets changes with every query the user
    // narrows. The nothing-to-do cases are handled by returning early BELOW, and by the
    // resource declining to make a round trip for an empty list.
    let ints = use_memo(move || {
        let mut ints = Vec::new();
        for value in missing_values.read().clone() {
            if let FacetOriginalValue::Int(i) = value {
                ints.push(i);
            }
        }
        ints
    });
    let map = use_resource(move || {
        let ints = ints();
        let field_name = map_string_terms().unwrap_or_default();

        async move {
            if ints.is_empty() {
                return std::collections::HashMap::new();
            }
            fetch_db_terms_for_ints(ints, field_name)
                .await
                .unwrap_or_default()
        }
    });

    if missing_values.read().is_empty() || ints().is_empty() {
        return rsx! {};
    }
    let map = map().unwrap_or_default();

    let mut facet_values = Vec::new();
    for value in missing_values.read().clone() {
        facet_values.push(common::search_result::SearchResultFacetItem {
            display_string: match &value {
                FacetOriginalValue::Int(i) => {
                    if let Some(s) = map.get(i) {
                        s.clone()
                    } else {
                        // The id resolved to no text: the term row is gone (a
                        // purged dataset) or the collection is unreadable. Showing the
                        // raw id is honest and still lets the user un-set the filter —
                        // `Missing2: Int(123)` was a debug print that shipped.
                        format!("#{i}")
                    }
                }
                FacetOriginalValue::String(s) => s.clone(),
            },
            original_value: value,
            count: 0,
        });
    }
    rsx! {
        ul {
            for result in facet_values {
                li {
                    key: "{result.display_string}-{result.count}-{result.original_value:?}",
                    FacetCheckbox {
                        query: modified_search_query,
                        facet_name: facet_field_name,
                        facet_value: result.original_value.clone(),
                        result_count: result.count,
                        result_display_string: result.display_string.clone(),
                    }
                }
            }
        }
    }
}

#[component]
pub fn FacetCheckbox(
    mut query: Signal<SearchQuery>,
    facet_name: ReadSignal<String>,
    facet_value: ReadSignal<FacetOriginalValue>,
    result_count: ReadSignal<u64>,
    result_display_string: ReadSignal<String>,
) -> Element {
    let is_checked = use_memo(move || {
        query
            .read()
            .facet_filters
            .get(&facet_name.read().clone())
            .unwrap_or(&BTreeSet::new())
            .contains(&facet_value.read().clone())
    });
    rsx! {

        div {
            class: "x-facet-list-item",
            style: "
                display: flex;
                flex-direction: row;
                gap: 10px;
                cursor: pointer;
                padding: 4px;
                margin: 4px;
                accent-color: #ffffff;
                align-items: center;
            ",
            onclick: move |_e| {
                let facet_name = facet_name.read().clone();
                let should_add = !is_checked();
                let facet_value = facet_value.read().clone();
                let mut query = query.write();

                let entry = query.facet_filters.entry(facet_name.clone()).or_insert(BTreeSet::new());
                if should_add {
                    entry.insert(facet_value);
                } else {
                    entry.remove(&facet_value);
                }
                if entry.is_empty() {
                    query.facet_filters.remove(&facet_name);
                }
            },

            // FACET CHECKBOX
            if is_checked() {
                Icon { icon: MdCheckBox, style: "width: 26px; height: 26px; color: rgb(28, 33, 45); flex-shrink: 0;" }
            } else {
                Icon { icon: MdCheckBoxOutlineBlank, style: "width: 26px; height: 26px; color: black; flex-shrink: 0;" }
            }
            // FACET NAME
            div {
                style: "
                    font-size: 20px;
                    line-height: 28px;
                    font-weight: 400;
                    color: rgb(0, 0, 0);
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    min-width: 0;
                ",
                "{result_display_string}"
            }

            // FACET SPACER
            div { style: "flex: 1 1 auto;", }

            // FACET COUNT
            div {
                style: "
                    font-size: 20px;
                    line-height: 28px;
                    font-weight: 400;
                    color: rgba(28, 33, 45, 0.7);
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    min-width: 0;
                    flex-shrink: 0;
                ",
                "{result_count}"
            }
        }
    }
}
