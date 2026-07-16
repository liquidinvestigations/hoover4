//! Admin server settings page.

use dioxus::prelude::*;

use crate::api::admin_api::{admin_list_settings, admin_set_setting};
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_SMALL, INPUT, SELECT, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;

fn setting_description(key: &str) -> &'static str {
    match key {
        "session_expiration_seconds" => "Web session lifetime in seconds (default: 604800 = 1 week)",
        "guest_permissions_mode" => "Guest access: 'all' (dev) or 'none'",
        _ => "",
    }
}

#[component]
pub fn AdminSettingsPage() -> Element {
    rsx! {
        Title { "Admin — Settings" }
        AdminGuard {
            AdminShell {
                title: "Server settings".to_string(),
                breadcrumb: "Settings".to_string(),
                active: "settings".to_string(),
                SuspendWrapper { SettingsContent {} }
            }
        }
    }
}

#[component]
fn SettingsContent() -> Element {
    let mut settings_res = use_resource(admin_list_settings);
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
        .and_then(|r| r.as_ref().err().map(|e| e.to_string()));

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
                        th { style: TH, "Key" }
                        th { style: TH, "Value" }
                        th { style: TH, "Description" }
                        th { style: TH, "" }
                    }
                }
                tbody {
                    for s in settings {
                        tr { key: "{s.key}",
                            td { style: "{TD} font-weight: 600;", "{s.key}" }
                            td { style: TD,
                                if s.key == "guest_permissions_mode" {
                                    select {
                                        style: SELECT,
                                        value: edit_values.read().get(&s.key).cloned().unwrap_or_else(|| s.value.clone()),
                                        onchange: {
                                            let k = s.key.clone();
                                            move |e: Event<FormData>| {
                                                edit_values.write().insert(k.clone(), e.value());
                                            }
                                        },
                                        option { value: "all", "all" }
                                        option { value: "none", "none" }
                                    }
                                } else {
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
                            }
                            td { style: "{TD} color: #999; font-size: 12px;", "{setting_description(&s.key)}" }
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
                                                        msg.set(Some(format!("The setting \u{201c}{k}\u{201d} was saved successfully.")));
                                                        settings_res.restart();
                                                    }
                                                    Err(e) => error_msg.set(Some(e.to_string())),
                                                }
                                            });
                                        }
                                    },
                                    "Save"
                                }
                            }
                        }
                    }
                }
            }
        } else {
            "Loading..."
        }
    }
}
