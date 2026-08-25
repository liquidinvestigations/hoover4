//! The operations log: every long operation somebody asked for, and how it really ended.
//!
//! The list exists to make a *partial* failure visible to a person who is not looking
//! for it. A run that finished over failed documents is the case this page is built
//! around, so a finished row never renders as plain success while its own counters say
//! otherwise, and a task type failing above the deployment's configured line is called
//! out rather than left to be noticed in a percentage column.

use common::operations_types::{OperationRow, OperationsPage, TaskErrorRate};
use dioxus::prelude::*;

use crate::api::admin_api::{admin_cancel_operation, admin_list_operations, admin_rerun_operation};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_SMALL, BTN_SMALL_DANGER, C_DANGER,
    HELP_TEXT, INPUT, LABEL, MODULE, MODULE_BODY, MODULE_CAPTION, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;

/// Rows per page. Deliberately small: the log is read newest-first and the interesting
/// row is almost always near the top.
const PAGE_SIZE: u32 = 25;

#[component]
pub fn AdminOperationsPage() -> Element {
    rsx! {
        Title { "Admin: operations" }
        AdminGuard {
            AdminShell {
                title: "Operations".to_string(),
                breadcrumb: "Operations".to_string(),
                active: "operations".to_string(),
                SuspendWrapper { OperationsContent {} }
            }
        }
    }
}

#[component]
fn OperationsContent() -> Element {
    let mut state_filter = use_signal(String::new);
    let mut collection_filter = use_signal(String::new);
    let mut page = use_signal(|| 0_u32);

    // Every filter is read **inside** the resource. A value read outside it is captured
    // once and the list then never changes when a control does, which is the single
    // most common way a filter here silently does nothing.
    let mut ops_res = use_resource(move || {
        let state = state_filter();
        let collection = collection_filter();
        let offset = page() * PAGE_SIZE;
        async move { admin_list_operations(state, collection, PAGE_SIZE, offset).await }
    });

    let msg = use_signal(|| None::<String>);
    let error_msg = use_signal(|| None::<String>);

    let data = ops_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();
    let load_error = ops_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(user_facing_message));

    let Some(data) = data else {
        return rsx! {
            if let Some(e) = load_error {
                ErrorBar { message: e }
            } else {
                p { style: HELP_TEXT, "Loading operations…" }
            }
        };
    };

    let collections = data.collections.clone();
    let has_more = data.has_more;
    let current_page = page();

    rsx! {
        if let Some(m) = msg() {
            SuccessBar { message: m }
        }
        if let Some(e) = error_msg() {
            ErrorBar { message: e }
        }
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Filters" }
            div { style: "{MODULE_BODY} display: flex; gap: 16px; flex-wrap: wrap; align-items: center;",
                label { style: LABEL,
                    "State"
                    select {
                        // Stable ids, because the screenshot harness drives these two
                        // controls and a selector built from styling breaks silently.
                        id: "x-ops-filter-state",
                        style: SELECT,
                        value: "{state_filter}",
                        onchange: move |e| {
                            state_filter.set(e.value());
                            page.set(0);
                        },
                        option { value: "", "Any state" }
                        for s in ["pending", "running", "finished", "errored", "cancelled"] {
                            option { value: "{s}", "{s}" }
                        }
                    }
                }
                label { style: LABEL,
                    "Collection"
                    select {
                        id: "x-ops-filter-collection",
                        style: SELECT,
                        value: "{collection_filter}",
                        onchange: move |e| {
                            collection_filter.set(e.value());
                            page.set(0);
                        },
                        option { value: "", "All collections" }
                        for c in collections.iter() {
                            option { value: "{c}", "{c}" }
                        }
                    }
                }
                span { style: HELP_TEXT,
                    "Choose a collection to see its per-task error rates."
                }
            }
        }

        TaskErrorRatePanel {
            rates: data.task_error_rates.clone(),
            threshold: data.error_rate_threshold_percent,
            collectionname: collection_filter(),
        }

        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Operations, newest first" }
            div { style: MODULE_BODY,
                OperationsTable {
                    rows: data.rows.clone(),
                    msg,
                    error_msg,
                    on_changed: EventHandler::new(move |_| ops_res.restart()),
                }
                div { style: "display: flex; gap: 8px; align-items: center; margin-top: 10px;",
                    button {
                        style: BTN_SMALL,
                        disabled: current_page == 0,
                        onclick: move |_| page.set(current_page.saturating_sub(1)),
                        "Newer"
                    }
                    span { style: HELP_TEXT, "Page {current_page + 1}" }
                    button {
                        style: BTN_SMALL,
                        disabled: !has_more,
                        onclick: move |_| page.set(current_page + 1),
                        "Older"
                    }
                }
            }
        }
    }
}

/// Per-task error rates, with the ones above the configured line made distinct.
///
/// Below the line is a success on a messy corpus and is deliberately quiet. Above it is
/// a candidate tooling limitation, which is the thing a person is meant to notice at a
/// glance without reading the percentages.
#[component]
fn TaskErrorRatePanel(
    rates: Vec<TaskErrorRate>,
    threshold: f64,
    collectionname: String,
) -> Element {
    if collectionname.is_empty() {
        return rsx! {};
    }
    let above: Vec<&TaskErrorRate> = rates.iter().filter(|r| r.above_threshold).collect();
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Failure rate by task type ({collectionname})" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    "One row per activity execution, retries included. Anything over "
                    b { "{threshold:.1}%" }
                    " is called out as a possible tooling limitation; below that is an ordinary "
                    "failure rate on a messy corpus."
                }
                if rates.is_empty() {
                    p { style: HELP_TEXT, "No task executions recorded for this collection yet." }
                } else {
                    if above.is_empty() {
                        p { style: "font-size: 13px; color: #2e7d32; margin: 0 0 10px;",
                            "No task type is failing above {threshold:.1}%."
                        }
                    } else {
                        p { style: "font-size: 13px; color: {C_DANGER}; font-weight: 600; margin: 0 0 10px;",
                            "{above.len()} task type(s) failing above {threshold:.1}%."
                        }
                    }
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Task" }
                                th { style: TH, "Error rate" }
                                th { style: TH, "Failed / total executions" }
                                th { style: TH, "Documents affected" }
                            }
                        }
                        tbody {
                            for r in rates.iter() {
                                tr {
                                    style: if r.above_threshold {
                                        "background: #fdeaea;"
                                    } else {
                                        ""
                                    },
                                    td { style: TD, "{r.task_name}" }
                                    td {
                                        style: if r.above_threshold {
                                            "{TD} color: {C_DANGER}; font-weight: 700;"
                                        } else {
                                            "{TD} color: #666;"
                                        },
                                        "{r.error_rate_percent:.1}%"
                                        if r.above_threshold {
                                            span { style: "margin-left: 6px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;",
                                                "above the line"
                                            }
                                        }
                                    }
                                    td { style: TD, "{r.runs_failed} / {r.runs_total}" }
                                    td { style: TD, "{r.documents_failed} / {r.documents_total}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

fn format_duration(seconds: u64) -> String {
    if seconds < 60 {
        format!("{seconds}s")
    } else if seconds < 3600 {
        format!("{}m {}s", seconds / 60, seconds % 60)
    } else {
        format!("{}h {}m", seconds / 3600, (seconds % 3600) / 60)
    }
}

/// The colour a state is rendered in. `finished` is deliberately not green here: a
/// finished operation is only good news once its failure counter has been read, and the
/// row says so beside it.
fn state_colour(state: &str) -> &'static str {
    match state {
        "running" => "#417690",
        "pending" => "#8a6d3b",
        "finished" => "#2e7d32",
        "cancelled" => "#666",
        _ => C_DANGER,
    }
}

/// The operations table itself, so `/admin/operations` and the collection page render
/// exactly the same row rather than two lists that drift.
#[component]
pub fn OperationsTable(
    rows: Vec<OperationRow>,
    msg: Signal<Option<String>>,
    error_msg: Signal<Option<String>>,
    on_changed: EventHandler<()>,
) -> Element {
    if rows.is_empty() {
        return rsx! {
            p { style: HELP_TEXT, "No operations recorded for this filter." }
        };
    }
    rsx! {
        table { style: TABLE,
            thead {
                tr {
                    th { style: TH, "Kind" }
                    th { style: TH, "Target" }
                    th { style: TH, "State" }
                    th { style: TH, "Started" }
                    th { style: TH, "Duration" }
                    th { style: TH, "Progress" }
                    th { style: TH, "ETA" }
                    th { style: TH, "Outcome" }
                    th { style: TH, "" }
                }
            }
            tbody {
                for row in rows.iter() {
                    OperationTableRow {
                        key: "{row.op_id}",
                        row: row.clone(),
                        msg,
                        error_msg,
                        on_changed,
                    }
                }
            }
        }
    }
}

#[component]
fn OperationTableRow(
    row: OperationRow,
    msg: Signal<Option<String>>,
    error_msg: Signal<Option<String>>,
    on_changed: EventHandler<()>,
) -> Element {
    let mut confirm_text = use_signal(String::new);
    let mut msg = msg;
    let mut error_msg = error_msg;

    let running = row.state == "running" || row.state == "pending";
    let target = row.target.clone();
    let confirm_ready = !row.destructive || *confirm_text.read() == target;

    rsx! {
        tr {
            td { style: TD,
                code { "{row.kind}" }
                if row.destructive {
                    div { style: "font-size: 11px; color: {C_DANGER}; text-transform: uppercase; letter-spacing: 0.5px;",
                        "destructive"
                    }
                }
                if !row.rerun_of.is_empty() {
                    div { style: HELP_TEXT, "re-run of {row.rerun_of}" }
                }
            }
            td { style: TD,
                "{row.target}"
                div { style: HELP_TEXT, "{row.user_id}" }
            }
            td {
                style: "{TD} color: {state_colour(&row.state)}; font-weight: 600;",
                "{row.state}"
            }
            td { style: TD, "{row.started_at}" }
            td { style: TD, "{format_duration(row.duration_seconds)}" }
            td { style: TD, ProgressCell { row: row.clone() } }
            td { style: TD,
                if row.eta_seconds > 0 {
                    "{format_duration(row.eta_seconds as u64)}"
                } else if running {
                    span { style: HELP_TEXT, "no estimate yet" }
                } else {
                    span { style: HELP_TEXT, "n/a" }
                }
            }
            td { style: TD, OutcomeCell { row: row.clone() } }
            td { style: TD,
                if running {
                    button {
                        style: BTN_SMALL_DANGER,
                        onclick: {
                            let op_id = row.op_id.clone();
                            move |_| {
                                let op_id = op_id.clone();
                                spawn(async move {
                                    match admin_cancel_operation(op_id).await {
                                        Ok(()) => {
                                            msg.set(Some("Cancellation requested.".into()));
                                            on_changed.call(());
                                        }
                                        Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                    }
                                });
                            }
                        },
                        "Cancel"
                    }
                } else {
                    if row.destructive {
                        input {
                            style: "{INPUT} width: 130px; margin-bottom: 4px;",
                            placeholder: "type {target} to confirm",
                            value: "{confirm_text}",
                            oninput: move |e| confirm_text.set(e.value()),
                        }
                    }
                    button {
                        style: BTN_SMALL,
                        disabled: !confirm_ready,
                        onclick: {
                            let op_id = row.op_id.clone();
                            move |_| {
                                let op_id = op_id.clone();
                                let confirm = confirm_text.read().clone();
                                spawn(async move {
                                    match admin_rerun_operation(op_id, confirm).await {
                                        Ok(new_id) => {
                                            msg.set(Some(format!("Dispatched {new_id}.")));
                                            confirm_text.set(String::new());
                                            on_changed.call(());
                                        }
                                        Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                    }
                                });
                            }
                        },
                        "Re-run"
                    }
                }
            }
        }
    }
}

/// The counters as a sentence, in the unit the kind actually counts.
///
/// **The unit is a property of the kind, not of the page.** A purge counts rows still in
/// the stores, an export counts bytes moved, and everything else counts plans; rendering
/// one label for all three states the wrong thing about two of them, and a reader has no
/// way to tell. "606989269 / 606989269 Plans" is not a number anyone can question.
/// Bytes are rendered human-readable, because nine digits is not a reading.
fn progress_reading(row: &OperationRow) -> String {
    match row.kind.as_str() {
        "export_collection" | "import_collection" => format!(
            "{} / {}",
            common::filter_summary::format_bytes(row.progress_done as i64),
            common::filter_summary::format_bytes(row.progress_total as i64),
        ),
        "purge_dataset" | "delete_dataset" => {
            format!("{} / {} rows", row.progress_done, row.progress_total)
        }
        _ => format!("{} / {} plans", row.progress_done, row.progress_total),
    }
}

/// The progress bar, and the one thing it must never do: render `0 / 0` as an empty bar
/// over a run that is working. Zero total means the scan has not produced plans yet,
/// which is a different statement from no progress.
#[component]
fn ProgressCell(row: OperationRow) -> Element {
    if row.progress_total == 0 {
        return rsx! {
            span { style: HELP_TEXT,
                if row.state == "running" || row.state == "pending" {
                    "counting work…"
                } else {
                    "n/a"
                }
            }
        };
    }
    let percent = (row.progress_done as f64 * 100.0 / row.progress_total as f64).clamp(0.0, 100.0);
    let complete = row.progress_done >= row.progress_total;
    let bar = if complete { "#79aec8" } else { "#417690" };
    rsx! {
        div { style: "min-width: 110px;",
            div { style: "background: #eee; border-radius: 3px; height: 8px; overflow: hidden;",
                div { style: "background: {bar}; height: 8px; width: {percent:.0}%;" }
            }
            div { style: HELP_TEXT, "{progress_reading(&row)}" }
        }
    }
}

/// What actually happened, which is not the same question as what state the row is in.
///
/// A `finished` operation over failed documents is the case this whole page exists for,
/// so the failure count is rendered here beside the state rather than left in a detail
/// view nobody opens. A count the operation never recorded reads as unknown, never as
/// zero: an invented clean result is worse than an absent one, because it is trusted.
#[component]
fn OutcomeCell(row: OperationRow) -> Element {
    rsx! {
        div {
            if !row.error.is_empty() {
                div { style: "color: {C_DANGER}; font-size: 12px; max-width: 320px; overflow-wrap: anywhere;",
                    "{row.error}"
                }
            }
            match row.failed_documents {
                Some(0) => rsx! {
                    span { style: "font-size: 12px; color: #2e7d32;", "no failed documents" }
                },
                Some(n) => rsx! {
                    div { style: "color: {C_DANGER}; font-weight: 700; font-size: 12px;",
                        "{n} document(s) failed"
                    }
                    if let Some(t) = row.failed_tasks {
                        div { style: HELP_TEXT, "{t} task failure(s)" }
                    }
                },
                None => rsx! {
                    if row.error.is_empty() {
                        span { style: HELP_TEXT, "failures not counted" }
                    }
                },
            }
        }
    }
}

/// The same log, scoped to one collection, for embedding on the collection page.
///
/// The scope is held in a signal and read inside the resource: the router reuses this
/// component when it navigates between two collections, and a prop read outside the
/// resource would leave the previous collection's rows on screen.
#[component]
pub fn CollectionOperationsPanel(collectionname: String) -> Element {
    let mut scope = use_signal(|| collectionname.clone());
    if *scope.read() != collectionname {
        scope.set(collectionname.clone());
    }
    let mut ops_res = use_resource(move || {
        let c = scope();
        async move { admin_list_operations(String::new(), c, 10, 0).await }
    });
    let msg = use_signal(|| None::<String>);
    let error_msg = use_signal(|| None::<String>);

    let data: Option<OperationsPage> = ops_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();

    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Operations" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    "Long operations dispatched against this collection, newest first. "
                    "Per-dataset OCR language changes are not operations yet and do not appear here."
                }
                if let Some(m) = msg() {
                    SuccessBar { message: m }
                }
                if let Some(e) = error_msg() {
                    ErrorBar { message: e }
                }
                match data {
                    Some(d) => rsx! {
                        OperationsTable {
                            rows: d.rows.clone(),
                            msg,
                            error_msg,
                            on_changed: EventHandler::new(move |_| ops_res.restart()),
                        }
                    },
                    None => rsx! { p { style: HELP_TEXT, "Loading operations…" } },
                }
            }
        }
    }
}
