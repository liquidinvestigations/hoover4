//! Admin section components, with Django-admin-inspired chrome and shared styles.

mod admin_guard;
mod admin_shell;
mod dataset_create_panel;
mod dataset_ocr_panel;
mod live_chats_panel;

pub use admin_guard::AdminGuard;
pub use admin_shell::AdminShell;
pub use dataset_create_panel::DatasetCreatePanel;
pub use dataset_ocr_panel::{DatasetOcrSettingsPanel, DatasetOperationStrip};
pub use live_chats_panel::LiveChatsPanel;

use dioxus::prelude::*;

// Django-admin palette, shared by every admin page. All admin CSS is inline
// in the Rust code on purpose (no main.css entries).
pub const C_HEADER: &str = "#417690";
pub const C_ACCENT: &str = "#79aec8";
pub const C_LINK: &str = "#447e9b";
pub const C_YELLOW: &str = "#f5dd5d";
pub const C_DANGER: &str = "#ba2121";

pub const FONT: &str =
    "font-family: 'Roboto', 'Lucida Grande', 'DejaVu Sans', Verdana, Arial, sans-serif;";

pub const TABLE: &str =
    "width: 100%; border-collapse: collapse; background: white; border: 1px solid #eee;";
pub const TH: &str = "padding: 8px 10px; text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #666; font-weight: 600; background: #f6f6f6; border-bottom: 1px solid #eee; white-space: nowrap;";
pub const TD: &str =
    "padding: 8px 10px; border-bottom: 1px solid #eee; font-size: 13px; color: #333;";
pub const LINK: &str = "color: #447e9b; text-decoration: none; font-weight: 600;";

pub const BTN: &str = "background: #79aec8; color: white; border: none; padding: 7px 14px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600;";
pub const BTN_PRIMARY: &str = "background: #417690; color: white; border: none; padding: 8px 16px; border-radius: 15px; cursor: pointer; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;";
pub const BTN_DANGER: &str = "background: #ba2121; color: white; border: none; padding: 7px 14px; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: 600;";
pub const BTN_SMALL: &str = "background: #79aec8; color: white; border: none; padding: 3px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;";
pub const BTN_SMALL_DANGER: &str = "background: white; color: #ba2121; border: 1px solid #ba2121; padding: 3px 10px; border-radius: 4px; cursor: pointer; font-size: 11px;";

pub const INPUT: &str = "border: 1px solid #ccc; border-radius: 4px; padding: 6px 8px; font-size: 13px; color: #333; background: white;";
pub const SELECT: &str = "border: 1px solid #ccc; border-radius: 4px; padding: 6px 8px; font-size: 13px; color: #333; background: white;";
pub const LABEL: &str = "font-size: 13px; color: #333; display: flex; align-items: center; gap: 6px;";

pub const MODULE: &str =
    "background: white; border: 1px solid #eee; margin-bottom: 24px; overflow: hidden;";
pub const MODULE_CAPTION: &str = "background: #79aec8; color: white; padding: 8px 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin: 0;";
pub const MODULE_BODY: &str = "padding: 12px;";

pub const PAGE_TITLE: &str = "margin: 0 0 20px; color: #666; font-size: 22px; font-weight: 400;";
pub const HELP_TEXT: &str = "color: #999; font-size: 12px;";

/// Django-style green success bar with a check mark.
#[component]
pub fn SuccessBar(message: String) -> Element {
    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 10px; background: #dff2df; color: #333; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; border-radius: 4px;",
            span {
                style: "display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background: #5fa25f; color: white; font-size: 12px; font-weight: 700; flex-shrink: 0;",
                "\u{2713}"
            }
            "{message}"
        }
    }
}

/// Django-style red error bar.
///
/// `x-error-bar`, not `x-error-display`: the screenshot gate reports these as warnings,
/// because an admin form rejecting bad input is the panel working, not a defect.
#[component]
pub fn ErrorBar(message: String) -> Element {
    rsx! {
        div {
            class: "x-error-bar",
            style: "display: flex; align-items: center; gap: 10px; background: #ffefef; color: #ba2121; padding: 10px 14px; margin-bottom: 16px; font-size: 13px; border-radius: 4px; border: 1px solid #f3c1c1;",
            span {
                style: "display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background: #ba2121; color: white; font-size: 12px; font-weight: 700; flex-shrink: 0;",
                "!"
            }
            "{message}"
        }
    }
}
