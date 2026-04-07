use common::document_sources::DocumentSourceItem;
use dioxus::prelude::*;

use crate::components::popover::{PopoverContent, PopoverRoot, PopoverTrigger};

#[component]
pub fn DocumentPreviewSourceSelector(
    sources: ReadSignal<Option<Vec<DocumentSourceItem>>>,
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
                }
            }
            PopoverContent {
                SelectedItemList {
                    sources,
                    selected_source,
                    on_source_selected: move |source: DocumentSourceItem| {
                        on_source_selected.call(source);
                        expand.set(false);
                    }
                }
            }
        }
    }
}

#[component]
fn SelectedItemList(
    sources: Vec<DocumentSourceItem>,
    selected_source: ReadSignal<DocumentSourceItem>,
    on_source_selected: Callback<DocumentSourceItem>,
) -> Element {
    rsx! {
        ul {
            style: "
            width: 350px;
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
            }
            span { style: "color: #666; margin-left: 4px; font-size: 12px;", "▼" }

        }
    }
}


#[component]
fn SourceItemRow(
    source: ReadSignal<DocumentSourceItem>,
    selected: bool,
) -> Element {

    let source = source.read().clone();
    let (icon, label, count) = match source {
        DocumentSourceItem::Text(source) => ("📄", source.extracted_by.clone(), 0),
        DocumentSourceItem::Pdf(_source) => ("📑", "PDF".to_string(), 0),
        DocumentSourceItem::Email(_source) => ("✉", "Email".to_string(), 0),
        DocumentSourceItem::Image(_source) => ("📷", "Image".to_string(), 0),
        DocumentSourceItem::Audio(_source) => ("🎧", "Audio".to_string(), 0),
        DocumentSourceItem::Video(_source) => ("🎥", "Video".to_string(), 0),
        _ => ("❓", format!("{:?}", source), 0),
    };
    let text_color = if selected { "#111" } else { "#333" };
    let dot_icon = if selected {"✔"} else { "●"};

    let count = if count == 0 {
        "".to_string()
    } else {
        count.to_string()
    };

    rsx!{
        div { style: "color: #666; font-size: 16px !important; line-height: 24px; width: 24px;", {dot_icon} }
        div { style: "font-size: 16px; line-height: 24px; width: 24px;", "{icon}" }
        div { style: "flex-grow: 1; flex-shrink: 1; font-weight: 400; color: {text_color}; font-size: 16px; line-height: 24px;", "{label}" }
        div { style: "flex-shrink: 0;color: #333; font-weight: 400; font-size: 20px; line-height: 24px; margin-left: 4px;", "{count}" }
    }

}