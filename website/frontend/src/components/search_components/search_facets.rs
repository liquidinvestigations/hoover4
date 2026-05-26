//! Search facets UI component.

use std::collections::BTreeSet;

use common::{search_query::SearchQuery, search_result::FacetOriginalValue};
use dioxus::{logger::tracing, prelude::*};
use dioxus_free_icons::{
    Icon,
    icons::{
        md_action_icons::{MdDelete, MdInfo},
        md_communication_icons::MdBusiness,
        md_social_icons::MdPerson,
        md_toggle_icons::{MdCheckBox, MdCheckBoxOutlineBlank},
    },
};

use crate::{
    api::search_api::search_string_facet,
    components::{error_boundary::ComponentErrorDisplay, suspend_boundary::SuspendWrapper},
};
use dioxus_free_icons::icons::{
    go_icons::GoDatabase, md_communication_icons::MdLocationOn, md_editor_icons::MdInsertDriveFile,
    md_navigation_icons::MdArrowDropDown,
};

#[derive(Clone, Copy)]
struct FacetContext {
    original_query: ReadSignal<SearchQuery>,
    modified_search_query: Signal<SearchQuery>,
    expanded_facet: Signal<String>,
    set_expanded_facet: Callback<String>,
}

#[component]
pub fn FacetButtonStrip(
    original_query: ReadSignal<SearchQuery>,
    modified_search_query: Signal<SearchQuery>,
    // trigger_search: Callback<()>,
) -> Element {
    let mut expanded_facet = use_signal(|| "".to_string());
    let set_expanded_facet: Callback<String> = Callback::new(move |facet: String| {
        expanded_facet.set(facet.clone());

        // if facet.is_empty() {
        //     // check if the facet is changed - if so, run a new search
        //     let new_query = modified_search_query.peek().clone();
        //     let old_query = original_query.peek().clone();
        //     if new_query != old_query {
        //         trigger_search(());
        //     }
        // }
    });
    use_context_provider(|| FacetContext {
        original_query,
        modified_search_query,
        expanded_facet,
        set_expanded_facet,
    });

    rsx! {
        div {
            id: "x-search-input-facet-chips-wrapper",
            style: "
                width: 100%;
                max-width: 100%;
                height: 100%;
                margin: 10px;
                display: flex;
                flex-direction:row;
                padding: 10px;

                // overflow-x:scroll;
                // overflow-y: hidden;
                align-items: center;
                // margin-bottom: calc(-100vh - 10px);
                // padding-bottom: calc(100vh - 10px);


            ",

            FacetButton {
                facet_field_name: "collection_dataset".to_string(),
                facet_display_name: "Collections".to_string(),
                facet_icon: GoDatabase,
            }

            FacetButton {
                facet_display_name: "File Types".to_string(),
                facet_field_name: "doc_metadata.file_types".to_string(),
                map_string_terms: Some("filetype".to_string()),
                facet_icon: MdInsertDriveFile,
            }

            // FacetButton {
            //     facet_display_name: "Mime Types".to_string(),
            //     facet_field_name: "doc_metadata.file_mime_types".to_string(),
            //     map_string_terms: Some("mime_type".to_string()),
            //     facet_icon: MdLocationOn,
            // }

            // FacetButton {
            //     facet_display_name: "File Extensions".to_string(),
            //     facet_field_name: "doc_metadata.file_extensions".to_string(),
            //     map_string_terms: Some("extension".to_string()),
            //     facet_icon: MdApps,
            // }

            // FacetButton {
            //     facet_display_name: "File Paths".to_string(),
            //     facet_field_name: "doc_metadata.file_paths".to_string(),
            //     map_string_terms: Some("parent_paths".to_string()),
            //     facet_icon: MdLocationOn,
            // }


            FacetButton {
                facet_display_name: "Person".to_string(),
                facet_field_name: "ner_per".to_string(),
                map_string_terms: Some("ner".to_string()),
                facet_icon: MdPerson,
            }
            FacetButton {
                facet_display_name: "Organization".to_string(),
                facet_field_name: "ner_org".to_string(),
                map_string_terms: Some("ner".to_string()),
                facet_icon: MdBusiness,
            }
            FacetButton {
                facet_display_name: "Location".to_string(),
                facet_field_name: "ner_loc".to_string(),
                map_string_terms: Some("ner".to_string()),
                facet_icon: MdLocationOn,
            }
            FacetButton {
                facet_display_name: "Misc".to_string(),
                facet_field_name: "ner_misc".to_string(),
                map_string_terms: Some("ner".to_string()),
                facet_icon: MdInfo,
            }

        }
    }
}

#[component]
fn FacetButton<I: dioxus_free_icons::IconShape + 'static + Clone + PartialEq>(
    facet_display_name: ReadSignal<String>,
    facet_field_name: ReadSignal<String>,
    map_string_terms: ReadSignal<Option<String>>,
    facet_icon: I,
) -> Element {
    let facet_context = use_context::<FacetContext>();
    let expanded_facet = facet_context.expanded_facet;
    let set_expanded_facet = facet_context.set_expanded_facet;
    let original_query = facet_context.original_query;
    let mut modified_search_query = facet_context.modified_search_query;

    let filter_values_present = use_memo(move || {
        let m= modified_search_query.read();
        let m: BTreeSet<_>  = m.facet_filters.keys().collect();
        let field = facet_field_name.read().clone();
        m.contains(&field)
    });



    let is_expanded =
        use_memo(move || expanded_facet.read().clone() == facet_display_name.read().clone());
    let button_z_level = use_memo(move || if is_expanded() { 1000 } else { 888 });
   
    let border_color = use_memo(move || {
        if filter_values_present() {
            "rgba(243,140,104,0.95)"
        } else {
            "rgba(0,0,0,0.5)"
        }
    });

    rsx! {
        if is_expanded() {
            div {
                style: "position: relative; width: 0px; height: 0px; top: 0px; left: 0px;",
                div {
                    style: "
                        position: absolute;
                        top: 12px;
                        left: -60px;
                        background: white;
                        min-width: 300px;
                        min-height: 300px;
                        max-width: 500px;
                        max-height: calc(100vh - 100px);
                        border: 1px solid rgba(0,0,0,0.5);
                        border-radius: 10px;
                        margin: 10px;
                        padding: 10px;
                        background-color: white;
                        box-shadow: 0 0 10px 0 rgba(0, 0, 0, 0.1);
                        z-index: 1000;
                        overflow-y: scroll;
                    ",
                    SuspendWrapper {
                        FacetSelectorList {
                            original_query,
                            modified_search_query,
                            facet_field_name,
                            map_string_terms,
                        }
                    }
                }
            }
            div {
                style: "
                position: absolute;
                top: 0px;
                left: 0px;
                z-index: 999;
                background-color: rgba(0,0,0,0.1);
                width: 100%;
                height: 100%;
                ",
                onclick: move |_| {
                    set_expanded_facet("".to_string());
                },
            }
        }

        button {
            onclick: move |_| {
                let currently_expanded = expanded_facet.read().clone();
                let our_name = facet_display_name.read().clone();
                if currently_expanded == our_name {
                    set_expanded_facet("".to_string());
                } else {
                    set_expanded_facet(our_name);
                }
            },
            style: "
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 6px;
                flex-direction:row;
                border: 3px solid {border_color()};
                border-radius: 1000px;
                background-color: white;
                box-shadow: 0 0 10px 0 rgba(0, 0, 0, 0.1);
                overflow: hidden;
                position: relative;
                height: 28px;
                padding: 20px 5px;
                font-size: 15px;
                line-height: 24px;
                font-weight: 400;
                z-index: {button_z_level()};
                margin-right: 16px;
                text-wrap: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
                flex-shrink: 0;
            ",
            div {
                style: "
                    width: 21px;
                    height: 21px;
                    color: white;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 15px;
                    border-radius: 4px;
                    flex-shrink: 0;
                ",
                Icon {
                    icon: facet_icon, style: "width: 20px; height: 20px; color:{border_color()}; background:white;"
                }
            },
            "{facet_display_name}"
            Icon { icon: MdArrowDropDown, style: "width: 20px; height: 20px; color:rgba(0,0,0,0.9);" }

            if filter_values_present() {
                div {
                    onclick: move |_e| {
                        _e.prevent_default();
                        _e.stop_propagation();
                        tracing::info!("Filter delete button clicked!");


                    let _val = modified_search_query
                        .write()
                        .facet_filters
                        .remove(&facet_field_name.read().clone());
                    tracing::info!("Removed values: {_val:?}");


                    },
                    class: "x-hover-color-red",
                    style: "cursor: pointer;",
                    Icon {
                        icon: MdDelete,
                        style:"width:20px;height:20px;",
                    }
                }
            }
        }
    }
}

#[component]
fn FacetSelectorList(
    original_query: ReadSignal<SearchQuery>,
    modified_search_query: Signal<SearchQuery>,
    facet_field_name: ReadSignal<String>,
    map_string_terms: ReadSignal<Option<String>>,
) -> Element {
    use_effect(move || {
        let x = facet_field_name.read().clone();

    tracing::info!("FacetSelectorList(facet_field_name={x})");
    });

    let search_result = use_resource(move || {
        let q = original_query.read().clone();
        search_string_facet(
            q,
            facet_field_name.read().clone(),
            map_string_terms.read().clone(),
        )
    })
    .suspend()?
    .cloned();
    let search_result = match search_result {
        Err(e) => return rsx! {ComponentErrorDisplay { error_txt: format!("{:#?}", e) }},
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
    let missing_values = originally_filtered_values
        .difference(&returned_values)
        .cloned()
        .collect::<Vec<_>>();

    rsx! {
        ul {
            for result in search_result.facet_values {
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
fn ResolveMissingItems(
    modified_search_query: Signal<SearchQuery>,
    missing_values: ReadSignal<Vec<FacetOriginalValue>>,
    facet_field_name: ReadSignal<String>,
    map_string_terms: ReadSignal<Option<String>>,
) -> Element {
    if missing_values.read().is_empty() {
        return rsx! {};
    }
    let ints = use_memo(move || {
        let mut ints = Vec::new();
        for value in missing_values.read().clone() {
            if let FacetOriginalValue::Int(i) = value {
                ints.push(i);
            }
        }
        ints
    });
    let ints = ints();
    if ints.is_empty() {
        return rsx! {};
    }
    tracing::info!("ints: {:?}", ints);
    tracing::info!("facet_field_name: {:?}", facet_field_name());
    tracing::info!("map_string_terms: {:?}", map_string_terms());
    let map = use_resource(move || {
        let ints = ints.clone();
        let field_name = map_string_terms().unwrap_or_default();

        async move {
            fetch_db_terms_for_ints(ints, field_name)
                .await
                .unwrap_or_default()
        }
    });
    let map = map().unwrap_or_default();
    tracing::info!("map: {:?}", map);

    let mut facet_values = Vec::new();
    for value in missing_values.read().clone() {
        facet_values.push(common::search_result::SearchResultFacetItem {
            display_string: match &value {
                FacetOriginalValue::Int(i) => {
                    if let Some(s) = map.get(&i) {
                        s.clone()
                    } else {
                        format!("Missing2: {:?}", &value)
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

#[server]
async fn fetch_db_terms_for_ints(
    ints: Vec<u64>,
    field_name: String,
) -> Result<std::collections::HashMap<u64, String>, ServerFnError> {
    let x = backend::api::search::fetch_db_terms_for_ints(ints, field_name).await;
    x.map_err(|e| ServerFnError::ServerError {
        message: e.to_string(),
        code: 500,
        details: None,
    })
}

#[component]
fn FacetCheckbox(
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
