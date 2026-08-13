//! Entities panel for the document viewer (grouped by type).

use common::{
    document_entities::{DocumentEntitiesResponse, DocumentEntityItem, DocumentEntityType},
    search_result::DocumentIdentifier,
};
use dioxus::prelude::*;

use crate::components::{
    document_view_components::doc_viewer_full_page::ViewerPageControls,
    error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator,
};

#[component]
pub fn DocumentEntitiesPanel(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let mut filter_value = use_signal(|| "".to_string());
    let mut provider_filter = use_signal(|| "".to_string());

    let document_identifier_value = document_identifier();
    let entities_res = use_resource(use_reactive!(|document_identifier_value| {
        async move { get_document_entities(document_identifier_value).await }
    }));

    let items: Vec<DocumentEntityItem> = match entities_res.read().clone() {
        Some(Ok(r)) => r.items,
        Some(Err(e)) => {
            return rsx! { ServerErrorDisplay { error: e } };
        }
        None => {
            return rsx! { LoadingIndicator {} };
        }
    };

    let filter = filter_value.read().trim().to_lowercase();
    let items = if filter.is_empty() {
        items
    } else {
        items
            .into_iter()
            .filter(|i| i.value.to_lowercase().contains(&filter))
            .collect()
    };

    // Every provider that found anything in this document, for the filter below. The
    // chips are already one per value — the rows are aggregated server-side — so this is
    // about answering "which model saw this", not about hiding duplicates.
    let mut providers: Vec<String> = items
        .iter()
        .flat_map(|i| i.providers.iter().cloned())
        .collect();
    providers.sort();
    providers.dedup();

    let selected = provider_filter.read().clone();
    let items: Vec<DocumentEntityItem> = if selected.is_empty() {
        items
    } else {
        items
            .into_iter()
            .filter(|i| i.providers.iter().any(|p| *p == selected))
            .collect()
    };
    let multi_provider = providers.len() > 1;

    rsx! {
        div {
            style: "
                height: 100%;
                width: 100%;
                display: flex;
                flex-direction: column;
                overflow: hidden;
            ",
            div {
                style: "padding: 10px 12px; flex-shrink: 0;",
                input {
                    r#type: "text",
                    placeholder: "Filter Entities ...",
                    style: "
                        width: 100%;
                        border: 1px solid rgba(0,0,0,0.35);
                        border-radius: 10px;
                        padding: 8px 10px;
                        font-size: 14px;
                        outline: none;
                    ",
                    value: "{filter_value()}",
                    oninput: move |e| {
                        filter_value.set(e.value());
                    }
                }
                // Only worth showing when there is a choice to make. One provider is the
                // normal deployment, and a filter with a single option is noise.
                if multi_provider {
                    div {
                        style: "display: flex; align-items: center; gap: 6px; margin-top: 8px; \
                                font-size: 12px; color: rgba(0,0,0,0.65);",
                        span { "Found by" }
                        select {
                            style: "border: 1px solid rgba(0,0,0,0.35); border-radius: 8px; \
                                    padding: 4px 6px; font-size: 12px;",
                            value: "{provider_filter()}",
                            onchange: move |e| provider_filter.set(e.value()),
                            option { value: "", "any model" }
                            for name in providers.iter() {
                                option { key: "{name}", value: "{name}", "{name}" }
                            }
                        }
                    }
                }
            }

            div {
                style: "flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 0 10px 10px 10px;",
                EntityGroup { title: "People".to_string(), entity_type: DocumentEntityType::Per, items: items.clone(), show_provider: multi_provider }
                EntityGroup { title: "Organizations".to_string(), entity_type: DocumentEntityType::Org, items: items.clone(), show_provider: multi_provider }
                EntityGroup { title: "Locations".to_string(), entity_type: DocumentEntityType::Loc, items: items.clone(), show_provider: multi_provider }
                EntityGroup { title: "Misc".to_string(), entity_type: DocumentEntityType::Misc, items, show_provider: multi_provider }
            }
        }
    }
}

#[component]
fn EntityGroup(
    title: String,
    entity_type: DocumentEntityType,
    items: Vec<DocumentEntityItem>,
    show_provider: bool,
) -> Element {
    let group_items = items
        .into_iter()
        .filter(|i| i.entity_type == entity_type)
        .collect::<Vec<_>>();
    if group_items.is_empty() {
        return rsx! {};
    }

    rsx! {
        div {
            style: "
                margin: 10px 0;
                border-top: 1px solid rgba(0,0,0,0.1);
                padding-top: 10px;
            ",
            div {
                style: "font-size: 14px; font-weight: 700; color: rgba(0,0,0,0.75); margin: 0 0 8px 2px;",
                "{title}"
            }
            div {
                style: "display: flex; flex-wrap: wrap; gap: 8px;",
                for item in group_items {
                    EntityChip { item, show_provider }
                }
            }
        }
    }
}

#[component]
fn EntityChip(item: DocumentEntityItem, show_provider: bool) -> Element {
    let provider_badge = item.providers.join(", ");
    let page_controls = use_context::<ViewerPageControls>();
    let on_find_query_changed = page_controls.on_find_query_changed.clone();

    rsx! {
        div {
            key: "{item.entity_type:?}-{item.value}-{item.hit_count}",
            style: "
                display: inline-flex;
                flex-direction: row;
                align-items: center;
                gap: 8px;
                padding: 6px 10px;
                border: 1px solid rgba(0,0,0,0.25);
                border-radius: 999px;
                background: white;
                max-width: 100%;
                cursor: pointer;
            ",
            class: "x-entity-chip",
            onclick: move |_e| {
                _e.prevent_default();
                let new_query = format!("\"{}\"", item.value);
                on_find_query_changed.call(new_query);
            },
            div {
                style: "
                    max-width: 260px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    font-size: 13px;
                ",
                "{item.value}"
            }
            if show_provider && !provider_badge.is_empty() {
                div {
                    title: "{provider_badge}",
                    style: "
                        font-size: 11px;
                        color: rgba(0,0,0,0.55);
                        background: rgba(0,0,0,0.06);
                        border-radius: 999px;
                        padding: 1px 7px;
                        flex-shrink: 0;
                        max-width: 140px;
                        overflow: hidden;
                        text-overflow: ellipsis;
                        white-space: nowrap;
                    ",
                    "{provider_badge}"
                }
            }
            div {
                style: "
                    font-size: 13px;
                    color: rgba(0,0,0,0.65);
                    border-left: 1px solid rgba(0,0,0,0.15);
                    padding-left: 8px;
                    flex-shrink: 0;
                ",
                "{item.hit_count}"
            }
        }
    }
}

#[server]
async fn get_document_entities(
    document_identifier: DocumentIdentifier,
) -> Result<DocumentEntitiesResponse, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_document_entities::get_document_entities(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}
