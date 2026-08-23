//! The "All filters" modal and the chip row that summarises it.
//!
//! Replaces the pill strip. The strip put one button per facet in the top bar, which
//! worked for four facets and does not for eleven, and there was nowhere to put a
//! filter that is not a checkbox list (a size range, a date range, a folder tree).
//!
//! Three things carried over from the strip deliberately, because a rewrite loses them
//! by default and each one is needed:
//!
//! * **Hit counts** on every row. The mockups drop them; without them a filter list is a
//!   guess.
//! * **The amber partial-shard notice.** When a shard could not be searched the counts
//!   are lower than the truth, and saying so is the difference between a wrong number
//!   and a known-incomplete one.
//! * **`ResolveMissingItems`.** A value that is selected but absent from the current
//!   buckets still renders, with count 0. Without it a filter that narrows to nothing
//!   cannot be un-set, because the control that would un-set it is not on screen.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use common::{
    date_histogram::{DateHistogram, DateHistogramBucket},
    entity_cards::{EntityTermHit, EntityTermHits},
    filter_summary::{CHIP_SUMMARY_BUDGET, summarize_dates, summarize_size, summarize_values},
    search_query::{RangeFilter, SearchQuery},
    search_result::{FacetOriginalValue, SearchResultFacetItem},
    vfs::{node_key_display_name, node_key_display_path},
};
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        go_icons::GoDatabase,
        md_action_icons::{MdAccountBalance, MdAccountBalanceWallet, MdDateRange, MdInfo, MdSearch},
        md_communication_icons::{MdBusiness, MdEmail, MdLocationOn, MdPhone},
        md_content_icons::MdFilterList,
        md_device_icons::MdStorage,
        md_editor_icons::{MdAttachMoney, MdInsertDriveFile},
        md_image_icons::MdStraighten,
        md_navigation_icons::MdClose,
        md_social_icons::{MdDomain, MdPerson},
        md_toggle_icons::{
            MdCheckBox, MdCheckBoxOutlineBlank, MdRadioButtonChecked, MdRadioButtonUnchecked,
        },
    },
};

use crate::{
    api::search_api::{
        search_date_histogram, search_entity_terms, search_for_results_hit_count,
        search_mentioned_date_histogram, search_numeric_facet, search_string_facet,
    },
    components::{
        error_boundary::ServerErrorDisplay,
        search_components::{
            collections_facet_pane::CollectionsFacetPane,
            search_facets::{FacetCheckbox, FacetSelectorList},
            storage_tree::{StorageRow, StorageTree, node_keys_from_terms},
            vfs_tree::TreeSkin,
        },
        suspend_boundary::SuspendWrapper,
    },
};

/// The accent used for "this has filters" everywhere in the search UI. Reused rather
/// than reinvented: the pill strip's border was this colour and the dot must read as the
/// same signal.
const ACCENT: &str = "rgba(243,140,104,0.95)";

/// `struct_flags` values that mean "this email has attachments".
///
/// The flag is bit 0 of a bitfield and Manticore's `IN` cannot mask, so the filter
/// enumerates the values that have the bit set. Two bits exist today
/// (`email_has_attachments`, `truncated_ancestry`), so the set is {1, 3}. **Adding a
/// third flag means extending this list**, which is why it is one named constant with
/// this comment rather than a literal at the call site.
const STRUCT_FLAGS_WITH_ATTACHMENTS: [u64; 2] = [1, 3];

/// Every filter category, in the order the modal lists them.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FilterCategory {
    Collections,
    FileTypes,
    FileSize,
    FileLocation,
    Dates,
    Email,
    Entities,
}

impl FilterCategory {
    pub const ALL: [FilterCategory; 7] = [
        FilterCategory::Collections,
        FilterCategory::FileTypes,
        FilterCategory::FileSize,
        FilterCategory::FileLocation,
        FilterCategory::Dates,
        FilterCategory::Email,
        FilterCategory::Entities,
    ];

    pub fn label(&self) -> &'static str {
        match self {
            FilterCategory::Collections => "Collections",
            FilterCategory::FileTypes => "File types",
            FilterCategory::FileSize => "File size",
            FilterCategory::FileLocation => "File location",
            FilterCategory::Dates => "Date",
            FilterCategory::Email => "Email",
            FilterCategory::Entities => "Entities",
        }
    }

    /// The `facet_filters` keys this category owns.
    pub fn facet_fields(&self) -> &'static [&'static str] {
        match self {
            FilterCategory::Collections => &["collection_dataset"],
            FilterCategory::FileTypes => &["file_types"],
            FilterCategory::FileLocation => &["file_paths"],
            FilterCategory::Email => &["email_from", "email_to", "struct_flags"],
            FilterCategory::Entities => &EntitySub::VALUE_FIELDS,
            FilterCategory::FileSize | FilterCategory::Dates => &[],
        }
    }

    /// The `range_filters` keys this category owns.
    pub fn range_fields(&self) -> &'static [&'static str] {
        match self {
            FilterCategory::FileSize => &["file_size_bytes"],
            FilterCategory::Dates => &["dates"],
            // A mentioned date is an entity the scanner found, not a property of the
            // file, so it belongs to this category rather than to Date -- and it is the
            // only range filter Entities owns.
            FilterCategory::Entities => &["mentioned_dates"],
            _ => &[],
        }
    }

    /// Whether anything in this category is set in `query`. Drives the dot.
    pub fn is_active(&self, query: &SearchQuery) -> bool {
        self.facet_fields().iter().any(|field| {
            query.facet_filters.get(*field).is_some_and(|values| !values.is_empty())
        }) || self.range_fields().iter().any(|field| {
            query.range_filters.get(*field).is_some_and(|filter| filter.is_active())
        })
    }

    /// Remove everything this category owns from `query`.
    pub fn clear(&self, query: &mut SearchQuery) {
        for field in self.facet_fields() {
            query.facet_filters.remove(*field);
        }
        for field in self.range_fields() {
            query.range_filters.remove(*field);
        }
    }
}

/// The `string_term_id_to_text` field a facet's integer values are ids in, or `None`
/// when they are not term ids at all.
///
/// One table rather than a literal at each call site, because the same string is needed
/// twice for every facet (once by the pane that resolves ids into checkbox labels, once
/// by the chip row that resolves the same ids into its summary), and the two disagreeing
/// is a chip that says `#229645745` next to a list that says `enron`.
///
/// Facets with no term field: `collection_dataset` values are already text,
/// `struct_flags` is a bitfield (see [`STRUCT_FLAGS_WITH_ATTACHMENTS`]), and
/// `mentioned_dates` holds timestamps rather than terms. It is a range field, like
/// `dates`.
///
/// The scanner's fields are never `ner`. The website applies the entity stop-list to
/// whatever maps to that field, and the stop-list exists to drop what a *model*
/// mislabels; against a checksummed identifier it would only do damage. `re_email` is
/// likewise not `email_address`: that one is the envelope's sender and recipients, this
/// one is every address the body mentions, and a needle matching an address should return
/// a row under each because ticking them applies different filters.
pub fn term_field_of(facet_field: &str) -> Option<&'static str> {
    match facet_field {
        "file_types" => Some("filetype"),
        "file_paths" => Some("vfs_node"),
        "email_from" | "email_to" => Some("email_address"),
        "ner_per" | "ner_org" | "ner_loc" | "ner_misc" => Some("ner"),
        "re_email" => Some("regex_email"),
        "re_phone" => Some("regex_phone"),
        "re_bank_account" => Some("regex_bank_account"),
        "re_company_id" => Some("regex_company_id"),
        "re_money" => Some("regex_money"),
        "re_crypto_wallet" => Some("regex_crypto_wallet"),
        _ => None,
    }
}

/// The same, as the `map_string_terms` prop wants it.
fn term_field_prop(facet_field: &str) -> Option<String> {
    term_field_of(facet_field).map(str::to_string)
}

/// The chip row under the search box: one chip per active category.
#[component]
pub fn FilterChips(
    query: Signal<SearchQuery>,
    on_open: Callback<FilterCategory>,
    /// Run the search for the query these chips just edited.
    ///
    /// Removing a chip used to edit the pending query and stop, which left the result
    /// list and its heading describing a filter the chip row no longer showed, until the
    /// user noticed Apply Filters had lit up. A control that removes a filter has to
    /// remove it from the results too.
    on_commit: Callback<()>,
) -> Element {
    // Every term id the chips need text for, grouped by term field. A memo in front of
    // the resource, so the round trip happens when the SELECTION changes and not when
    // anything else in the query does. A resource reading `query` itself would resolve
    // the same ids again on every keystroke in the search box.
    let wanted = use_memo(move || term_ids_to_resolve(&query.read()));
    let texts = use_resource(move || {
        let wanted = wanted();
        async move { resolve_term_texts(wanted).await }
    });
    let chips = use_memo(move || {
        let texts = texts.read().clone();
        build_chips(&query.read(), texts.as_ref())
    });
    if chips().is_empty() {
        return rsx! {};
    }
    rsx! {
        div {
            id: "x-filter-chips",
            style: "display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 6px 10px;",
            for chip in chips() {
                {
                    let category = chip.category;
                    rsx! {
                        div {
                            key: "{chip.label}",
                            // The width budget. `min(320px, 28ch)`, the character half
                            // is applied to the text by the summariser, this is the
                            // pixel half.
                            style: "
                                display: inline-flex; align-items: center; gap: 6px;
                                max-width: min(320px, 28ch);
                                border: 1px solid {ACCENT}; border-radius: 100px;
                                background: rgba(243,140,104,0.10);
                                padding: 3px 6px 3px 10px; font-size: 14px; line-height: 20px;
                                cursor: pointer;
                            ",
                            // The full selection, always. The summary is lossy by design.
                            title: "{chip.full}",
                            onclick: move |_| on_open.call(category),
                            span {
                                style: "font-weight: 600; flex-shrink: 0;",
                                "{chip.label}"
                            }
                            span {
                                style: "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                                "{chip.summary}"
                            }
                            button {
                                style: "border: none; background: none; cursor: pointer; padding: 0; display: flex; align-items: center; flex-shrink: 0;",
                                class: "x-hover-color-red",
                                title: "Remove this filter",
                                onclick: move |event: Event<MouseData>| {
                                    event.stop_propagation();
                                    // Scoped so the borrow is released before the search
                                    // reads the signal it was just written through.
                                    category.clear(&mut query.write());
                                    on_commit.call(());
                                },
                                Icon { icon: MdClose, style: "width: 16px; height: 16px;" }
                            }
                        }
                    }
                }
            }
            button {
                style: "border: none; background: none; cursor: pointer; text-decoration: underline; font-size: 14px; color: rgba(0,0,0,0.7);",
                onclick: move |_| {
                    {
                        let mut q = query.write();
                        q.facet_filters.clear();
                        q.range_filters.clear();
                    }
                    on_commit.call(());
                },
                "Clear all"
            }
        }
    }
}

#[derive(Clone, PartialEq)]
pub struct Chip {
    pub category: FilterCategory,
    pub label: &'static str,
    pub summary: String,
    pub full: String,
}

/// The term ids the chip row has to resolve, grouped by the field they live in.
///
/// A `BTreeMap` of `BTreeSet`s so the value is stable and comparable: it feeds a memo,
/// and the point of the memo is that an unchanged selection is not fetched twice.
fn term_ids_to_resolve(query: &SearchQuery) -> BTreeMap<&'static str, BTreeSet<u64>> {
    let mut wanted: BTreeMap<&'static str, BTreeSet<u64>> = BTreeMap::new();
    for category in FilterCategory::ALL {
        for field in category.facet_fields() {
            let Some(term_field) = term_field_of(field) else {
                continue;
            };
            let Some(values) = query.facet_filters.get(*field) else {
                continue;
            };
            for value in values {
                if let FacetOriginalValue::Int(id) = value {
                    wanted.entry(term_field).or_default().insert(*id);
                }
            }
        }
    }
    wanted
}

/// Resolve every id the chips need, in ONE call per term field.
///
/// Not one per chip and certainly not one per value: a folder filter is routinely twenty
/// node keys, and the endpoint takes a list. Term ids are content hashes of the term text
/// alone, so ids from different fields cannot be confused in one flat map.
async fn resolve_term_texts(
    wanted: BTreeMap<&'static str, BTreeSet<u64>>,
) -> HashMap<u64, String> {
    let mut texts = HashMap::new();
    for (term_field, ids) in wanted {
        let resolved = crate::api::search_api::fetch_db_terms_for_ints(
            ids.into_iter().collect(),
            term_field.to_string(),
        )
        .await
        .unwrap_or_default();
        texts.extend(resolved);
    }
    texts
}

/// One chip per active category, summarised inside the budget.
///
/// `texts` is `None` while the term lookup is in flight. The chips render then too, and
/// a value that has no text yet says so rather than flashing a raw id first.
fn build_chips(query: &SearchQuery, texts: Option<&HashMap<u64, String>>) -> Vec<Chip> {
    let mut chips = Vec::new();
    for category in FilterCategory::ALL {
        if !category.is_active(query) {
            continue;
        }
        let (summary, full) = match category {
            FilterCategory::FileSize => {
                let filter = query.range_filters.get("file_size_bytes").cloned().unwrap_or_default();
                let text = summarize_size(&filter);
                (text.clone(), text)
            }
            FilterCategory::Dates => {
                let filter = query.range_filters.get("dates").cloned().unwrap_or_default();
                let text = summarize_dates(&filter, epoch_to_iso_date);
                (text.clone(), text)
            }
            other => {
                // Two lists, because the chip and its tooltip answer different
                // questions: `enron` is what fits, `/disk-files/enron` is which one.
                let mut short: Vec<String> = Vec::new();
                let mut long: Vec<String> = Vec::new();
                // Entities is the one category with both a facet half and a range half.
                // The range half is prefixed rather than rendered like a Date chip:
                // `Mentioned 1998–2004` next to `Date 1998–2004` says which question was
                // asked, and two chips reading the same words would not.
                if other == FilterCategory::Entities
                    && let Some(filter) = query.range_filters.get("mentioned_dates")
                    && filter.is_active()
                {
                    let text = format!("Mentioned {}", summarize_dates(filter, epoch_to_iso_date));
                    short.push(text.clone());
                    long.push(text);
                }
                for field in other.facet_fields() {
                    let Some(set) = query.facet_filters.get(*field) else {
                        continue;
                    };
                    if set.is_empty() {
                        continue;
                    }
                    // `struct_flags` is a bitfield whose selected set is the enumeration
                    // of the values carrying one bit, one label covers all of them, and
                    // there is no term dictionary to look them up in.
                    if *field == "struct_flags" {
                        short.push("Has attachments".to_string());
                        long.push("Has attachments".to_string());
                        continue;
                    }
                    for value in set {
                        let (chip_text, full_text) = display_value(field, value, texts);
                        short.push(chip_text);
                        long.push(full_text);
                    }
                }
                (summarize_values(&short, CHIP_SUMMARY_BUDGET), long.join(", "))
            }
        };
        if summary.is_empty() {
            continue;
        }
        chips.push(Chip { category, label: category.label(), summary, full });
    }
    chips
}

/// A facet value as `(chip text, tooltip text)`.
///
/// The query stores term IDS, so the text comes from `texts`, the batch the chip row
/// resolved for the whole selection. `None` means that batch is still in flight; a
/// resolved batch missing an id means the term row is gone (a purged dataset) or its
/// collection is unreadable, and then the raw id is what the row shows: it still says a
/// filter exists and still lets it be removed.
fn display_value(
    field: &str,
    value: &FacetOriginalValue,
    texts: Option<&HashMap<u64, String>>,
) -> (String, String) {
    let int_text = |i: &u64| match texts {
        None => None,
        Some(texts) => Some(texts.get(i).cloned().unwrap_or_else(|| format!("#{i}"))),
    };
    match value {
        FacetOriginalValue::String(s) => (s.clone(), s.clone()),
        FacetOriginalValue::Int(i) => match int_text(i) {
            // A `vfs_node` term value IS the node key, which is machine text.
            Some(text) if field == "file_paths" => (
                node_key_display_name(&text).to_string(),
                node_key_display_path(&text).to_string(),
            ),
            Some(text) => (text.clone(), text),
            None => ("…".to_string(), "…".to_string()),
        },
    }
}

/// `YYYY-MM-DD` for a signed epoch-second value, for the date inputs and the chip.
///
/// Civil-from-days rather than a date library, and `div_euclid` rather than `/`, because
/// this has to be right for negative values: `-1` is 1969-12-31, and truncating division
/// puts it in 1970.
pub fn epoch_to_iso_date(epoch_seconds: i64) -> String {
    let days = epoch_seconds.div_euclid(86_400);
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = if m <= 2 { y + 1 } else { y };
    format!("{y:04}-{m:02}-{d:02}")
}

/// The inverse: `YYYY-MM-DD` to epoch seconds at midnight UTC. `None` for anything that
/// is not a complete date. A half-typed `2013-` must not become a filter.
pub fn iso_date_to_epoch(text: &str) -> Option<i64> {
    let mut parts = text.split('-');
    let y: i64 = parts.next()?.parse().ok()?;
    let m: i64 = parts.next()?.parse().ok()?;
    let d: i64 = parts.next()?.parse().ok()?;
    if parts.next().is_some() || !(1..=12).contains(&m) || !(1..=31).contains(&d) {
        return None;
    }
    let y_adj = if m <= 2 { y - 1 } else { y };
    let era = y_adj.div_euclid(400);
    let yoe = y_adj - era * 400;
    let mp = if m > 2 { m - 3 } else { m + 9 };
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some(days * 86_400)
}


// ---------------------------------------------------------------------------------
// The modal
// ---------------------------------------------------------------------------------

const OVERLAY_STYLE: &str = "
    position: fixed; inset: 0; z-index: 2000;
    background: rgba(0,0,0,0.35);
    display: flex; align-items: center; justify-content: center;
";

const DIALOG_STYLE: &str = "
    background: white; border-radius: 12px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.3);
    width: min(920px, 94vw); height: min(660px, 90vh);
    display: flex; flex-direction: column; overflow: hidden;
";

const CATEGORY_LIST_STYLE: &str = "
    width: 210px; flex-shrink: 0; border-right: 1px solid rgba(0,0,0,0.12);
    overflow-y: auto; padding: 6px 0;
";

const PANE_STYLE: &str = "
    flex: 1 1 auto; min-width: 0; overflow-y: auto; padding: 12px 16px;
";

const FOOTER_STYLE: &str = "
    display: flex; align-items: center; gap: 12px;
    border-top: 1px solid rgba(0,0,0,0.12); padding: 10px 16px;
";

const INPUT_STYLE: &str = "
    border: 1px solid rgba(0,0,0,0.3); border-radius: 6px;
    padding: 5px 8px; font-size: 15px; min-width: 0;
";

/// The "All filters" modal. Edits a PENDING copy of the query; nothing reaches the URL
/// until `Show N results`.
#[component]
pub fn FilterModal(
    original_query: ReadSignal<SearchQuery>,
    pending: Signal<SearchQuery>,
    open_category: Signal<Option<FilterCategory>>,
    on_apply: Callback<()>,
) -> Element {
    let Some(active) = *open_category.read() else {
        return rsx! {};
    };

    rsx! {
        div {
            style: "{OVERLAY_STYLE}",
            onclick: move |_| open_category.set(None),
            div {
                // Named so a script or a test can scope a click to the dialog. Text like
                // a dataset name appears both here and on the result cards behind the
                // overlay, and a document-wide search finds the wrong one.
                id: "x-filter-modal",
                style: "{DIALOG_STYLE}",
                // The dialog is inside the click-away overlay, so it has to stop clicks
                // that land on it from closing the thing they landed on.
                onclick: move |event: Event<MouseData>| event.stop_propagation(),

                div {
                    style: "display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid rgba(0,0,0,0.12);",
                    Icon { icon: MdFilterList, style: "width: 22px; height: 22px; color: rgba(0,0,0,0.8);" }
                    div { style: "font-size: 18px; font-weight: 600; flex: 1 1 auto;", "All filters" }
                    button {
                        style: "border: none; background: none; cursor: pointer; display: flex;",
                        class: "x-hover-color-red",
                        title: "Close without applying",
                        onclick: move |_| open_category.set(None),
                        Icon { icon: MdClose, style: "width: 22px; height: 22px;" }
                    }
                }

                div {
                    style: "flex: 1 1 auto; display: flex; min-height: 0;",

                    div {
                        style: "{CATEGORY_LIST_STYLE}",
                        for category in FilterCategory::ALL {
                            {
                                let is_active = category.is_active(&pending.read());
                                let is_selected = category == active;
                                // rsx! string interpolation takes an expression, not a
                                // block, so conditionals are resolved here.
                                let selected_background =
                                    if is_selected { "rgba(0,0,0,0.06)" } else { "none" };
                                rsx! {
                                    button {
                                        key: "{category:?}",
                                        class: "x-facet-list-item",
                                        style: "
                                            display: flex; align-items: center; gap: 8px;
                                            width: 100%; border: none; text-align: left;
                                            padding: 8px 12px; font-size: 15px; cursor: pointer;
                                            background: {selected_background};
                                        ",
                                        onclick: move |_| open_category.set(Some(category)),
                                        // Fixed 16 px slot so labels stay aligned whether
                                        // or not the dot is there.
                                        div {
                                            style: "width: 16px; flex-shrink: 0; display: flex; align-items: center; justify-content: center;",
                                            if is_active {
                                                div { style: "width: 8px; height: 8px; border-radius: 50%; background: {ACCENT};" }
                                            }
                                        }
                                        CategoryIcon { category }
                                        "{category.label()}"
                                    }
                                }
                            }
                        }
                    }

                    div {
                        style: "{PANE_STYLE}",
                        match active {
                            FilterCategory::Collections => rsx! {
                                CollectionsFacetPane { original_query, pending }
                            },
                            FilterCategory::FileTypes => rsx! {
                                SearchableFacetPane {
                                    original_query, pending,
                                    field: "file_types".to_string(),
                                    map_string_terms: term_field_prop("file_types"),
                                    placeholder: "Search file types…".to_string(),
                                    // A handful of buckets, all on screen, and no rows in
                                    // the term table: a corpus-wide search would answer
                                    // nothing for every needle.
                                    server_side: false,
                                }
                            },
                            FilterCategory::FileSize => rsx! {
                                FileSizePane { original_query, pending }
                            },
                            FilterCategory::FileLocation => rsx! {
                                FileLocationPane { pending }
                            },
                            FilterCategory::Dates => rsx! {
                                DatePane { original_query, pending }
                            },
                            FilterCategory::Email => rsx! {
                                EmailPane { original_query, pending }
                            },
                            FilterCategory::Entities => rsx! {
                                EntitiesPane { original_query, pending }
                            },
                        }
                    }
                }

                FilterModalFooter { pending, open_category, on_apply }
            }
        }
    }
}

#[component]
fn CategoryIcon(category: FilterCategory) -> Element {
    let style = "width: 18px; height: 18px; color: rgba(0,0,0,0.65); flex-shrink: 0;";
    match category {
        FilterCategory::Collections => rsx! { Icon { icon: GoDatabase, style } },
        FilterCategory::FileTypes => rsx! { Icon { icon: MdInsertDriveFile, style } },
        FilterCategory::FileSize => rsx! { Icon { icon: MdStraighten, style } },
        FilterCategory::FileLocation => rsx! { Icon { icon: MdStorage, style } },
        FilterCategory::Dates => rsx! { Icon { icon: MdDateRange, style } },
        FilterCategory::Email => rsx! { Icon { icon: MdEmail, style } },
        FilterCategory::Entities => rsx! { Icon { icon: MdPerson, style } },
    }
}

/// `Clear all` / `Cancel` / `Show N results`.
///
/// The count is the PENDING query's hit count, debounced, and the button never blocks on
/// it: a filter modal that goes unresponsive while it counts is worse than one that
/// shows a slightly stale number. The previous value stays on screen, greyed, while a
/// new one is in flight.
#[component]
fn FilterModalFooter(
    pending: Signal<SearchQuery>,
    open_category: Signal<Option<FilterCategory>>,
    on_apply: Callback<()>,
) -> Element {
    let mut debounced = use_signal(|| pending.read().clone());
    let mut last_count = use_signal(|| None::<u64>);

    // 300 ms of quiet before asking the server. Ticking through a list of file types
    // would otherwise fire one fan-out per click.
    use_effect(move || {
        let q = pending.read().clone();
        spawn(async move {
            // `n0_future::time::sleep`, never `gloo_timers`: gloo's futures feature is
            // wasm-only and this component also compiles into the server binary.
            n0_future::time::sleep(std::time::Duration::from_millis(300)).await;
            if *pending.peek() == q {
                debounced.set(q);
            }
        });
    });

    let count = use_resource(move || {
        let q = debounced.read().clone();
        search_for_results_hit_count(q)
    });

    let in_flight = count.read().is_none();
    if let Some(Ok(value)) = count.read().as_ref() {
        let total = value.total;
        if last_count.peek().as_ref() != Some(&total) {
            last_count.set(Some(total));
        }
    }

    // Greyed while a fresh count is in flight, showing the previous value rather than
    // blanking: a number that flickers to nothing on every keystroke is worse than a
    // number that is briefly one edit behind.
    let count_opacity = if in_flight { "0.75" } else { "1" };

    rsx! {
        div {
            style: "{FOOTER_STYLE}",
            button {
                style: "border: none; background: none; cursor: pointer; text-decoration: underline; font-size: 15px;",
                onclick: move |_| {
                    let mut q = pending.write();
                    q.facet_filters.clear();
                    q.range_filters.clear();
                },
                "Clear all"
            }
            div { style: "flex: 1 1 auto;" }
            button {
                style: "border: 1px solid rgba(0,0,0,0.3); background: white; border-radius: 100px; padding: 8px 18px; cursor: pointer; font-size: 15px;",
                class: "hoover4-hover-shadow-background",
                onclick: move |_| open_category.set(None),
                "Cancel"
            }
            button {
                style: "
                    border: none; background: rgba(0,0,255,1.0); color: white;
                    border-radius: 100px; padding: 8px 18px; cursor: pointer;
                    font-size: 15px; font-weight: 600;
                    opacity: {count_opacity};
                ",
                onclick: move |_| {
                    open_category.set(None);
                    on_apply.call(());
                },
                match *last_count.read() {
                    Some(total) => format!("Show {total} results"),
                    None => "Show results".to_string(),
                }
            }
        }
    }
}

/// A checkbox facet list with a search box over its own values.
///
/// Two kinds of search box, and which one a facet gets is a property of the facet.
///
/// `file_types` narrows CLIENT-SIDE, because it has a handful of buckets and every one of
/// them is already on screen. Everything else asks the corpus: a facet pane holds the top
/// twenty-one buckets of one query, so narrowing those answers "nothing matches" for a
/// value that is present and merely unpopular, which on a corpus with tens of thousands
/// of distinct addresses is nearly every value anybody types.
///
/// The corpus-wide path resolves the needle to term ids (`search_entity_terms`), hands
/// them to the facet query as `restrict_to_ids`, and shows Manticore's own highlight as
/// each row's reason for being there.
#[component]
fn SearchableFacetPane(
    original_query: ReadSignal<SearchQuery>,
    pending: Signal<SearchQuery>,
    /// A SIGNAL rather than a `String`, and the difference decides correctness. The Entities rail renders one
    /// instance of this pane for eleven of its twelve children, so switching child hands
    /// the SAME component a different field. A plain prop is read once into the hooks
    /// below and never again: the corpus-wide term search would keep asking about the
    /// column the reader left, and answer the column they are looking at with its term
    /// ids, which renders as "nothing matches" for a value the facet plainly holds.
    field: ReadSignal<String>,
    map_string_terms: ReadSignal<Option<String>>,
    placeholder: String,
    /// Ask the corpus rather than the buckets on screen. False only for a facet whose
    /// values are few enough to all be visible.
    #[props(default = true)]
    server_side: bool,
    /// A needle owned by a parent, for the merged view that drives ten panes at once.
    /// When set, this pane draws no box of its own.
    #[props(default)]
    shared_needle: Option<ReadSignal<String>>,
) -> Element {
    let owns_box = shared_needle.is_none();
    let mut own_needle = use_signal(String::new);
    // The box empties when the field under it changes. A needle typed for one list is
    // not a needle for the next one, and leaving it in place narrows a list the reader
    // never typed into.
    use_effect(move || {
        let _ = field.read();
        own_needle.set(String::new());
    });
    let needle: ReadSignal<String> = match shared_needle {
        Some(shared) => shared,
        None => ReadSignal::from(own_needle),
    };
    let hits = use_entity_term_search(original_query, needle, move || vec![field.read().clone()],
                                      server_side);
    let restrict_to_ids = use_memo(move || hits.read().as_ref().map(EntityTermHits::term_ids));
    let match_reasons = use_memo(move || match_reason_map(hits.read().as_ref()));
    // The client-side needle is only handed on when nothing else narrowed: passing both
    // would filter the server's answer a second time, against a display string that the
    // needle matched somewhere the label does not show.
    let client_needle = use_memo(move || {
        if server_side { String::new() } else { needle.read().clone() }
    });

    rsx! {
        if owns_box {
            div {
                style: "display: flex; align-items: center; gap: 6px; margin-bottom: 8px;",
                Icon { icon: MdSearch, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.5);" }
                input {
                    r#type: "text",
                    style: "{INPUT_STYLE} flex: 1 1 auto;",
                    placeholder: "{placeholder}",
                    value: "{own_needle}",
                    oninput: move |event| own_needle.set(event.value()),
                }
            }
        }
        SuspendWrapper {
            FacetSelectorList {
                original_query,
                modified_search_query: pending,
                facet_field_name: field,
                map_string_terms,
                needle: ReadSignal::from(client_needle),
                restrict_to_ids: ReadSignal::from(restrict_to_ids),
                match_reasons: ReadSignal::from(match_reasons),
            }
        }
    }
}

/// Resolve a debounced needle to term ids, or `None` while there is no needle.
///
/// Debounced at the same 300 ms the footer's hit count uses, because the alternative is
/// one Manticore fan-out per keystroke. The result is `None`, not an empty list, when
/// the box is empty, and the difference is carried all the way down: `None` means
/// "show the whole facet", `Some([])` means "the needle matched nothing".
fn use_entity_term_search(
    original_query: ReadSignal<SearchQuery>,
    needle: ReadSignal<String>,
    columns: impl Fn() -> Vec<String> + Clone + 'static,
    server_side: bool,
) -> Memo<Option<EntityTermHits>> {
    let mut debounced = use_signal(String::new);
    use_effect(move || {
        let text = needle.read().trim().to_string();
        spawn(async move {
            n0_future::time::sleep(std::time::Duration::from_millis(300)).await;
            if needle.peek().trim() == text {
                debounced.set(text);
            }
        });
    });
    let resource = use_resource(move || {
        let query = original_query.read().clone();
        let text = debounced.read().clone();
        let columns = columns();
        async move {
            if !server_side || text.is_empty() {
                return None;
            }
            search_entity_terms(query, text, columns).await.ok()
        }
    });
    use_memo(move || resource.read().clone().flatten())
}

/// Hits by term id, for the reason line under each row.
fn match_reason_map(hits: Option<&EntityTermHits>) -> HashMap<u64, EntityTermHit> {
    hits.map(|hits| {
        hits.hits.iter().map(|hit| (hit.term_id, hit.clone())).collect()
    })
    .unwrap_or_default()
}

#[component]
fn FileSizePane(original_query: ReadSignal<SearchQuery>, pending: Signal<SearchQuery>) -> Element {
    let buckets = use_resource(move || {
        let q = original_query.read().clone();
        search_numeric_facet(q)
    });

    let current = use_memo(move || {
        pending.read().range_filters.get("file_size_bytes").cloned().unwrap_or_default()
    });
    // The custom inputs are in MB because that is the unit a person thinks in; bytes go
    // on the wire.
    let mut min_mb = use_signal(String::new);
    let mut max_mb = use_signal(String::new);

    let apply_custom = move |_| {
        let parse = |raw: String| -> Option<i64> {
            let text = raw.trim().to_string();
            if text.is_empty() { return None; }
            text.parse::<f64>().ok().map(|mb| (mb * 1_048_576.0).round() as i64)
        };
        let min = parse(min_mb.read().clone());
        let max = parse(max_mb.read().clone());
        let mut q = pending.write();
        if min.is_none() && max.is_none() {
            q.range_filters.remove("file_size_bytes");
        } else {
            q.range_filters.insert(
                "file_size_bytes".to_string(),
                RangeFilter { min, max, include_unknown: false },
            );
        }
    };

    let inverted = use_memo(move || {
        let parse = |raw: String| raw.trim().parse::<f64>().ok();
        match (parse(min_mb.read().clone()), parse(max_mb.read().clone())) {
            (Some(lo), Some(hi)) => lo > hi,
            _ => false,
        }
    });

    rsx! {
        div {
            style: "display: flex; flex-direction: column; gap: 4px;",
            match buckets.read().as_ref() {
                None => rsx! { div { style: "color: rgba(0,0,0,0.5);", "Counting…" } },
                Some(Err(error)) => rsx! {
                    div {
                        class: "x-error-display",
                        style: "color: rgb(160,30,30);",
                        "Could not load size buckets: {error}"
                    }
                },
                Some(Ok(result)) => rsx! {
                    if result.partial {
                        PartialNotice {}
                    }
                    for item in result.facet_values.clone() {
                        {
                            let bucket = match item.original_value {
                                FacetOriginalValue::Int(i) => i as usize,
                                _ => 0,
                            };
                            let (min, max) = bucket_range(bucket);
                            let selected = current() == RangeFilter { min, max, include_unknown: false };
                            rsx! {
                                div {
                                    key: "{item.display_string}",
                                    class: "x-facet-list-item",
                                    style: "display: flex; align-items: center; gap: 10px; padding: 5px 4px; cursor: pointer;",
                                    onclick: move |_| {
                                        let mut q = pending.write();
                                        if selected {
                                            q.range_filters.remove("file_size_bytes");
                                        } else {
                                            q.range_filters.insert(
                                                "file_size_bytes".to_string(),
                                                RangeFilter { min, max, include_unknown: false },
                                            );
                                        }
                                        min_mb.set(String::new());
                                        max_mb.set(String::new());
                                    },
                                    if selected {
                                        Icon { icon: MdCheckBox, style: "width: 22px; height: 22px; color: rgb(28,33,45);" }
                                    } else {
                                        Icon { icon: MdCheckBoxOutlineBlank, style: "width: 22px; height: 22px; color: rgba(0,0,0,0.6);" }
                                    }
                                    div { style: "flex: 1 1 auto;", "{item.display_string}" }
                                    div { style: "color: rgba(0,0,0,0.6);", "{item.count}" }
                                }
                            }
                        }
                    }
                },
            }

            div {
                style: "display: flex; align-items: center; gap: 10px; margin: 10px 0 6px;",
                div { style: "flex: 1 1 auto; height: 1px; background: rgba(0,0,0,0.15);" }
                div { style: "color: rgba(0,0,0,0.5); font-size: 13px;", "Or" }
                div { style: "flex: 1 1 auto; height: 1px; background: rgba(0,0,0,0.15);" }
            }

            div {
                style: "display: flex; align-items: center; gap: 8px; flex-wrap: wrap;",
                span { style: "font-size: 14px;", "Between" }
                input {
                    r#type: "number", min: "0", step: "0.1",
                    style: "{INPUT_STYLE} width: 90px;",
                    placeholder: "min",
                    value: "{min_mb}",
                    oninput: move |event| min_mb.set(event.value()),
                    onchange: apply_custom,
                }
                span { style: "font-size: 14px;", "and" }
                input {
                    r#type: "number", min: "0", step: "0.1",
                    style: "{INPUT_STYLE} width: 90px;",
                    placeholder: "max",
                    value: "{max_mb}",
                    oninput: move |event| max_mb.set(event.value()),
                    onchange: apply_custom,
                }
                span { style: "font-size: 14px;", "MB" }
            }
            if inverted() {
                div {
                    style: "color: rgb(160,30,30); font-size: 13px; margin-top: 4px;",
                    "The minimum is larger than the maximum."
                }
            }
        }
    }
}

/// `(min, max)` bytes for a bucket index, mirroring the server's `INTERVAL()` edges.
fn bucket_range(bucket: usize) -> (Option<i64>, Option<i64>) {
    const EDGES: [i64; 3] = [1_048_576, 10_485_760, 104_857_600];
    match bucket {
        0 => (Some(0), Some(EDGES[0] - 1)),
        1 => (Some(EDGES[0]), Some(EDGES[1] - 1)),
        2 => (Some(EDGES[1]), Some(EDGES[2] - 1)),
        _ => (Some(EDGES[2]), None),
    }
}

/// Five mutually exclusive states, because they are five different questions: no filter,
/// a low-pass, a high-pass, a band-pass, and "documents we could not date at all".
///
/// All three range modes were already expressible on the wire: `RangeFilter`'s bounds
/// are `Option`s and `range_predicate` has always turned a missing one into an open end,
/// but the pane offered one "Custom range…" row with two boxes, so the only way to ask
/// for "everything after 2016" was to know that leaving a box blank meant that.
#[component]
fn DatePane(
    original_query: ReadSignal<SearchQuery>,
    pending: Signal<SearchQuery>,
    /// Which range filter this pane edits: `dates` for the document's own dates,
    /// `mentioned_dates` for the days its text names.
    ///
    /// One component over two fields rather than two components. Everything visible here
    /// (the five modes, the ISO parsing, the inverted-range error, the histogram
    /// brushing, the unknown-only toggle) is identical for both, and a copy would drift
    /// until the two date panes behaved differently for no reason a user could see.
    #[props(default = "dates".to_string())]
    field: String,
) -> Element {
    let mentions = field == "mentioned_dates";
    // A `Signal` rather than the `String` prop: every closure below is stored in an
    // `rsx!` handler or a `Callback`, which needs them `Copy`, and a captured `String`
    // is not. The signal is written once and read everywhere.
    let filter_key = use_signal(|| field.clone());
    let current = use_memo(move || {
        pending.read().range_filters.get(&filter_key.read().clone()).cloned().unwrap_or_default()
    });

    // The mode a person picked outlives a half-filled filter. Without that, "Between"
    // survives only until the first of its two boxes is typed into: one bound and no
    // other reads as "After", which moves the radio and takes the second box off screen
    // before it can be filled, so a closed range cannot be entered at all. `sticky` is
    // empty only before anything is picked and after a page arrives carrying a filter in
    // its URL, and the bounds are what names the mode in both of those.
    let mut sticky = use_signal(|| None::<DateMode>);
    let mode = use_memo(move || date_mode(&current(), sticky()));

    // The histogram's bin edges depend on the cutoffs, so it is the pending query that
    // goes over the wire. Debounced for the same reason the footer count is, or dragging
    // a date field fires one fan-out per keystroke.
    let mut debounced = use_signal(move || pending.peek().clone());
    use_effect(move || {
        let q = pending.read().clone();
        spawn(async move {
            n0_future::time::sleep(std::time::Duration::from_millis(300)).await;
            if *pending.peek() == q {
                debounced.set(q);
            }
        });
    });
    let histogram = use_resource(move || {
        let q = debounced.read().clone();
        async move {
            if mentions {
                search_mentioned_date_histogram(q).await
            } else {
                search_date_histogram(q).await
            }
        }
    });

    let mut set_filter = move |min: Option<i64>, max: Option<i64>| {
        let key = filter_key.peek().clone();
        let mut q = pending.write();
        let filter = RangeFilter { min, max, include_unknown: false };
        if filter.is_active() {
            q.range_filters.insert(key, filter);
        } else {
            q.range_filters.remove(&key);
        }
    };

    let mut set_bound = move |which: &'static str, text: String| {
        let epoch = iso_date_to_epoch(&text);
        let filter = current();
        match which {
            "min" => set_filter(epoch, filter.max),
            _ => set_filter(filter.min, epoch),
        }
    };

    // Switching mode reinterprets the bounds you already gave rather than discarding
    // them: going from "after 2016" to "before" should hand 2016 to the other end, not
    // silently clear the filter.
    let mut set_mode = move |target: DateMode| {
        sticky.set(Some(target));
        let filter = current();
        match target {
            DateMode::Off => {
                let key = filter_key.peek().clone();
                pending.write().range_filters.remove(&key);
            }
            DateMode::UnknownOnly => {
                let key = filter_key.peek().clone();
                pending.write().range_filters.insert(
                    key,
                    RangeFilter { min: None, max: None, include_unknown: true },
                );
            }
            DateMode::Before => set_filter(None, filter.max.or(filter.min)),
            DateMode::After => set_filter(filter.min.or(filter.max), None),
            DateMode::Between => set_filter(filter.min, filter.max),
        }
    };

    let on_bucket = Callback::new(move |bucket: DateHistogramBucket| {
        // A click means whatever the mode says it means. In the two modes with no cutoff
        // to move (no filtering, and unknown-only), the click means "this bin", which is the
        // only reading available and is what the tooltip promises.
        match mode() {
            DateMode::Before => set_filter(None, Some(bucket.end - 1)),
            DateMode::After => set_filter(Some(bucket.start), None),
            _ => {
                sticky.set(Some(DateMode::Between));
                set_filter(Some(bucket.start), Some(bucket.end - 1));
            }
        }
    });

    let on_unknown = Callback::new(move |_| set_mode(DateMode::UnknownOnly));

    rsx! {
        div {
            style: "display: flex; flex-direction: column; gap: 6px;",
            for (label, target) in DateMode::ROWS {
                div {
                    key: "{label}",
                    class: "x-facet-list-item",
                    style: "display: flex; align-items: center; gap: 10px; padding: 5px 4px; cursor: pointer;",
                    onclick: move |_| set_mode(target),
                    if mode() == target {
                        Icon { icon: MdRadioButtonChecked, style: "width: 20px; height: 20px; color: rgb(28,33,45);" }
                    } else {
                        Icon { icon: MdRadioButtonUnchecked, style: "width: 20px; height: 20px; color: rgba(0,0,0,0.6);" }
                    }
                    "{label}"
                }
            }

            // Only the boxes the mode actually uses: an always-visible inert date field
            // invites people to type into something that does nothing.
            if mode().shows_min() || mode().shows_max() {
                div {
                    style: "display: flex; align-items: center; gap: 8px; padding: 6px 0 0 30px; flex-wrap: wrap;",
                    if mode().shows_min() {
                        span { style: "font-size: 14px;", "From" }
                        input {
                            r#type: "date",
                            style: "{INPUT_STYLE}",
                            value: "{current().min.map(epoch_to_iso_date).unwrap_or_default()}",
                            oninput: move |event| set_bound("min", event.value()),
                        }
                    }
                    if mode().shows_max() {
                        span { style: "font-size: 14px;", if mode() == DateMode::Between { "to" } else { "Before" } }
                        input {
                            r#type: "date",
                            style: "{INPUT_STYLE}",
                            value: "{current().max.map(epoch_to_iso_date).unwrap_or_default()}",
                            oninput: move |event| set_bound("max", event.value()),
                        }
                    }
                }
                div {
                    style: "font-size: 13px; color: rgba(0,0,0,0.6); padding-left: 30px;",
                    if mentions {
                        // Not the same sentence as the one below it, and the difference
                        // is the whole feature: a document naming 1936 and 2020 mentions
                        // neither 2005 nor anything between them.
                        "A document matches if any single date its text names falls in the range."
                    } else {
                        "A document matches if any of its confirmed dates falls in the range."
                    }
                }
            }

            div {
                style: "margin-top: 14px; border-top: 1px solid rgba(0,0,0,0.12); padding-top: 8px;",
                match histogram.read().as_ref() {
                    None => rsx! { div { style: "color: rgba(0,0,0,0.5);", "Counting…" } },
                    Some(Err(error)) => rsx! {
                        div {
                            class: "x-error-display",
                            style: "color: rgb(160,30,30);",
                            "Could not load the histogram: {error}"
                        }
                    },
                    Some(Ok(result)) => rsx! {
                        if result.partial {
                            PartialNotice {}
                        }
                        DateHistogramChart {
                            histogram: result.clone(),
                            selection: current(),
                            mode: mode(),
                            on_bucket,
                            on_unknown,
                        }
                    },
                }
            }
        }
    }
}

/// The bars under the date selector.
///
/// Grey is the corpus this query narrows to, ignoring its own date filter; accent is the
/// part the cutoffs keep. Drawn from the same `[start, end)` numbers the server binned
/// with, so a click produces a filter that lines up exactly with the bar you clicked.
#[component]
fn DateHistogramChart(
    histogram: DateHistogram,
    selection: RangeFilter,
    mode: DateMode,
    on_bucket: Callback<DateHistogramBucket>,
    on_unknown: Callback<()>,
) -> Element {
    let unknown_selected = mode == DateMode::UnknownOnly;
    let unknown_row = rsx! {
        if histogram.unknown_count > 0 {
            div {
                class: "x-facet-list-item",
                style: "
                    display: flex; align-items: center; gap: 8px; cursor: pointer;
                    padding: 4px 6px; border-radius: 6px; font-size: 13px; margin-top: 6px;
                ",
                title: "Click to show only the documents with no date of this kind",
                onclick: move |_| on_unknown.call(()),
                if unknown_selected {
                    Icon { icon: MdCheckBox, style: "width: 18px; height: 18px; color: rgb(28,33,45);" }
                } else {
                    Icon { icon: MdCheckBoxOutlineBlank, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.6);" }
                }
                div {
                    style: "flex: 1 1 auto;",
                    if histogram.counts_mentions { "Mentions no date" } else { "No confirmed date" }
                }
                div { style: "color: rgba(0,0,0,0.6);", "{histogram.unknown_count}" }
            }
        }
    };

    if histogram.is_empty() {
        // The empty-domain copy has to name WHICH dates it found none of. A corpus of
        // undated scans that all discuss the 1970s has no document dates and plenty of
        // mentioned ones, and one sentence for both would be wrong for one of them.
        let nothing = if histogram.counts_mentions {
            "No document here mentions a date."
        } else {
            "No dated documents match."
        };
        return rsx! {
            div { style: "color: rgba(0,0,0,0.5); font-size: 14px;", "{nothing}" }
            {unknown_row}
        };
    }

    let max = histogram.max_count();
    let first = histogram.buckets.first().map(|b| b.start).unwrap_or_default();
    let last = histogram.buckets.last().map(|b| b.end - 1).unwrap_or_default();

    rsx! {
        div {
            style: "font-size: 13px; color: rgba(0,0,0,0.6); margin-bottom: 4px;",
            if histogram.counts_mentions {
                // The bars are not comparable with the other histogram's: a document
                // naming three days in one bin contributes three to it. Saying so is
                // cheaper than a reader working out why the totals do not add up.
                "Mentions by date. Click a bar to filter."
            } else {
                "Documents by date. Click a bar to filter."
            }
        }
        div {
            // `align-items: flex-end` so bars grow from a shared baseline, and a fixed
            // height so a tall bar cannot push the modal's layout around.
            style: "display: flex; align-items: flex-end; gap: 2px; height: 96px; width: 100%;",
            for bucket in histogram.buckets.clone() {
                {
                    let covered = bucket.is_covered(selection.min, selection.max)
                        && selection.is_active()
                        && !unknown_selected;
                    let colour = if covered { ACCENT } else { "rgba(0,0,0,0.22)" };
                    // Zero-count bins keep a hairline so the axis stays continuous and
                    // the gaps in the corpus are visible as gaps rather than as nothing.
                    let height = if bucket.count == 0 { 1 } else { (bucket.count * 100 / max).max(3) };
                    let range = format!(
                        "{} – {}",
                        epoch_to_iso_date(bucket.start),
                        epoch_to_iso_date(bucket.end - 1)
                    );
                    let action = mode.click_action(&bucket);
                    let count = bucket.count;
                    rsx! {
                        div {
                            key: "{bucket.start}",
                            style: "flex: 1 1 0; min-width: 3px; height: 100%; display: flex; align-items: flex-end; cursor: pointer;",
                            title: "{range}\n{count} documents\nClick to {action}",
                            onclick: move |_| on_bucket.call(bucket.clone()),
                            div { style: "width: 100%; height: {height}%; background: {colour}; border-radius: 2px 2px 0 0;" }
                        }
                    }
                }
            }
        }
        div {
            style: "display: flex; justify-content: space-between; font-size: 12px; color: rgba(0,0,0,0.55); margin-top: 3px;",
            span { "{epoch_to_iso_date(first)}" }
            span { "{epoch_to_iso_date(last)}" }
        }
        {unknown_row}
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum DateMode {
    Off,
    Before,
    After,
    Between,
    UnknownOnly,
}

/// Which radio is lit, given the filter and the row the reader last clicked.
///
/// A picked mode wins over the bounds. Deriving the mode from the bounds alone makes
/// "Between" collapse the instant one of its two boxes is filled (one bound and no other
/// reads as "After" or "Before", and the box the reader has not typed into yet leaves the
/// screen), so a closed range cannot be entered through the boxes at all. With nothing
/// picked, which is the state a URL-borne filter arrives in, the bounds name the mode.
fn date_mode(filter: &RangeFilter, picked: Option<DateMode>) -> DateMode {
    if !filter.is_active() {
        return picked.unwrap_or(DateMode::Off);
    }
    match picked {
        Some(DateMode::Off) | None => match (filter.min, filter.max, filter.include_unknown) {
            (None, None, true) => DateMode::UnknownOnly,
            (Some(_), Some(_), _) => DateMode::Between,
            (None, Some(_), _) => DateMode::Before,
            _ => DateMode::After,
        },
        Some(chosen) => chosen,
    }
}

impl DateMode {
    const ROWS: [(&'static str, DateMode); 5] = [
        ("No filtering", DateMode::Off),
        ("Before…", DateMode::Before),
        ("After…", DateMode::After),
        ("Between…", DateMode::Between),
        ("Unknown only", DateMode::UnknownOnly),
    ];

    fn shows_min(&self) -> bool {
        matches!(self, DateMode::After | DateMode::Between)
    }

    fn shows_max(&self) -> bool {
        matches!(self, DateMode::Before | DateMode::Between)
    }

    /// What clicking a bar will do, in words, for the bar's tooltip. The answer depends
    /// on the mode, so the tooltip is the only place a user can find it out before
    /// committing, which is why every mode has a sentence here rather than a default.
    fn click_action(&self, bucket: &DateHistogramBucket) -> String {
        let from = epoch_to_iso_date(bucket.start);
        let to = epoch_to_iso_date(bucket.end - 1);
        match self {
            DateMode::Before => format!("show only documents before {}", epoch_to_iso_date(bucket.end)),
            DateMode::After => format!("show only documents from {from} onwards"),
            DateMode::Between => format!("narrow the range to {from} – {to}"),
            DateMode::Off | DateMode::UnknownOnly => {
                format!("filter to {from} – {to}")
            }
        }
    }
}

/// The File-location pane: the unified tree with a tri-state box at every level.
///
/// It used to refuse to render at all until a dataset had been picked under Collections,
/// on the grounds that "a folder tree is a tree of one dataset". That is true of the
/// STRUCTURE INDEX and was never true of the filter: `file_paths` is a flat set of term
/// ids, and a dataset's root node is a term id like any folder's. So a dataset tick is
/// just a coarser folder tick, the collection rows aggregate their datasets, and the
/// pane shows everything the user may read.
#[component]
fn FileLocationPane(pending: Signal<SearchQuery>) -> Element {
    let mut selected = use_signal(std::collections::BTreeSet::<String>::new);
    // The picker has no "here": nothing is focused, so the tree does not elide ancestors
    // and its sibling windows fall back to the top of each level.
    let nothing = use_memo(String::new);

    // Seed the ticks from the filter that is already active.
    //
    // `file_paths` holds TERM IDS, and a node key cannot be derived from one. The id is
    // a truncated hash. So the seed is a reverse lookup through the term dictionary,
    // which is the same table the forward direction mints ids in. Without it, reopening
    // the pane showed an empty tree over a live filter, and the only way to change the
    // filter was to clear it.
    //
    // `peek`, not a read: this resource must run ONCE per pane opening. Reading `pending`
    // here would re-run it on every tick and race the user's own edits back over them.
    let seed = use_resource(move || {
        let ids: Vec<u64> = pending
            .peek()
            .facet_filters
            .get("file_paths")
            .map(|set| {
                set.iter()
                    .filter_map(|v| match v {
                        FacetOriginalValue::Int(id) => Some(*id),
                        FacetOriginalValue::String(_) => None,
                    })
                    .collect()
            })
            .unwrap_or_default();
        async move {
            if ids.is_empty() {
                return HashMap::new();
            }
            crate::api::search_api::fetch_db_terms_for_ints(
                ids,
                term_field_of("file_paths").unwrap_or_default().to_string(),
            )
            .await
            .unwrap_or_default()
        }
    });

    use_effect(move || {
        let Some(map) = seed.read().clone() else {
            return;
        };
        // Only while the user has not started ticking: the lookup is a round trip and
        // must never overwrite a selection made while it was in flight.
        if !selected.peek().is_empty() {
            return;
        }
        let keys = node_keys_from_terms(map.into_values());
        if !keys.is_empty() {
            selected.set(keys);
        }
    });

    // Node keys -> `file_paths` term ids, for the WHOLE selection, in one call. It runs
    // on a tick rather than in an effect over `selected`: an effect fires on mount too,
    // which would round-trip the seed straight back into the query.
    let resolve = Callback::new(move |_| {
        let keys: Vec<String> = selected.peek().iter().cloned().collect();
        spawn(async move {
            let ids = if keys.is_empty() {
                Vec::new()
            } else {
                crate::api::storage_api::vfs_node_term_ids(keys).await.unwrap_or_default()
            };
            let mut q = pending.write();
            if ids.is_empty() {
                q.facet_filters.remove("file_paths");
            } else {
                q.facet_filters.insert(
                    "file_paths".to_string(),
                    ids.into_iter().map(FacetOriginalValue::Int).collect(),
                );
            }
        });
    });

    rsx! {
        div {
            style: "font-size: 13px; color: rgba(0,0,0,0.6); margin-bottom: 6px;",
            "Filtering on a folder finds everything below it, including inside archives and emails."
        }
        div {
            style: "max-height: 420px; overflow-y: auto; overflow-x: hidden; border: 1px solid rgba(0,0,0,0.12); border-radius: 8px; padding: 4px;",
            StorageTree {
                skin: TreeSkin::Picker,
                selected,
                current_dataset: nothing,
                focus_key: nothing,
                on_activate: Callback::new(move |_row: StorageRow| resolve.call(())),
            }
        }
    }
}

#[component]
fn EmailPane(original_query: ReadSignal<SearchQuery>, pending: Signal<SearchQuery>) -> Element {
    let has_attachments = use_memo(move || {
        pending
            .read()
            .facet_filters
            .get("struct_flags")
            .is_some_and(|set| !set.is_empty())
    });

    rsx! {
        div {
            class: "x-facet-list-item",
            style: "display: flex; align-items: center; gap: 10px; padding: 5px 4px; cursor: pointer; margin-bottom: 8px;",
            onclick: move |_| {
                let mut q = pending.write();
                if has_attachments() {
                    q.facet_filters.remove("struct_flags");
                } else {
                    q.facet_filters.insert(
                        "struct_flags".to_string(),
                        STRUCT_FLAGS_WITH_ATTACHMENTS.iter().map(|v| FacetOriginalValue::Int(*v)).collect(),
                    );
                }
            },
            if has_attachments() {
                Icon { icon: MdCheckBox, style: "width: 22px; height: 22px; color: rgb(28,33,45);" }
            } else {
                Icon { icon: MdCheckBoxOutlineBlank, style: "width: 22px; height: 22px; color: rgba(0,0,0,0.6);" }
            }
            "Email has attachments"
        }

        div {
            style: "display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap;",
            div {
                style: "flex: 1 1 260px; min-width: 0;",
                div { style: "font-weight: 600; margin-bottom: 4px;", "Sender" }
                SearchableFacetPane {
                    original_query, pending,
                    field: "email_from".to_string(),
                    map_string_terms: term_field_prop("email_from"),
                    placeholder: "Search senders…".to_string(),
                }
            }
            div {
                style: "flex: 1 1 260px; min-width: 0;",
                div { style: "font-weight: 600; margin-bottom: 4px;", "Receiver" }
                SearchableFacetPane {
                    original_query, pending,
                    field: "email_to".to_string(),
                    map_string_terms: term_field_prop("email_to"),
                    placeholder: "Search receivers…".to_string(),
                }
            }
        }
    }
}

/// The children of the Entities category.
///
/// One list at a time rather than four stacked panes. Stacking was already cramped with
/// the four NER types, and eleven value lists plus a date pane in one column is a scroll
/// rather than a list of anything.
///
/// Two of the twelve are not facets. `All` is a synthetic merge of the ten value lists,
/// and `MentionedDate` is a range with a histogram. Mentions are POINTS in time and the
/// pane that filters them is the date pane, not a checkbox list.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EntitySub {
    All,
    Per,
    Org,
    Loc,
    Misc,
    Email,
    Phone,
    BankAccount,
    CompanyId,
    Money,
    CryptoWallet,
    MentionedDate,
}

impl EntitySub {
    pub const ALL: [EntitySub; 12] = [
        EntitySub::All,
        EntitySub::Per,
        EntitySub::Org,
        EntitySub::Loc,
        EntitySub::Misc,
        EntitySub::Email,
        EntitySub::Phone,
        EntitySub::BankAccount,
        EntitySub::CompanyId,
        EntitySub::Money,
        EntitySub::CryptoWallet,
        EntitySub::MentionedDate,
    ];

    /// The ten value facets, in rail order. `All` merges exactly these; Mentioned Date is
    /// excluded because a timestamp has no place in a list sorted by document count.
    pub const VALUE_FIELDS: [&'static str; 10] = [
        "ner_per",
        "ner_org",
        "ner_loc",
        "ner_misc",
        "re_email",
        "re_phone",
        "re_bank_account",
        "re_company_id",
        "re_money",
        "re_crypto_wallet",
    ];

    pub fn label(&self) -> &'static str {
        match self {
            EntitySub::All => "All",
            EntitySub::Per => "Person",
            EntitySub::Org => "Organization",
            EntitySub::Loc => "Location",
            EntitySub::Misc => "Misc",
            EntitySub::Email => "Email",
            EntitySub::Phone => "Phone",
            EntitySub::BankAccount => "Bank account",
            EntitySub::CompanyId => "Company ID",
            EntitySub::Money => "Money",
            EntitySub::CryptoWallet => "Crypto wallet",
            EntitySub::MentionedDate => "Mentioned Date",
        }
    }

    /// The `facet_filters` key this child ticks into, or `None` for the two that are not
    /// a single facet.
    pub fn field(&self) -> Option<&'static str> {
        match self {
            EntitySub::All | EntitySub::MentionedDate => None,
            EntitySub::Per => Some("ner_per"),
            EntitySub::Org => Some("ner_org"),
            EntitySub::Loc => Some("ner_loc"),
            EntitySub::Misc => Some("ner_misc"),
            EntitySub::Email => Some("re_email"),
            EntitySub::Phone => Some("re_phone"),
            EntitySub::BankAccount => Some("re_bank_account"),
            EntitySub::CompanyId => Some("re_company_id"),
            EntitySub::Money => Some("re_money"),
            EntitySub::CryptoWallet => Some("re_crypto_wallet"),
        }
    }

    /// The child a facet field belongs to, for the merged view's type column.
    pub fn of_field(field: &str) -> Option<EntitySub> {
        EntitySub::ALL.into_iter().find(|sub| sub.field() == Some(field))
    }
}

#[component]
fn EntitySubIcon(sub: EntitySub, style: String) -> Element {
    match sub {
        EntitySub::All | EntitySub::Per => rsx! { Icon { icon: MdPerson, style } },
        EntitySub::Org => rsx! { Icon { icon: MdBusiness, style } },
        EntitySub::Loc => rsx! { Icon { icon: MdLocationOn, style } },
        EntitySub::Misc => rsx! { Icon { icon: MdInfo, style } },
        EntitySub::Email => rsx! { Icon { icon: MdEmail, style } },
        EntitySub::Phone => rsx! { Icon { icon: MdPhone, style } },
        EntitySub::BankAccount => rsx! { Icon { icon: MdAccountBalance, style } },
        EntitySub::CompanyId => rsx! { Icon { icon: MdDomain, style } },
        EntitySub::Money => rsx! { Icon { icon: MdAttachMoney, style } },
        EntitySub::CryptoWallet => rsx! { Icon { icon: MdAccountBalanceWallet, style } },
        EntitySub::MentionedDate => rsx! { Icon { icon: MdDateRange, style } },
    }
}

#[component]
fn EntitiesPane(original_query: ReadSignal<SearchQuery>, pending: Signal<SearchQuery>) -> Element {
    let mut open_sub = use_signal(|| EntitySub::All);
    let active = open_sub();
    rsx! {
        div {
            style: "display: flex; gap: 12px; align-items: stretch; height: 100%; min-height: 0;",
            // The children rail. Permanently visible: a collapsed rail hides the fact
            // that there are eleven kinds of value to filter on, and the reason to open
            // Entities at all is usually one of the seven that are not a person's name.
            div {
                style: "
                    flex: 0 0 168px; display: flex; flex-direction: column; gap: 1px;
                    border-right: 1px solid rgba(0,0,0,0.12); padding-right: 6px;
                    overflow-y: auto;
                ",
                for sub in EntitySub::ALL {
                    {
                        let selected = sub == active;
                        let background = if selected { "rgba(0,0,0,0.06)" } else { "transparent" };
                        let weight = if selected { "600" } else { "400" };
                        let is_set = entity_sub_is_active(sub, &pending.read());
                        rsx! {
                            button {
                                key: "{sub:?}",
                                class: "x-facet-list-item",
                                style: "
                                    display: flex; align-items: center; gap: 7px; width: 100%;
                                    border: none; text-align: left; padding: 6px 8px;
                                    font-size: 14px; font-weight: {weight}; cursor: pointer;
                                    background: {background}; border-radius: 6px;
                                ",
                                onclick: move |_| open_sub.set(sub),
                                div {
                                    style: "width: 8px; flex-shrink: 0; display: flex; align-items: center;",
                                    if is_set {
                                        div { style: "width: 6px; height: 6px; border-radius: 50%; background: {ACCENT};" }
                                    }
                                }
                                EntitySubIcon { sub, style: "width: 16px; height: 16px; flex-shrink: 0;".to_string() }
                                span {
                                    style: "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                                    "{sub.label()}"
                                }
                            }
                        }
                    }
                }
            }

            div {
                style: "flex: 1 1 auto; min-width: 0; overflow-y: auto;",
                match active {
                    EntitySub::All => rsx! { EntitiesAllPane { original_query, pending } },
                    EntitySub::MentionedDate => rsx! {
                        DatePane {
                            original_query, pending,
                            field: "mentioned_dates".to_string(),
                        }
                    },
                    other => {
                        let field = other.field().expect("every other child names a facet");
                        rsx! {
                            SearchableFacetPane {
                                original_query, pending,
                                field: field.to_string(),
                                map_string_terms: term_field_prop(field),
                                placeholder: format!("Search {}…", other.label().to_lowercase()),
                            }
                        }
                    }
                }
            }
        }
    }
}

/// Whether one child of Entities has anything set.
fn entity_sub_is_active(sub: EntitySub, query: &SearchQuery) -> bool {
    match sub {
        // `All` lights when any of the ten does, because it is the view that shows all
        // ten and a rail with no dot anywhere over a filtered corpus is a lie.
        EntitySub::All => EntitySub::VALUE_FIELDS.iter().any(|field| {
            query.facet_filters.get(*field).is_some_and(|values| !values.is_empty())
        }),
        EntitySub::MentionedDate => query
            .range_filters
            .get("mentioned_dates")
            .is_some_and(|filter| filter.is_active()),
        other => other.field().is_some_and(|field| {
            query.facet_filters.get(field).is_some_and(|values| !values.is_empty())
        }),
    }
}

/// The ten value lists merged into one, sorted by document count.
///
/// The type column between the checkbox and the text is what makes the merge readable: a
/// row saying `enron` is a different claim depending on whether it is an organisation or
/// a mentioned company registration, and the merged list is the only place the two sit
/// next to each other.
///
/// Ticking a row writes into that row's OWN facet field, so the merged view produces
/// exactly the query its sub-list would. The ten fetches are the sub-lists' own queries
/// verbatim, and identical queries hit the backend's Manticore result cache, switching
/// between All and a child is not ten fresh fan-outs.
#[component]
fn EntitiesAllPane(
    original_query: ReadSignal<SearchQuery>,
    pending: Signal<SearchQuery>,
) -> Element {
    let mut needle = use_signal(String::new);
    let hits = use_entity_term_search(
        original_query,
        ReadSignal::from(needle),
        || EntitySub::VALUE_FIELDS.iter().map(|f| f.to_string()).collect(),
        true,
    );
    let restrict_to_ids = use_memo(move || hits.read().as_ref().map(EntityTermHits::term_ids));

    let lists = use_resource(move || {
        let query = original_query.read().clone();
        let restrict = restrict_to_ids.read().clone();
        async move {
            let mut rows: Vec<(&'static str, SearchResultFacetItem)> = Vec::new();
            let mut partial = false;
            for field in EntitySub::VALUE_FIELDS {
                let result = search_string_facet(
                    query.clone(),
                    field.to_string(),
                    term_field_prop(field),
                    restrict.clone(),
                )
                .await?;
                partial = partial || result.partial;
                rows.extend(result.facet_values.into_iter().map(|item| (field, item)));
            }
            rows.sort_by_key(|(_, item)| (u64::MAX - item.count, item.display_string.clone()));
            Ok::<_, ServerFnError>((rows, partial))
        }
    });

    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 6px; margin-bottom: 8px;",
            Icon { icon: MdSearch, style: "width: 18px; height: 18px; color: rgba(0,0,0,0.5);" }
            input {
                r#type: "text",
                style: "{INPUT_STYLE} flex: 1 1 auto;",
                placeholder: "Search every entity type…",
                value: "{needle}",
                oninput: move |event| needle.set(event.value()),
            }
        }
        match lists.read().as_ref() {
            // Every list, or none: a merged view that renders while three of its ten
            // sources are still in flight is sorted by a count it does not have yet, and
            // reorders itself under the reader's cursor as they arrive.
            None => rsx! { div { style: "padding: 8px; color: rgba(0,0,0,0.5);", "Loading…" } },
            Some(Err(error)) => rsx! { ServerErrorDisplay { error: error.clone() } },
            Some(Ok((rows, partial))) => rsx! {
                if *partial {
                    PartialNotice {}
                }
                if rows.is_empty() {
                    div {
                        style: "padding: 8px 10px; font-size: 14px; color: rgba(0,0,0,0.55);",
                        "No entities match."
                    }
                }
                for (field, item) in rows.clone() {
                    {
                        let sub = EntitySub::of_field(field).unwrap_or(EntitySub::Misc);
                        rsx! {
                            div {
                                key: "{field}-{item.original_value:?}",
                                style: "display: flex; align-items: center; gap: 4px;",
                                div {
                                    style: "flex: 1 1 auto; min-width: 0;",
                                    FacetCheckbox {
                                        query: pending,
                                        facet_name: field.to_string(),
                                        facet_value: item.original_value.clone(),
                                        result_count: item.count,
                                        result_display_string: item.display_string.clone(),
                                    }
                                }
                            }
                            div {
                                style: "display: flex; align-items: center; gap: 5px; padding: 0 0 4px 40px; font-size: 12px; color: rgba(0,0,0,0.55);",
                                EntitySubIcon { sub, style: "width: 13px; height: 13px;".to_string() }
                                "{sub.label()}"
                            }
                        }
                    }
                }
            },
        }
    }
}

/// The amber notice. One shard could not be searched, so every count on screen is a
/// lower bound. Carried over from the pill strip verbatim.
#[component]
fn PartialNotice() -> Element {
    rsx! {
        div {
            style: "
                width: 100%; padding: 6px 10px; margin-bottom: 6px;
                border: 1px solid rgba(200, 120, 0, 0.6); border-radius: 6px;
                background-color: rgba(255, 180, 60, 0.15); color: rgb(120, 70, 0);
                font-size: 13px;
            ",
            "Some collections could not be searched, so counts may be incomplete."
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn iso_dates_round_trip_including_before_1970() {
        for iso in ["1970-01-01", "2013-05-01", "1936-04-01", "1849-12-31", "2024-02-29"] {
            let epoch = iso_date_to_epoch(iso).expect(iso);
            assert_eq!(epoch_to_iso_date(epoch), iso, "{iso}");
        }
    }

    #[test]
    fn a_pre_epoch_date_is_negative() {
        assert!(iso_date_to_epoch("1936-04-01").unwrap() < 0);
        assert_eq!(epoch_to_iso_date(-1), "1969-12-31");
    }

    #[test]
    fn a_half_typed_date_is_not_a_filter() {
        for bad in ["", "2013", "2013-", "2013-05", "2013-13-01", "2013-05-32", "x-y-z",
                    "2013-05-01-1"] {
            assert!(iso_date_to_epoch(bad).is_none(), "{bad:?} should not parse");
        }
    }

    /// Filling one end of a range must not take the other end's box off screen.
    #[test]
    fn a_half_filled_between_is_still_between() {
        let half = RangeFilter { min: Some(1_104_537_600), max: None, include_unknown: false };
        assert_eq!(date_mode(&half, Some(DateMode::Between)), DateMode::Between);
        assert!(date_mode(&half, Some(DateMode::Between)).shows_max());
        let other_half = RangeFilter { min: None, max: Some(1_136_073_599), include_unknown: false };
        assert_eq!(date_mode(&other_half, Some(DateMode::Between)), DateMode::Between);
        assert!(date_mode(&other_half, Some(DateMode::Between)).shows_min());
    }

    /// A filter that arrived in the URL has no picked row behind it, so its bounds are
    /// the only thing that can name the mode.
    #[test]
    fn an_unpicked_pane_reads_its_mode_off_the_bounds() {
        let after = RangeFilter { min: Some(1), max: None, include_unknown: false };
        assert_eq!(date_mode(&after, None), DateMode::After);
        let before = RangeFilter { min: None, max: Some(1), include_unknown: false };
        assert_eq!(date_mode(&before, None), DateMode::Before);
        let between = RangeFilter { min: Some(1), max: Some(2), include_unknown: false };
        assert_eq!(date_mode(&between, None), DateMode::Between);
        let unknown = RangeFilter { min: None, max: None, include_unknown: true };
        assert_eq!(date_mode(&unknown, None), DateMode::UnknownOnly);
        assert_eq!(date_mode(&RangeFilter::default(), None), DateMode::Off);
    }

    #[test]
    fn a_category_owns_its_own_fields_and_nothing_else() {
        let mut query = SearchQuery::default();
        query.facet_filters.insert(
            "file_types".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(7)]),
        );
        query.range_filters.insert(
            "dates".to_string(),
            RangeFilter { min: Some(0), max: Some(1), include_unknown: false },
        );

        assert!(FilterCategory::FileTypes.is_active(&query));
        assert!(FilterCategory::Dates.is_active(&query));
        assert!(!FilterCategory::Collections.is_active(&query));

        FilterCategory::Dates.clear(&mut query);
        assert!(!FilterCategory::Dates.is_active(&query));
        assert!(FilterCategory::FileTypes.is_active(&query), "clearing one category must not touch another");
    }

    #[test]
    fn an_empty_facet_set_does_not_light_the_dot() {
        // Un-ticking the last value leaves an empty set behind in some code paths; an
        // empty set is not a filter and must not show a chip or a dot.
        let mut query = SearchQuery::default();
        query.facet_filters.insert("file_types".to_string(), BTreeSet::new());
        assert!(!FilterCategory::FileTypes.is_active(&query));
        assert!(build_chips(&query, Some(&HashMap::new())).is_empty());
    }

    #[test]
    fn chips_are_one_per_category_not_one_per_value() {
        let mut query = SearchQuery::default();
        query.facet_filters.insert(
            "ner_per".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(1), FacetOriginalValue::Int(2)]),
        );
        query.facet_filters.insert(
            "ner_org".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(3)]),
        );
        let texts = HashMap::from([
            (1_u64, "Alice".to_string()),
            (2_u64, "Bob".to_string()),
            (3_u64, "Acme Ltd".to_string()),
        ]);
        let chips = build_chips(&query, Some(&texts));
        assert_eq!(chips.len(), 1, "all ten entity value fields are ONE Entities chip");
        assert_eq!(chips[0].label, "Entities");
        assert_eq!(chips[0].full, "Alice, Bob, Acme Ltd", "the tooltip carries the whole selection");
        assert!(!chips[0].summary.contains('#'), "a resolved term id never renders as an id");
    }

    /// Every child of Entities lands in the same chip, including the six the scanner
    /// finds. A second chip here would mean the category's field list had drifted from
    /// the rail.
    #[test]
    fn a_scanner_value_lands_in_the_entities_chip_too() {
        let mut query = SearchQuery::default();
        query.facet_filters.insert(
            "re_bank_account".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(9)]),
        );
        query.facet_filters.insert(
            "ner_per".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(1)]),
        );
        let texts = HashMap::from([
            (1_u64, "Alice".to_string()),
            (9_u64, "GB82WEST12345698765432".to_string()),
        ]);
        let chips = build_chips(&query, Some(&texts));
        assert_eq!(chips.len(), 1);
        assert_eq!(chips[0].label, "Entities");
        assert!(chips[0].full.contains("GB82WEST12345698765432"), "{}", chips[0].full);
    }

    /// A Mentioned Date range alone lights the Entities dot and produces its chip. It is
    /// the only range filter the category owns, and it must never be mistaken for the
    /// Date chip -- hence the prefix.
    #[test]
    fn a_mentioned_date_range_alone_is_an_entities_chip() {
        let mut query = SearchQuery::default();
        query.range_filters.insert(
            "mentioned_dates".to_string(),
            // 1998-01-01 .. 2004-12-31
            RangeFilter { min: Some(883_612_800), max: Some(1_104_537_599), include_unknown: false },
        );
        assert!(FilterCategory::Entities.is_active(&query), "the dot must light");
        let chips = build_chips(&query, Some(&HashMap::new()));
        assert_eq!(chips.len(), 1);
        assert_eq!(chips[0].label, "Entities");
        assert!(chips[0].summary.starts_with("Mentioned "), "{}", chips[0].summary);
        assert!(chips[0].summary.contains("1998"), "{}", chips[0].summary);
    }

    /// `Clear all` and the chip's own X walk facet and range fields together, so removing
    /// the Entities chip has to remove the mentioned-date range as well as the ticks.
    #[test]
    fn clearing_entities_clears_its_range_filter_too() {
        let mut query = SearchQuery::default();
        query.facet_filters.insert(
            "re_money".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(4)]),
        );
        query.range_filters.insert(
            "mentioned_dates".to_string(),
            RangeFilter { min: Some(0), max: Some(100), include_unknown: false },
        );
        FilterCategory::Entities.clear(&mut query);
        assert!(!FilterCategory::Entities.is_active(&query));
        assert!(query.range_filters.get("mentioned_dates").is_none());
    }

    /// The rail's twelve children: ten facets, one merged view, one range pane. The
    /// merged view lists exactly the ten, and Mentioned Date is not among them -- a
    /// timestamp has no place in a list sorted by document count.
    #[test]
    fn the_entities_rail_covers_every_value_field_exactly_once() {
        let mut fields: Vec<&str> = EntitySub::ALL
            .into_iter()
            .filter_map(|sub| sub.field())
            .collect();
        fields.sort_unstable();
        let mut expected: Vec<&str> = EntitySub::VALUE_FIELDS.to_vec();
        expected.sort_unstable();
        assert_eq!(fields, expected);
        assert_eq!(FilterCategory::Entities.facet_fields(), &EntitySub::VALUE_FIELDS);
        assert!(EntitySub::of_field("mentioned_dates").is_none());
        for field in EntitySub::VALUE_FIELDS {
            assert!(EntitySub::of_field(field).is_some(), "{field} has no rail entry");
            assert!(term_field_of(field).is_some(), "{field} has no term dictionary");
        }
    }

    #[test]
    fn a_size_chip_never_says_custom() {
        let mut query = SearchQuery::default();
        query.range_filters.insert(
            "file_size_bytes".to_string(),
            RangeFilter { min: Some(2_621_440), max: Some(41_943_040), include_unknown: false },
        );
        let chips = build_chips(&query, Some(&HashMap::new()));
        assert_eq!(chips[0].summary, "2.5 MB – 40 MB");
    }

    #[test]
    fn a_folder_chip_shows_names_and_tooltips_paths() {
        use common::vfs::{dataset_root_key, make_node_key};

        let enron = make_node_key("testdata_testfiles", "", "/disk-files/enron");
        let root = dataset_root_key("other_emails");
        let mut query = SearchQuery::default();
        query.facet_filters.insert(
            "file_paths".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(10), FacetOriginalValue::Int(20)]),
        );
        let texts = HashMap::from([(10_u64, enron), (20_u64, root)]);

        let chips = build_chips(&query, Some(&texts));
        assert_eq!(chips.len(), 1);
        // Node keys are machine text, two unit separators and a container hash. Neither
        // form of them belongs on screen.
        assert!(!chips[0].summary.contains('\u{1f}') && !chips[0].full.contains('\u{1f}'));
        assert_eq!(chips[0].summary, "enron, other_emails");
        assert_eq!(chips[0].full, "/disk-files/enron, other_emails");

        // Still resolving: no raw id flashes up while the round trip is in flight.
        let pending = build_chips(&query, None);
        assert_eq!(pending[0].summary, "…, …");
        // Resolved, but the term row is gone: the id is all there is, and it still names
        // a filter the user can remove.
        let orphaned = build_chips(&query, Some(&HashMap::new()));
        assert_eq!(orphaned[0].summary, "#10, #20");
    }

    #[test]
    fn the_attachment_filter_is_one_label_not_two_bitfield_values() {
        // `struct_flags` has no term dictionary. {1, 3} Is an enumeration of the values
        // carrying one bit, and "Has attachments, Has attachments" is not a summary.
        let mut query = SearchQuery::default();
        query.facet_filters.insert(
            "struct_flags".to_string(),
            STRUCT_FLAGS_WITH_ATTACHMENTS.iter().map(|v| FacetOriginalValue::Int(*v)).collect(),
        );
        let chips = build_chips(&query, Some(&HashMap::new()));
        assert_eq!(chips[0].summary, "Has attachments");
    }

    #[test]
    fn every_facet_that_stores_term_ids_has_a_term_field() {
        // The failure this guards: a facet pane added with a `map_string_terms` string at
        // the call site, and a chip row that knows nothing about it, giving a list of names
        // next to a chip of `#229645745`.
        for field in FilterCategory::ALL.iter().flat_map(|c| c.facet_fields()) {
            let expected = !matches!(*field, "collection_dataset" | "struct_flags");
            assert_eq!(
                term_field_of(field).is_some(),
                expected,
                "{field} is in the wrong half of the term-field table"
            );
        }
    }

    #[test]
    fn the_chip_row_resolves_each_term_field_once_for_the_whole_selection() {
        let mut query = SearchQuery::default();
        query.facet_filters.insert(
            "ner_per".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(1), FacetOriginalValue::Int(2)]),
        );
        query.facet_filters.insert(
            "ner_org".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(2), FacetOriginalValue::Int(3)]),
        );
        query.facet_filters.insert(
            "file_types".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(9)]),
        );
        // Values with no term field never reach the endpoint.
        query.facet_filters.insert(
            "struct_flags".to_string(),
            BTreeSet::from([FacetOriginalValue::Int(1)]),
        );
        query.facet_filters.insert(
            "collection_dataset".to_string(),
            BTreeSet::from([FacetOriginalValue::String("testdata_shapes".to_string())]),
        );

        let wanted = term_ids_to_resolve(&query);
        assert_eq!(wanted.len(), 2, "one entry per TERM FIELD, not per facet: {wanted:?}");
        // The four NER facets share one dictionary, and id 2 is asked for once.
        assert_eq!(wanted["ner"], BTreeSet::from([1, 2, 3]));
        assert_eq!(wanted["filetype"], BTreeSet::from([9]));
    }

    #[test]
    fn the_attachment_flag_values_cover_every_combination_of_the_other_flags() {
        // Bit 0 set, with and without bit 1. If a third flag is added this test is the
        // one that should fail.
        for value in STRUCT_FLAGS_WITH_ATTACHMENTS {
            assert_eq!(value & 1, 1);
        }
        let covered: BTreeSet<u64> = STRUCT_FLAGS_WITH_ATTACHMENTS.into_iter().collect();
        let expected: BTreeSet<u64> = (0..4_u64).filter(|v| v & 1 == 1).collect();
        assert_eq!(covered, expected, "a flag was added without extending the enumeration");
    }
}
