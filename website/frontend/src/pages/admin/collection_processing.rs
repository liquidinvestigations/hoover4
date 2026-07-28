//! Admin page: processing status, workflows and failures for one collection.

use common::processing_types::{
    CollectionProcessingStatus, DocumentFailure, StageProgress, TaskFailureGroup, WorkflowFilter,
    WorkflowSummary,
};
use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_collection_processing, admin_list_document_failures, admin_list_task_failures,
    admin_list_workflows, admin_retry_document, admin_retry_failed_task,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_SMALL, HELP_TEXT, LINK, MODULE, MODULE_BODY,
    MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

/// How many rows each list fetches. Deliberately small: these pages are a triage view,
/// not an export.
const LIST_LIMIT: u32 = 50;

#[component]
pub fn AdminCollectionProcessingPage(collection_id: String) -> Element {
    let for_content = collection_id.clone();
    rsx! {
        Title { "Admin \u{2014} Processing {collection_id}" }
        AdminGuard {
            AdminShell {
                title: "Collection processing".to_string(),
                breadcrumb: format!("Collections \u{203a} {collection_id} \u{203a} Processing"),
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

    let filter = use_signal(|| WorkflowFilter::All);
    let wf_id = collection_id.clone();
    let workflows_res =
        use_resource(move || admin_list_workflows(wf_id.clone(), *filter.read(), LIST_LIMIT));

    let tf_id = collection_id.clone();
    let task_failures_res = use_resource(move || admin_list_task_failures(tf_id.clone(), LIST_LIMIT));

    let df_id = collection_id.clone();
    let doc_failures_res =
        use_resource(move || admin_list_document_failures(df_id.clone(), String::new(), LIST_LIMIT));

    let msg = use_signal(|| None::<String>);
    let error_msg = use_signal(|| None::<String>);

    // One "refresh everything" closure, so a retry updates the progress bars and the
    // workflow list too — the two things an admin looks at right after clicking Retry.
    // `Resource` is `Copy`, so each call re-copies the handles; that keeps the closure
    // `Fn` and lets it be handed to more than one `EventHandler`.
    let refresh_all = move || {
        let (mut s, mut w, mut t, mut d) =
            (status_res, workflows_res, task_failures_res, doc_failures_res);
        s.restart();
        w.restart();
        t.restart();
        d.restart();
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
                "\u{2190} Back to collection"
            }
        }

        StagesPanel { status: status_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned() }

        WorkflowsPanel {
            workflows: workflows_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned(),
            filter: filter,
        }

        TaskFailuresPanel {
            collection_id: collection_id.clone(),
            failures: task_failures_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned(),
            msg: msg,
            error_msg: error_msg,
            on_retry: EventHandler::new(move |_| refresh_all()),
        }

        DocumentFailuresPanel {
            collection_id: collection_id.clone(),
            failures: doc_failures_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned(),
            msg: msg,
            error_msg: error_msg,
            on_retry: EventHandler::new(move |_| refresh_all()),
        }
    }
}

#[component]
fn StagesPanel(status: Option<CollectionProcessingStatus>) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Processing stages" }
            div { style: MODULE_BODY,
                match status {
                    None => rsx! { "Loading\u{2026}" },
                    Some(s) if !s.db_ready => rsx! {
                        p { style: HELP_TEXT, "The collection database is still being provisioned." }
                    },
                    Some(s) if s.datasets.is_empty() => rsx! {
                        p { style: HELP_TEXT, "This collection has no datasets yet." }
                    },
                    Some(s) => rsx! {
                        for ds in s.datasets {
                            div { key: "{ds.collection_dataset}", style: "margin-bottom: 22px;",
                                div { style: "font-size: 13px; font-weight: 700; color: #333; margin-bottom: 8px;",
                                    "{ds.dataset_display_name} "
                                    span { style: HELP_TEXT, "({ds.collection_dataset})" }
                                    if ds.error_count > 0 {
                                        span { style: "color: #ba2121; margin-left: 8px;", "{ds.error_count} errors" }
                                    }
                                }
                                for stage in ds.stages {
                                    StageBar { key: "{stage.stage}", stage: stage }
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
    let bar_color = if complete { "#5fa25f" } else { "#79aec8" };
    let width = percent.unwrap_or(0.0);

    rsx! {
        div { style: "display: flex; align-items: center; gap: 10px; margin-bottom: 5px;",
            div { style: "width: 220px; font-size: 12px; color: #333; flex-shrink: 0;", "{stage.label}" }
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
            div { style: "width: 190px; font-size: 12px; color: #666; flex-shrink: 0;",
                match stage.total {
                    Some(total) => rsx! { "{stage.done} / {total} {stage.unit}" },
                    None => rsx! { "{stage.done} {stage.unit}" },
                }
            }
            div { style: "width: 130px; font-size: 12px; color: #999; flex-shrink: 0;",
                match stage.eta_seconds {
                    Some(eta) => rsx! { "ETA {humanize_seconds(eta)}" },
                    None if complete => rsx! { span { style: "color: #5fa25f;", "done" } },
                    None => rsx! { "\u{2014}" },
                }
            }
        }
    }
}

#[component]
fn WorkflowsPanel(workflows: Option<Vec<WorkflowSummary>>, filter: Signal<WorkflowFilter>) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Temporal workflows" }
            div { style: MODULE_BODY,
                div { style: "display: flex; gap: 8px; margin-bottom: 12px;",
                    for (label, value) in [("All", WorkflowFilter::All), ("Running", WorkflowFilter::Running), ("Failed", WorkflowFilter::Failed)] {
                        button {
                            key: "{label}",
                            style: if *filter.read() == value {
                                "background: #417690; color: white; border: none; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;"
                            } else {
                                "background: white; color: #417690; border: 1px solid #79aec8; padding: 4px 12px; border-radius: 4px; cursor: pointer; font-size: 12px;"
                            },
                            onclick: move |_| filter.set(value),
                            "{label}"
                        }
                    }
                }
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    "Only the top-level pipeline workflows of this collection are listed. Child workflows are reachable from a run's Temporal page."
                }
                match workflows {
                    None => rsx! { "Loading\u{2026}" },
                    Some(list) if list.is_empty() => rsx! {
                        p { style: HELP_TEXT, "No workflows match this filter." }
                    },
                    Some(list) => rsx! {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, "Workflow" }
                                    th { style: TH, "Type" }
                                    th { style: TH, "Status" }
                                    th { style: TH, "Started" }
                                    th { style: TH, "Closed" }
                                    th { style: TH, "Temporal" }
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
                                                    "color: #ba2121; font-weight: 700;"
                                                } else if wf.is_running() {
                                                    "color: #417690; font-weight: 700;"
                                                } else {
                                                    "color: #5fa25f;"
                                                },
                                                "{wf.status}"
                                            }
                                        }
                                        td { style: TD, "{wf.start_time}" }
                                        td { style: TD, {wf.close_time.clone().unwrap_or_else(|| "\u{2014}".to_string())} }
                                        td { style: TD,
                                            a { href: "{wf.temporal_url}", target: "_blank", style: LINK, "open \u{2197}" }
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
    failures: Option<Vec<TaskFailureGroup>>,
    msg: Signal<Option<String>>,
    error_msg: Signal<Option<String>>,
    on_retry: EventHandler<()>,
) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Failed tasks" }
            div { style: MODULE_BODY,
                match failures {
                    None => rsx! { "Loading\u{2026}" },
                    Some(list) if list.is_empty() => rsx! {
                        p { style: HELP_TEXT, "No task failures recorded." }
                    },
                    Some(list) => rsx! {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, "Task" }
                                    th { style: TH, "Dataset" }
                                    th { style: TH, "Errors" }
                                    th { style: TH, "Documents" }
                                    th { style: TH, "Last seen" }
                                    th { style: TH, "Sample" }
                                    th { style: TH, "" }
                                }
                            }
                            tbody {
                                for f in list {
                                    tr { key: "{f.collection_dataset}-{f.task_name}",
                                        td { style: TD, "{f.task_name}" }
                                        td { style: TD, "{f.collection_dataset}" }
                                        td { style: "{TD} color: #ba2121; font-weight: 700;", "{f.error_count}" }
                                        td { style: TD, "{f.document_count}" }
                                        td { style: TD, "{f.last_seen}" }
                                        td { style: "{TD} font-family: monospace; font-size: 11px; max-width: 380px; overflow: hidden; text-overflow: ellipsis;", "{f.sample_error}" }
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
                                                                Ok(run) => msg.set(Some(format!("Retry started (run {run}).")))
                                                                ,
                                                                Err(e) => error_msg.set(Some(e.to_string())),
                                                            }
                                                            on_retry.call(());
                                                        });
                                                    }
                                                },
                                                "Retry"
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
    failures: Option<Vec<DocumentFailure>>,
    msg: Signal<Option<String>>,
    error_msg: Signal<Option<String>>,
    on_retry: EventHandler<()>,
) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Failures per document" }
            div { style: MODULE_BODY,
                match failures {
                    None => rsx! { "Loading\u{2026}" },
                    Some(list) if list.is_empty() => rsx! {
                        p { style: HELP_TEXT, "No document failures recorded." }
                    },
                    Some(list) => rsx! {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, "Document" }
                                    th { style: TH, "Dataset" }
                                    th { style: TH, "Failed tasks" }
                                    th { style: TH, "Errors" }
                                    th { style: TH, "Last seen" }
                                    th { style: TH, "" }
                                }
                            }
                            tbody {
                                for f in list {
                                    tr { key: "{f.collection_dataset}-{f.hash}",
                                        td { style: TD,
                                            if f.hash.is_empty() {
                                                span { style: HELP_TEXT, "dataset-level" }
                                            } else {
                                                div {
                                                    div { style: "font-family: monospace; font-size: 11px;", "{f.hash}" }
                                                    if let Some(p) = f.path.clone() {
                                                        div { style: HELP_TEXT, "{p}" }
                                                    }
                                                }
                                            }
                                        }
                                        td { style: TD, "{f.collection_dataset}" }
                                        td { style: TD, {f.task_names.join(", ")} }
                                        td { style: "{TD} color: #ba2121; font-weight: 700;", "{f.error_count}" }
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
                                                                    Ok(run) => msg.set(Some(format!("Document retry started (run {run})."))),
                                                                    Err(e) => error_msg.set(Some(e.to_string())),
                                                                }
                                                                on_retry.call(());
                                                            });
                                                        }
                                                    },
                                                    "Retry"
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
    use super::humanize_seconds;

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
