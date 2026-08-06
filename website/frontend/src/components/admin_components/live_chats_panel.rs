//! Admin panel: LLM chats this website process is answering right now.
//!
//! Answers "who is on the GPU, and can I stop them". Polls rather than streams — the
//! interesting runs last tens of seconds and a two-second refresh is enough to watch
//! one, without a websocket for a page an admin has open for a minute at a time.
//!
//! Scope is stated on the page rather than hidden: these are *inline* chat turns held
//! open by this process. Deep-research turns run in a Temporal worker and are listed in
//! the Temporal UI, which the panel links to instead of half-reproducing.

use std::time::Duration;

use common::chat_types::LiveChatRun;
use dioxus::prelude::*;

use crate::api::chat_api::{chat_admin_cancel_run, chat_admin_live_runs};
use crate::components::admin_components::{HELP_TEXT, MODULE, MODULE_BODY, MODULE_CAPTION, TABLE, TD, TH};

/// Poll interval. Fast enough to watch a run tick, slow enough not to matter.
const REFRESH_MS: u64 = 2_000;

/// A run older than this is called out in red. Well past the p95 of a real turn
/// (~20 s measured on this hardware), so it means stuck rather than slow.
const SLOW_RUN_MS: u64 = 120_000;

#[component]
pub fn LiveChatsPanel() -> Element {
    let mut tick = use_signal(|| 0_u64);
    let mut action_error = use_signal(|| None::<String>);

    // Re-runs whenever `tick` changes; the future below bumps it on a timer.
    let runs_res = use_resource(move || {
        let _ = tick.read();
        chat_admin_live_runs()
    });

    // `n0_future::time::sleep` rather than `gloo_timers`: it resolves to browser timers
    // under wasm and to a native timer otherwise, so this one loop compiles for both the
    // wasm bundle and the server-side render build. (`gloo_timers` is wasm-only and
    // broke the `--features server` build.) Same primitive `_crack_utils::sleep_ms`
    // wraps.
    use_future(move || async move {
        loop {
            n0_future::time::sleep(Duration::from_millis(REFRESH_MS)).await;
            tick += 1;
        }
    });

    let runs = runs_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();

    rsx! {
        div { style: MODULE,
            h2 { style: MODULE_CAPTION, "Live LLM chats" }
            div { style: MODULE_BODY,
                p { style: "{HELP_TEXT} margin: 0 0 12px;",
                    "Inline chat turns this website process is answering right now, longest-running first. \
                     Refreshes every 2 s. Deep-research turns run in Temporal and are not listed here."
                }
                if let Some(e) = action_error.read().clone() {
                    p { style: "color: #ba2121; font-size: 12px; margin: 0 0 8px;", "{e}" }
                }
                match runs {
                    None => rsx! { p { style: HELP_TEXT, "Loading\u{2026}" } },
                    Some(list) if list.is_empty() => rsx! {
                        p { style: HELP_TEXT, "No chats running." }
                    },
                    Some(list) => rsx! {
                        table { style: TABLE,
                            thead {
                                tr {
                                    th { style: TH, "User" }
                                    th { style: TH, "Conversation" }
                                    th { style: TH, "Question" }
                                    th { style: TH, "Research" }
                                    th { style: TH, "Internet" }
                                    th { style: TH, "Running" }
                                    th { style: TH, "Attempt" }
                                    th { style: TH, "Started" }
                                    th { style: TH, "" }
                                }
                            }
                            tbody {
                                for run in list {
                                    LiveChatRow {
                                        key: "{run.run_id}",
                                        run: run.clone(),
                                        on_error: move |e| action_error.set(Some(e)),
                                        on_done: move |_| { tick += 1; },
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
    }
}

#[component]
fn LiveChatRow(
    run: LiveChatRun,
    on_error: EventHandler<String>,
    on_done: EventHandler<()>,
) -> Element {
    let mut killing = use_signal(|| false);
    let run_id = run.run_id;

    let duration_style = if run.running_ms >= SLOW_RUN_MS {
        format!("{TD} color: #ba2121; font-weight: 700;")
    } else {
        TD.to_string()
    };

    rsx! {
        tr {
            td { style: TD, "{run.username}" }
            td {
                style: "{TD} max-width: 220px; overflow: hidden; text-overflow: ellipsis; \
                        white-space: nowrap;",
                title: "{run.session_id}",
                "{run.title}"
            }
            td {
                style: "{TD} max-width: 320px; font-size: 12px; color: #555;",
                "{run.message_preview}"
            }
            td { style: TD, {yes_no(run.deep_research)} }
            td { style: TD, {yes_no(run.internet_tools)} }
            td { style: duration_style, "{humanize_duration(run.running_ms)}" }
            td { style: TD, "{run.attempt}" }
            td { style: "{TD} font-size: 12px; color: #555;", "{run.started_at}" }
            td { style: TD,
                if run.cancel_requested {
                    span {
                        style: "font-size: 12px; color: #b8860b;",
                        title: "The run stops at its next checkpoint. It cannot abort a \
                                generation already in flight.",
                        "stopping\u{2026}"
                    }
                } else {
                    button {
                        style: "font-size: 12px; padding: 2px 8px; cursor: pointer;",
                        disabled: *killing.read(),
                        onclick: move |_| {
                            killing.set(true);
                            spawn(async move {
                                match chat_admin_cancel_run(run_id).await {
                                    // `false` means it finished on its own between the
                                    // page rendering and the click — not an error.
                                    Ok(_) => on_done.call(()),
                                    Err(e) => on_error.call(e.to_string()),
                                }
                                killing.set(false);
                            });
                        },
                        "Kill"
                    }
                }
            }
        }
    }
}

fn yes_no(on: bool) -> Element {
    if on {
        rsx! { span { style: "color: #2e7d32; font-weight: 600;", "on" } }
    } else {
        rsx! { span { style: "color: #999;", "off" } }
    }
}

/// Compact elapsed time. Sub-minute runs are the common case and read best in seconds
/// with one decimal; past a minute the decimal is noise.
pub fn humanize_duration(ms: u64) -> String {
    let secs = ms as f64 / 1000.0;
    if secs < 60.0 {
        return format!("{secs:.1}s");
    }
    let total = ms / 1000;
    let minutes = total / 60;
    let seconds = total % 60;
    if minutes < 60 {
        return format!("{minutes}m {seconds:02}s");
    }
    format!("{}h {:02}m", minutes / 60, minutes % 60)
}

#[cfg(test)]
mod tests {
    use super::humanize_duration;

    #[test]
    fn durations_read_naturally_at_every_scale() {
        assert_eq!(humanize_duration(0), "0.0s");
        assert_eq!(humanize_duration(4_400), "4.4s");
        assert_eq!(humanize_duration(59_900), "59.9s");
        assert_eq!(humanize_duration(60_000), "1m 00s");
        assert_eq!(humanize_duration(125_000), "2m 05s");
        assert_eq!(humanize_duration(3_600_000), "1h 00m");
        assert_eq!(humanize_duration(7_830_000), "2h 10m");
    }
}
