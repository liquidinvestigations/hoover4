//! Admin page: `/admin/llm` — provider health, catalog, defaults, allowlist.

use common::llm_types::{AdminLlmPage as LlmPageData, LlmModelItem};
use dioxus::prelude::*;

use crate::api::admin_api::{
    admin_get_llm, admin_refresh_catalog, admin_set_default_chat_model, admin_set_model_allowed,
    admin_set_summarization_model,
};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN, BTN_PRIMARY, BTN_SMALL, HELP_TEXT, INPUT,
    LABEL, LINK, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::routes::Route;

#[component]
pub fn AdminLlmPage() -> Element {
    rsx! {
        Title { "Admin — LLM" }
        AdminGuard {
            AdminShell {
                title: "LLM".to_string(),
                breadcrumb: "LLM".to_string(),
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
    let mut chat_model = use_signal(String::new);
    let mut summary_model = use_signal(String::new);
    let mut filter = use_signal(String::new);

    // Seeding the two selects from the loaded page, in an effect rather than in the
    // render body: a signal written during render schedules another render from inside
    // one. Read (not peeked) so a Refresh that clears them re-seeds.
    use_effect(move || {
        let Some(p) = page_res.read().as_ref().and_then(|r| r.as_ref().ok()).cloned() else {
            return;
        };
        if chat_model.read().is_empty() && !p.default_chat_model.is_empty() {
            chat_model.set(p.default_chat_model.clone());
        }
        if summary_model.read().is_empty() && !p.summarization_model.is_empty() {
            summary_model.set(p.summarization_model.clone());
        }
    });

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
                DefaultsPanel {
                    page: p.clone(),
                    chat_model,
                    summary_model,
                    flash,
                    reload,
                }
                CatalogPanel {
                    page: p,
                    filter,
                    flash,
                    reload,
                }
            },
        }
    }
}

#[component]
fn ProviderPanel(page: LlmPageData, mut reload: Signal<u32>, mut flash: Signal<Option<Result<String, String>>>) -> Element {
    let mut busy = use_signal(|| false);
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Providers" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 12px;",
                    "Catalog refresh is single-flight and runs in the background. Stale rows stay visible while it works."
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
                                Err(e) => flash.set(Some(Err(e.to_string()))),
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

#[component]
fn DefaultsPanel(
    page: LlmPageData,
    mut chat_model: Signal<String>,
    mut summary_model: Signal<String>,
    mut flash: Signal<Option<Result<String, String>>>,
    mut reload: Signal<u32>,
) -> Element {
    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Default models" }
            div { style: MODULE_BODY,
                div { style: "display: flex; flex-wrap: wrap; gap: 16px; align-items: end;",
                    label { style: LABEL,
                        "Chat"
                        input {
                            style: "{INPUT} min-width: 320px;",
                            value: "{chat_model}",
                            oninput: move |e| chat_model.set(e.value()),
                        }
                    }
                    button {
                        style: BTN,
                        onclick: move |_| {
                            let id = chat_model.read().clone();
                            spawn(async move {
                                match admin_set_default_chat_model(id).await {
                                    Ok(()) => {
                                        flash.set(Some(Ok("Chat default saved".to_string())));
                                        let next = *reload.peek() + 1;
                                        reload.set(next);
                                    }
                                    Err(e) => flash.set(Some(Err(e.to_string()))),
                                }
                            });
                        },
                        "Save chat default"
                    }
                    label { style: LABEL,
                        "Summarisation"
                        input {
                            style: "{INPUT} min-width: 320px;",
                            value: "{summary_model}",
                            oninput: move |e| summary_model.set(e.value()),
                        }
                    }
                    button {
                        style: BTN,
                        onclick: move |_| {
                            let id = summary_model.read().clone();
                            spawn(async move {
                                match admin_set_summarization_model(id).await {
                                    Ok(()) => {
                                        flash.set(Some(Ok("Summarisation default saved".to_string())));
                                        let next = *reload.peek() + 1;
                                        reload.set(next);
                                    }
                                    Err(e) => flash.set(Some(Err(e.to_string()))),
                                }
                            });
                        },
                        "Save summarisation default"
                    }
                }
                p { style: "{HELP_TEXT} margin: 12px 0 0;",
                    "Current chat default: {page.default_chat_model}. Summarisation: {page.summarization_model}."
                }
            }
        }
    }
}

#[component]
fn CatalogPanel(
    page: LlmPageData,
    mut filter: Signal<String>,
    mut flash: Signal<Option<Result<String, String>>>,
    mut reload: Signal<u32>,
) -> Element {
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
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Catalog allowlist" }
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
                            th { style: TH, "Allowed" }
                        }
                    }
                    tbody {
                        for m in models {
                            {
                                let model_id = m.model_id.clone();
                                let allowed = m.is_allowed;
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
                                            if m.median_latency_ms > 0 { "{m.median_latency_ms} ms" } else { "—" }
                                        }
                                        td { style: TD, "{m.call_count_14d}" }
                                        td { style: TD,
                                            button {
                                                style: BTN_SMALL,
                                                onclick: move |_| {
                                                    let id = model_id.clone();
                                                    spawn(async move {
                                                        match admin_set_model_allowed(id, !allowed).await {
                                                            Ok(()) => {
                                                                flash.set(Some(Ok("Allowlist updated".to_string())));
                                                                let next = *reload.peek() + 1;
                                                                reload.set(next);
                                                            }
                                                            Err(e) => flash.set(Some(Err(e.to_string()))),
                                                        }
                                                    });
                                                },
                                                if allowed { "yes" } else { "no" }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                p { style: "{HELP_TEXT} margin-top: 12px;",
                    "A forged model id in a chat request is rejected server-side, not merely hidden here. "
                    Link { to: Route::AdminAiStatusPage {}, style: LINK, "AI status" }
                    " shows live serving health."
                }
            }
        }
    }
}
