//! Admin page: `/admin/ai_status`, the silent-fallback surface.

use common::llm_types::AdminAiStatus;
use dioxus::prelude::*;

use crate::api::admin_api::admin_get_ai_status;
use crate::components::admin_components::{
    AdminGuard, AdminShell, HELP_TEXT, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;

#[component]
pub fn AdminAiStatusPage() -> Element {
    rsx! {
        Title { "Admin — AI status" }
        AdminGuard {
            AdminShell {
                title: "AI status".to_string(),
                breadcrumb: "AI status".to_string(),
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
            "Configured versus actually serving. Auto-fallback to CPU twins is silent by design — this page is how you notice."
        }
        match status {
            None => rsx! { "Loading\u{2026}" },
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Config fingerprint" }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    tbody {
                        tr {
                            td { style: "{TD} font-weight: 600; width: 220px;", "Website / worker" }
                            td { style: TD, "{status.fingerprint_local}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", "AI server" }
                            td { style: TD, "{ai_fingerprint}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", "Match" }
                            td { style: TD, "{match_label}" }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", "Embeddings probe" }
                            td { style: TD,
                                "{status.embeddings_serving_model} · {status.embeddings_serving_dim} dims"
                            }
                        }
                        tr {
                            td { style: "{TD} font-weight: 600;", "LLM configured" }
                            td { style: TD, if status.llm_configured { "yes" } else { "no" } }
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Capabilities" }
            div { style: MODULE_BODY,
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Capability" }
                            th { style: TH, "Configured" }
                            th { style: TH, "Serving" }
                            th { style: TH, "Model" }
                            th { style: TH, "Reachable" }
                            th { style: TH, "Detail" }
                        }
                    }
                    tbody {
                        for c in status.capabilities {
                            tr { key: "{c.name}",
                                td { style: TD, "{c.name}" }
                                td { style: TD, "{c.configured_provider}" }
                                td { style: TD, "{c.serving_provider}" }
                                td { style: TD, "{c.serving_model}" }
                                td { style: TD, if c.reachable { "yes" } else { "NO" } }
                                td { style: "{TD} font-size: 12px; color: #666;", "{c.detail}" }
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Vector shard dims vs probe" }
            div { style: MODULE_BODY,
                if status.shard_dims.is_empty() {
                    p { style: HELP_TEXT, "No collections yet." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Collection" }
                                th { style: TH, "Shard" }
                                th { style: TH, "knn_dims" }
                                th { style: TH, "Matches probe" }
                            }
                        }
                        tbody {
                            for s in status.shard_dims {
                                tr { key: "{s.collection}-{s.table}",
                                    td { style: TD, "{s.collection}" }
                                    td { style: TD, "{s.table}" }
                                    td { style: TD, "{s.knn_dims}" }
                                    td { style: TD, if s.matches_probe { "yes" } else { "NO" } }
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Browser router" }
            div { style: MODULE_BODY,
                p {
                    "Live sessions: {status.browser_live_sessions} / {status.browser_max_sessions}"
                }
                p { style: HELP_TEXT, "{status.browser_detail}" }
            }
        }
    }
}

#[component]
fn TrafficPanel(status: AdminAiStatus) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Recent LLM traffic (24 h)" }
            div { style: MODULE_BODY,
                if status.recent_traffic.is_empty() {
                    p { style: HELP_TEXT, "No llm_call_events yet." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "User" }
                                th { style: TH, "Calls" }
                                th { style: TH, "Errors" }
                                th { style: TH, "p50" }
                            }
                        }
                        tbody {
                            for t in status.recent_traffic {
                                tr { key: "{t.username}",
                                    td { style: TD, "{t.username}" }
                                    td { style: TD, "{t.calls}" }
                                    td { style: TD, "{t.errors}" }
                                    td { style: TD, "{t.median_latency_ms} ms" }
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Service use% (24 h)" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 12px;",
                    "Busy seconds / 86400 from ai_service_telemetry (and llm_call_events for LLM when the telemetry table is still empty)."
                }
                if status.service_use.is_empty() {
                    p { style: HELP_TEXT, "No samples yet." }
                } else {
                    table { style: TABLE,
                        thead {
                            tr {
                                th { style: TH, "Service" }
                                th { style: TH, "Calls" }
                                th { style: TH, "Errors" }
                                th { style: TH, "Busy s" }
                                th { style: TH, "Use %" }
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
