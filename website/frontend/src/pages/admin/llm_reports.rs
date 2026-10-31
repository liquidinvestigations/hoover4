//! The "Reports" section of `/admin/llm`: error counts, recent errors, tool calls and
//! top users, read from `agent_step_events`.
//!
//! Each module keeps its result in a signal that only its "Run report" button fills,
//! so a page load runs no report. The element ids are stable because the screenshot
//! harness clicks each button and waits for its result table.

use common::llm_types::{ErrorCountRow, ErrorLogRow, ToolTableRow, TopUserRow};
use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_llm_error_counts, admin_llm_error_log, admin_llm_tool_table, admin_llm_top_users,
};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    ErrorBar, BTN, HELP_TEXT, INPUT, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::routes::Route;
use crate::tr;

/// A report result: the rows and the time they were read, or an error message.
type ReportState<T> = Option<Result<(Vec<T>, String), String>>;

/// Format Unix milliseconds as `YYYY-MM-DD HH:MM:SS UTC`.
pub fn format_utc_ms(ms: i64) -> String {
    let secs = ms.div_euclid(1000);
    let days = secs.div_euclid(86_400);
    let rem = secs.rem_euclid(86_400);
    // Civil date from days since 1970-01-01, after H. Hinnant's `civil_from_days`.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    tr!("admin-llm-reports-utc", year: format!("{:04}", year), month: format!("{:02}", month), day: format!("{:02}", day), rem_3600: format!("{:02}", rem / 3600), rem_3600_60: format!("{:02}", (rem % 3600) / 60), rem_60: format!("{:02}", rem % 60))
}

/// The time now, as text. Only a click handler calls it, so it runs in the browser.
fn read_at() -> String {
    #[cfg(target_arch = "wasm32")]
    {
        format_utc_ms(web_sys::js_sys::Date::now() as i64)
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        String::new()
    }
}

/// Render milliseconds as seconds with one decimal.
fn seconds(ms: u64) -> String {
    format!("{:.1} s", ms as f64 / 1000.0)
}

#[component]
pub fn LlmReports() -> Element {
    rsx! {
        h2 { style: "font-size: var(--x-text-section); line-height: var(--x-line-section); margin: 23px 0 8px;", {tr!("admin-llm-reports-reports")} }
        p { style: "{HELP_TEXT} margin: 0 0 12px;",
            {tr!("admin-llm-reports-each-report-runs-when-you")}
        }
        ErrorCountsReport {}
        ErrorLogReport {}
        ToolTableReport {}
        TopUsersReport {}
        SystemOneReport {}
    }
}

/// The button and the "read at" line of one module.
#[component]
fn RunBar(id: String, busy: bool, read_at: String, onclick: EventHandler<()>) -> Element {
    rsx! {
        div { style: "display: flex; gap: 12px; align-items: center; margin-bottom: 10px;",
            button {
                id: "{id}",
                style: BTN,
                disabled: busy,
                onclick: move |_| onclick.call(()),
                if busy { {tr!("admin-llm-reports-running-u")} } else { {tr!("admin-llm-reports-run-report")} }
            }
            if !read_at.is_empty() {
                span { style: HELP_TEXT, {tr!("admin-llm-reports-read-at", read_at: read_at.to_string())} }
            }
        }
    }
}

#[component]
fn ErrorCountsReport() -> Element {
    let mut state = use_signal(|| None::<Result<(Vec<ErrorCountRow>, String), String>>);
    let mut busy = use_signal(|| false);
    let run = move |_| {
        busy.set(true);
        spawn(async move {
            let r = admin_llm_error_counts().await;
            state.set(Some(r.map(|rows| (rows, read_at())).map_err(|e| user_facing_message(&e))));
            busy.set(false);
        });
    };
    let current: ReportState<ErrorCountRow> = state.read().clone();
    let at = current.as_ref().and_then(|r| r.as_ref().ok()).map(|(_, t)| t.clone()).unwrap_or_default();
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-llm-reports-errors")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;",
                    {tr!("admin-llm-reports-failed-attempts-by-step-and")}
                }
                RunBar { id: "x-llm-report-errors-run", busy: *busy.read(), read_at: at, onclick: run }
                match current {
                    None => rsx! {},
                    Some(Err(m)) => rsx! { ErrorBar { message: m } },
                    Some(Ok((rows, _))) => rsx! {
                        table { id: "x-llm-report-errors-result", style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-llm-reports-source")} }
                                    th { style: TH, {tr!("admin-llm-reports-class")} }
                                    th { style: TH, "24 h" }
                                    th { style: TH, "7 d" }
                                    th { style: TH, "30 d" }
                                }
                            }
                            tbody {
                                if rows.is_empty() {
                                    tr { td { style: TD, colspan: "5", {tr!("admin-llm-reports-no-errors-in-30-days")} } }
                                }
                                for (i, r) in rows.into_iter().enumerate() {
                                    tr { key: "{i}",
                                        td { style: TD, "{r.source}" }
                                        td { style: TD, "{r.class}" }
                                        td { style: TD, "{r.d1}" }
                                        td { style: TD, "{r.d7}" }
                                        td { style: TD, "{r.d30}" }
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
fn ErrorLogReport() -> Element {
    let mut state = use_signal(|| None::<Result<(Vec<ErrorLogRow>, String), String>>);
    let mut busy = use_signal(|| false);
    let run = move |_| {
        busy.set(true);
        spawn(async move {
            let r = admin_llm_error_log().await;
            state.set(Some(r.map(|rows| (rows, read_at())).map_err(|e| user_facing_message(&e))));
            busy.set(false);
        });
    };
    let current: ReportState<ErrorLogRow> = state.read().clone();
    let at = current.as_ref().and_then(|r| r.as_ref().ok()).map(|(_, t)| t.clone()).unwrap_or_default();
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-llm-reports-recent-errors")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;",
                    {tr!("admin-llm-reports-the-newest-100-failed-attempts")}
                }
                RunBar { id: "x-llm-report-log-run", busy: *busy.read(), read_at: at, onclick: run }
                match current {
                    None => rsx! {},
                    Some(Err(m)) => rsx! { ErrorBar { message: m } },
                    Some(Ok((rows, _))) => rsx! {
                        table { id: "x-llm-report-log-result", style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-llm-reports-time")} }
                                    th { style: TH, {tr!("admin-llm-reports-source")} }
                                    th { style: TH, {tr!("admin-llm-reports-user")} }
                                    th { style: TH, {tr!("admin-llm-reports-name")} }
                                    th { style: TH, {tr!("admin-llm-reports-class")} }
                                    th { style: TH, {tr!("admin-llm-reports-error")} }
                                }
                            }
                            tbody {
                                if rows.is_empty() {
                                    tr { td { style: TD, colspan: "6", {tr!("admin-llm-reports-no-errors-in-7-days")} } }
                                }
                                for (i, r) in rows.into_iter().enumerate() {
                                    tr { key: "{i}",
                                        td { style: "{TD} white-space: nowrap;", "{format_utc_ms(r.time_ms)}" }
                                        td { style: TD, "{r.source}" }
                                        td { style: TD, "{r.username}" }
                                        td { style: TD, "{r.name}" }
                                        td { style: TD, "{r.class}" }
                                        td { style: TD,
                                            details {
                                                summary { style: "cursor: pointer;", {tr!("admin-llm-reports-show")} }
                                                pre { style: "white-space: pre-wrap; margin: 6px 0 0; font-size: var(--x-text-xs);", "{r.error}" }
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
fn ToolTableReport() -> Element {
    let mut state = use_signal(|| None::<Result<(Vec<ToolTableRow>, String), String>>);
    let mut busy = use_signal(|| false);
    let run = move |_| {
        busy.set(true);
        spawn(async move {
            let r = admin_llm_tool_table().await;
            state.set(Some(r.map(|rows| (rows, read_at())).map_err(|e| user_facing_message(&e))));
            busy.set(false);
        });
    };
    let current: ReportState<ToolTableRow> = state.read().clone();
    let at = current.as_ref().and_then(|r| r.as_ref().ok()).map(|(_, t)| t.clone()).unwrap_or_default();
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-llm-reports-tool-calls")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;",
                    {tr!("admin-llm-reports-one-row-for-each-tool")}
                }
                RunBar { id: "x-llm-report-tools-run", busy: *busy.read(), read_at: at, onclick: run }
                match current {
                    None => rsx! {},
                    Some(Err(m)) => rsx! { ErrorBar { message: m } },
                    Some(Ok((rows, _))) => rsx! {
                        table { id: "x-llm-report-tools-result", style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-llm-reports-tool")} }
                                    th { style: TH, {tr!("admin-llm-reports-calls-24-h")} }
                                    th { style: TH, {tr!("admin-llm-reports-error-24-h")} }
                                    th { style: TH, {tr!("admin-llm-reports-avg-ms-24-h")} }
                                    th { style: TH, {tr!("admin-llm-reports-calls-7-d")} }
                                    th { style: TH, {tr!("admin-llm-reports-error-7-d")} }
                                    th { style: TH, {tr!("admin-llm-reports-avg-ms-7-d")} }
                                    th { style: TH, {tr!("admin-llm-reports-calls-30-d")} }
                                    th { style: TH, {tr!("admin-llm-reports-error-30-d")} }
                                    th { style: TH, {tr!("admin-llm-reports-avg-ms-30-d")} }
                                }
                            }
                            tbody {
                                if rows.is_empty() {
                                    tr { td { style: TD, colspan: "10", {tr!("admin-llm-reports-no-tool-calls-in-30")} } }
                                }
                                for r in rows {
                                    tr { key: "{r.tool}",
                                        td { style: TD, "{r.tool}" }
                                        td { style: TD, "{r.calls_24h}" }
                                        td { style: TD, "{r.err_pct_24h:.1}" }
                                        td { style: TD, "{r.avg_ms_24h:.0}" }
                                        td { style: TD, "{r.calls_7d}" }
                                        td { style: TD, "{r.err_pct_7d:.1}" }
                                        td { style: TD, "{r.avg_ms_7d:.0}" }
                                        td { style: TD, "{r.calls_30d}" }
                                        td { style: TD, "{r.err_pct_30d:.1}" }
                                        td { style: TD, "{r.avg_ms_30d:.0}" }
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
fn TopUsersReport() -> Element {
    let mut state = use_signal(|| None::<Result<(Vec<TopUserRow>, String), String>>);
    let mut busy = use_signal(|| false);
    let mut days = use_signal(|| 30u16);
    let run = move |_| {
        busy.set(true);
        let window = *days.peek();
        spawn(async move {
            let r = admin_llm_top_users(window).await;
            state.set(Some(r.map(|rows| (rows, read_at())).map_err(|e| user_facing_message(&e))));
            busy.set(false);
        });
    };
    let current: ReportState<TopUserRow> = state.read().clone();
    let at = current.as_ref().and_then(|r| r.as_ref().ok()).map(|(_, t)| t.clone()).unwrap_or_default();
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-llm-reports-top-users")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 8px;",
                    {tr!("admin-llm-reports-the-30-users-with-the")}
                }
                select {
                    id: "x-llm-report-users-window",
                    style: "{INPUT} margin-bottom: 8px;",
                    value: "{days}",
                    onchange: move |e| days.set(e.value().parse().unwrap_or(30)),
                    option { value: "30", {tr!("admin-llm-reports-30-days")} }
                    option { value: "7", {tr!("admin-llm-reports-7-days")} }
                    option { value: "1", {tr!("admin-llm-reports-24-hours")} }
                }
                RunBar { id: "x-llm-report-users-run", busy: *busy.read(), read_at: at, onclick: run }
                match current {
                    None => rsx! {},
                    Some(Err(m)) => rsx! { ErrorBar { message: m } },
                    Some(Ok((rows, _))) => rsx! {
                        table { id: "x-llm-report-users-result", style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, {tr!("admin-llm-reports-user")} }
                                    th { style: TH, {tr!("admin-llm-reports-tool-calls")} }
                                    th { style: TH, {tr!("admin-llm-reports-tool-time")} }
                                    th { style: TH, {tr!("admin-llm-reports-model-calls")} }
                                    th { style: TH, {tr!("admin-llm-reports-model-time")} }
                                    th { style: TH, {tr!("admin-llm-reports-tokens-in")} }
                                    th { style: TH, {tr!("admin-llm-reports-tokens-out")} }
                                }
                            }
                            tbody {
                                if rows.is_empty() {
                                    tr { td { style: TD, colspan: "7", {tr!("admin-llm-reports-no-agent-use-in-the")} } }
                                }
                                for r in rows {
                                    tr { key: "{r.username}",
                                        td { style: TD,
                                            Link {
                                                to: Route::AdminUserLlmPage { username: r.username.clone() },
                                                style: LINK,
                                                "{r.username}"
                                            }
                                        }
                                        td { style: TD, "{r.tool_calls}" }
                                        td { style: TD, "{seconds(r.tool_ms)}" }
                                        td { style: TD, "{r.model_calls}" }
                                        td { style: TD, "{seconds(r.model_ms)}" }
                                        td { style: TD, "{r.tokens_in}" }
                                        td { style: TD, "{r.tokens_out}" }
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
    use super::format_utc_ms;

    #[test]
    fn unix_milliseconds_format_as_utc() {
        assert_eq!(format_utc_ms(0), "1970-01-01 00:00:00 UTC");
        assert_eq!(format_utc_ms(951_782_400_000), "2000-02-29 00:00:00 UTC");
        assert_eq!(format_utc_ms(1_790_000_000_123), "2026-09-21 14:13:20 UTC");
    }
}

#[component]
fn SystemOneReport() -> Element {
    let mut state = use_signal(|| None::<Result<(common::llm_types::SystemOneReport, String), String>>);
    let mut busy = use_signal(|| false);
    let mut failures = use_signal(|| false);
    let run = move |_| {
        busy.set(true);
        spawn(async move {
            let response = crate::api::admin_api::admin_llm_systemone().await;
            state.set(Some(response.map(|report| (report, read_at())).map_err(|e| user_facing_message(&e))));
            busy.set(false);
        });
    };
    let current = state.read().clone();
    let at = current.as_ref().and_then(|r| r.as_ref().ok()).map(|(_, t)| t.clone()).unwrap_or_default();
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-llm-reports-system-one-checks")} }
            div { style: MODULE_BODY,
                p { style: HELP_TEXT, {tr!("admin-llm-reports-requests-are-grouped-by-hook")} }
                RunBar { id: "x-admin-llm-run-systemone", busy: busy(), read_at: at, onclick: run }
                button { style: BTN, onclick: move |_| failures.set(false), {tr!("admin-llm-reports-counts")} }
                button { style: BTN, onclick: move |_| failures.set(true), {tr!("admin-llm-reports-recent-failures")} }
                match current {
                    None => rsx! { p { style: HELP_TEXT, {tr!("admin-llm-reports-select-run-report-to-read")} } },
                    Some(Err(error)) => rsx! { ErrorBar { message: error } },
                    Some(Ok((report, _))) => rsx! {
                        if failures() {
                            table { id: "x-admin-llm-systemone-failures", style: TABLE,
                                thead { tr { th { style: TH, {tr!("admin-llm-reports-time")} } th { style: TH, {tr!("admin-llm-reports-hook")} } th { style: TH, {tr!("admin-llm-reports-rule")} } th { style: TH, {tr!("admin-llm-reports-outcome")} } } }
                                tbody { for (index, row) in report.failures.iter().enumerate() {
                                    tr { key: "{index}",
                                        td { style: TD, "{format_utc_ms(row.time_ms)}" }
                                        td { style: TD, "{row.hook}" } td { style: TD, "{row.rule_id}" } td { style: TD, "{row.outcome}" }
                                    }
                                } }
                            }
                        } else {
                            table { id: "x-admin-llm-systemone", style: TABLE,
                                thead { tr {
                                    for title in ["Hook".to_string(), tr!("admin-llm-reports-rule"), "24h".to_string(), "7d".to_string(), "30d".to_string(), tr!("admin-llm-reports-questions"), tr!("admin-llm-reports-median-ms"), tr!("admin-llm-reports-95th-percentile-ms"), tr!("admin-llm-reports-error-2"), tr!("admin-llm-reports-positive"), tr!("admin-llm-reports-actions")] {
                                        th { key: "{title}", style: TH, "{title}" }
                                    }
                                } }
                                tbody { for row in report.rows {
                                    tr { key: "{row.hook}-{row.rule_id}",
                                        td { style: TD, "{row.hook}" } td { style: TD, "{row.rule_id}" }
                                        td { style: TD, "{row.requests_24h}" } td { style: TD, "{row.requests_7d}" } td { style: TD, "{row.requests_30d}" }
                                        td { style: TD, "{row.questions}" } td { style: TD, "{row.median_ms:.0}" } td { style: TD, "{row.p95_ms:.0}" }
                                        td { style: TD, "{row.error_pct:.1}" } td { style: TD, "{row.positive_pct:.1}" } td { style: TD, "{row.actions}" }
                                    }
                                } }
                            }
                        }
                    },
                }
            }
        }
    }
}
