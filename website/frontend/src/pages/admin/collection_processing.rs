//! Admin page: processing status, workflows and failures for one collection.

use std::time::Duration;

use common::processing_types::{
    CollectionProcessingStatus, DocumentFailure, EtaSamplePoint, LiveTaskActivity, StageProgress,
    TaskFailureGroup, TaskTimeBreakdown, WorkflowFilter, WorkflowSummary, LIVE_WINDOW_SECONDS,
    STAGE_EXECUTE, STAGE_INDEX, STAGE_NLP, STAGE_PLAN,
};
use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{
    admin_collection_processing, admin_list_document_failures, admin_list_eta_samples,
    admin_list_task_failures, admin_list_workflows, admin_retry_document, admin_retry_failed_task,
    admin_task_time_breakdown, admin_task_time_live,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, DatasetOperationStrip, ErrorBar, SuccessBar, BTN_SMALL, HELP_TEXT, LINK,
    MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::tr;
// Shadows the prelude's element table so `svg_title` exists. See its module docs. An
// HTML `<title>` inside an `<svg>` is a foreign element and never becomes a tooltip.
use crate::components::svg_title::dioxus_elements;
use crate::routes::Route;

/// How many rows each list fetches. Deliberately small: these pages are a triage view,
/// not an export.
const LIST_LIMIT: u32 = 50;

/// What one panel's data is actually in, including *failed*, which this page used to
/// throw away.
///
/// Every panel here read its resource as `…and_then(|r| r.as_ref().ok()).cloned()`, which
/// maps a server fn that returned an error onto the same `None` as a request still in
/// flight. So a 500 rendered as "Loading…" without end, and with no error anywhere on the page.
/// Both failure lists 500'd on every collection that actually had failures and the page
/// said nothing at all about it; that is the bug this type exists to make unrepresentable.
#[derive(Clone, PartialEq)]
enum Load<T> {
    Pending,
    Failed(String),
    Ready(T),
}

fn load_state<T: Clone + 'static>(res: Resource<Result<T, ServerFnError>>) -> Load<T> {
    match &*res.read() {
        None => Load::Pending,
        Some(Ok(value)) => Load::Ready(value.clone()),
        Some(Err(e)) => Load::Failed(user_facing_message(&e)),
    }
}

/// The "this panel could not load" line. Inline rather than a page-level `ErrorBar`: the
/// reader needs to know *which* list is missing, and the rest of the page is still good.
#[component]
fn PanelError(message: String) -> Element {
    rsx! {
        p {
            style: "color: var(--x-danger); font-size: var(--x-text-sm); margin: 0;",
            {tr!("admin-collection-processing-could-not-load-this-panel", message: message.to_string())}
        }
    }
}

#[component]
pub fn AdminCollectionProcessingPage(collection_id: String) -> Element {
    let for_content = collection_id.clone();
    rsx! {
        Title { {tr!("admin-collection-processing-admin-processing-of", collection_id: collection_id.to_string())} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-collection-processing-processing-of", collection_id: collection_id.to_string()),
                breadcrumb: tr!("admin-collection-processing-collections", collection_id: collection_id.to_string()),
                active: "collections".to_string(),
                SuspendWrapper { ProcessingContent { collection_id: for_content } }
            }
        }
    }
}

/// Render a duration in the largest sensible unit. An ETA of "13140 s" is unreadable.
fn humanize_seconds(seconds: u64) -> String {
    match seconds {
        s if s < 60 => format!("{s}s"),
        s if s < 3600 => format!("{}m", s / 60),
        s if s < 86_400 => format!("{}h {}m", s / 3600, (s % 3600) / 60),
        s => format!("{}d {}h", s / 86_400, (s % 86_400) / 3600),
    }
}

#[component]
fn ProcessingContent(collection_id: String) -> Element {
    let status_id = collection_id.clone();
    let status_res = use_resource(move || admin_collection_processing(status_id.clone()));

    let eta_id = collection_id.clone();
    let eta_res = use_resource(move || admin_list_eta_samples(eta_id.clone()));

    let filter = use_signal(|| WorkflowFilter::All);
    let wf_id = collection_id.clone();
    let workflows_res =
        use_resource(move || admin_list_workflows(wf_id.clone(), *filter.read(), LIST_LIMIT));

    let tf_id = collection_id.clone();
    let task_failures_res = use_resource(move || admin_list_task_failures(tf_id.clone(), LIST_LIMIT));

    let df_id = collection_id.clone();
    let doc_failures_res =
        use_resource(move || admin_list_document_failures(df_id.clone(), String::new(), LIST_LIMIT));

    let tt_id = collection_id.clone();
    let task_time_res = use_resource(move || admin_task_time_breakdown(tt_id.clone()));

    let msg = use_signal(|| None::<String>);
    let error_msg = use_signal(|| None::<String>);

    // One "refresh everything" closure, so a retry updates the progress bars and the
    // workflow list too, which are the two things an admin looks at right after clicking Retry.
    // `Resource` is `Copy`, so each call re-copies the handles; that keeps the closure
    // `Fn` and lets it be handed to more than one `EventHandler`.
    let refresh_all = move || {
        let (mut s, mut w, mut t, mut d, mut e, mut tt) = (
            status_res,
            workflows_res,
            task_failures_res,
            doc_failures_res,
            eta_res,
            task_time_res,
        );
        s.restart();
        w.restart();
        t.restart();
        d.restart();
        e.restart();
        tt.restart();
    };

    rsx! {
        if let Some(m) = msg.read().clone() {
            SuccessBar { message: m }
        }
        if let Some(e) = error_msg.read().clone() {
            ErrorBar { message: e }
        }
        div { style: "margin-bottom: 16px;",
            Link {
                to: Route::AdminCollectionPage { collection_id: collection_id.clone() },
                style: LINK,
                {tr!("admin-collection-processing-u-back-to-collection")}
            }
        }

        // One strip per dataset that has ever had an admin job. This page is where an
        // admin looks when processing seems stuck, and an apply job running here is the
        // most likely reason the dataset's own form is locked.
        if let Some(Ok(status)) = status_res.read().as_ref() {
            for dataset in status.datasets.iter() {
                DatasetOperationStrip {
                    key: "{dataset.collection_dataset}",
                    collection_dataset: dataset.collection_dataset.clone(),
                }
            }
        }

        StagesPanel {
            status: load_state(status_res),
            eta_samples: eta_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned(),
        }

        LiveActivityPanel { collection_id: collection_id.clone() }

        TaskTimePanel { breakdown: load_state(task_time_res) }

        WorkflowsPanel {
            workflows: load_state(workflows_res),
            filter: filter,
        }

        TaskFailuresPanel {
            collection_id: collection_id.clone(),
            failures: load_state(task_failures_res),
            msg: msg,
            error_msg: error_msg,
            on_retry: EventHandler::new(move |_| refresh_all()),
        }

        DocumentFailuresPanel {
            collection_id: collection_id.clone(),
            failures: load_state(doc_failures_res),
            msg: msg,
            error_msg: error_msg,
            on_retry: EventHandler::new(move |_| refresh_all()),
        }
    }
}

#[component]
fn StagesPanel(status: Load<CollectionProcessingStatus>, eta_samples: Option<Vec<EtaSamplePoint>>) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-processing-processing-stages")} }
            div { style: MODULE_BODY,
                match status {
                    Load::Pending => rsx! { {tr!("admin-collection-processing-loading-u")} },
                    Load::Failed(e) => rsx! { PanelError { message: e } },
                    Load::Ready(s) if !s.db_ready => rsx! {
                        p { style: HELP_TEXT, {tr!("admin-collection-processing-the-collection-database-is-still")} }
                    },
                    Load::Ready(s) if s.datasets.is_empty() => rsx! {
                        p { style: HELP_TEXT, {tr!("admin-collection-processing-this-collection-has-no-datasets")} }
                    },
                    Load::Ready(s) => rsx! {
                        for ds in s.datasets {
                            div { key: "{ds.collection_dataset}", style: "margin-bottom: 22px;",
                                div { style: "font-size: var(--x-text-sm); font-weight: 700; color: var(--x-ink); margin-bottom: 8px;",
                                    "{ds.dataset_display_name} "
                                    span { style: HELP_TEXT, "({ds.collection_dataset})" }
                                    if ds.error_count > 0 {
                                        span { style: "color: var(--x-danger); margin-left: 8px;", {tr!("admin-collection-processing-errors-2", ds_error_count: ds.error_count)} }
                                    }
                                }
                                for stage in ds.stages {
                                    StageBar { key: "{stage.stage}", stage: stage }
                                }
                                EtaSection {
                                    samples: eta_samples
                                        .as_ref()
                                        .map(|all| {
                                            all.iter()
                                                .filter(|p| p.collection_dataset == ds.collection_dataset)
                                                .cloned()
                                                .collect::<Vec<_>>()
                                        })
                                        .unwrap_or_default(),
                                }
                            }
                        }
                    },
                }
            }
        }
    }
}

#[component]
fn StageBar(stage: StageProgress) -> Element {
    let percent = stage.percent();
    let complete = stage.is_complete();
    let bar_color = if complete { "var(--x-ok)" } else { "var(--x-link)" };
    let width = percent.unwrap_or(0.0);

    rsx! {
        div { style: "display: flex; align-items: center; gap: 10px; margin-bottom: 5px;",
            div { style: "width: 220px; font-size: var(--x-text-xs); color: var(--x-ink); flex-shrink: 0;", "{stage.label}" }
            div {
                style: "flex: 1; height: 14px; background: #eee; border-radius: 3px; overflow: hidden; min-width: 80px;",
                // A stage with no denominator gets a flat neutral fill rather than a
                // misleading empty or full bar.
                if percent.is_some() {
                    div { style: "height: 100%; width: {width}%; background: {bar_color};" }
                } else {
                    div { style: "height: 100%; width: 100%; background: repeating-linear-gradient(45deg, #ddd, #ddd 6px, #eee 6px, #eee 12px);" }
                }
            }
            div { style: "width: 190px; font-size: var(--x-text-xs); color: var(--x-ink-muted); flex-shrink: 0;",
                match stage.total {
                    Some(total) => rsx! { "{stage.done} / {total} {stage.unit}" },
                    None => rsx! { "{stage.done} {stage.unit}" },
                }
            }
            div { style: "width: 130px; font-size: var(--x-text-xs); color: var(--x-ink-muted); flex-shrink: 0;",
                match stage.eta_seconds {
                    Some(eta) => rsx! { {tr!("admin-collection-processing-eta", humanize_seconds_eta: (humanize_seconds(eta)).to_string())} },
                    None if complete => rsx! { span { style: "color: var(--x-ok);", {tr!("admin-collection-processing-done")} } },
                    None => rsx! { "\u{2014}" },
                }
            }
            // A stage that lost documents must not read as finished. The pipeline
            // records per-document failures and carries on by design, so `done / total`
            // alone hides them. This is the column that says so, next to the bar the
            // failure happened at rather than only in the panels further down.
            div { style: "width: 110px; font-size: var(--x-text-xs); flex-shrink: 0;",
                if stage.failed_documents > 0 {
                    span { style: "color: var(--x-danger);", {tr!("admin-collection-processing-failed-2", stage_failed_documents: stage.failed_documents.to_string())} }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// ETA estimates
// ---------------------------------------------------------------------------

/// Stage colors for the estimate chart, keyed by the `STAGE_*` constants.
const ETA_STAGE_STYLES: &[(&str, &str, &str)] = &[
    (STAGE_PLAN, "P1 plan", "var(--x-link)"),
    (STAGE_EXECUTE, "P2/P3 execute", "var(--x-link)"),
    (STAGE_NLP, "P4 nlp", "#c1883c"),
    (STAGE_INDEX, "P6 index", "var(--x-ok)"),
];

/// Per-dataset ETA: the current best-effort deadline and a chart of the last
/// 100 stored estimates per stage.
///
/// The chart plots the *time remaining* against sample time: a converging estimate
/// falls towards zero, a sawtooth means the estimate is wandering and should not be
/// trusted, and a flat line means no progress is being made.
///
/// It must not plot the absolute deadline instead. `deadline = sampled_at + eta`, so a
/// steady pipeline draws `y = x`: every stage lands on the same 45° line and the chart
/// says nothing at all. The interesting quantity is the offset, so plot the offset.
#[component]
fn EtaSection(samples: Vec<EtaSamplePoint>) -> Element {
    if samples.is_empty() {
        return rsx! {
            p { style: "{HELP_TEXT} margin: 4px 0 0;",
                {tr!("admin-collection-processing-no-estimate-samples-yet-they")}
            }
        };
    }

    // Samples arrive newest-first per stage (LIMIT 100 BY dataset, stage).
    // The current estimate is the newest sample of each stage; the dataset
    // deadline is the latest deadline among stages that still have one.
    let mut newest_per_stage: std::collections::BTreeMap<&str, &EtaSamplePoint> =
        std::collections::BTreeMap::new();
    for s in &samples {
        newest_per_stage.entry(s.stage.as_str()).or_insert(s);
    }
    let current = newest_per_stage
        .values()
        .filter(|s| s.eta_seconds > 0)
        .max_by_key(|s| s.deadline_unix);

    rsx! {
        div { style: "margin: 8px 0 4px; padding: 10px; background-color: var(--x-surface-muted); border: 1px solid; border-color: var(--x-border); border-radius: 4px;",
            div { style: "font-size: var(--x-text-sm); color: var(--x-ink); margin-bottom: 6px;",
                match current {
                    Some(c) => rsx! {
                        {tr!("admin-collection-processing-estimated-completion")}
                        b { "{c.deadline}" }
                        span { style: HELP_TEXT, {tr!("admin-collection-processing-in-a-best-effort-estimate", humanize_seconds_c_eta_seconds: (humanize_seconds(c.eta_seconds)).to_string())} }
                    },
                    None => rsx! {
                        span { style: HELP_TEXT, {tr!("admin-collection-processing-no-current-estimate-the-pipeline")} }
                    },
                }
            }
            EtaChart { samples: samples.clone() }
            div { style: "display: flex; gap: 14px; margin-top: 4px;",
                for (stage, label, color) in ETA_STAGE_STYLES {
                    span { key: "{stage}", style: "font-size: var(--x-text-xs); color: var(--x-ink-muted);",
                        span { style: "display: inline-block; width: 10px; height: 10px; background: {color}; margin-right: 4px; border-radius: 2px;" }
                        "{label}"
                    }
                }
            }
        }
    }
}

#[component]
fn EtaChart(samples: Vec<EtaSamplePoint>) -> Element {
    const W: f64 = 720.0;
    const H: f64 = 180.0;
    // Gutters, not padding: the axis labels live outside the plot area, which is what
    // keeps the two time labels from landing on top of each other in the corner.
    const LEFT: f64 = 56.0;
    const RIGHT: f64 = 10.0;
    const TOP: f64 = 12.0;
    const BOTTOM: f64 = 22.0;

    let plot_w = W - LEFT - RIGHT;
    let plot_h = H - TOP - BOTTOM;
    let baseline = TOP + plot_h;

    let (min_x, max_x) = samples
        .iter()
        .fold((i64::MAX, i64::MIN), |(lo, hi), s| {
            (lo.min(s.sampled_at_unix), hi.max(s.sampled_at_unix))
        });
    // The axis starts at zero: "how much is left" is a magnitude, and a remaining-time
    // axis that does not include zero hides how close the finish is.
    let max_eta = samples.iter().map(|s| s.eta_seconds).max().unwrap_or(0);
    // Degenerate ranges (one sample, or a perfectly stable estimate) still
    // need a span to scale against.
    let span_x = (max_x - min_x).max(1) as f64;
    let span_y = max_eta.max(1) as f64;

    let px = move |t: i64| LEFT + (t - min_x) as f64 / span_x * plot_w;
    let py = move |eta: u64| baseline - eta as f64 / span_y * plot_h;

    // Three ticks over a real range; one when there is no range. Every remaining time
    // being zero is a finished pipeline, and three gridlines all reading `0s` describe an
    // axis that does not exist. The baseline alone is the whole truth there.
    let ticks: Vec<(f64, String)> = if max_eta == 0 {
        vec![(baseline, humanize_seconds(0))]
    } else {
        (0..=2)
            .map(|i| {
                let fraction = i as f64 / 2.0;
                (
                    baseline - fraction * plot_h,
                    humanize_seconds((max_eta as f64 * fraction).round() as u64),
                )
            })
            .collect()
    };

    let first = samples.iter().min_by_key(|s| s.sampled_at_unix);
    let last = samples.iter().max_by_key(|s| s.sampled_at_unix);

    rsx! {
        svg {
            width: "100%",
            height: "{H}",
            "viewBox": "0 0 {W} {H}",
            style: "background: white; border: 1px solid; border-color: var(--x-border); max-width: 720px; display: block;",

            // Keyed by position on the axis, never by the label: two ticks can carry the
            // same text, and duplicate keys among siblings are a dioxus-core assertion on
            // a debug build and an undefined re-association on a release one.
            for (tick, (y, label)) in ticks.into_iter().enumerate() {
                g {
                    key: "y-{tick}",
                    line {
                        x1: "{LEFT}", y1: "{y}", x2: "{W - RIGHT}", y2: "{y}",
                        "stroke": "#e5e5e5", "stroke-width": "1",
                    }
                    text {
                        x: "{LEFT - 6.0}", y: "{y + 3.5}",
                        "text-anchor": "end",
                        style: "font-size: var(--x-text-xs); fill: #666;",
                        "{label}"
                    }
                }
            }
            text {
                x: "{LEFT - 6.0}", y: "{TOP - 3.0}",
                "text-anchor": "end",
                style: "font-size: var(--x-text-xs); fill: #999;",
                {tr!("admin-collection-processing-left")}
            }

            for (stage, label, color) in ETA_STAGE_STYLES {
                {
                    let mut pts: Vec<&EtaSamplePoint> =
                        samples.iter().filter(|s| s.stage == *stage).collect();
                    // Query order is newest-first; plot oldest to newest.
                    pts.reverse();
                    let points = pts
                        .iter()
                        .map(|s| format!("{:.1},{:.1}", px(s.sampled_at_unix), py(s.eta_seconds)))
                        .collect::<Vec<_>>()
                        .join(" ");
                    rsx! {
                        polyline {
                            key: "{stage}",
                            points: "{points}",
                            fill: "none",
                            "stroke": "{color}",
                            "stroke-width": "2",
                            "stroke-linejoin": "round",
                            svgtitle { "{label}" }
                        }
                    }
                }
            }

            line {
                x1: "{LEFT}", y1: "{baseline}", x2: "{W - RIGHT}", y2: "{baseline}",
                "stroke": "#bbb", "stroke-width": "1",
            }
            // The sample window, anchored to opposite ends of the plot. Left-anchoring
            // both inside it prints one timestamp over the other.
            if let (Some(f), Some(l)) = (first, last) {
                text {
                    x: "{LEFT}", y: "{H - 7.0}",
                    "text-anchor": "start",
                    style: "font-size: var(--x-text-xs); fill: #666;",
                    "{f.sampled_at}"
                }
                if l.sampled_at_unix != f.sampled_at_unix {
                    text {
                        x: "{W - RIGHT}", y: "{H - 7.0}",
                        "text-anchor": "end",
                        style: "font-size: var(--x-text-xs); fill: #666;",
                        "{l.sampled_at}"
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Where processing time goes
// ---------------------------------------------------------------------------

/// How often the live panel re-reads. Matches the worker's in-flight sampling interval
/// (`tasks/task_timing.py`), so the page never renders the same sample twice in a row
/// and never skips one.
const LIVE_REFRESH_MS: u64 = 5_000;

/// Seconds, in the largest unit that still shows the magnitude. A per-task total is
/// read against the others on the page, so the raw seconds stay visible next to it.
fn format_seconds(seconds: f64) -> String {
    if seconds < 60.0 {
        format!("{seconds:.1} s")
    } else {
        format!("{:.0} s ({})", seconds, humanize_seconds(seconds as u64))
    }
}

/// A horizontal share bar, same visual language as [`StageBar`]'s fill.
#[component]
fn ShareBar(percent: f64, color: String) -> Element {
    let width = percent.clamp(0.0, 100.0);
    rsx! {
        div {
            style: "width: 120px; height: 10px; background: #eee; border-radius: 3px; overflow: hidden;",
            div { style: "height: 100%; width: {width}%; background: {color};" }
        }
    }
}

/// Per-task-type time breakdown, sorted so the top row is where to optimise.
///
/// Reads `processing_task_runs`, one row per activity execution, failures included at
/// their real cost. This is the after-the-fact view; the live panel above it is the
/// during-the-run one.
#[component]
fn TaskTimePanel(breakdown: Load<TaskTimeBreakdown>) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-processing-where-processing-time-goes")} }
            div { style: MODULE_BODY,
                match breakdown {
                    Load::Pending => rsx! { {tr!("admin-collection-processing-loading-u")} },
                    Load::Failed(e) => rsx! { PanelError { message: e } },
                    Load::Ready(b) if b.rows.is_empty() => rsx! {
                        p { style: HELP_TEXT,
                            {tr!("admin-collection-processing-no-task-executions-recorded-yet")}
                        }
                    },
                    Load::Ready(b) => rsx! {
                        div { style: "display: flex; gap: 26px; flex-wrap: wrap; margin-bottom: 14px;",
                            Metric {
                                label: tr!("admin-collection-processing-summed-task-time").to_string(),
                                value: format_seconds(b.total_seconds),
                                note: tr!("admin-collection-processing-executions-2", b_total_executions: b.total_executions.to_string()),
                            }
                            Metric {
                                label: tr!("admin-collection-processing-wall-clock").to_string(),
                                value: format_seconds(b.wall_clock_seconds),
                                note: b.first_started.clone().unwrap_or_default(),
                            }
                            Metric {
                                label: tr!("admin-collection-processing-achieved-parallelism").to_string(),
                                value: format!("{:.2}\u{00d7}", b.achieved_parallelism),
                                note: "task-seconds per elapsed second".to_string(),
                            }
                        }
                        p { style: "{HELP_TEXT} margin: 0 0 12px;",
                            {tr!("admin-collection-processing-summed-task-time-divided-by")}
                        }
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-collection-processing-task")} }
                                    th { style: TH, {tr!("admin-collection-processing-total")} }
                                    th { style: TH, {tr!("admin-collection-processing-share")} }
                                    th { style: TH, {tr!("admin-collection-processing-executions")} }
                                    th { style: TH, {tr!("admin-collection-processing-mean")} }
                                    th { style: TH, "p95" }
                                    th { style: TH, {tr!("admin-collection-processing-max")} }
                                    th { style: TH, {tr!("admin-collection-processing-failed")} }
                                }
                            }
                            tbody {
                                for row in b.rows {
                                    tr { key: "{row.task_name}",
                                        td { style: TD, "{row.task_name}" }
                                        td { style: "{TD} white-space: nowrap;", {format_seconds(row.total_seconds)} }
                                        td { style: TD,
                                            div { style: "display: flex; align-items: center; gap: 8px;",
                                                ShareBar { percent: row.share_percent, color: "var(--x-link)".to_string() }
                                                span { {format!("{:.1}%", row.share_percent)} }
                                            }
                                        }
                                        td { style: TD, "{row.executions}" }
                                        td { style: TD, {tr!("admin-collection-processing-ms", row_mean_ms: format!("{:.0}", row.mean_ms))} }
                                        td { style: TD, {tr!("admin-collection-processing-ms-2", row_p95_ms: format!("{:.0}", row.p95_ms))} }
                                        td { style: TD, {tr!("admin-collection-processing-ms-2-2", row_max_ms: row.max_ms.to_string())} }
                                        td {
                                            style: if row.error_count > 0 {
                                                "{TD} color: var(--x-danger); font-weight: 700;"
                                            } else {
                                                "{TD} color: var(--x-ink-muted);"
                                            },
                                            "{row.error_count}"
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
}

/// One big number with a caption, for the summary strips.
#[component]
fn Metric(label: String, value: String, note: String) -> Element {
    rsx! {
        div {
            div { style: "font-size: var(--x-text-xs); letter-spacing: 0.04em; color: #888;", "{label}" }
            div { style: "font-size: var(--x-text-section); line-height: var(--x-line-section); font-weight: 700; color: var(--x-ink);", "{value}" }
            div { style: HELP_TEXT, "{note}" }
        }
    }
}

/// What the pipeline is doing right now, refreshed on a timer.
///
/// Self-refreshing rather than driven by the page's `refresh_all`: an admin opens this
/// page precisely to watch a running ingest, and the rest of the page is expensive to
/// recompute every five seconds.
///
/// The poll is a `tick` signal read inside `use_resource` (the pattern
/// `LiveChatsPanel` already uses), NOT `use_effect { clear(); restart(); }`. That
/// pairing fires on mount and doubles every request. `collection_id` goes through
/// `use_reactive!` because a prop is not reactive on its own.
#[component]
fn LiveActivityPanel(collection_id: String) -> Element {
    let mut tick = use_signal(|| 0_u64);

    let live_res = use_resource(use_reactive!(|collection_id| {
        let _ = tick.read();
        admin_task_time_live(collection_id.clone(), LIVE_WINDOW_SECONDS)
    }));

    // `n0_future::time::sleep`, never `gloo_timers`: this file is compiled both to wasm
    // and for the server-side render build, and gloo's timers are wasm-only.
    use_future(move || async move {
        loop {
            n0_future::time::sleep(Duration::from_millis(LIVE_REFRESH_MS)).await;
            tick += 1;
        }
    });

    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-processing-live-activity")} }
            div { style: MODULE_BODY,
                match load_state(live_res) {
                    Load::Pending => rsx! { {tr!("admin-collection-processing-loading-u")} },
                    Load::Failed(e) => rsx! { PanelError { message: e } },
                    Load::Ready(live) => rsx! { LiveActivityBody { live: live } },
                }
            }
        }
    }
}

#[component]
fn LiveActivityBody(live: LiveTaskActivity) -> Element {
    if live.rows.is_empty() {
        return rsx! {
            p { style: HELP_TEXT,
                {tr!("admin-collection-processing-nothing-running-no-activity-finished", live_window_seconds: live.window_seconds.to_string())}
            }
        };
    }

    rsx! {
        div { style: "display: flex; gap: 26px; flex-wrap: wrap; margin-bottom: 14px;",
            Metric {
                label: tr!("admin-collection-processing-in-flight").to_string(),
                value: format!("{}", live.in_flight_total),
                note: match live.sampled_at.clone() {
                    Some(at) => tr!("admin-collection-processing-as-of", at: at.to_string()),
                    None => "no worker sample in the last few seconds".to_string(),
                },
            }
            Metric {
                label: tr!("admin-collection-processing-average-concurrency").to_string(),
                value: format!("{:.2}\u{00d7}", live.average_concurrency),
                note: tr!("admin-collection-processing-over-the-last-s", live_window_seconds: live.window_seconds.to_string()),
            }
            Metric {
                label: tr!("admin-collection-processing-task-time-in-window").to_string(),
                value: format_seconds(live.total_seconds_in_window),
                note: "sums to the window \u{00d7} concurrency".to_string(),
            }
        }
        p { style: "{HELP_TEXT} margin: 0 0 12px;",
            {tr!("admin-collection-processing-share-of-processing-time-over", live_window_seconds: live.window_seconds.to_string())}
        }
        table { style: TABLE,
            thead {
                tr {
                    th { style: TH, {tr!("admin-collection-processing-task")} }
                    th { style: TH, {tr!("admin-collection-processing-share-of-window")} }
                    th { style: TH, {tr!("admin-collection-processing-task-time")} }
                    th { style: TH, {tr!("admin-collection-processing-completed")} }
                    th { style: TH, {tr!("admin-collection-processing-in-flight")} }
                    th { style: TH, {tr!("admin-collection-processing-oldest-running")} }
                }
            }
            tbody {
                for row in live.rows {
                    tr { key: "{row.task_name}",
                        td { style: TD, "{row.task_name}" }
                        td { style: TD,
                            div { style: "display: flex; align-items: center; gap: 8px;",
                                ShareBar { percent: row.share_percent, color: "#c1883c".to_string() }
                                span { {format!("{:.1}%", row.share_percent)} }
                            }
                        }
                        td { style: "{TD} white-space: nowrap;", {format_seconds(row.seconds_in_window)} }
                        td { style: TD, "{row.completed}" }
                        td {
                            style: if row.in_flight > 0 {
                                "{TD} color: var(--x-link); font-weight: 700;"
                            } else {
                                "{TD} color: var(--x-ink-muted);"
                            },
                            "{row.in_flight}"
                        }
                        td { style: TD,
                            if row.in_flight > 0 {
                                {humanize_seconds(row.oldest_age_seconds)}
                            } else {
                                span { style: "color: var(--x-ink-muted);", "\u{2014}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn WorkflowsPanel(workflows: Load<Vec<WorkflowSummary>>, filter: Signal<WorkflowFilter>) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-processing-temporal-workflows")} }
            div { style: MODULE_BODY,
                div { style: "display: flex; gap: 8px; margin-bottom: 12px;",
                    for (label, value) in [("All", WorkflowFilter::All), ("Running", WorkflowFilter::Running), ("Failed", WorkflowFilter::Failed)] {
                        button {
                            key: "{label}",
                            style: if *filter.read() == value {
                                "background-color: var(--x-link); color: white; border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: var(--x-text-xs);"
                            } else {
                                "background: white; color: var(--x-link); border: 1px solid; border-color: var(--x-link); padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: var(--x-text-xs);"
                            },
                            onclick: move |_| filter.set(value),
                            "{label}"
                        }
                    }
                }
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    {tr!("admin-collection-processing-workflows-of-this-collection-s")}
                }
                match workflows {
                    Load::Pending => rsx! { {tr!("admin-collection-processing-loading-u")} },
                    Load::Failed(e) => rsx! { PanelError { message: e } },
                    Load::Ready(list) if list.is_empty() => rsx! {
                        p { style: HELP_TEXT, {tr!("admin-collection-processing-no-workflows-match-this-filter")} }
                    },
                    Load::Ready(list) => rsx! {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-collection-processing-workflow")} }
                                    th { style: TH, {tr!("admin-collection-processing-type")} }
                                    th { style: TH, {tr!("admin-collection-processing-status")} }
                                    th { style: TH, {tr!("admin-collection-processing-started")} }
                                    th { style: TH, {tr!("admin-collection-processing-closed")} }
                                    th { style: TH, {tr!("admin-collection-processing-temporal")} }
                                }
                            }
                            tbody {
                                for wf in list {
                                    tr { key: "{wf.run_id}",
                                        td { style: TD, "{wf.workflow_id}" }
                                        td { style: TD, "{wf.workflow_type}" }
                                        td { style: TD,
                                            span {
                                                style: if wf.is_failed() {
                                                    "color: var(--x-danger); font-weight: 700;"
                                                } else if wf.is_running() {
                                                    "color: var(--x-link); font-weight: 700;"
                                                } else {
                                                    "color: var(--x-ok);"
                                                },
                                                "{wf.status}"
                                            }
                                        }
                                        td { style: TD, "{wf.start_time}" }
                                        td { style: TD, {wf.close_time.clone().unwrap_or_else(|| "\u{2014}".to_string())} }
                                        td { style: TD,
                                            a { href: "{wf.temporal_url}", target: "_blank", style: LINK, {tr!("admin-collection-processing-open-u")} }
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
}

#[component]
fn TaskFailuresPanel(
    collection_id: String,
    failures: Load<Vec<TaskFailureGroup>>,
    msg: Signal<Option<String>>,
    error_msg: Signal<Option<String>>,
    on_retry: EventHandler<()>,
) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-processing-failed-tasks")} }
            div { style: MODULE_BODY,
                match failures {
                    Load::Pending => rsx! { {tr!("admin-collection-processing-loading-u")} },
                    Load::Failed(e) => rsx! { PanelError { message: e } },
                    Load::Ready(list) if list.is_empty() => rsx! {
                        p { style: HELP_TEXT, {tr!("admin-collection-processing-no-task-failures-recorded")} }
                    },
                    Load::Ready(list) => rsx! {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-collection-processing-task")} }
                                    th { style: TH, {tr!("admin-collection-processing-dataset")} }
                                    th { style: TH, {tr!("admin-collection-processing-errors")} }
                                    th { style: TH, {tr!("admin-collection-processing-documents")} }
                                    th { style: TH, {tr!("admin-collection-processing-last-seen")} }
                                    th { style: TH, {tr!("admin-collection-processing-sample")} }
                                    th { style: TH, "" }
                                }
                            }
                            tbody {
                                for f in list {
                                    tr { key: "{f.collection_dataset}-{f.task_name}",
                                        td { style: TD, "{f.task_name}" }
                                        td { style: TD, "{f.collection_dataset}" }
                                        td { style: "{TD} color: var(--x-danger); font-weight: 700;", "{f.error_count}" }
                                        td { style: TD, "{f.document_count}" }
                                        td { style: TD, "{f.last_seen}" }
                                        td { style: "{TD} font-family: monospace; font-size: var(--x-text-xs); max-width: 380px; overflow: hidden; text-overflow: ellipsis;", "{f.sample_error}" }
                                        td { style: TD,
                                            button {
                                                style: BTN_SMALL,
                                                onclick: {
                                                    let cname = collection_id.clone();
                                                    let ds = f.collection_dataset.clone();
                                                    let task = f.task_name.clone();
                                                    let mut msg = msg;
                                                    let mut error_msg = error_msg;
                                                    move |_| {
                                                        let cname = cname.clone();
                                                        let ds = ds.clone();
                                                        let task = task.clone();
                                                        spawn(async move {
                                                            msg.set(None);
                                                            error_msg.set(None);
                                                            match admin_retry_failed_task(cname, ds, task).await {
                                                                Ok(run) => msg.set(Some(tr!("admin-collection-processing-retry-started-run", run: run.to_string())))
                                                                ,
                                                                Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                                            }
                                                            on_retry.call(());
                                                        });
                                                    }
                                                },
                                                {tr!("admin-collection-processing-retry")}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
}

#[component]
fn DocumentFailuresPanel(
    collection_id: String,
    failures: Load<Vec<DocumentFailure>>,
    msg: Signal<Option<String>>,
    error_msg: Signal<Option<String>>,
    on_retry: EventHandler<()>,
) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-collection-processing-failures-per-document")} }
            div { style: MODULE_BODY,
                match failures {
                    Load::Pending => rsx! { {tr!("admin-collection-processing-loading-u")} },
                    Load::Failed(e) => rsx! { PanelError { message: e } },
                    Load::Ready(list) if list.is_empty() => rsx! {
                        p { style: HELP_TEXT, {tr!("admin-collection-processing-no-document-failures-recorded")} }
                    },
                    Load::Ready(list) => rsx! {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-collection-processing-document")} }
                                    th { style: TH, {tr!("admin-collection-processing-dataset")} }
                                    th { style: TH, {tr!("admin-collection-processing-failed-tasks")} }
                                    th { style: TH, {tr!("admin-collection-processing-errors")} }
                                    th { style: TH, {tr!("admin-collection-processing-last-seen")} }
                                    th { style: TH, "" }
                                }
                            }
                            tbody {
                                for f in list {
                                    tr { key: "{f.collection_dataset}-{f.hash}",
                                        td { style: TD,
                                            if f.hash.is_empty() {
                                                span { style: HELP_TEXT, {tr!("admin-collection-processing-dataset-level")} }
                                            } else {
                                                div {
                                                    div { style: "font-family: monospace; font-size: var(--x-text-xs);", "{f.hash}" }
                                                    if let Some(p) = f.path.clone() {
                                                        div { style: HELP_TEXT, "{p}" }
                                                    }
                                                }
                                            }
                                        }
                                        td { style: TD, "{f.collection_dataset}" }
                                        td { style: TD, {f.task_names.join(", ")} }
                                        td { style: "{TD} color: var(--x-danger); font-weight: 700;", "{f.error_count}" }
                                        td { style: TD, "{f.last_seen}" }
                                        td { style: TD,
                                            if !f.hash.is_empty() {
                                                button {
                                                    style: BTN_SMALL,
                                                    onclick: {
                                                        let cname = collection_id.clone();
                                                        let ds = f.collection_dataset.clone();
                                                        let hash = f.hash.clone();
                                                        let mut msg = msg;
                                                        let mut error_msg = error_msg;
                                                        move |_| {
                                                            let cname = cname.clone();
                                                            let ds = ds.clone();
                                                            let hash = hash.clone();
                                                            spawn(async move {
                                                                msg.set(None);
                                                                error_msg.set(None);
                                                                match admin_retry_document(cname, ds, hash).await {
                                                                    Ok(run) => msg.set(Some(tr!("admin-collection-processing-document-retry-started-run", run: run.to_string()))),
                                                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                                                }
                                                                on_retry.call(());
                                                            });
                                                        }
                                                    },
                                                    {tr!("admin-collection-processing-retry")}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{format_seconds, humanize_seconds};

    #[test]
    fn seconds_keep_their_magnitude_and_gain_a_unit_when_large() {
        assert_eq!(format_seconds(0.0), "0.0 s");
        assert_eq!(format_seconds(12.34), "12.3 s");
        // Past a minute the raw seconds are still there (they are what the rows are
        // compared on) with a readable unit beside them.
        assert_eq!(format_seconds(3661.0), "3661 s (1h 1m)");
    }

    #[test]
    fn humanize_picks_the_largest_unit() {
        assert_eq!(humanize_seconds(0), "0s");
        assert_eq!(humanize_seconds(59), "59s");
        assert_eq!(humanize_seconds(60), "1m");
        assert_eq!(humanize_seconds(3599), "59m");
        assert_eq!(humanize_seconds(3661), "1h 1m");
        assert_eq!(humanize_seconds(90_000), "1d 1h");
    }
}
