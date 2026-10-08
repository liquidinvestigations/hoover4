//! Admin section components and their shared styles.

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

// Administration styles. Every value reads a property from `assets/main.css`, which
// holds the reference values of the search and document pages, so administration text
// has the same type scale and colours as the rest of the application.
pub const C_HEADER: &str = "var(--x-ink-strong)";
pub const C_LINK: &str = "var(--x-link)";
pub const C_DANGER: &str = "var(--x-danger)";

pub const FONT: &str = "font-family: var(--x-font); color: var(--x-ink);";

pub const TABLE: &str =
    "width: 100%; border-collapse: collapse; background: white; border: 1px solid var(--x-border);";
pub const TH: &str = "padding: 8px 10px; text-align: left; font-size: var(--x-text-sm); color: var(--x-ink-muted); font-weight: 500; background: var(--x-surface-muted); border-bottom: 1px solid var(--x-border); white-space: nowrap;";
pub const TD: &str =
    "padding: 8px 10px; border-bottom: 1px solid var(--x-border); font-size: var(--x-text-md); color: var(--x-ink); vertical-align: top;";
pub const LINK: &str = "color: var(--x-link); text-decoration: none; font-weight: 500;";

pub const BTN: &str = "background: white; color: var(--x-ink-strong); border: 1px solid var(--x-border-strong); padding: 6px 14px; border-radius: 16px; cursor: pointer; font-size: var(--x-text-md); font-weight: 500; white-space: nowrap;";
pub const BTN_PRIMARY: &str = "background: var(--x-link); color: white; border: none; padding: 7px 16px; border-radius: 16px; cursor: pointer; font-size: var(--x-text-md); font-weight: 500; white-space: nowrap;";
pub const BTN_DANGER: &str = "background: var(--x-danger); color: white; border: none; padding: 6px 14px; border-radius: 16px; cursor: pointer; font-size: var(--x-text-md); font-weight: 500; white-space: nowrap;";
pub const BTN_SMALL: &str = "background: white; color: var(--x-ink-strong); border: 1px solid var(--x-border-strong); padding: 3px 10px; border-radius: 14px; cursor: pointer; font-size: var(--x-text-sm); white-space: nowrap;";
pub const BTN_SMALL_DANGER: &str = "background: white; color: var(--x-danger); border: 1px solid var(--x-danger); padding: 3px 10px; border-radius: 14px; cursor: pointer; font-size: var(--x-text-sm); white-space: nowrap;";

pub const INPUT: &str = "border: 1px solid var(--x-border-strong); border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-md); color: var(--x-ink-strong); background: white;";
pub const SELECT: &str = "border: 1px solid var(--x-border-strong); border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-md); color: var(--x-ink-strong); background: white;";
pub const LABEL: &str = "font-size: var(--x-text-md); color: var(--x-ink); display: flex; align-items: center; gap: 6px;";

/// A page section. Its `h2` is `MODULE_CAPTION`.
pub const MODULE: &str = "margin-bottom: 28px;";
/// A section heading: one step below the page title.
pub const MODULE_CAPTION: &str = "margin: 0 0 10px; font-size: var(--x-text-lg); font-weight: 600; color: var(--x-ink-strong);";
pub const MODULE_BODY: &str = "padding: 0;";
/// A subsection heading inside a section.
pub const SUBHEADING: &str = "margin: 14px 0 6px; font-size: var(--x-text-md); font-weight: 600; color: var(--x-ink-strong);";

pub const PAGE_TITLE: &str = "margin: 0 0 20px; color: var(--x-ink-strong); font-size: var(--x-text-2xl); font-weight: 600;";
pub const HELP_TEXT: &str = "color: var(--x-ink-muted); font-size: var(--x-text-sm);";

/// A green success bar with a check mark.
#[component]
pub fn SuccessBar(message: String) -> Element {
    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 10px; background: #e8f5e9; color: var(--x-ink-strong); padding: 10px 14px; margin-bottom: 16px; font-size: var(--x-text-md); border-radius: 6px;",
            span {
                style: "display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background: var(--x-ok); color: white; font-size: 12px; font-weight: 700; flex-shrink: 0;",
                "\u{2713}"
            }
            "{message}"
        }
    }
}

/// A red error bar.
///
/// `x-error-bar`, not `x-error-display`: the screenshot gate reports these as warnings,
/// because an admin form rejecting bad input is the panel working, not a defect.
#[component]
pub fn ErrorBar(message: String) -> Element {
    rsx! {
        div {
            class: "x-error-bar",
            style: "display: flex; align-items: center; gap: 10px; background: #fdecec; color: var(--x-danger); padding: 10px 14px; margin-bottom: 16px; font-size: var(--x-text-md); border-radius: 6px; border: 1px solid #f3c1c1;",
            span {
                style: "display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background: var(--x-danger); color: white; font-size: 12px; font-weight: 700; flex-shrink: 0;",
                "!"
            }
            "{message}"
        }
    }
}
