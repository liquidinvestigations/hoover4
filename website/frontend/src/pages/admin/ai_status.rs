//! Admin page: `/admin/ai_status`, the silent-fallback surface.

use common::llm_types::AdminAiStatus;
use dioxus::prelude::*;

use crate::api::admin_api::admin_get_ai_status;
use crate::components::admin_components::{
    AdminGuard, AdminShell, HELP_TEXT, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::tr;

#[component]
pub fn AdminAiStatusPage() -> Element {
    rsx! {
        Title { {tr!("admin-ai-status-admin-ai-status")} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-ai-status-ai-status").to_string(),
                breadcrumb: String::new(),
                active: "ai_status".to_string(),
                SuspendWrapper { AiStatusContent {} }
            }
        }
    }
}

#[component]
fn AiStatusContent() -> Element {
    let status_res = use_resource(admin_get_ai_status);
    let status = status_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();
    rsx! {
        p { style: "{HELP_TEXT} margin: 0 0 16px;",
            {tr!("admin-ai-status-the-configured-service-and-the")}
        }
        match status {
            None => rsx! { {tr!("admin-ai-status-loading-u")} },
            Some(s) => rsx! {
                FingerprintPanel { status: s.clone() }
                CapabilitiesPanel { status: s.clone() }
                ShardPanel { status: s.clone() }
                BrowserPanel { status: s.clone() }
                TrafficPanel { status: s.clone() }
                UsePanel { status: s }
            },
        }
    }
}

#[component]
fn FingerprintPanel(status: AdminAiStatus) -> Element {
    // A deployment with no GPU tier has no second fingerprint to compare, which is a
    // complete answer rather than an incomplete comparison. Saying "incomplete" there
    // put a permanent unexplained defect on the page of every CPU-only host.
    let match_label = if !status.ai_server_present {
        "n/a - no AI server on this deployment"
    } else if status.fingerprint_match {
        "match"
    } else if status.fingerprint_local.is_empty() || status.fingerprint_ai_server.is_empty() {
        "incomplete"
    } else {
        "MISMATCH"
    };
    let ai_fingerprint = if status.ai_server_present {
        status.fingerprint_ai_server.clone()
    } else {
        "not deployed".to_string()
    };
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-ai-status-config-fingerprint")} }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    tbody {
                        tr {
                            td { style: "{TD} font-weight: 600; width: 220px;", {tr!("admin-ai-status-website-worker")} }
                            td { style: TD, "{status.fingerprint_local}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", {tr!("admin-ai-status-ai-server")} }
                            td { style: TD, "{ai_fingerprint}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", {tr!("admin-ai-status-match")} }
                            td { style: TD, "{match_label}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", {tr!("admin-ai-status-embeddings-probe")} }
                            td { style: TD,
                                {tr!("admin-ai-status-dims", status_embeddings_serving_model: status.embeddings_serving_model.to_string(), status_embeddings_serving_dim: status.embeddings_serving_dim.to_string())}
                            }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", {tr!("admin-ai-status-llm-configured")} }
                            td { style: TD, if status.llm_configured { {tr!("admin-ai-status-yes")} } else { {tr!("admin-ai-status-no-2")} } }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn CapabilitiesPanel(status: AdminAiStatus) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-ai-status-capabilities")} }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, {tr!("admin-ai-status-capability")} }
                            th { style: TH, {tr!("admin-ai-status-configured")} }
                            th { style: TH, {tr!("admin-ai-status-serving")} }
                            th { style: TH, {tr!("admin-ai-status-model")} }
                            th { style: TH, {tr!("admin-ai-status-reachable")} }
                            th { style: TH, {tr!("admin-ai-status-detail")} }
                        }
                    }
                    tbody {
                        for c in status.capabilities {
                            tr { key: "{c.name}",
                                td { style: TD, "{c.name}" }
                                td { style: TD, "{c.configured_provider}" }
                                td { style: TD, "{c.serving_provider}" }
                                td { style: TD, "{c.serving_model}" }
                                td { style: TD, if c.reachable { {tr!("admin-ai-status-yes")} } else { {tr!("admin-ai-status-no")} } }
                                td { style: "{TD} font-size: var(--x-text-xs); color: var(--x-ink-muted);", "{c.detail}" }
                            }
                        }
                    }
                }
            }
        }
    }
}

#[component]
fn ShardPanel(status: AdminAiStatus) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-ai-status-vector-shard-dims-vs-probe")} }
            div { style: MODULE_BODY,
                if status.shard_dims.is_empty() {
                    p { style: HELP_TEXT, {tr!("admin-ai-status-no-collections-yet")} }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, {tr!("admin-ai-status-collection")} }
                                th { style: TH, {tr!("admin-ai-status-shard")} }
                                th { style: TH, "knn_dims" }
                                th { style: TH, {tr!("admin-ai-status-matches-probe")} }
                            }
                        }
                        tbody {
                            for s in status.shard_dims {
                                tr { key: "{s.collection}-{s.table}",
                                    td { style: TD, "{s.collection}" }
                                    td { style: TD, "{s.table}" }
                                    td { style: TD, "{s.knn_dims}" }
                                    td { style: TD, if s.matches_probe { {tr!("admin-ai-status-yes")} } else { {tr!("admin-ai-status-no")} } }
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
fn BrowserPanel(status: AdminAiStatus) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-ai-status-browser-router")} }
            div { style: MODULE_BODY,
                p {
                    {tr!("admin-ai-status-live-sessions", status_browser_live_sessions: status.browser_live_sessions.to_string(), status_browser_max_sessions: status.browser_max_sessions.to_string())}
                }
                p { style: HELP_TEXT, "{status.browser_detail}" }
            }
        }
    }
}

#[component]
fn TrafficPanel(status: AdminAiStatus) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-ai-status-recent-llm-traffic-24-h")} }
            div { style: MODULE_BODY,
                if status.recent_traffic.is_empty() {
                    p { style: HELP_TEXT, {tr!("admin-ai-status-no-llm-call-events-yet")} }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, {tr!("admin-ai-status-user")} }
                                th { style: TH, {tr!("admin-ai-status-calls")} }
                                th { style: TH, {tr!("admin-ai-status-errors")} }
                                th { style: TH, "p50" }
                            }
                        }
                        tbody {
                            for t in status.recent_traffic {
                                tr { key: "{t.username}",
                                    td { style: TD, "{t.username}" }
                                    td { style: TD, "{t.calls}" }
                                    td { style: TD, "{t.errors}" }
                                    td { style: TD, {tr!("admin-ai-status-ms", t_median_latency_ms: t.median_latency_ms.to_string())} }
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
fn UsePanel(status: AdminAiStatus) -> Element {
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, {tr!("admin-ai-status-service-use-24-h")} }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 12px;",
                    {tr!("admin-ai-status-busy-seconds-in-the-last")}
                }
                if status.service_use.is_empty() {
                    p { style: HELP_TEXT, {tr!("admin-ai-status-no-samples-yet")} }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, {tr!("admin-ai-status-service")} }
                                th { style: TH, {tr!("admin-ai-status-calls")} }
                                th { style: TH, {tr!("admin-ai-status-errors")} }
                                th { style: TH, {tr!("admin-ai-status-busy-s")} }
                                th { style: TH, {tr!("admin-ai-status-use")} }
                            }
                        }
                        tbody {
                            for u in status.service_use {
                                tr { key: "{u.service}",
                                    td { style: TD, "{u.service}" }
                                    td { style: TD, "{u.calls_24h}" }
                                    td { style: TD, "{u.errors_24h}" }
                                    td { style: TD, "{u.busy_seconds_24h:.1}" }
                                    td { style: TD, "{u.use_pct:.2}" }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
