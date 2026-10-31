//! Admin server settings page.

use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::admin_api::{admin_list_deployment_config, admin_list_settings, admin_set_setting};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_SMALL, INPUT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::tr;

fn setting_description(key: &str) -> String {
    match key {
        "session_expiration_seconds" => tr!("admin-settings-web-session-lifetime-in-seconds"),
        "chat_enabled" => {
            tr!("admin-settings-turns-every-new-chat-turn")
        }
        "embeddings_serving_model" | "embeddings_serving_dim" => {
            tr!("admin-settings-written-by-main-py-probe")
        }
        _ => String::new(),
    }
}

/// Deployment keys are rendered read-only, so the page has to say where they are changed.
fn deployment_description(key: &str) -> String {
    match key {
        "datasets_mount_path" => {
            tr!("admin-settings-the-folder-whose-subfolders-the")
        }
        _ => tr!("admin-settings-from-hoover4-ini-changing-it"),
    }
}

#[component]
pub fn AdminSettingsPage() -> Element {
    rsx! {
        Title { {tr!("admin-settings-admin-settings")} }
        AdminGuard {
            AdminShell {
                title: tr!("admin-settings-server-settings").to_string(),
                breadcrumb: String::new(),
                active: "settings".to_string(),
                SuspendWrapper { SettingsContent {} }
            }
        }
    }
}

#[component]
fn SettingsContent() -> Element {
    let mut settings_res = use_resource(admin_list_settings);
    let deployment_res = use_resource(admin_list_deployment_config);
    let mut edit_values = use_signal(std::collections::HashMap::<String, String>::new);
    let mut msg = use_signal(|| None::<String>);
    let mut error_msg = use_signal(|| None::<String>);

    let settings = settings_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();

    let load_error = settings_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().err().map(|e| user_facing_message(&e)));

    rsx! {
        if let Some(m) = msg.read().clone() {
            SuccessBar { message: m }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        if let Some(err) = load_error {
            ErrorBar { message: err }
        } else if let Some(settings) = settings {
            table { style: TABLE,
                thead {
                    tr {
                        th { style: TH, {tr!("admin-settings-key")} }
                        th { style: TH, {tr!("admin-settings-value")} }
                        th { style: TH, {tr!("admin-settings-description")} }
                        th { style: TH, "" }
                    }
                }
                tbody {
                    for s in settings {
                        tr { key: "{s.key}",
                            td { style: "{TD} font-weight: 600;", "{s.key}" }
                            td { style: TD,
                                input {
                                    style: INPUT,
                                    value: edit_values.read().get(&s.key).cloned().unwrap_or_else(|| s.value.clone()),
                                    oninput: {
                                        let k = s.key.clone();
                                        move |e: Event<FormData>| {
                                            edit_values.write().insert(k.clone(), e.value());
                                        }
                                    },
                                }
                            }
                            td { style: "{TD} color: var(--x-ink-muted); font-size: var(--x-text-xs);", "{setting_description(&s.key)}" }
                            td { style: TD,
                                button {
                                    style: BTN_SMALL,
                                    onclick: {
                                        let k = s.key.clone();
                                        let default_v = s.value.clone();
                                        move |_| {
                                            let k = k.clone();
                                            let default_v = default_v.clone();
                                            let v = edit_values.read().get(&k).cloned().unwrap_or(default_v);
                                            spawn(async move {
                                                msg.set(None);
                                                error_msg.set(None);
                                                match admin_set_setting(k.clone(), v).await {
                                                    Ok(()) => {
                                                        msg.set(Some(tr!("admin-settings-the-setting-was-saved-successfully", k: k.to_string())));
                                                        settings_res.restart();
                                                    }
                                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                                }
                                            });
                                        }
                                    },
                                    {tr!("admin-settings-save")}
                                }
                            }
                        }
                    }
                }
            }
        } else {
            {tr!("admin-settings-loading")}
        }

        if let Some(Ok(deployment)) = deployment_res.read().as_ref() {
            if !deployment.is_empty() {
                h2 { style: "margin: 23px 0 8px; color: var(--x-ink-muted); font-size: var(--x-text-section); line-height: var(--x-line-section); font-weight: 400;",
                    {tr!("admin-settings-deployment-configuration-read-only")}
                }
                table { style: TABLE,
                    thead {
                        tr {
                            th { style: TH, {tr!("admin-settings-key")} }
                            th { style: TH, {tr!("admin-settings-value")} }
                            th { style: TH, {tr!("admin-settings-description")} }
                        }
                    }
                    tbody {
                        for item in deployment.iter() {
                            tr { key: "{item.key}",
                                td { style: "{TD} font-weight: 600;", "{item.key}" }
                                td { style: "{TD} font-family: ui-monospace, monospace;",
                                    if item.value.is_empty() { {tr!("admin-settings-not-set")} } else { "{item.value}" }
                                }
                                td { style: "{TD} color: var(--x-ink-muted); font-size: var(--x-text-xs);",
                                    "{deployment_description(&item.key)}"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
