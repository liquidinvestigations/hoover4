//! The table explorer: a spreadsheet's cells as a sortable, filterable, paged grid.
//!
//! Rendered inside `PreviewWrapper` like every other preview source, so it inherits the
//! search pane's and the full-page viewer's two different layouts for free.
//!
//! # Where the view lives
//!
//! The selected sheet, the sort, the filters, the hidden columns and the page are in
//! `DocViewerState::table_state` and therefore in the URL. A table view someone found is
//! worth sending to a colleague. They are deliberately NOT in
//! `DocumentSourceItem::Table`: that variant is the key of `ItemHitCounts` and the value
//! the source selector compares against the selected source, so a variant carrying view
//! state would stop equalling itself and deselect the grid on every click.
//!
//! # The two Dioxus traps this component is exposed to
//!
//! * **Every hook runs on every render, in the same order.** The natural shape here
//!   ("once the overview resolves, seed the visible columns") is exactly the conditional
//!   `use_effect` that trapped two other pages in this repo. So: the resources are
//!   declared unconditionally at the top, every early return happens after them, and the
//!   "has the overview arrived" question is asked *inside* closures, never around a hook.
//!   `cargo check` is blind to this; `dx check --package frontend` is the gate.
//! * **A `ReadSignal` prop is a fresh signal on every parent render**, so a `use_resource`
//!   subscribed to it never re-runs. Both resources are keyed with `use_reactive!` over
//!   the *values* they depend on.

use common::document_sources::DocumentTableSourceItem;
use common::document_tables::{
    DEFAULT_TABLE_PAGE_ROWS, TableCell, TableColumnClass,
    TableColumnFilter, TableColumnInfo, TableColumnValue, TableFilterKind, TableOverview,
    TablePage, TableSort, TableViewQuery,
};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        md_action_icons::{MdDateRange, MdSearch, MdViewColumn},
        md_content_icons::{MdContentCopy, MdFilterList, MdLink, MdSort},
        md_editor_icons::MdTableChart,
        md_navigation_icons::{MdArrowDownward, MdArrowUpward, MdChevronLeft, MdChevronRight},
    },
};

use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::components::popover::{PopoverContent, PopoverRoot, PopoverTrigger};
use crate::components::suspend_boundary::LoadingIndicator;
use crate::data_definitions::doc_viewer_state::DocTableState;
use crate::pages::search_page::DocViewerStateControl;

/// Characters of a cell drawn inline before it is cut. The whole value is one click away.
const CELL_PREVIEW_CHARS: usize = 120;

#[component]
pub fn DocumentPreviewForTable(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentTableSourceItem>,
) -> Element {
    let control = use_context::<DocViewerStateControl>();
    let document_identifier_value = document_identifier();

    // ---- hooks, all of them, unconditionally ---------------------------------------
    let overview: Resource<Option<TableOverview>> =
        use_resource(use_reactive!(|document_identifier_value| {
            async move {
                get_table_overview(document_identifier_value)
                    .await
                    .ok()
                    .flatten()
            }
        }));

    let viewer_state = control.doc_viewer_state.read().clone().unwrap_or_default();
    let find_query = viewer_state.find_query.clone();
    let table_state = viewer_state.table_state();
    let overview_value = overview.read().clone().flatten();

    // The sheet the grid is on. The state names an ordinal, not an index, and a sheet
    // that produced no cells is simply absent, so a state naming a sheet this document
    // does not have falls back to the first one the manifest lists rather than to an
    // empty grid that reads as "this sheet is empty".
    let sheet_id = match (&overview_value, table_state.sheet_id) {
        (Some(overview), Some(wanted)) if overview.sheet(wanted).is_some() => wanted,
        (Some(overview), _) => overview.first_sheet_id(),
        (None, wanted) => wanted.unwrap_or(0),
    };

    let sheet_columns: Vec<TableColumnInfo> = overview_value
        .as_ref()
        .map(|o| o.columns_of(sheet_id).into_iter().cloned().collect())
        .unwrap_or_default();
    // Hidden, not visible: a re-ingest that ADDS a column should show it, not have it
    // silently missing from a link written before it existed.
    let visible_columns: Vec<u32> = sheet_columns
        .iter()
        .map(|c| c.column_id)
        .filter(|id| !table_state.hidden_columns.contains(id))
        .collect();

    let table_query = TableViewQuery {
        sheet_id,
        visible_columns: visible_columns.clone(),
        sort: table_state.sort,
        filters: table_state.filters.clone(),
        // The viewer's find box doubles as the in-table search: one box, and the number
        // beside the Table source in the selector counts the same thing it narrows to.
        search: find_query.clone(),
        offset: table_state.page * DEFAULT_TABLE_PAGE_ROWS as u64,
        limit: DEFAULT_TABLE_PAGE_ROWS,
    };
    let has_columns = !visible_columns.is_empty();
    let query_key = table_query.clone();
    let page: Resource<Option<TablePage>> =
        use_resource(use_reactive!(|document_identifier_value, query_key| {
            async move {
                // The condition is INSIDE the closure. A resource declared behind an `if`
                // would shift every hook after it the moment the overview arrived.
                if query_key.visible_columns.is_empty() {
                    return None;
                }
                get_table_page(document_identifier_value, query_key).await.ok()
            }
        }));
    let page_value = page.read().clone().flatten();

    // ---- state updates --------------------------------------------------------------
    let set_table_state = Callback::new(move |next: DocTableState| {
        let mut state = control.doc_viewer_state.read().clone().unwrap_or_default();
        state.table_state = Some(next);
        control.set_doc_viewer_state.call(state);
    });

    // ---- render ---------------------------------------------------------------------
    let Some(overview) = overview_value else {
        return rsx! {
            PreviewWrapper {
                controls: rsx! { "Table" },
                page: rsx! { LoadingIndicator {} }
            }
        };
    };
    if overview.sheets.is_empty() {
        return rsx! {
            PreviewWrapper {
                controls: rsx! { "Table" },
                page: rsx! {
                    div {
                        style: "padding: 12px; color: rgba(0,0,0,0.6);",
                        "This document was read as a table but stored no sheets."
                    }
                }
            }
        };
    }

    let active_filters = table_state.filters.len();
    let banner = overview.truncation_banner();
    let clamp_note = page_value.as_ref().and_then(|p| p.clamps.message());
    let source_value = source();

    let controls = rsx! {
        div {
            style: "display: flex; flex-direction: row; align-items: center; gap: 8px; flex-wrap: wrap;",
            Icon { icon: MdTableChart, style: "width: 20px; height: 20px;" }
            SheetPicker {
                overview: overview.clone(),
                sheet_id,
                table_state: table_state.clone(),
                set_table_state,
            }
            ColumnPicker {
                columns: sheet_columns.clone(),
                table_state: table_state.clone(),
                set_table_state,
            }
            if active_filters > 0 {
                button {
                    style: FILTER_CHIP_STYLE,
                    title: "Remove every column filter",
                    onclick: {
                        let table_state = table_state.clone();
                        move |_| {
                            let mut next = table_state.clone();
                            next.filters.clear();
                            set_table_state.call(next.reset_page());
                        }
                    },
                    Icon { icon: MdFilterList, style: "width: 16px; height: 16px;" }
                    // A filter you cannot see is how people conclude the data is missing.
                    "{active_filters} filter(s) \u{00b7} clear"
                }
            }
            if !find_query.is_empty() {
                span {
                    style: "display: inline-flex; align-items: center; gap: 4px; color: rgba(0,0,0,0.6); font-size: 13px;",
                    Icon { icon: MdSearch, style: "width: 16px; height: 16px;" }
                    "matching \u{201c}{find_query}\u{201d}"
                }
            }
            span {
                style: "color: rgba(0,0,0,0.5); font-size: 13px;",
                "{source_value.label()}"
            }
        }
    };

    let body = rsx! {
        div {
            style: "display: flex; flex-direction: column; height: 100%; min-height: 0;",
            if let Some(banner) = banner {
                div { style: BANNER_STYLE, "{banner}" }
            }
            if let Some(note) = clamp_note {
                div { style: BANNER_STYLE, "{note}." }
            }
            if !has_columns {
                div {
                    style: "padding: 12px; color: rgba(0,0,0,0.6);",
                    "Every column of this sheet is hidden. Use the Columns button to show one."
                }
            } else {
                match page_value.clone() {
                    None => rsx! { LoadingIndicator {} },
                    Some(page_value) => rsx! {
                        TableGrid {
                            columns: sheet_columns.clone(),
                            // The SERVER's applied list, not the requested one: the whole
                            // set is sent so the clamp is reported rather than applied
                            // silently, and a 300-column sheet must draw the 60 the
                            // response actually carries cells for.
                            visible_columns: page_value.columns.clone(),
                            page: page_value.clone(),
                            table_state: table_state.clone(),
                            set_table_state,
                            find_query: find_query.clone(),
                            document_identifier: document_identifier_value.clone(),
                            sheet_id,
                        }
                        TablePager {
                            page: page_value,
                            table_state: table_state.clone(),
                            set_table_state,
                        }
                    },
                }
            }
        }
    };

    rsx! {
        PreviewWrapper { controls, page: body }
    }
}

const BANNER_STYLE: &str = "
    margin: 0 0 6px 0;
    padding: 6px 10px;
    background: rgba(220, 160, 0, 0.12);
    border: 1px solid rgba(180, 130, 0, 0.35);
    border-radius: 6px;
    font-size: 13px;
    color: rgba(0,0,0,0.75);
    flex: 0 0 auto;
";

const FILTER_CHIP_STYLE: &str = "
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 8px; border-radius: 12px; cursor: pointer;
    border: 1px solid rgba(0,0,0,0.25); background: rgba(0,0,0,0.03);
    font-size: 13px;
";

const CONTROL_BUTTON_STYLE: &str = "
    display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 10px; border-radius: 14px; cursor: pointer;
    border: 1px solid #ccc; background: white; font-size: 14px;
";

/// The sheet dropdown, built from the manifest's rows.
///
/// Never from a range: `sheet_id` is the workbook's own ordinal and a sheet that produced
/// no cells is absent, so a two-sheet workbook really can have sheets 0 and 2.
#[component]
fn SheetPicker(
    overview: TableOverview,
    sheet_id: u16,
    table_state: DocTableState,
    set_table_state: Callback<DocTableState>,
) -> Element {
    let mut open = use_signal(|| false);
    let current = overview
        .sheet(sheet_id)
        .map(|s| format!("{} ({} \u{00d7} {})", s.label(), s.row_count, s.column_count))
        .unwrap_or_else(|| "Sheet".to_string());
    if overview.sheets.len() == 1 {
        return rsx! {
            span { style: "color: rgba(0,0,0,0.7); font-size: 14px;", "{current}" }
        };
    }
    rsx! {
        PopoverRoot {
            open: open(),
            on_open_change: move |value: bool| open.set(value),
            PopoverTrigger {
                span { style: CONTROL_BUTTON_STYLE, "{current}" }
            }
            PopoverContent {
                ul {
                    style: "min-width: 240px; max-height: 320px; overflow-y: auto;",
                    for sheet in overview.sheets.iter().cloned() {
                        li {
                            key: "{sheet.sheet_id}",
                            style: if sheet.sheet_id == sheet_id { "padding: 4px 10px; cursor: pointer; font-weight: 600;" } else { "padding: 4px 10px; cursor: pointer;" },
                            onclick: {
                                let table_state = table_state.clone();
                                move |_| {
                                    let mut next = table_state.clone();
                                    next.sheet_id = Some(sheet.sheet_id);
                                    // A column ordinal, a sort and a filter all name
                                    // columns of the sheet they were set on; carrying them
                                    // to another sheet silently filters on a different
                                    // column of the same number.
                                    next.hidden_columns.clear();
                                    next.sort = None;
                                    next.filters.clear();
                                    set_table_state.call(next.reset_page());
                                    open.set(false);
                                }
                            },
                            "{sheet.label()} \u{00b7} {sheet.row_count} \u{00d7} {sheet.column_count}"
                        }
                    }
                }
            }
        }
    }
}

/// The column-visibility popover: a checkbox per column, show/hide all, and a filter box
/// over column names for the sheets that have 300 of them.
#[component]
fn ColumnPicker(
    columns: Vec<TableColumnInfo>,
    table_state: DocTableState,
    set_table_state: Callback<DocTableState>,
) -> Element {
    let mut open = use_signal(|| false);
    let mut name_filter = use_signal(String::new);
    let hidden = table_state.hidden_columns.clone();
    let shown = columns.len().saturating_sub(hidden.len());
    let needle = name_filter().to_lowercase();
    let listed: Vec<TableColumnInfo> = columns
        .iter()
        .filter(|c| needle.is_empty() || c.label().to_lowercase().contains(&needle))
        .cloned()
        .collect();
    rsx! {
        PopoverRoot {
            open: open(),
            on_open_change: move |value: bool| open.set(value),
            PopoverTrigger {
                span {
                    style: CONTROL_BUTTON_STYLE,
                    Icon { icon: MdViewColumn, style: "width: 16px; height: 16px;" }
                    "{shown} of {columns.len()}"
                }
            }
            PopoverContent {
                div {
                    style: "min-width: 280px; max-height: 380px; overflow-y: auto; padding: 6px;",
                    input {
                        style: "width: 100%; padding: 4px 6px; margin-bottom: 6px;",
                        placeholder: "Find a column\u{2026}",
                        value: "{name_filter}",
                        oninput: move |e| name_filter.set(e.value()),
                    }
                    div {
                        style: "display: flex; gap: 8px; margin-bottom: 6px;",
                        button {
                            style: FILTER_CHIP_STYLE,
                            onclick: {
                                let table_state = table_state.clone();
                                move |_| {
                                    let mut next = table_state.clone();
                                    next.hidden_columns.clear();
                                    set_table_state.call(next);
                                }
                            },
                            "Show all"
                        }
                        button {
                            style: FILTER_CHIP_STYLE,
                            onclick: {
                                let table_state = table_state.clone();
                                let all: Vec<u32> = columns.iter().map(|c| c.column_id).collect();
                                move |_| {
                                    let mut next = table_state.clone();
                                    next.hidden_columns = all.clone();
                                    set_table_state.call(next);
                                }
                            },
                            "Hide all"
                        }
                    }
                    for column in listed {
                        {
                            let is_hidden = hidden.contains(&column.column_id);
                            let table_state = table_state.clone();
                            let column_id = column.column_id;
                            rsx! {
                                div {
                                    key: "{column_id}",
                                    style: "display: flex; align-items: center; gap: 8px; padding: 3px 2px; cursor: pointer;",
                                    onclick: move |_| {
                                        let mut next = table_state.clone();
                                        if is_hidden {
                                            next.hidden_columns.retain(|c| *c != column_id);
                                        } else {
                                            next.hidden_columns.push(column_id);
                                        }
                                        set_table_state.call(next);
                                    },
                                    input {
                                        r#type: "checkbox",
                                        checked: !is_hidden,
                                        readonly: true,
                                    }
                                    span { style: "color: rgba(0,0,0,0.45); width: 28px;", "{column.letter}" }
                                    span { "{column.label()}" }
                                    span { style: "color: rgba(0,0,0,0.4); font-size: 12px;", "{column.column_type}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The grid itself: sticky header row, sticky `#` column, horizontal scrolling inside its
/// own container and never on the page.
#[component]
fn TableGrid(
    columns: Vec<TableColumnInfo>,
    visible_columns: Vec<u32>,
    page: TablePage,
    table_state: DocTableState,
    set_table_state: Callback<DocTableState>,
    find_query: String,
    document_identifier: DocumentIdentifier,
    sheet_id: u16,
) -> Element {
    rsx! {
        div {
            style: "
                flex: 1 1 auto;
                min-height: 0;
                overflow: auto;
                border: 1px solid rgba(0,0,0,0.2);
                border-radius: 4px;
                background: white;
            ",
            table {
                style: "border-collapse: separate; border-spacing: 0; font-size: 13px; width: max-content; min-width: 100%;",
                thead {
                    tr {
                        th {
                            style: "position: sticky; left: 0; top: 0; z-index: 3; background: #f3f3f3; border-bottom: 1px solid rgba(0,0,0,0.2); border-right: 1px solid rgba(0,0,0,0.12); padding: 4px 8px; text-align: right; color: rgba(0,0,0,0.5);",
                            title: "The row number the file itself gives",
                            "#"
                        }
                        for column_id in visible_columns.iter().copied() {
                            {
                                let column = columns.iter().find(|c| c.column_id == column_id).cloned().unwrap_or_default();
                                rsx! {
                                    ColumnHeader {
                                        key: "{column_id}",
                                        column,
                                        table_state: table_state.clone(),
                                        set_table_state,
                                        document_identifier: document_identifier.clone(),
                                        sheet_id,
                                    }
                                }
                            }
                        }
                    }
                }
                tbody {
                    for row in page.rows.iter().cloned() {
                        tr {
                            key: "{row.row_id}",
                            td {
                                style: "position: sticky; left: 0; z-index: 1; background: #fafafa; border-right: 1px solid rgba(0,0,0,0.12); border-bottom: 1px solid rgba(0,0,0,0.06); padding: 2px 8px; text-align: right; color: rgba(0,0,0,0.45); font-variant-numeric: tabular-nums;",
                                "{row.source_row}"
                            }
                            for column_id in visible_columns.iter().copied() {
                                {
                                    let cell = row.cell(column_id).cloned();
                                    let class = columns
                                        .iter()
                                        .find(|c| c.column_id == column_id)
                                        .map(|c| c.class())
                                        .unwrap_or(TableColumnClass::Text);
                                    rsx! {
                                        GridCell {
                                            key: "{row.row_id}-{column_id}",
                                            cell,
                                            class,
                                            find_query: find_query.clone(),
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// A header cell: the letter, the label, a type mark, a tri-state sort and a filter.
#[component]
fn ColumnHeader(
    column: TableColumnInfo,
    table_state: DocTableState,
    set_table_state: Callback<DocTableState>,
    document_identifier: DocumentIdentifier,
    sheet_id: u16,
) -> Element {
    let column_id = column.column_id;
    let class = column.class();
    let sort = table_state.sort;
    let sorted = sort.filter(|s| s.column_id == column_id);
    let filtered = table_state.filters.iter().any(|f| f.column_id == column_id);

    // Tri-state on one click: none -> ascending -> descending -> none. Applied
    // immediately, unlike the search toolbar's sort, which edits a pending query behind
    // an Apply button. There is nothing pending here.
    let on_sort = {
        let table_state = table_state.clone();
        move |_| {
            let mut next = table_state.clone();
            next.sort = match sorted {
                None => Some(TableSort { column_id, desc: false }),
                Some(TableSort { desc: false, .. }) => Some(TableSort { column_id, desc: true }),
                Some(_) => None,
            };
            set_table_state.call(next.reset_page());
        }
    };

    let align = if class == TableColumnClass::Number { "right" } else { "left" };
    rsx! {
        th {
            style: "position: sticky; top: 0; z-index: 2; background: #f3f3f3; border-bottom: 1px solid rgba(0,0,0,0.2); padding: 3px 8px; text-align: {align}; white-space: nowrap; font-weight: 600;",
            div {
                style: "display: inline-flex; align-items: center; gap: 4px;",
                span { style: "color: rgba(0,0,0,0.4); font-weight: 400;", "{column.letter}" }
                span {
                    title: "{column.column_type}, {column.non_empty} values, {column.distinct_count} distinct",
                    "{column.label()}"
                }
                // The type is stated in the header, from the manifest, so it is drawn
                // before any cell arrives.
                match class {
                    TableColumnClass::Number => rsx! {
                        span { style: "color: rgba(0,0,0,0.4); font-weight: 400;", title: "Numeric column", "#" }
                    },
                    TableColumnClass::Temporal => rsx! {
                        Icon { icon: MdDateRange, style: "width: 14px; height: 14px; opacity: 0.45;" }
                    },
                    TableColumnClass::Text => rsx! {},
                }
                span {
                    style: "cursor: pointer; display: inline-flex;",
                    title: "Sort. Rows with nothing in this column come last, either way.",
                    onclick: on_sort,
                    match sorted {
                        Some(TableSort { desc: false, .. }) => rsx! {
                            Icon { icon: MdArrowUpward, style: "width: 14px; height: 14px;" }
                        },
                        Some(TableSort { desc: true, .. }) => rsx! {
                            Icon { icon: MdArrowDownward, style: "width: 14px; height: 14px;" }
                        },
                        None => rsx! {
                            Icon { icon: MdSort, style: "width: 14px; height: 14px; opacity: 0.35;" }
                        },
                    }
                }
                ColumnFilterPopover {
                    column: column.clone(),
                    active: filtered,
                    table_state: table_state.clone(),
                    set_table_state,
                    document_identifier,
                    sheet_id,
                }
            }
        }
    }
}

/// The per-column filter popover. Which controls it offers follows the column's class,
/// because a range filter over a column that is half text silently hides rows.
#[component]
fn ColumnFilterPopover(
    column: TableColumnInfo,
    active: bool,
    table_state: DocTableState,
    set_table_state: Callback<DocTableState>,
    document_identifier: DocumentIdentifier,
    sheet_id: u16,
) -> Element {
    let column_id = column.column_id;
    let class = column.class();
    let mut open = use_signal(|| false);
    let mut text = use_signal(String::new);
    let mut low = use_signal(String::new);
    let mut high = use_signal(String::new);

    // Declared for every column, not only text ones: a resource behind an `if` would
    // shift the hook order of every header after it. Every condition lives in the closure.
    //
    // `is_open` is one of them, and it is not an optimisation. A header renders one of
    // these per column, so fetching the value list eagerly costs one GROUP BY over a whole
    // column PER COLUMN on every page render, 60 server calls to open a wide sheet whose
    // reader may never touch a filter. The list is only ever shown inside the popover.
    let value_search = text();
    let is_text = class == TableColumnClass::Text;
    let is_open = open();
    let values: Resource<Vec<TableColumnValue>> = use_resource(use_reactive!(|(
        document_identifier,
        sheet_id,
        column_id,
        value_search,
        is_text,
        is_open
    )| {
        async move {
            if !is_text || !is_open {
                return Vec::new();
            }
            get_table_column_values(document_identifier, sheet_id, column_id, value_search)
                .await
                .unwrap_or_default()
        }
    }));

    let apply = {
        let table_state = table_state.clone();
        move |kind: TableFilterKind| {
            let mut next = table_state.clone();
            next.filters.retain(|f| f.column_id != column_id);
            if !kind.is_noop() {
                next.filters.push(TableColumnFilter { column_id, kind });
            }
            set_table_state.call(next.reset_page());
        }
    };
    let apply_clear = apply.clone();
    let apply_empty = apply.clone();
    let apply_text = apply.clone();
    let apply_range = apply.clone();
    let apply_starts = apply.clone();
    let apply_value = apply;

    let colour = if active { "#0b57d0" } else { "rgba(0,0,0,0.35)" };
    rsx! {
        PopoverRoot {
            open: open(),
            on_open_change: move |value: bool| open.set(value),
            PopoverTrigger {
                span {
                    style: "cursor: pointer; display: inline-flex; color: {colour};",
                    title: "Filter this column",
                    Icon { icon: MdFilterList, style: "width: 14px; height: 14px;" }
                }
            }
            PopoverContent {
                div {
                    style: "min-width: 260px; max-width: 320px; max-height: 380px; overflow-y: auto; padding: 8px; font-weight: 400; text-align: left;",
                    div {
                        style: "font-size: 12px; color: rgba(0,0,0,0.55); margin-bottom: 6px;",
                        "{column.column_type} \u{00b7} {column.distinct_count} distinct \u{00b7} {column.min_value} \u{2013} {column.max_value}"
                    }
                    match class {
                        TableColumnClass::Number | TableColumnClass::Temporal => rsx! {
                            div {
                                style: "display: flex; gap: 6px; align-items: center;",
                                input {
                                    style: "width: 100px; padding: 3px 5px;",
                                    placeholder: "from",
                                    value: "{low}",
                                    oninput: move |e| low.set(e.value()),
                                }
                                span { "\u{2013}" }
                                input {
                                    style: "width: 100px; padding: 3px 5px;",
                                    placeholder: "to",
                                    value: "{high}",
                                    oninput: move |e| high.set(e.value()),
                                }
                            }
                            button {
                                style: "{FILTER_CHIP_STYLE} margin-top: 6px;",
                                onclick: move |_| {
                                    // Open ends on either side are legal, exactly as the
                                    // search page's date pane allows.
                                    let kind = if class == TableColumnClass::Number {
                                        TableFilterKind::NumberRange {
                                            min: low().trim().parse::<f64>().ok(),
                                            max: high().trim().parse::<f64>().ok(),
                                        }
                                    } else {
                                        TableFilterKind::DateRange {
                                            min: (!low().trim().is_empty()).then(|| low().trim().to_string()),
                                            max: (!high().trim().is_empty()).then(|| high().trim().to_string()),
                                        }
                                    };
                                    apply_range(kind);
                                    open.set(false);
                                },
                                "Apply range"
                            }
                        },
                        TableColumnClass::Text => rsx! {
                            input {
                                style: "width: 100%; padding: 4px 6px;",
                                placeholder: "Contains\u{2026}",
                                value: "{text}",
                                oninput: move |e| text.set(e.value()),
                            }
                            div {
                                style: "display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap;",
                                button {
                                    style: FILTER_CHIP_STYLE,
                                    onclick: move |_| {
                                        apply_text(TableFilterKind::Contains(text()));
                                        open.set(false);
                                    },
                                    "Contains"
                                }
                                button {
                                    style: FILTER_CHIP_STYLE,
                                    onclick: move |_| {
                                        apply_starts(TableFilterKind::StartsWith(text()));
                                        open.set(false);
                                    },
                                    "Starts with"
                                }
                            }
                            div {
                                style: "margin-top: 8px; border-top: 1px solid rgba(0,0,0,0.1); padding-top: 6px;",
                                match values.read().clone() {
                                    None => rsx! { div { style: "font-size: 12px; color: rgba(0,0,0,0.5);", "Loading values\u{2026}" } },
                                    Some(values) if values.is_empty() => rsx! {
                                        div { style: "font-size: 12px; color: rgba(0,0,0,0.5);", "No values match." }
                                    },
                                    Some(values) => rsx! {
                                        for value in values {
                                            div {
                                                key: "{value.value}",
                                                style: "display: flex; justify-content: space-between; gap: 8px; padding: 2px 0; cursor: pointer;",
                                                onclick: {
                                                    let chosen = value.value.clone();
                                                    let apply_value = apply_value.clone();
                                                    move |_| {
                                                        apply_value(TableFilterKind::Equals(chosen.clone()));
                                                        open.set(false);
                                                    }
                                                },
                                                span {
                                                    style: "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                                                    "{value.value}"
                                                }
                                                span { style: "color: rgba(0,0,0,0.45);", "{value.count}" }
                                            }
                                        }
                                    },
                                }
                            }
                        },
                    }
                    div {
                        style: "display: flex; gap: 6px; margin-top: 8px; border-top: 1px solid rgba(0,0,0,0.1); padding-top: 6px;",
                        button {
                            style: FILTER_CHIP_STYLE,
                            onclick: move |_| {
                                apply_empty(TableFilterKind::IsEmpty);
                                open.set(false);
                            },
                            "Is empty"
                        }
                        button {
                            style: FILTER_CHIP_STYLE,
                            onclick: move |_| {
                                // A no-op kind clears this column's filter.
                                apply_clear(TableFilterKind::Contains(String::new()));
                                open.set(false);
                            },
                            "Clear"
                        }
                    }
                }
            }
        }
    }
}

/// One cell: cut for the grid, whole in a popover, with the find query marked.
#[component]
fn GridCell(cell: Option<TableCell>, class: TableColumnClass, find_query: String) -> Element {
    let Some(cell) = cell else {
        return rsx! {
            td { style: "{cell_style(class)}" }
        };
    };
    let full = cell.text.clone();
    let cut: String = full.chars().take(CELL_PREVIEW_CHARS).collect();
    let is_cut = cut.chars().count() < full.chars().count();
    let mut open = use_signal(|| false);
    rsx! {
        td {
            style: "{cell_style(class)}",
            title: "{full}",
            PopoverRoot {
                open: open(),
                on_open_change: move |value: bool| open.set(value),
                PopoverTrigger {
                    span {
                        style: "cursor: pointer;",
                        HighlightedText { text: if is_cut { format!("{cut}\u{2026}") } else { cut.clone() }, needle: find_query }
                    }
                }
                PopoverContent {
                    div {
                        // `overflow-wrap: anywhere`, never a horizontally scrolling card:
                        // a 4 000-character cell must read, not slide.
                        style: "max-width: 480px; max-height: 320px; overflow-y: auto; overflow-wrap: anywhere; padding: 8px; font-size: 13px;",
                        div { style: "white-space: pre-wrap;", "{full}" }
                        if let Some(exact) = cell.int_value {
                            // The exact integer, which is the one to copy above 2^53
                            // where the float the sort uses is approximate.
                            div { style: "margin-top: 6px; color: rgba(0,0,0,0.55);", "exact: {exact}" }
                        }
                        if !cell.formula.is_empty() {
                            div { style: "margin-top: 6px; font-family: monospace; color: rgba(0,0,0,0.6);", "= {cell.formula}" }
                        }
                        // Only ODS carries a cell link; for every other reader its
                        // absence is normal, so there is no empty link affordance.
                        if !cell.link.is_empty() {
                            a {
                                style: "margin-top: 6px; display: inline-flex; align-items: center; gap: 4px;",
                                href: "{cell.link}",
                                target: "_blank",
                                Icon { icon: MdLink, style: "width: 14px; height: 14px;" }
                                "{cell.link}"
                            }
                        }
                        div {
                            style: "margin-top: 8px; display: flex; align-items: center; gap: 6px; color: rgba(0,0,0,0.5); font-size: 12px;",
                            Icon { icon: MdContentCopy, style: "width: 14px; height: 14px;" }
                            "{cell.kind}"
                        }
                    }
                }
            }
        }
    }
}

fn cell_style(class: TableColumnClass) -> String {
    let align = if class == TableColumnClass::Number { "right" } else { "left" };
    format!(
        "padding: 2px 8px; border-bottom: 1px solid rgba(0,0,0,0.06); text-align: {align}; \
         max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; \
         font-variant-numeric: tabular-nums;"
    )
}

/// The find query marked inside a cell, with the same accent the search snippets use.
#[component]
fn HighlightedText(text: String, needle: String) -> Element {
    if needle.is_empty() {
        return rsx! { "{text}" };
    }
    let haystack = text.to_lowercase();
    let lowered = needle.to_lowercase();
    let mut pieces: Vec<(String, bool)> = Vec::new();
    let mut cursor = 0usize;
    while let Some(found) = haystack[cursor..].find(&lowered) {
        let start = cursor + found;
        let end = start + lowered.len();
        if start > cursor {
            pieces.push((text[cursor..start].to_string(), false));
        }
        pieces.push((text[start..end].to_string(), true));
        cursor = end;
    }
    if cursor < text.len() {
        pieces.push((text[cursor..].to_string(), false));
    }
    rsx! {
        for (index, (piece, marked)) in pieces.into_iter().enumerate() {
            span {
                key: "{index}",
                style: if marked { "background: rgba(255, 220, 0, 0.5);" } else { "" },
                "{piece}"
            }
        }
    }
}

/// Server-side paging, 50 rows at a time. Not a virtualised grid: the app already has a
/// pager idiom and a virtual scroller is a large amount of new machinery to save one
/// round trip.
#[component]
fn TablePager(
    page: TablePage,
    table_state: DocTableState,
    set_table_state: Callback<DocTableState>,
) -> Element {
    let per_page = page.limit.max(1) as u64;
    let current = table_state.page;
    let last_page = page.total_rows.saturating_sub(1) / per_page;
    let first_row = if page.rows.is_empty() { 0 } else { page.offset + 1 };
    let last_row = page.offset + page.rows.len() as u64;
    let go = Callback::new(move |target: u64| {
        let mut next = table_state.clone();
        next.page = target;
        set_table_state.call(next);
    });
    rsx! {
        div {
            style: "display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 4px 2px; flex: 0 0 auto; font-size: 13px; color: rgba(0,0,0,0.65);",
            div {
                style: "display: flex; align-items: center; gap: 6px;",
                button {
                    style: FILTER_CHIP_STYLE,
                    disabled: current == 0,
                    onclick: move |_| go.call(current.saturating_sub(1)),
                    Icon { icon: MdChevronLeft, style: "width: 16px; height: 16px;" }
                    "Previous"
                }
                span { "page {current + 1} of {last_page + 1}" }
                button {
                    style: FILTER_CHIP_STYLE,
                    disabled: current >= last_page,
                    onclick: move |_| go.call((current + 1).min(last_page)),
                    "Next"
                    Icon { icon: MdChevronRight, style: "width: 16px; height: 16px;" }
                }
            }
            div { "rows {first_row}\u{2013}{last_row} of {page.total_rows}" }
        }
    }
}

#[server]
pub async fn get_table_overview(
    document_identifier: DocumentIdentifier,
) -> Result<Option<TableOverview>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::table_browse::get_table_overview(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

#[server]
pub async fn get_table_page(
    document_identifier: DocumentIdentifier,
    query: TableViewQuery,
) -> Result<TablePage, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::table_browse::get_table_page(&user, document_identifier, query)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

#[server]
pub async fn get_table_column_values(
    document_identifier: DocumentIdentifier,
    sheet_id: u16,
    column_id: u32,
    search: String,
) -> Result<Vec<TableColumnValue>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::table_browse::get_table_column_values(
        &user,
        document_identifier,
        sheet_id,
        column_id,
        search,
    )
    .await
    .map_err(crate::api::error_util::to_server_fn_error)
}
