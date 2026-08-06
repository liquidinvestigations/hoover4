//! Registry of agent runs currently in flight, for the admin "live chats" panel.
//!
//! **In-process, not in ClickHouse, and that is deliberate.** A row here means "this
//! website process is holding an HTTP request open against the agent right now". If it
//! were persisted, a process that was killed mid-run would leave rows claiming work
//! that nobody is doing, and an admin looking for a chat to kill would be shown ghosts.
//! Losing the whole table on restart is the correct behaviour: after a restart there
//! genuinely are no in-flight runs.
//!
//! Follows the `PERM_CACHE` / `SYNC_CACHE` `Mutex<HashMap>` idiom in
//! `auth/session_middleware.rs` rather than introducing Redis — same reasoning as the
//! rate limiter (see `api/rate_limit.rs`): correct while the website is one container,
//! and the thing that has to change first if it is ever scaled out.
//!
//! Cancellation is cooperative. [`request_cancel`] sets a flag; the run notices between
//! retry attempts and before writing its result. It cannot abort a request already
//! in flight inside `reqwest`, so a kill during a slow agent call takes effect when
//! that call returns or times out.

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::sync::{Arc, LazyLock, Mutex};
use std::time::Instant;

use common::chat_types::{ChatOptions, LiveChatRun};
use time::format_description::well_known::Rfc3339;

/// How much of the question is shown to the admin. Enough to recognise a runaway chat,
/// short enough that the panel is not a transcript viewer — an admin looking for "who
/// is burning the GPU" does not need the whole prompt.
const PREVIEW_CHARS: usize = 200;

static NEXT_RUN_ID: AtomicU64 = AtomicU64::new(1);

static RUNS: LazyLock<Mutex<HashMap<u64, Arc<RunState>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

struct RunState {
    run_id: u64,
    username: String,
    session_id: String,
    title: String,
    message_preview: String,
    options: ChatOptions,
    started: Instant,
    started_at: time::OffsetDateTime,
    attempt: AtomicU32,
    cancel: AtomicBool,
}

/// Handle held by the running turn. Dropping it deregisters the run, so an early
/// return, a `?` or a panic cannot leave a phantom entry in the panel.
pub struct RunGuard {
    state: Arc<RunState>,
}

impl RunGuard {
    /// Record which attempt is now in flight (1-based).
    pub fn set_attempt(&self, attempt: u32) {
        self.state.attempt.store(attempt, Ordering::Relaxed);
    }

    /// Whether an admin has asked this run to stop.
    pub fn is_cancelled(&self) -> bool {
        self.state.cancel.load(Ordering::Relaxed)
    }
}

impl Drop for RunGuard {
    fn drop(&mut self) {
        if let Ok(mut runs) = RUNS.lock() {
            runs.remove(&self.state.run_id);
        }
    }
}

/// Register a turn as in flight. Keep the guard alive for the duration of the run.
pub fn register(
    username: &str,
    session_id: &str,
    title: &str,
    message: &str,
    options: ChatOptions,
) -> RunGuard {
    let run_id = NEXT_RUN_ID.fetch_add(1, Ordering::Relaxed);
    let state = Arc::new(RunState {
        run_id,
        username: username.to_string(),
        session_id: session_id.to_string(),
        title: title.to_string(),
        message_preview: preview(message),
        options,
        started: Instant::now(),
        started_at: time::OffsetDateTime::now_utc(),
        attempt: AtomicU32::new(1),
        cancel: AtomicBool::new(false),
    });
    if let Ok(mut runs) = RUNS.lock() {
        runs.insert(run_id, Arc::clone(&state));
    }
    RunGuard { state }
}

fn preview(message: &str) -> String {
    let flat: String = message.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.chars().count() <= PREVIEW_CHARS {
        return flat;
    }
    format!("{}\u{2026}", flat.chars().take(PREVIEW_CHARS).collect::<String>())
}

/// Every run in flight, longest-running first — the order an admin hunting a stuck
/// chat wants, without having to sort the table themselves.
pub fn snapshot() -> Vec<LiveChatRun> {
    let Ok(runs) = RUNS.lock() else {
        return Vec::new();
    };
    let mut out: Vec<LiveChatRun> = runs
        .values()
        .map(|s| LiveChatRun {
            run_id: s.run_id,
            username: s.username.clone(),
            session_id: s.session_id.clone(),
            title: s.title.clone(),
            message_preview: s.message_preview.clone(),
            deep_research: s.options.deep_research,
            internet_tools: s.options.internet_tools,
            running_ms: s.started.elapsed().as_millis().min(u128::from(u64::MAX)) as u64,
            started_at: s
                .started_at
                .format(&Rfc3339)
                .unwrap_or_else(|_| s.started_at.to_string()),
            attempt: s.attempt.load(Ordering::Relaxed),
            cancel_requested: s.cancel.load(Ordering::Relaxed),
        })
        .collect();
    out.sort_by(|a, b| b.running_ms.cmp(&a.running_ms));
    out
}

/// Ask a run to stop. Returns false when the id is not in flight — which is the normal
/// outcome of clicking "kill" on a run that finished while the page was open.
pub fn request_cancel(run_id: u64) -> bool {
    let Ok(runs) = RUNS.lock() else {
        return false;
    };
    match runs.get(&run_id) {
        Some(state) => {
            state.cancel.store(true, Ordering::Relaxed);
            true
        }
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The registry is a process-global static and cargo runs these in parallel
    /// threads, so a test must only ever assert about *its own* run id — never about
    /// the size of the snapshot, which another test is concurrently changing.
    fn find(runs: &[LiveChatRun], run_id: u64) -> Option<&LiveChatRun> {
        runs.iter().find(|r| r.run_id == run_id)
    }

    #[test]
    fn a_registered_run_appears_and_disappears_with_its_guard() {
        let run_id;
        {
            let guard = register(
                "ann",
                "s1",
                "Water",
                "who paid for the water?",
                ChatOptions::default(),
            );
            run_id = guard.state.run_id;

            let runs = snapshot();
            let run = find(&runs, run_id).expect("registered run must be listed");
            assert_eq!(run.username, "ann");
            assert_eq!(run.session_id, "s1");
            assert_eq!(run.attempt, 1);
            assert!(!run.cancel_requested);

            guard.set_attempt(3);
            assert_eq!(find(&snapshot(), run_id).unwrap().attempt, 3);
        }
        assert!(
            find(&snapshot(), run_id).is_none(),
            "guard drop must deregister the run"
        );
    }

    #[test]
    fn cancel_sets_the_flag_the_run_polls() {
        let guard = register("bob", "s2", "T", "q", ChatOptions::default());
        let run_id = guard.state.run_id;
        assert!(!guard.is_cancelled());
        assert!(request_cancel(run_id));
        assert!(guard.is_cancelled());
        assert!(find(&snapshot(), run_id).unwrap().cancel_requested);
    }

    #[test]
    fn the_options_a_run_was_started_with_are_reported_verbatim() {
        // The admin panel shows the *enforced* switches, so they must survive the trip
        // through the registry unchanged.
        let opts = ChatOptions {
            deep_research: true,
            internet_tools: false,
            locked: true,
        };
        let guard = register("cleo", "s3", "T", "q", opts);
        let runs = snapshot();
        let run = find(&runs, guard.state.run_id).unwrap();
        assert!(run.deep_research);
        assert!(!run.internet_tools);
    }

    #[test]
    fn cancelling_an_unknown_run_is_not_an_error() {
        assert!(!request_cancel(u64::MAX));
    }

    #[test]
    fn preview_collapses_whitespace_and_truncates() {
        assert_eq!(preview("  a\n b  "), "a b");
        let long = "x".repeat(PREVIEW_CHARS + 50);
        assert_eq!(preview(&long).chars().count(), PREVIEW_CHARS + 1);
    }
}
