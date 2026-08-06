//! Admin page: `/admin/metrics` — usage counters and per-function API stats
//! over the rolling last 24 h.

use common::metrics_types::{ApiFunctionStats, UsageMetrics};
use dioxus::prelude::*;

use crate::api::admin_api::admin_get_metrics;
use crate::components::admin_components::{
    AdminGuard, AdminShell, LiveChatsPanel, HELP_TEXT, MODULE, MODULE_BODY, MODULE_CAPTION,
    TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;

#[component]
pub fn AdminMetricsPage() -> Element {
    rsx! {
        Title { "Admin — Metrics" }
        AdminGuard {
            AdminShell {
                title: "Metrics".to_string(),
                breadcrumb: "Metrics".to_string(),
                active: "metrics".to_string(),
                SuspendWrapper { MetricsContent {} }
            }
        }
    }
}

fn humanize_bytes(bytes: u64) -> String {
    match bytes {
        b if b < 1024 => format!("{b} B"),
        b if b < 1024 * 1024 => format!("{:.1} KiB", b as f64 / 1024.0),
        b if b < 1024 * 1024 * 1024 => format!("{:.1} MiB", b as f64 / 1024.0 / 1024.0),
        b => format!("{:.2} GiB", b as f64 / 1024.0 / 1024.0 / 1024.0),
    }
}

#[component]
fn MetricsContent() -> Element {
    let metrics_res = use_resource(admin_get_metrics);
    let metrics = metrics_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();

    rsx! {
        // Live first: it is the only thing on this page that is actionable right now.
        LiveChatsPanel {}
        p { style: "{HELP_TEXT} margin: 0 0 16px;",
            "Rolling last 24 hours. Events record who, which route class or function name, and when — never a URL or a query string."
        }
        match metrics {
            None => rsx! { "Loading\u{2026}" },
            Some(m) => rsx! {
                UsagePanel { usage: m.usage }
                ApiPanel { api: m.api }
            },
        }
    }
}

#[component]
fn UsagePanel(usage: UsageMetrics) -> Element {
    let max_series = usage.series.iter().map(|p| p.count).max().unwrap_or(1).max(1);
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Usage — last 24 h" }
            div { style: MODULE_BODY,
                h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "Events by type" }
                table { style: "{TABLE} margin-bottom: 20px;",
                    thead {
                        tr {
                            th { style: TH, "Event" }
                            th { style: TH, "Count" }
                        }
                    }
                    tbody {
                        for e in usage.per_event_type {
                            tr { key: "{e.event_type}",
                                td { style: TD, "{e.event_type}" }
                                td { style: TD, "{e.count}" }
                            }
                        }
                    }
                }

                h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "Events per hour" }
                if usage.series.is_empty() {
                    p { style: HELP_TEXT, "No events recorded yet." }
                } else {
                    div { style: "display: flex; align-items: flex-end; gap: 2px; height: 80px; margin-bottom: 20px;",
                        for p in usage.series {
                            div {
                                key: "{p.bucket}",
                                title: "{p.bucket} — {p.count}",
                                style: "flex: 1; min-width: 4px; background: #79aec8; height: {p.count * 100 / max_series}%;",
                            }
                        }
                    }
                }

                h3 { style: "font-size: 13px; color: #333; margin: 0 0 8px;", "Busiest users" }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "User" }
                            th { style: TH, "Events" }
                        }
                    }
                    tbody {
                        for u in usage.per_user {
                            tr { key: "{u.username}",
                                td { style: TD, "{u.username}" }
                                td { style: TD, "{u.count}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn ApiPanel(api: Vec<ApiFunctionStats>) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "API calls — last 24 h" }
            div { style: MODULE_BODY,
                if api.is_empty() {
                    p { style: HELP_TEXT, "No API calls recorded yet." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Function" }
                                th { style: TH, "Calls" }
                                th { style: TH, "Errors" }
                                th { style: TH, "Error rate" }
                                th { style: TH, "p50" }
                                th { style: TH, "p95" }
                                th { style: TH, "max" }
                                th { style: TH, "Bytes in" }
                                th { style: TH, "Bytes out" }
                            }
                        }
                        tbody {
                            for f in api {
                                tr { key: "{f.function_name}",
                                    td { style: "{TD} font-family: monospace; font-size: 12px;", "{f.function_name}" }
                                    td { style: TD, "{f.calls}" }
                                    td {
                                        style: if f.errors > 0 { format!("{TD} color: #ba2121; font-weight: 700;") } else { TD.to_string() },
                                        "{f.errors}"
                                    }
                                    td { style: TD, "{f.error_rate * 100.0:.1}%" }
                                    td { style: TD, "{f.p50_ms} ms" }
                                    td { style: TD, "{f.p95_ms} ms" }
                                    td { style: TD, "{f.max_ms} ms" }
                                    td { style: TD, "{humanize_bytes(f.bytes_in)}" }
                                    td { style: TD, "{humanize_bytes(f.bytes_out)}" }
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
    use super::humanize_bytes;

    #[test]
    fn humanize_picks_a_unit() {
        assert_eq!(humanize_bytes(512), "512 B");
        assert_eq!(humanize_bytes(2048), "2.0 KiB");
        assert_eq!(humanize_bytes(5 * 1024 * 1024), "5.0 MiB");
        assert_eq!(humanize_bytes(3 * 1024 * 1024 * 1024), "3.00 GiB");
    }
}
