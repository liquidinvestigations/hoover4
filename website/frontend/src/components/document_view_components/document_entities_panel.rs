//! Entities panel for the document viewer (grouped by type).

use common::{
    document_entities::{DocumentEntitiesResponse, DocumentEntityItem, DocumentEntityType},
    search_result::DocumentIdentifier,
};
use dioxus::prelude::*;

use crate::components::{
    error_boundary::ComponentErrorDisplay, suspend_boundary::LoadingIndicator,
};

#[component]
pub fn DocumentEntitiesPanel(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let mut filter_value = use_signal(|| "".to_string());

    let mut entities_res = use_resource(move || {
        let document_identifier = document_identifier.read().clone();
        async move { get_document_entities(document_identifier).await }
    });
    use_effect(move || {
        let _ = document_identifier.read().clone();
        entities_res.clear();
        entities_res.restart();
    });

    let items: Vec<DocumentEntityItem> = match entities_res.read().clone() {
        Some(Ok(r)) => r.items,
        Some(Err(e)) => {
            return rsx! { ComponentErrorDisplay { error_txt: format!("{:#?}", e) } };
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
            }

            div {
                style: "flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 0 10px 10px 10px;",
                EntityGroup { title: "People".to_string(), entity_type: DocumentEntityType::Per, items: items.clone() }
                EntityGroup { title: "Organizations".to_string(), entity_type: DocumentEntityType::Org, items: items.clone() }
                EntityGroup { title: "Locations".to_string(), entity_type: DocumentEntityType::Loc, items: items.clone() }
                EntityGroup { title: "Misc".to_string(), entity_type: DocumentEntityType::Misc, items }
            }
        }
    }
}

#[component]
fn EntityGroup(title: String, entity_type: DocumentEntityType, items: Vec<DocumentEntityItem>) -> Element {
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
                    EntityChip { item }
                }
            }
        }
    }
}

#[component]
fn EntityChip(item: DocumentEntityItem) -> Element {
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
            ",
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
            div {
                style: "
                    font-size: 12px;
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
    backend::api::documents::get_document_entities::get_document_entities(document_identifier)
        .await
        .map_err(|e| ServerFnError::from(e))
}

