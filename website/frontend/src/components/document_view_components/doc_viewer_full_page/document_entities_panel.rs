//! Entities panel for the document viewer, grouped by type.
//!
//! Two extractors, one panel. The first four sections are what an NER model judged to be
//! a name, an organisation or a place; the rest are what a rule's validator accepted as
//! an identifier, an amount or a date. They sit in one list because a reader asking "what
//! is in this document" is asking one question, and they keep separate sections because
//! the confidence behind them is not comparable — a name is a judgement, an IBAN either
//! has a valid check digit or it does not.
//!
//! **`View Details` is what makes the second half legible.** A normalised identifier says
//! almost nothing about itself: `GB82WEST12345698765432` is a bank account in the United
//! Kingdom at a named institution and none of that is readable in the string. The card is
//! fetched from the scanner that produced the value, because the scanner is the only
//! thing that knows which rule accepted it, what that rule's validator checked, and what
//! acceptance does not prove.

use std::collections::BTreeMap;

use common::{
    document_entities::{DocumentEntitiesResponse, DocumentEntityItem, DocumentEntityType},
    entity_cards::EntityExplanation,
    search_result::DocumentIdentifier,
};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        md_action_icons::{MdAccountBalance, MdAccountBalanceWallet, MdDateRange, MdInfo},
        md_communication_icons::{MdBusiness, MdEmail, MdLocationOn, MdPhone},
        md_editor_icons::MdAttachMoney,
        md_navigation_icons::{MdChevronRight, MdExpandMore},
        md_social_icons::{MdDomain, MdPerson},
    },
};

use crate::api::search_api::explain_entity;
use crate::components::{
    chat_components::markdown_text::MarkdownishText,
    document_view_components::doc_viewer_full_page::ViewerPageControls,
    error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator,
};

/// Rows on one page of a section, and the most pages a section will offer.
///
/// A cap rather than a scroll: a mail archive routinely names two thousand addresses, and
/// a panel that renders all of them is a panel nobody scrolls to the bottom of. Ten pages
/// of fifty is five hundred values, ordered by occurrence count, which is past the point
/// where the list is answering a question about the document.
const PAGE_SIZE: usize = 50;
const MAX_PAGES: usize = 10;

/// The sections, in the order the panel lists them.
///
/// `Unknown` is last and is not dead weight: the scanner finds vessels, coordinates and
/// publications, none of which has a section, and they arrive here rather than
/// disappearing. A rule added upstream shows up as something to name.
const SECTIONS: [DocumentEntityType; 12] = [
    DocumentEntityType::Per,
    DocumentEntityType::Org,
    DocumentEntityType::Loc,
    DocumentEntityType::Misc,
    DocumentEntityType::Email,
    DocumentEntityType::Phone,
    DocumentEntityType::BankAccount,
    DocumentEntityType::CompanyId,
    DocumentEntityType::Money,
    DocumentEntityType::CryptoWallet,
    DocumentEntityType::MentionedDate,
    DocumentEntityType::Unknown,
];

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
            .filter(|i| {
                i.value.to_lowercase().contains(&filter)
                    || i.surface_text.to_lowercase().contains(&filter)
            })
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
        // A rule-found value has no model behind it, so a model filter must not sweep it
        // away: the two halves of the panel answer to different provenance.
        items
            .into_iter()
            .filter(|i| {
                i.entity_type.is_rule_found() || i.providers.iter().any(|p| *p == selected)
            })
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
                for entity_type in SECTIONS {
                    EntityGroup {
                        key: "{entity_type:?}",
                        entity_type,
                        items: items.clone(),
                        show_provider: multi_provider,
                    }
                }
            }
        }
    }
}

#[component]
fn EntityTypeIcon(entity_type: DocumentEntityType, style: String) -> Element {
    match entity_type {
        DocumentEntityType::Per => rsx! { Icon { icon: MdPerson, style } },
        DocumentEntityType::Org => rsx! { Icon { icon: MdBusiness, style } },
        DocumentEntityType::Loc => rsx! { Icon { icon: MdLocationOn, style } },
        DocumentEntityType::Email => rsx! { Icon { icon: MdEmail, style } },
        DocumentEntityType::Phone => rsx! { Icon { icon: MdPhone, style } },
        DocumentEntityType::BankAccount => rsx! { Icon { icon: MdAccountBalance, style } },
        DocumentEntityType::CompanyId => rsx! { Icon { icon: MdDomain, style } },
        DocumentEntityType::Money => rsx! { Icon { icon: MdAttachMoney, style } },
        DocumentEntityType::CryptoWallet => rsx! { Icon { icon: MdAccountBalanceWallet, style } },
        DocumentEntityType::MentionedDate => rsx! { Icon { icon: MdDateRange, style } },
        DocumentEntityType::Misc | DocumentEntityType::Unknown => {
            rsx! { Icon { icon: MdInfo, style } }
        }
    }
}

/// A bucket id as a reader should see it.
///
/// The stored id is canonical ASCII (`USD 10k-100k`) because a label spelling change must
/// never be a reindex. The en-dash is applied here, at render time, and only to the range
/// itself — never to the currency code in front of it.
fn render_bucket(bucket: &str) -> String {
    match bucket.split_once(' ') {
        Some((currency, range)) => format!("{currency} {}", range.replace('-', "\u{2013}")),
        None => bucket.to_string(),
    }
}

/// What a click on this value should search the page for.
///
/// The surface form, where the two differ. `+442075623419` never appears verbatim in a
/// document that wrote `+44 (0)20 7562 3419`, and searching the normalised value there
/// finds nothing while looking exactly like a broken chip.
fn find_query_for(item: &DocumentEntityItem) -> String {
    let needle = if item.surface_text.is_empty() { &item.value } else { &item.surface_text };
    format!("\"{needle}\"")
}

#[component]
fn EntityGroup(
    entity_type: DocumentEntityType,
    items: Vec<DocumentEntityItem>,
    show_provider: bool,
) -> Element {
    let mut expanded = use_signal(|| false);
    let mut page = use_signal(|| 0_usize);

    let group_items = items
        .into_iter()
        .filter(|i| i.entity_type == entity_type)
        .collect::<Vec<_>>();
    if group_items.is_empty() {
        return rsx! {};
    }

    let total = group_items.len();
    let pages = total.div_ceil(PAGE_SIZE).min(MAX_PAGES).max(1);
    let current = page().min(pages - 1);
    let start = current * PAGE_SIZE;
    let visible: Vec<DocumentEntityItem> =
        group_items.iter().skip(start).take(PAGE_SIZE).cloned().collect();
    let shown_cap = pages * PAGE_SIZE;
    let hidden = total.saturating_sub(shown_cap);
    // A card comes from the rule that produced the value, so the toggle appears when the
    // group holds at least one value that names one. Asking the SECTION instead would
    // deny cards to `Other`, which is where every scanner type without a section of its
    // own lands — CVEs, IMEIs, MAC addresses, autonomous-system numbers — each of them a
    // validated value the scanner can explain in full.
    let has_details = group_items.iter().any(|item| !item.rule_id.is_empty());
    let is_expanded = expanded() && has_details;

    rsx! {
        div {
            style: "
                margin: 10px 0;
                border-top: 1px solid rgba(0,0,0,0.1);
                padding-top: 10px;
            ",
            div {
                style: "display: flex; align-items: center; gap: 6px; margin: 0 0 8px 2px;",
                EntityTypeIcon {
                    entity_type,
                    style: "width: 16px; height: 16px; color: rgba(0,0,0,0.7); flex-shrink: 0;".to_string(),
                }
                div {
                    style: "font-size: 14px; font-weight: 700; color: rgba(0,0,0,0.75); flex: 1 1 auto;",
                    "{entity_type.label()}"
                }
                div { style: "font-size: 12px; color: rgba(0,0,0,0.5);", "{total}" }
                if has_details {
                    button {
                        style: "
                            border: 1px solid rgba(0,0,0,0.25); background: white;
                            border-radius: 999px; padding: 2px 9px; font-size: 12px;
                            cursor: pointer; display: inline-flex; align-items: center; gap: 3px;
                        ",
                        class: "hoover4-hover-shadow-background",
                        onclick: move |_| expanded.toggle(),
                        if is_expanded {
                            Icon { icon: MdExpandMore, style: "width: 14px; height: 14px;" }
                        } else {
                            Icon { icon: MdChevronRight, style: "width: 14px; height: 14px;" }
                        }
                        "View Details"
                    }
                }
            }

            if is_expanded && entity_type == DocumentEntityType::Money {
                MoneyCards { items: visible.clone() }
            } else if is_expanded {
                div {
                    style: "display: flex; flex-direction: column; gap: 10px;",
                    for item in visible.clone() {
                        {
                            // A value no rule produced has no card to open, so it stays a
                            // chip inside an expanded group. `Other` mixes the two, and a
                            // card that can only say "no details available" is worse than
                            // the chip it replaced.
                            let carded = !item.rule_id.is_empty();
                            let value = item.value.clone();
                            rsx! {
                                div {
                                    key: "{value}",
                                    if carded {
                                        EntityCard { item: item.clone() }
                                    } else {
                                        EntityChip { item: item.clone(), show_provider }
                                    }
                                }
                            }
                        }
                    }
                }
            } else {
                div {
                    style: "display: flex; flex-wrap: wrap; gap: 8px;",
                    for item in visible.clone() {
                        EntityChip { key: "{item.value}", item, show_provider }
                    }
                }
            }

            if pages > 1 {
                div {
                    style: "display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 12px;",
                    button {
                        style: "border: 1px solid rgba(0,0,0,0.25); background: white; border-radius: 6px; padding: 2px 8px; cursor: pointer;",
                        disabled: current == 0,
                        onclick: move |_| page.set(page().saturating_sub(1)),
                        "Previous"
                    }
                    span { style: "color: rgba(0,0,0,0.6);", "Page {current + 1} of {pages}" }
                    button {
                        style: "border: 1px solid rgba(0,0,0,0.25); background: white; border-radius: 6px; padding: 2px 8px; cursor: pointer;",
                        disabled: current + 1 >= pages,
                        onclick: move |_| page.set(current + 1),
                        "Next"
                    }
                    if hidden > 0 {
                        // The cap is not a bug and must not read as one: saying how many
                        // values are past it is the difference between a bounded list and
                        // a list that quietly lost things.
                        span {
                            style: "color: rgba(0,0,0,0.5);",
                            "{hidden} more not shown"
                        }
                    }
                }
            }
        }
    }
}

/// Money, one card per magnitude bucket.
///
/// A card per amount would be a page of near-identical cards saying the same thing about
/// ISO 4217; the bucket is what the facet files them under and therefore what a reader
/// clicking through to the corpus will get. The amounts stay reachable — each one is a
/// find-in-page click of its own, on the surface text the document actually wrote.
#[component]
fn MoneyCards(items: Vec<DocumentEntityItem>) -> Element {
    let mut by_bucket: BTreeMap<String, Vec<DocumentEntityItem>> = BTreeMap::new();
    for item in items {
        by_bucket.entry(item.bucket.clone()).or_default().push(item);
    }
    rsx! {
        div {
            style: "display: flex; flex-direction: column; gap: 10px;",
            for (bucket, group) in by_bucket {
                {
                    let first = group[0].clone();
                    rsx! {
                        div {
                            key: "{bucket}",
                            EntityCard {
                                item: first,
                                bucket_line: render_bucket(&bucket),
                                amounts: group.clone(),
                            }
                        }
                    }
                }
            }
        }
    }
}

/// One value's explainer card, fetched from the scanner.
///
/// The fetch never fails the panel. A scanner that is down, a rule with no catalogue
/// entry and a card this build cannot read all render as "no details available", because
/// the reader does the same thing in all three cases.
#[component]
fn EntityCard(
    item: DocumentEntityItem,
    /// Shown above the title, for a card that stands for a group rather than one value.
    #[props(default)]
    bucket_line: String,
    /// The individual amounts a money card covers, each a find-in-page click.
    #[props(default)]
    amounts: Vec<DocumentEntityItem>,
) -> Element {
    let rule_id = item.rule_id.clone();
    let value_json = item.value_json.clone();
    let surface = item.surface_text.clone();
    let card = use_resource(move || {
        let rule_id = rule_id.clone();
        let value_json = value_json.clone();
        let surface = surface.clone();
        async move {
            let surface = if surface.is_empty() { None } else { Some(surface) };
            explain_entity(rule_id, value_json, surface).await.ok().flatten()
        }
    });
    let page_controls = use_context::<ViewerPageControls>();
    let on_find_query_changed = page_controls.on_find_query_changed.clone();
    let mut show_amounts = use_signal(|| false);

    rsx! {
        div {
            style: "
                border: 1px solid rgba(0,0,0,0.18); border-radius: 10px;
                padding: 10px 12px; background: white;
            ",
            if !bucket_line.is_empty() {
                div {
                    style: "font-size: 12px; color: rgba(0,0,0,0.55);",
                    "({bucket_line})"
                }
            }
            match card.read().as_ref() {
                None => rsx! {
                    div { style: "font-size: 13px; color: rgba(0,0,0,0.5);", "Loading details…" }
                },
                Some(None) => rsx! {
                    div {
                        style: "font-weight: 600; font-size: 14px;",
                        "{item.value}"
                    }
                    div {
                        style: "font-size: 12px; color: rgba(0,0,0,0.55); margin-top: 2px;",
                        "No details available for this value."
                    }
                },
                Some(Some(explanation)) => rsx! {
                    EntityCardBody { explanation: explanation.clone(), value: item.value.clone() }
                },
            }
            if amounts.len() > 1 {
                div {
                    style: "margin-top: 8px;",
                    button {
                        style: "border: none; background: none; padding: 0; font-size: 12px; \
                                color: rgba(0,0,0,0.65); cursor: pointer; text-decoration: underline;",
                        onclick: move |_| show_amounts.toggle(),
                        if show_amounts() {
                            "Hide the {amounts.len()} amounts in this bucket"
                        } else {
                            "Show the {amounts.len()} amounts in this bucket"
                        }
                    }
                    if show_amounts() {
                        div {
                            style: "display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;",
                            for amount in amounts.clone() {
                                button {
                                    key: "{amount.value}",
                                    style: "
                                        border: 1px solid rgba(0,0,0,0.2); border-radius: 999px;
                                        background: white; padding: 2px 9px; font-size: 12px;
                                        cursor: pointer;
                                    ",
                                    class: "x-entity-chip",
                                    onclick: {
                                        let query = find_query_for(&amount);
                                        let on_find_query_changed = on_find_query_changed.clone();
                                        move |_| on_find_query_changed.call(query.clone())
                                    },
                                    "{amount.value}"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn EntityCardBody(explanation: EntityExplanation, value: String) -> Element {
    rsx! {
        div {
            style: "font-weight: 700; font-size: 14px;",
            "{explanation.title}"
        }
        if !explanation.subtitle.is_empty() {
            div {
                style: "font-size: 12px; color: rgba(0,0,0,0.6); margin-top: 1px;",
                "{explanation.subtitle}"
            }
        }
        div {
            style: "font-family: ui-monospace, monospace; font-size: 12px; margin-top: 6px; \
                    word-break: break-all; color: rgba(0,0,0,0.8);",
            "{value}"
        }
        if !explanation.body.is_empty() {
            div {
                style: "font-size: 13px; margin-top: 6px;",
                MarkdownishText { text: explanation.body.clone() }
            }
        }
        if !explanation.facts.is_empty() {
            div {
                style: "display: grid; grid-template-columns: auto 1fr; gap: 2px 10px; \
                        margin-top: 8px; font-size: 12px;",
                for fact in explanation.facts.clone() {
                    div {
                        key: "l{fact.label}",
                        style: "color: rgba(0,0,0,0.55); white-space: nowrap;",
                        "{fact.label}"
                    }
                    div { key: "v{fact.label}", "{fact.value}" }
                }
            }
        }
        if !explanation.references.is_empty() {
            div {
                style: "margin-top: 8px; display: flex; flex-direction: column; gap: 2px;",
                for link in explanation.references.clone() {
                    a {
                        key: "{link.url}",
                        href: "{link.url}",
                        target: "_blank",
                        rel: "noopener noreferrer",
                        title: "{link.note}",
                        style: "font-size: 12px; color: rgb(20,80,180);",
                        "{link.title}"
                    }
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
    let find_query = find_query_for(&item);
    // The bucket is part of what a money row says: `$25,000.00` on its own does not tell
    // a reader which facet bucket ticking through would land them in.
    let label = if item.bucket.is_empty() {
        item.value.clone()
    } else {
        format!("{} ({})", item.value, render_bucket(&item.bucket))
    };
    let title = if item.surface_text.is_empty() {
        item.value.clone()
    } else {
        format!("{}\nas written: {}", item.value, item.surface_text)
    };

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
            title: "{title}",
            onclick: move |_e| {
                _e.prevent_default();
                on_find_query_changed.call(find_query.clone());
            },
            div {
                style: "
                    max-width: 260px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    font-size: 13px;
                ",
                "{label}"
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

#[cfg(test)]
mod tests {
    use super::*;

    /// The en-dash is a render-time concern and never reaches storage, because a label
    /// spelling change must never be a reindex. It applies to the range and not to the
    /// currency code, which has no hyphen to confuse it.
    #[test]
    fn a_bucket_renders_with_an_en_dash_and_stores_with_a_hyphen() {
        assert_eq!(render_bucket("USD 10k-100k"), "USD 10k\u{2013}100k");
        assert_eq!(render_bucket("EUR under 1"), "EUR under 1");
        assert_eq!(render_bucket("JPY over 100M"), "JPY over 100M");
        assert_eq!(render_bucket(""), "");
    }

    /// A normalised phone number is not what the document wrote, so a find-in-page click
    /// on it finds nothing while looking exactly like a broken chip.
    #[test]
    fn a_click_searches_the_surface_form_where_there_is_one() {
        let mut item = DocumentEntityItem {
            entity_type: DocumentEntityType::Phone,
            value: "+442075623419".to_string(),
            hit_count: 1,
            providers: Vec::new(),
            rule_id: "phone.international".to_string(),
            value_json: String::new(),
            surface_text: "+44 (0)20 7562 3419".to_string(),
            bucket: String::new(),
        };
        assert_eq!(find_query_for(&item), "\"+44 (0)20 7562 3419\"");
        item.surface_text = String::new();
        assert_eq!(find_query_for(&item), "\"+442075623419\"");
    }
}
