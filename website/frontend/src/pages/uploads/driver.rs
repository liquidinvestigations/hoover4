//! The channel between an upload page and `assets/uploads.js`, and the controls that both
//! upload pages share: the drop zone and the progress dialog.
//!
//! The script holds the browser `File` objects and runs the transfer. The page keeps the
//! selection list, runs the checks of `common::uploads`, and builds the `begin` body. The
//! page sends commands with [`UploadDriver::send`], and the script answers with
//! [`DriverEvent`]s.

use common::upload_pages::SelectedFile;
use common::uploads::{format_count, format_upload_size};
use dioxus::prelude::*;
use dioxus_free_icons::icons::md_file_icons::MdCloudUpload;
use dioxus_free_icons::Icon;

use crate::components::admin_components::{BTN, BTN_DANGER, BTN_PRIMARY};
use crate::tr;

const TUS_JS: Asset = asset!("/assets/vendor/tus.min.js");
const UPLOADS_JS: Asset = asset!("/assets/uploads.js");

/// The script of the channel. It waits for both scripts, connects the event sink, and
/// passes each command to the driver.
const CHANNEL_SCRIPT: &str = r#"
while (!window.hooverUploads || !window.tus) await new Promise(r => setTimeout(r, 50));
window.hooverUploads.attach((event) => dioxus.send(event));
while (true) { window.hooverUploads.command(await dioxus.recv()); }
"#;

/// A file that failed after the last retry, or whose prefix does not match.
#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
pub struct FailedFile {
    pub path: String,
    pub error: String,
}

/// The transfer state that the script reports. `sent` and `done` count what the server
/// acknowledged.
#[derive(Debug, Clone, PartialEq, Default, serde::Deserialize)]
pub struct Progress {
    pub sent: u64,
    pub total: u64,
    pub done: u64,
    pub count: u64,
    pub in_flight: Vec<String>,
    /// The most files in transfer at one time, so the dialog keeps one line for each.
    pub slots: u64,
    pub failed: Vec<FailedFile>,
    pub paused: bool,
    pub phase: String,
}

/// An event of the script.
#[derive(Debug, Clone, PartialEq, serde::Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DriverEvent {
    /// Files were dropped or chosen.
    Added { files: Vec<SelectedFile> },
    /// `begin` answered with a refusal. `body` is the response text.
    Refused { status: u16, body: String },
    Begun { batch_id: String },
    Phase { phase: String },
    ResumeFailed { message: String },
    Progress {
        sent: u64,
        total: u64,
        done: u64,
        count: u64,
        in_flight: Vec<String>,
        #[serde(default)]
        slots: u64,
        failed: Vec<FailedFile>,
        paused: bool,
        phase: String,
    },
    Committed { detail: String },
    /// The server deleted the aborted batch.
    Aborted { batch_id: String },
    /// The abort request failed. Abort can be sent again.
    AbortFailed { message: String },
    CommitFailed { message: String },
    /// A "Continue upload" run sent its files without a commit, because other files of
    /// the batch still wait for bytes.
    Sent { batch_id: String },
    /// "Continue upload" compared the acknowledged prefixes.
    /// `sending` counts the files that it resumes.
    Checked { mismatched: Vec<FailedFile>, sending: u64 },
}

impl DriverEvent {
    /// The progress fields of a `Progress` event.
    pub fn progress(&self) -> Option<Progress> {
        match self {
            DriverEvent::Progress { sent, total, done, count, in_flight, slots, failed, paused, phase } => Some(Progress {
                sent: *sent,
                total: *total,
                done: *done,
                count: *count,
                in_flight: in_flight.clone(),
                slots: *slots,
                failed: failed.clone(),
                paused: *paused,
                phase: phase.clone(),
            }),
            _ => None,
        }
    }
}

/// The page side of the channel.
#[derive(Clone, Copy, PartialEq)]
pub struct UploadDriver {
    eval: Signal<Option<document::Eval>>,
}

impl UploadDriver {
    /// Send one command. A command before the channel opens is dropped, and the controls
    /// that send commands appear only after the page has loaded its data.
    pub fn send(&self, command: serde_json::Value) {
        if let Some(eval) = *self.eval.peek() {
            if let Err(e) = eval.send(command) {
                dioxus::logger::tracing::warn!("upload driver command failed: {e}");
            }
        }
    }
}

/// Open the channel and pass each event to `on_event`.
pub fn use_upload_driver(on_event: Callback<DriverEvent>) -> UploadDriver {
    let mut eval = use_signal(|| None::<document::Eval>);
    use_future(move || async move {
        let mut channel = document::eval(CHANNEL_SCRIPT);
        eval.set(Some(channel));
        loop {
            match channel.recv::<DriverEvent>().await {
                Ok(event) => on_event.call(event),
                Err(e) => {
                    dioxus::logger::tracing::warn!("upload driver channel ended: {e}");
                    break;
                }
            }
        }
    });
    use_drop(move || {
        document::eval("if (window.hooverUploads) window.hooverUploads.command({cmd: 'detach'});");
    });
    UploadDriver { eval }
}

/// The two script tags. Each page that uses the driver renders this once.
#[component]
pub fn UploadScripts() -> Element {
    rsx! {
        document::Script { src: TUS_JS }
        document::Script { src: UPLOADS_JS }
        document::Style { ".x-upload-progress button:disabled, .x-upload-submit:disabled, .x-upload-finish:disabled {{ opacity: 0.5; cursor: not-allowed; }}" }
    }
}

const ZONE_STYLE: &str = "display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 23px; border: 1px dashed; border-color: var(--x-border-strong); border-radius: 8px; cursor: pointer; color: var(--x-ink); font-size: var(--x-text-body);";

/// The drop zone and the folder button. The script handles the drop and the click on any
/// element with `data-upload-drop`.
#[component]
pub fn DropZone(driver: UploadDriver) -> Element {
    rsx! {
        div {
            class: "x-upload-drop",
            "data-upload-drop": "true",
            style: ZONE_STYLE,
            Icon { icon: MdCloudUpload, width: 28, height: 28 }
            span { {tr!("uploads-driver-drop-files-or-folders-here")} }
            span { style: "color: var(--x-ink-muted);", {tr!("uploads-driver-or-click-to-choose-files")} }
        }
        div { style: "margin-top: 8px;",
            button {
                class: "x-upload-choose-folder",
                style: BTN,
                onclick: move |_| driver.send(serde_json::json!({"cmd": "open_folder"})),
                {tr!("uploads-driver-choose-a-folder")}
            }
        }
    }
}

const OVERLAY_STYLE: &str = "position: fixed; inset: 0; background-color: rgba(0,0,0,0.3); z-index: 2000; display: flex; align-items: center; justify-content: center;";
/// The dialog keeps one size during a transfer: 80 % of the window, one line for each path.
const DIALOG_STYLE: &str = "background: white; border-radius: 10px; padding: 18px 20px; width: 80vw; height: 80vh; box-sizing: border-box; box-shadow: 0 8px 30px rgba(0,0,0,0.2); display: flex; flex-direction: column; gap: 8px; font-size: var(--x-text-body); color: var(--x-ink); overflow: hidden;";
const PATH_LINE_STYLE: &str = "display: flex; min-width: 0; white-space: nowrap; line-height: 1.5;";
const PATH_HEAD_STYLE: &str = "flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis;";
const PATH_TAIL_STYLE: &str = "flex: 0 0 auto;";

/// The most characters of a path in the dialog. A longer path loses its middle.
pub const PATH_CHARS: usize = 120;
/// The characters at the end of a path that always stay visible.
const PATH_TAIL_CHARS: usize = 40;

/// A path with at most `max` characters: its start, an ellipsis and its end.
pub fn trim_middle(path: &str, max: usize) -> String {
    let chars: Vec<char> = path.chars().collect();
    if chars.len() <= max {
        return path.to_string();
    }
    let tail = PATH_TAIL_CHARS.min(max.saturating_sub(1));
    let head = max.saturating_sub(tail + 1);
    let mut out: String = chars[..head].iter().collect();
    out.push('\u{2026}');
    out.extend(&chars[chars.len() - tail..]);
    out
}

/// One path on one line. When the line is too narrow, CSS cuts the start part with an
/// ellipsis, and the end part, with the file name, stays.
#[component]
fn PathLine(path: String, #[props(default)] class: String, #[props(default)] color: String) -> Element {
    let shown = trim_middle(&path, PATH_CHARS);
    let chars: Vec<char> = shown.chars().collect();
    let split = chars.len().saturating_sub(PATH_TAIL_CHARS);
    let head: String = chars[..split].iter().collect();
    let tail: String = chars[split..].iter().collect();
    let color = if color.is_empty() { "var(--x-ink-muted)".to_string() } else { color };
    rsx! {
        div { class: "{class}", style: "{PATH_LINE_STYLE} color: {color};", title: "{path}",
            span { style: PATH_HEAD_STYLE, "{head}" }
            span { style: PATH_TAIL_STYLE, "{tail}" }
        }
    }
}

/// The progress dialog of a transfer. It has no close control: the transfer ends by
/// itself and starts indexing, or Abort deletes it.
#[component]
pub fn ProgressDialog(
    heading: String,
    state: Progress,
    /// A failed `commit` or abort, shown under the bar.
    error: Option<String>,
    driver: UploadDriver,
) -> Element {
    let progress = state;
    let percent = if progress.total == 0 { 100 } else { progress.sent.saturating_mul(100) / progress.total };
    let count_line = tr!("uploads-driver-of-of-files", format_upload_size_progress_sent: (format_upload_size(progress.sent)).to_string(), format_upload_size_progress_total: (format_upload_size(progress.total)).to_string(), format_count_progress_done: (format_count(progress.done)).to_string(), format_count_progress_count: (format_count(progress.count)).to_string());
    let paused = progress.paused;
    let committing = progress.phase == "committing";
    let aborting = progress.phase == "aborting";
    let abort_failed = progress.phase == "abort_failed";
    let failed_commit = progress.phase == "commit_failed";
    let ready = progress.phase == "transferring" && error.is_none();
    let can_abort = ready || abort_failed || failed_commit;
    let status = match progress.phase.as_str() {
        "starting" => tr!("uploads-driver-starting-upload"),
        "checking" => tr!("uploads-driver-checking-selected-files"),
        "committing" => tr!("uploads-driver-finishing-upload"),
        "aborting" => tr!("uploads-driver-aborting-upload"),
        "abort_failed" => tr!("uploads-driver-the-upload-could-not-be-aborted"),
        _ if failed_commit => tr!("uploads-driver-the-upload-could-not-finish"),
        _ if paused => tr!("uploads-driver-upload-paused"),
        _ => tr!("uploads-driver-sending-files"),
    };
    let slots = progress.slots.max(progress.in_flight.len() as u64).max(1) as usize;
    rsx! {
        div { style: OVERLAY_STYLE,
            div { class: "x-upload-progress", style: DIALOG_STYLE, role: "dialog", "aria-modal": "true", tabindex: "-1",
                onmounted: move |_| { document::eval("document.querySelector('.x-upload-progress')?.focus()"); },
                p { class: "x-upload-status", role: "status", style: "margin: 0;", "{status}" }
                h2 { style: "margin: 0; font-size: var(--x-text-section); font-weight: 600; color: var(--x-ink-strong); overflow-wrap: anywhere;",
                    "{heading}"
                }
                div { style: "display: flex; align-items: center; gap: 10px;",
                    progress {
                        class: "x-upload-bar",
                        style: "flex: 1 1 auto; height: 14px; accent-color: var(--x-link);",
                        max: "{progress.total.max(1)}",
                        value: "{progress.sent}",
                    }
                    span { "{percent} %" }
                }
                div { class: "x-upload-count", "{count_line}" }
                div { class: "x-upload-in-flight", style: "display: flex; flex-direction: column; min-height: calc({slots} * 1.5em);",
                    for (index, path) in progress.in_flight.iter().enumerate() {
                        PathLine { key: "{index}", path: path.clone() }
                    }
                }
                if !progress.failed.is_empty() {
                    div { class: "x-upload-failed-count", style: "color: var(--x-danger); font-weight: 500;",
                        {tr!("uploads-driver-files-failed", count: progress.failed.len())}
                    }
                }
                div { style: "flex: 1 1 auto; min-height: 0; overflow-y: auto;",
                    for (index, failed) in progress.failed.iter().enumerate() {
                        div { key: "failed-{index}", class: "x-upload-failed", style: "margin-bottom: 4px;",
                            PathLine { path: failed.path.clone(), color: "var(--x-danger)".to_string() }
                            div { style: "color: var(--x-danger); font-size: var(--x-text-detail); overflow: hidden; white-space: nowrap; text-overflow: ellipsis;", title: "{failed.error}", "{failed.error}" }
                        }
                    }
                }
                if let Some(error) = error {
                    div { style: "color: var(--x-danger);", "{error}" }
                }
                div { style: "display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px;",
                    button {
                        class: "x-upload-abort",
                        style: BTN_DANGER,
                        disabled: !can_abort || aborting,
                        onclick: move |_| driver.send(serde_json::json!({"cmd": "abort"})),
                        {tr!("uploads-driver-abort")}
                    }
                    span { style: "flex: 1 1 auto;" }
                    if failed_commit {
                        button {
                            class: "x-upload-retry-commit",
                            style: BTN_PRIMARY,
                            disabled: committing,
                            onclick: move |_| driver.send(serde_json::json!({"cmd": "retry_commit"})),
                            {tr!("uploads-driver-retry-finish")}
                        }
                    }
                    if paused {
                        button {
                            class: "x-upload-continue",
                            style: BTN,
                            disabled: !ready,
                            onclick: move |_| driver.send(serde_json::json!({"cmd": "continue"})),
                            {tr!("uploads-driver-continue")}
                        }
                    } else {
                        button {
                            class: "x-upload-pause",
                            style: BTN,
                            disabled: !ready,
                            onclick: move |_| driver.send(serde_json::json!({"cmd": "pause"})),
                            {tr!("uploads-driver-pause")}
                        }
                    }
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn trim_middle_keeps_short_paths_and_cuts_the_middle_of_long_ones() {
        assert_eq!(trim_middle("docs/a.md", PATH_CHARS), "docs/a.md");
        let long = format!("{}/{}", "d".repeat(150), "file-name.png");
        let trimmed = trim_middle(&long, PATH_CHARS);
        assert_eq!(trimmed.chars().count(), PATH_CHARS);
        assert!(trimmed.ends_with("file-name.png"));
        assert!(trimmed.contains('\u{2026}'));
    }
}
