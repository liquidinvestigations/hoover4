//! Admin page: `/admin/users/:username/llm`, per-user LLM usage: chat
//! sessions, message and tool-call counts, agent (GPU) time, and current
//! rate-limit usage.

use common::metrics_types::{AdminUserLlmMetrics, RateWindowUsage};
use dioxus::prelude::*;

use crate::api::admin_api::admin_get_user_llm;
use crate::components::admin_components::{
    AdminGuard, AdminShell, HELP_TEXT, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminUserLlmPage(username: String) -> Element {
    let for_content = username.clone();
    rsx! {
        Title { "Admin: LLM use by {username}" }
        AdminGuard {
            AdminShell {
                title: "LLM usage".to_string(),
                breadcrumb: format!("Users \u{203a} {username} \u{203a} LLM usage"),
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
                "\u{2190} Back to user"
            }
        }
        match metrics {
            None => rsx! { "Loading\u{2026}" },
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Totals (all time)" }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    tbody {
                        tr {
                            td { style: "{TD} font-weight: 600; width: 240px;", "Chat sessions" }
                            td { style: TD, "{metrics.sessions.len()}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", "Messages" }
                            td { style: TD, "{metrics.chat_messages}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", "Tool calls" }
                            td { style: TD, "{metrics.tool_calls}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", "Agent time" }
                            td { style: TD,
                                "{humanize_ms(metrics.agent_duration_ms_total)} "
                                span { style: HELP_TEXT, "wall time the agent spent on this user's turns, which is what the chat rate limit exists to bound" }
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Rate-limit usage (current windows)" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 10px;",
                    "In-process counters of the running website container. Chat limit {metrics.chat_per_minute}/min, API limit {metrics.api_per_minute}/min, with a decaying sustained rate over the longer windows."
                }
                div { style: "display: flex; gap: 32px; flex-wrap: wrap;",
                    div {
                        h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "Chat messages" }
                        WindowTable { usage: metrics.chat_limit.clone() }
                    }
                    div {
                        h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "API calls" }
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
                    th { style: TH, "Window" }
                    th { style: TH, "Used" }
                    th { style: TH, "Budget" }
                }
            }
            tbody {
                for w in usage {
                    tr { key: "{w.window}",
                        td { style: TD, "{w.window}" }
                        td {
                            style: if w.used >= w.budget { format!("{TD} color: #ba2121; font-weight: 700;") } else { TD.to_string() },
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Chat sessions" }
            div { style: MODULE_BODY,
                if metrics.sessions.is_empty() {
                    p { style: HELP_TEXT, "No chat sessions." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Title" }
                                th { style: TH, "Created" }
                                th { style: TH, "Messages" }
                                th { style: TH, "Tool calls" }
                                th { style: TH, "Agent time" }
                            }
                        }
                        tbody {
                            for s in metrics.sessions {
                                tr { key: "{s.session_id}",
                                    td { style: TD,
                                        if s.title.is_empty() {
                                            span { style: HELP_TEXT, "(untitled)" }
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
