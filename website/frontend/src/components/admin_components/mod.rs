//! Admin section components and their shared styles.

mod admin_guard;
mod admin_shell;
mod dataset_create_panel;
mod dataset_ocr_panel;
mod live_chats_panel;
mod processing_updates_panel;

pub use admin_guard::AdminGuard;
pub use admin_shell::AdminShell;
pub use dataset_create_panel::DatasetCreatePanel;
pub use dataset_ocr_panel::{DatasetOcrSettingsPanel, DatasetOperationStrip};
pub use live_chats_panel::LiveChatsPanel;
pub use processing_updates_panel::ProcessingUpdatesPanel;

use dioxus::prelude::*;
use dioxus_free_icons::icons::md_file_icons::MdCloudUpload;
use dioxus_free_icons::Icon;

use crate::tr;

// Administration styles. Every value reads a property from `assets/main.css`, which
// holds the reference values of the search and document pages, so administration text
// has the same type scale and colours as the rest of the application.
pub const C_HEADER: &str = "var(--x-ink-strong)";
pub const C_LINK: &str = "var(--x-link)";
pub const C_DANGER: &str = "var(--x-danger)";

pub const FONT: &str = "font-family: var(--x-font); color: var(--x-ink);";

pub const TABLE: &str =
    "width: 100%; border-collapse: collapse; background: white; border: 1px solid; border-color: var(--x-border);";
pub const TH: &str = "padding: 8px 11px; text-align: left; font-size: var(--x-text-detail); color: var(--x-ink-muted); font-weight: 500; background-color: var(--x-surface-muted); border-bottom: 1px solid; border-bottom-color: var(--x-border); white-space: nowrap;";
pub const TD: &str =
    "padding: 8px 11px; border-bottom: 1px solid; border-bottom-color: var(--x-border); font-size: var(--x-text-detail); color: var(--x-ink); vertical-align: top;";
pub const LINK: &str = "color: var(--x-link); text-decoration: none; font-weight: 500;";

pub const BTN: &str = "background: white; color: var(--x-ink-strong); border: 1px solid; border-color: var(--x-border-strong); padding: 4px 11px; border-radius: 16px; cursor: pointer; font-size: var(--x-text-body); font-weight: 500; white-space: nowrap;";
pub const BTN_PRIMARY: &str = "background-color: var(--x-link); color: white; border: none; padding: 4px 15px; border-radius: 16px; cursor: pointer; font-size: var(--x-text-body); font-weight: 500; white-space: nowrap;";
pub const BTN_DANGER: &str = "background-color: var(--x-danger); color: white; border: none; padding: 4px 11px; border-radius: 16px; cursor: pointer; font-size: var(--x-text-body); font-weight: 500; white-space: nowrap;";
/// The opacity and cursor of a button that can be disabled. Both states write both
/// properties: the interpreter keeps an old longhand that a new style string lacks, so a
/// style that only drops `opacity` leaves an enabled button faded.
pub fn action_state(enabled: bool) -> &'static str {
    if enabled {
        "opacity: 1; cursor: pointer;"
    } else {
        "opacity: 0.5; cursor: not-allowed;"
    }
}
pub const BTN_SMALL: &str = "background: white; color: var(--x-ink-strong); border: 1px solid; border-color: var(--x-border-strong); padding: 4px 11px; border-radius: 14px; cursor: pointer; font-size: var(--x-text-detail); white-space: nowrap;";
pub const BTN_SMALL_DANGER: &str = "background: white; color: var(--x-danger); border: 1px solid; border-color: var(--x-danger); padding: 4px 11px; border-radius: 14px; cursor: pointer; font-size: var(--x-text-detail); white-space: nowrap;";

pub const INPUT: &str = "border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 4px 8px; font-size: var(--x-text-body); color: var(--x-ink-strong); background: white;";
pub const SELECT: &str = "border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 4px 8px; font-size: var(--x-text-body); color: var(--x-ink-strong); background: white;";
pub const LABEL: &str = "font-size: var(--x-text-detail); color: var(--x-ink); display: flex; align-items: center; gap: 4px;";

/// A page section. Its `h2` is `MODULE_CAPTION`.
pub const MODULE: &str = "margin-bottom: 23px;";
/// A section heading: one step below the page title.
pub const MODULE_CAPTION: &str = "margin: 0 0 11px; font-size: var(--x-text-section); line-height: var(--x-line-section); font-weight: 600; color: var(--x-ink-strong);";
pub const MODULE_BODY: &str = "padding: 0;";
/// A subsection heading inside a section.
pub const SUBHEADING: &str = "margin: 15px 0 4px; font-size: var(--x-text-body); font-weight: 600; color: var(--x-ink-strong);";

pub const PAGE_TITLE: &str = "margin: 0 0 15px; color: var(--x-ink-strong); font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600;";
pub const HELP_TEXT: &str = "color: var(--x-ink-muted); font-size: var(--x-text-detail);";

/// The mark of a collection or dataset that accepts uploads, after its name in a list.
#[component]
pub fn UploadsBadge() -> Element {
    rsx! {
        span {
            class: "x-uploads-badge",
            title: tr!("admin-uploads-badge-title"),
            style: "display: inline-flex; align-items: center; gap: 3px; margin-left: 6px; padding: 0 7px; \
                    border: 1px solid; border-color: var(--x-link); border-radius: 999px; color: var(--x-link); \
                    font-size: var(--x-text-xs); font-weight: 500; vertical-align: middle; white-space: nowrap;",
            Icon { icon: MdCloudUpload, width: 12, height: 12 }
            {tr!("admin-uploads-badge")}
        }
    }
}

/// A green success bar with a check mark.
#[component]
pub fn SuccessBar(message: String) -> Element {
    rsx! {
        div {
            style: "display: flex; align-items: center; gap: 8px; background: #e8f5e9; color: var(--x-ink-strong); padding: 8px 11px; margin-bottom: 15px; font-size: var(--x-text-body); border-radius: 6px;",
            span {
                style: "display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background-color: var(--x-ok); color: white; font-size: 13px; font-weight: 700; flex-shrink: 0;",
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
            style: "display: flex; align-items: center; gap: 8px; background: #fdecec; color: var(--x-danger); padding: 8px 11px; margin-bottom: 15px; font-size: var(--x-text-body); border-radius: 6px; border: 1px solid #f3c1c1;",
            span {
                style: "display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background-color: var(--x-danger); color: white; font-size: 13px; font-weight: 700; flex-shrink: 0;",
                "!"
            }
            "{message}"
        }
    }
}
