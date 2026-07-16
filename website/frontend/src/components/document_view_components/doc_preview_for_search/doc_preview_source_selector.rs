use common::{
    document_sources::{DocumentSourceItem, ItemHitCounts},
    search_result::DocumentIdentifier,
};
use dioxus::prelude::*;
use dioxus_free_icons::{
    IconShape,
    icons::{
        md_action_icons::MdQuestionAnswer,
        md_communication_icons::MdEmail,
        md_file_icons::MdTextSnippet,
        md_image_icons::{MdAudiotrack, MdImage, MdPictureAsPdf, MdSwitchVideo},
        md_navigation_icons::MdCheck,
        md_toggle_icons::MdRadioButtonUnchecked,
    },
};

use crate::components::popover::{PopoverContent, PopoverRoot, PopoverTrigger};

#[server]
pub async fn search_document_item_hit_counts(
    _document_identifier: DocumentIdentifier,
    _find_query: String,
    _sources: Vec<DocumentSourceItem>,
) -> Result<ItemHitCounts, ServerFnError> {
    if _find_query.is_empty() || _sources.is_empty() {
        return Ok(ItemHitCounts(Vec::new()));
    }
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::search_document_itemcount::search_document_item_count(
        &user,
        _document_identifier,
        _find_query,
        _sources,
    )
    .await
    .map_err(crate::api::error_util::to_server_fn_error)
}

#[component]
pub fn DocumentPreviewSourceSelectorDropdown(
    sources: ReadSignal<Option<Vec<DocumentSourceItem>>>,
    item_hit_counts: ReadSignal<ItemHitCounts>,
    selected_source: ReadSignal<Option<DocumentSourceItem>>,
    on_source_selected: Callback<DocumentSourceItem>,
) -> Element {
    let sources = sources.read().clone().unwrap_or_default();
    if sources.is_empty() {
        return rsx! {
            "No Sources!"
        };
    };
    let Some(selected_source) = selected_source.read().clone() else {
        return rsx! {
            "No Selected Source!"
        };
    };

    let mut expand = use_signal(move || false);
    rsx! {
        PopoverRoot {
            open: expand(),
            on_open_change: move |open: bool| {
                expand.set(open);
            },
            PopoverTrigger {

                SelectedItemDropdownDisplay {
                    selected_item: selected_source.clone(),
                    expand,
                    item_hit_counts: item_hit_counts,
                }
            }
            PopoverContent {
                SelectedItemList {
                    sources,
                    selected_source,
                    on_source_selected: move |source: DocumentSourceItem| {
                        on_source_selected.call(source);
                        expand.set(false);
                    },
                    item_hit_counts: item_hit_counts,
                }
            }
        }
    }
}

#[component]
pub fn DocumentPreviewSourceSelectorList(
    sources: ReadSignal<Option<Vec<DocumentSourceItem>>>,
    selected_source: ReadSignal<Option<DocumentSourceItem>>,
    on_source_selected: Callback<DocumentSourceItem>,
    item_hit_counts: ReadSignal<ItemHitCounts>,
) -> Element {
    let sources = sources.read().clone().unwrap_or_default();
    if sources.is_empty() {
        return rsx! {
            "No Sources!"
        };
    };
    let Some(selected_source) = selected_source.read().clone() else {
        return rsx! {
            "No Selected Source!"
        };
    };
    rsx! {
        SelectedItemList {
            sources,
            selected_source,
            on_source_selected: move |source: DocumentSourceItem| {
                on_source_selected.call(source);
            },
            item_hit_counts: item_hit_counts,
        }
    }
}

#[component]
fn SelectedItemList(
    sources: Vec<DocumentSourceItem>,
    selected_source: ReadSignal<DocumentSourceItem>,
    on_source_selected: Callback<DocumentSourceItem>,
    item_hit_counts: ReadSignal<ItemHitCounts>,
) -> Element {
    rsx! {
        ul {
            style: "
            width: 300px;
            height: fit-content;
            position: relative; top: 0px; left: 0px;",

            for source in sources.into_iter() {
                if _should_display(&source) {

                    div {
                        key: "{source:?}",
                        style: "
                        display: inline-flex;
                        align-items: center;
                        gap: 8px;
                        padding: 4px 12px;
                        background: white;
                        cursor: pointer;
                        width: 100%;
                        ",

                        onclick: move |_| {
                            on_source_selected(source.clone());
                        },
                        SourceItemRow {
                            source: source.clone(),
                            selected: source == selected_source.read().clone(),
                            item_hit_counts: item_hit_counts,
                        }
                    }
                }
            }
        }
    }
}

fn _should_display(source: &DocumentSourceItem) -> bool {
    match source {
        DocumentSourceItem::FileLocations => false,
        DocumentSourceItem::Metadata => false,
        _ => true,
    }
}

#[component]
fn SelectedItemDropdownDisplay(
    selected_item: ReadSignal<DocumentSourceItem>,
    expand: Signal<bool>,
    item_hit_counts: ReadSignal<ItemHitCounts>,
) -> Element {
    rsx! {
        div {
            onclick: move |_e| {
                dioxus::logger::tracing::info!("toggle expand");
                _e.prevent_default();
                _e.stop_propagation();
                expand.toggle();
            },
            style: "
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 4px 12px;
            border: 1px solid #ccc;
            border-radius: 20px;
            background: white;
            cursor: pointer;
            font-size: 16px;
            line-height: 24px;
            font-weight: 400;
            width: 250px;
            margin-right: 10px;
            ",

            SourceItemRow {
                source: selected_item.clone(),
                selected: false,
                item_hit_counts: item_hit_counts,
            }
            span { style: "color: #666; margin-left: 4px; font-size: 12px;", "▼" }

        }
    }
}

#[component]
fn SourceItemRow(
    source: ReadSignal<DocumentSourceItem>,
    selected: bool,
    item_hit_counts: ReadSignal<ItemHitCounts>,
) -> Element {
    let source = source.read().clone();
    let item_hit_counts = item_hit_counts.read().clone();
    let item_hit_counts = std::collections::BTreeMap::from_iter(item_hit_counts.0);
    let count = item_hit_counts.get(&source).unwrap_or(&0);
    let (icon, label) = match source {
        DocumentSourceItem::Text(source) => {
            (_item_icon_rsx(MdTextSnippet), source.extracted_by.clone())
        }
        DocumentSourceItem::Pdf(_source) => (_item_icon_rsx(MdPictureAsPdf), "PDF".to_string()),
        DocumentSourceItem::Email(_source) => (_item_icon_rsx(MdEmail), "Email".to_string()),
        DocumentSourceItem::Image(_source) => (_item_icon_rsx(MdImage), "Image".to_string()),
        DocumentSourceItem::Audio(_source) => (_item_icon_rsx(MdAudiotrack), "Audio".to_string()),
        DocumentSourceItem::Video(_source) => (_item_icon_rsx(MdSwitchVideo), "Video".to_string()),
        _ => (_item_icon_rsx(MdQuestionAnswer), format!("{:?}", source)),
    };
    let text_color = if selected { "#111" } else { "#333" };
    let dot_icon = if selected {
        _item_icon_rsx(MdCheck)
    } else {
        _item_icon_rsx(MdRadioButtonUnchecked)
    };

    let count = if *count == 0 {
        "".to_string()
    } else {
        count.to_string()
    };

    rsx! {
        div { style: "color: #666; font-size: 16px !important; line-height: 24px; width: 24px;", {dot_icon} }
        div { style: "font-size: 16px; line-height: 24px; width: 24px;", {icon} }
        div { style: "flex-grow: 1; flex-shrink: 1; font-weight: 400; color: {text_color}; font-size: 16px; line-height: 24px;", "{label}" }
        div { style: "flex-shrink: 0;color: #333; font-weight: 400; font-size: 20px; line-height: 24px; margin-left: 4px;", "{count}" }
    }
}

fn _item_icon_rsx<T: IconShape + Clone + PartialEq + 'static>(icon: T) -> Element {
    rsx! {
        dioxus_free_icons::Icon {
            icon: icon,
            style: "width: 24px; height: 24px;",
            width: 24,
            height: 24,
        }
    }
}
