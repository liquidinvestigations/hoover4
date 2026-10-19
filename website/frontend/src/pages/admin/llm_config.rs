//! Admin page: `/admin/llm`, provider health, the models that `hoover4.ini` sets, the
//! thinking switch, the catalog and reports.

use common::llm_types::{AdminLlmPage as LlmPageData, LlmModelItem};
use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{admin_get_llm, admin_refresh_catalog, admin_set_llm_thinking};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_PRIMARY, HELP_TEXT, INPUT, LINK, MODULE,
    MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::pages::admin::llm_reports::LlmReports;
use crate::routes::Route;

#[component]
pub fn AdminLlmPage() -> Element {
    rsx! {
        Title { "Admin: LLM" }
        AdminGuard {
            AdminShell {
                title: "LLM".to_string(),
                breadcrumb: String::new(),
                active: "llm".to_string(),
                SuspendWrapper { LlmContent {} }
            }
        }
    }
}

#[component]
fn LlmContent() -> Element {
    let mut reload = use_signal(|| 0u32);
    let page_res = use_resource(move || {
        let _ = *reload.read();
        admin_get_llm()
    });
    let page = page_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned();
    let mut flash = use_signal(|| None::<Result<String, String>>);
    let mut filter = use_signal(String::new);

    rsx! {
        if let Some(msg) = flash.read().as_ref() {
            match msg {
                Ok(m) => rsx! { SuccessBar { message: m.clone() } },
                Err(m) => rsx! { ErrorBar { message: m.clone() } },
            }
        }
        match page {
            None => rsx! { "Loading\u{2026}" },
            Some(p) => rsx! {
                if !p.llm_configured {
                    ErrorBar {
                        message: "No LLM provider is configured. Set LLM_BASE_URL / LLM_MODEL in hoover4.ini and redeploy.".to_string()
                    }
                }
                ProviderPanel { page: p.clone(), reload, flash }
                ModelsPanel { page: p.clone(), flash, reload }
                CatalogPanel { page: p, filter }
                LlmReports {}
            },
        }
    }
}

#[component]
fn ProviderPanel(page: LlmPageData, mut reload: Signal<u32>, mut flash: Signal<Option<Result<String, String>>>) -> Element {
    let mut busy = use_signal(|| false);
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Providers" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 12px;",
                    "The refresh runs in the background. The current list stays visible meanwhile."
                    if page.refresh_in_flight {
                        " Refresh in flight\u{2026}"
                    }
                }
                table { style: "{TABLE} margin-bottom: 12px;",
                    thead {
                        tr {
                            th { style: TH, "Provider" }
                            th { style: TH, "Models" }
                            th { style: TH, "Freshest" }
                            th { style: TH, "Status" }
                        }
                    }
                    tbody {
                        for pr in page.providers {
                            tr { key: "{pr.provider}",
                                td { style: TD, "{pr.provider}" }
                                td { style: TD, "{pr.model_count}" }
                                td { style: TD, "{pr.freshest_fetched_at}" }
                                td { style: TD,
                                    if pr.ok && !pr.stale { "fresh" }
                                    else if pr.ok { "stale" }
                                    else { "{pr.error}" }
                                }
                            }
                        }
                    }
                }
                button {
                    style: BTN_PRIMARY,
                    disabled: *busy.read() || page.refresh_in_flight,
                    onclick: move |_| {
                        busy.set(true);
                        spawn(async move {
                            match admin_refresh_catalog().await {
                                Ok(true) => flash.set(Some(Ok("Refresh started".to_string()))),
                                Ok(false) => flash.set(Some(Ok("Refresh already in flight".to_string()))),
                                Err(e) => flash.set(Some(Err(user_facing_message(&e)))),
                            }
                            busy.set(false);
                            let next = *reload.peek() + 1;
                            reload.set(next);
                        });
                    },
                    "Refresh catalog"
                }
            }
        }
    }
}

/// The models of the deployment, read only: `hoover4.ini` sets them. The thinking switch is
/// the one model setting that an administrator changes here.
#[component]
fn ModelsPanel(
    page: LlmPageData,
    mut flash: Signal<Option<Result<String, String>>>,
    mut reload: Signal<u32>,
) -> Element {
    let agent = if page.agent_model.is_empty() { "none".to_string() } else { page.agent_model.clone() };
    let short = if page.short_call_model.is_empty() { "none".to_string() } else { page.short_call_model.clone() };
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Models" }
            div { style: MODULE_BODY,
                table { class: "x-admin-llm-models", style: TABLE,
                    tbody {
                        tr {
                            td { style: TD, "Agent turns, board assessments and report conversions" }
                            td { style: "{TD} font-family: monospace;", "{agent}" }
                        }
                        tr {
                            td { style: TD, "Titles, summaries and board labels" }
                            td { style: "{TD} font-family: monospace;", "{short}" }
                        }
                    }
                }
                p { style: "{HELP_TEXT} margin: 8px 0 14px;",
                    "hoover4.ini sets these models: quality_model of the LLM provider for agent turns, board assessments and report conversions when it is set, and its model for the rest."
                }
                label { style: "display: flex; gap: 8px; align-items: center; font-weight: 600; margin-bottom: 4px;",
                    input {
                        r#type: "checkbox",
                        checked: page.thinking,
                        onchange: move |e| {
                            let on = e.checked();
                            spawn(async move {
                                match admin_set_llm_thinking(on).await {
                                    Ok(()) => {
                                        let msg = if on { "Thinking is on" } else { "Thinking is off" };
                                        flash.set(Some(Ok(msg.to_string())));
                                        let next = *reload.peek() + 1;
                                        reload.set(next);
                                    }
                                    Err(e) => flash.set(Some(Err(user_facing_message(&e)))),
                                }
                            });
                        },
                    }
                    "Thinking"
                }
                p { style: "{HELP_TEXT} margin: 0;",
                    "The model reasons before each tool call and each answer."
                }
            }
        }
    }
}

#[component]
fn CatalogPanel(page: LlmPageData, mut filter: Signal<String>) -> Element {
    let q = filter.read().to_lowercase();
    let models: Vec<LlmModelItem> = page
        .models
        .into_iter()
        .filter(|m| {
            q.is_empty()
                || m.model_id.to_lowercase().contains(&q)
                || m.display_name.to_lowercase().contains(&q)
                || m.provider.to_lowercase().contains(&q)
        })
        .collect();
    rsx! {
        div { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Catalog" }
            div { style: MODULE_BODY,
                div { style: "margin-bottom: 12px; display: flex; gap: 12px; align-items: center;",
                    input {
                        style: "{INPUT} min-width: 280px;",
                        placeholder: "Filter models\u{2026}",
                        value: "{filter}",
                        oninput: move |e| filter.set(e.value()),
                    }
                    span { style: HELP_TEXT, "{models.len()} shown" }
                }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, "Provider" }
                            th { style: TH, "Model" }
                            th { style: TH, "Flags" }
                            th { style: TH, "p50" }
                            th { style: TH, "Calls 14d" }
                        }
                    }
                    tbody {
                        for m in models {
                            {
                                rsx! {
                                    tr { key: "{m.provider}-{m.model_id}",
                                        td { style: TD, "{m.provider}" }
                                        td { style: TD,
                                            div { style: "font-weight: 600;", "{m.display_name}" }
                                            div { style: HELP_TEXT, "{m.model_id}" }
                                        }
                                        td { style: TD,
                                            if m.supports_tools { "tools " }
                                            if m.supports_vision { "vision " }
                                            if m.is_reasoning { "reasoning" }
                                        }
                                        td { style: TD,
                                            if m.median_latency_ms > 0 { "{m.median_latency_ms} ms" } else { "n/a" }
                                        }
                                        td { style: TD, "{m.call_count_14d}" }
                                    }
                                }
                            }
                        }
                    }
                }
                p { style: "{HELP_TEXT} margin-top: 12px;",
                    Link { to: Route::AdminAiStatusPage {}, style: LINK, "AI status" }
                    " shows the serving health."
                }
            }
        }
    }
}
