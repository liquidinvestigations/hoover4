//! Admin page: `/admin/users/:username/llm`, per-user LLM usage: chat
//! sessions, message and tool-call counts, model and tool time, and current
//! rate-limit usage.

use common::metrics_types::{AdminUserLlmMetrics, RateWindowUsage};
use dioxus::prelude::*;

use crate::api::admin_api::admin_get_user_llm;
use crate::components::admin_components::{
    AdminGuard, AdminShell, HELP_TEXT, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH, SUBHEADING};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;
use crate::tr;

#[component]
pub fn AdminUserLlmPage(username: String) -> Element {
    let for_content = username.clone();
    rsx! {
        Title { {tr!("admin-user-llm-admin-llm-use-by", username: username.to_string())} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-user-llm-llm-usage-of", username: username.to_string()),
                breadcrumb: tr!("admin-user-llm-users", username: username.to_string()),
                active: "users".to_string(),
                SuspendWrapper { UserLlmContent { username: for_content } }
            }
        }
    }
}

/// Render milliseconds of agent time as a duration.
fn humanize_ms(ms: u64) -> String {
    let seconds = ms / 1000;
    match seconds {
        s if s < 60 => format!("{s}s"),
        s if s < 3600 => format!("{}m {}s", s / 60, s % 60),
        s => format!("{}h {}m", s / 3600, (s % 3600) / 60),
    }
}

#[component]
fn UserLlmContent(username: String) -> Element {
    let for_res = username.clone();
    let metrics_res = use_resource(move || admin_get_user_llm(for_res.clone()));
    let metrics = metrics_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();

    rsx! {
        div { style: "margin-bottom: 16px;",
            Link {
                to: Route::AdminUserPage { username: username.clone() },
                style: LINK,
                {tr!("admin-user-llm-u-back-to-user")}
            }
        }
        match metrics {
            None => rsx! { {tr!("admin-user-llm-loading-u")} },
            Some(m) => rsx! {
                SummaryPanel { metrics: m.clone() }
                LimitsPanel { metrics: m.clone() }
                SessionsPanel { metrics: m }
            },
        }
    }
}

#[component]
fn SummaryPanel(metrics: AdminUserLlmMetrics) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-user-llm-totals-all-time")} }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    tbody {
                        tr {
                            td { style: "{TD} font-weight: 600; width: 240px;", {tr!("admin-user-llm-chat-sessions")} }
                            td { style: TD, "{metrics.sessions.len()}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", {tr!("admin-user-llm-messages")} }
                            td { style: TD, "{metrics.chat_messages}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", {tr!("admin-user-llm-tool-calls")} }
                            td { style: TD, "{metrics.tool_calls}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", {tr!("admin-user-llm-model-and-tool-time")} }
                            td { style: TD,
                                "{humanize_ms(metrics.agent_duration_ms_total)} "
                                span { style: HELP_TEXT, {tr!("admin-user-llm-model-and-tool-time-of")} }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn LimitsPanel(metrics: AdminUserLlmMetrics) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-user-llm-rate-limit-usage-current-windows")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    {tr!("admin-user-llm-in-process-counters-of-the", metrics_chat_per_minute: metrics.chat_per_minute.to_string(), metrics_api_per_minute: metrics.api_per_minute.to_string())}
                }
                div { style: "display: flex; gap: 32px; flex-wrap: wrap;",
                    div {
                        h3 { style: SUBHEADING, {tr!("admin-user-llm-chat-messages")} }
                        WindowTable { usage: metrics.chat_limit.clone() }
                    }
                    div {
                        h3 { style: SUBHEADING, {tr!("admin-user-llm-api-calls")} }
                        WindowTable { usage: metrics.api_limit.clone() }
                    }
                }
            }
        }
    }
}

#[component]
fn WindowTable(usage: Vec<RateWindowUsage>) -> Element {
    rsx! {
        table { style: TABLE,
            thead {
                tr {
                    th { style: TH, {tr!("admin-user-llm-window")} }
                    th { style: TH, {tr!("admin-user-llm-used")} }
                    th { style: TH, {tr!("admin-user-llm-budget")} }
                }
            }
            tbody {
                for w in usage {
                    tr { key: "{w.window}",
                        td { style: TD, "{w.window}" }
                        td {
                            style: if w.used >= w.budget { format!("{TD} color: var(--x-danger); font-weight: 700;") } else { TD.to_string() },
                            "{w.used}"
                        }
                        td { style: TD, "{w.budget}" }
                    }
                }
            }
        }
    }
}

#[component]
fn SessionsPanel(metrics: AdminUserLlmMetrics) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-user-llm-chat-sessions")} }
            div { style: MODULE_BODY,
                if metrics.sessions.is_empty() {
                    p { style: HELP_TEXT, {tr!("admin-user-llm-no-chat-sessions")} }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, {tr!("admin-user-llm-title")} }
                                th { style: TH, {tr!("admin-user-llm-created")} }
                                th { style: TH, {tr!("admin-user-llm-messages")} }
                                th { style: TH, {tr!("admin-user-llm-tool-calls")} }
                                th { style: TH, {tr!("admin-user-llm-model-and-tool-time")} }
                            }
                        }
                        tbody {
                            for s in metrics.sessions {
                                tr { key: "{s.session_id}",
                                    td { style: TD,
                                        if s.title.is_empty() {
                                            span { style: HELP_TEXT, {tr!("admin-user-llm-untitled")} }
                                        } else {
                                            "{s.title}"
                                        }
                                    }
                                    td { style: TD, "{s.created_at}" }
                                    td { style: TD, "{s.message_count}" }
                                    td { style: TD, "{s.tool_calls}" }
                                    td { style: TD, "{humanize_ms(s.agent_duration_ms)}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::humanize_ms;

    #[test]
    fn humanize_ms_picks_a_unit() {
        assert_eq!(humanize_ms(500), "0s");
        assert_eq!(humanize_ms(45_000), "45s");
        assert_eq!(humanize_ms(90_000), "1m 30s");
        assert_eq!(humanize_ms(3_900_000), "1h 5m");
    }
}
