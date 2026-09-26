//! The queued state of an agent run, read from Temporal.
//!
//! A run whose `run_agent` activity waits in its task queue for a free slot writes no
//! row, because the keepalive of the run row runs inside the activity attempt. Its turn
//! then stops advancing, and after the stall window the page would call it interrupted.
//! [`run_waits_for_slot`] asks Temporal whether the activity is still scheduled, and
//! [`turn_verdict`] turns that answer into the page's verdict.
//!
//! A scheduled activity also stays scheduled when no worker polls its queue. The caller
//! therefore counts a run as queued only while another run on the same queue has a fresh
//! row (`db_chat::queue_has_live_run`).
//!
//! A failed, slow or refused read of Temporal gives `false`, which is the verdict the
//! page gave before this module existed.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use crate::temporal_ready::temporal_base_url;

/// The longest wait for one describe request.
const DESCRIBE_TIMEOUT: Duration = Duration::from_secs(2);

/// How long one answer is kept for its workflow id. The poll steps every 500 ms, so this
/// bounds the describe requests to one for each waiting run every 10 s in each process.
const CACHE_TTL: Duration = Duration::from_secs(10);

/// The name of the activity whose schedule is read.
const RUN_AGENT_ACTIVITY: &str = "run_agent";

/// Whether a describe response shows the `run_agent` activity waiting in its task queue.
pub fn run_agent_scheduled(describe: &serde_json::Value) -> bool {
    describe["pendingActivities"]
        .as_array()
        .is_some_and(|activities| {
            activities.iter().any(|a| {
                a["activityType"]["name"].as_str() == Some(RUN_AGENT_ACTIVITY)
                    && is_scheduled(&a["state"])
            })
        })
}

/// Temporal writes an enum as its full name, its short name or its number, by version.
fn is_scheduled(state: &serde_json::Value) -> bool {
    match state {
        serde_json::Value::String(s) => {
            s == "PENDING_ACTIVITY_STATE_SCHEDULED" || s.eq_ignore_ascii_case("Scheduled")
        }
        serde_json::Value::Number(n) => n.as_u64() == Some(1),
        _ => false,
    }
}

/// The page's verdict on an open turn: `(active, queued, interrupted)`.
///
/// `advancing` means a row of the turn moved within the stall window. `has_rows` means
/// the turn wrote a row at all. `queued_run` means a run of the turn waits for a slot
/// while another run on its queue holds one.
pub fn turn_verdict(
    turn_open: bool,
    advancing: bool,
    plan_pending: bool,
    has_rows: bool,
    queued_run: bool,
) -> (bool, bool, bool) {
    let queued = turn_open && !advancing && !plan_pending && queued_run;
    let active = turn_open && (advancing || queued);
    let interrupted = turn_open && has_rows && !advancing && !queued && !plan_pending;
    (active, queued, interrupted)
}

fn client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(DESCRIBE_TIMEOUT)
            .build()
            .expect("the describe client builds from constant settings")
    })
}

fn cache() -> &'static Mutex<HashMap<String, (Instant, bool)>> {
    static CACHE: OnceLock<Mutex<HashMap<String, (Instant, bool)>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

/// Describe one workflow, and keep the answer [`CACHE_TTL`] for its id.
///
/// The request does not wait for Temporal's readiness, because a page poll must not
/// hold for it. An error, a timeout or a non-2xx status gives `false`.
pub async fn run_waits_for_slot(workflow_id: &str) -> bool {
    let now = Instant::now();
    {
        let mut entries = cache().lock().unwrap_or_else(|e| e.into_inner());
        entries.retain(|_, (at, _)| now.duration_since(*at) < CACHE_TTL);
        if let Some((_, answer)) = entries.get(workflow_id) {
            return *answer;
        }
    }
    let answer = describe_scheduled(workflow_id).await;
    cache()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert(workflow_id.to_string(), (Instant::now(), answer));
    answer
}

async fn describe_scheduled(workflow_id: &str) -> bool {
    let url = format!(
        "{}/api/v1/namespaces/default/workflows/{workflow_id}",
        temporal_base_url()
    );
    let response = match client().get(&url).send().await {
        Ok(response) if response.status().is_success() => response,
        Ok(response) => {
            tracing::debug!("describe of {workflow_id}: {}", response.status());
            return false;
        }
        Err(e) => {
            tracing::debug!("describe of {workflow_id}: {e}");
            return false;
        }
    };
    match response.json::<serde_json::Value>().await {
        Ok(body) => run_agent_scheduled(&body),
        Err(e) => {
            tracing::debug!("describe of {workflow_id}: {e}");
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn describe(name: &str, state: serde_json::Value) -> serde_json::Value {
        json!({
            "workflowExecutionInfo": {"status": "WORKFLOW_EXECUTION_STATUS_RUNNING"},
            "pendingActivities": [
                {"activityId": "1", "activityType": {"name": name}, "state": state}
            ]
        })
    }

    #[test]
    fn run_queue_scheduled_by_full_name() {
        assert!(run_agent_scheduled(&describe(
            "run_agent",
            json!("PENDING_ACTIVITY_STATE_SCHEDULED")
        )));
    }

    #[test]
    fn run_queue_scheduled_by_short_name() {
        assert!(run_agent_scheduled(&describe("run_agent", json!("Scheduled"))));
    }

    #[test]
    fn run_queue_scheduled_by_number() {
        assert!(run_agent_scheduled(&describe("run_agent", json!(1))));
    }

    #[test]
    fn run_queue_started_is_not_scheduled() {
        assert!(!run_agent_scheduled(&describe(
            "run_agent",
            json!("PENDING_ACTIVITY_STATE_STARTED")
        )));
        assert!(!run_agent_scheduled(&describe("run_agent", json!(2))));
    }

    #[test]
    fn run_queue_other_activity_is_not_read() {
        assert!(!run_agent_scheduled(&describe(
            "open_run",
            json!("PENDING_ACTIVITY_STATE_SCHEDULED")
        )));
    }

    #[test]
    fn run_queue_no_pending_activities_is_not_scheduled() {
        assert!(!run_agent_scheduled(&json!({
            "workflowExecutionInfo": {"status": "WORKFLOW_EXECUTION_STATUS_RUNNING"}
        })));
        assert!(!run_agent_scheduled(&json!({"pendingActivities": []})));
    }

    #[test]
    fn run_queue_stale_turn_with_a_queued_run_is_active_and_queued() {
        // turn_open, advancing, plan_pending, has_rows, queued_run
        assert_eq!(turn_verdict(true, false, false, true, true), (true, true, false));
    }

    #[test]
    fn run_queue_stale_turn_without_a_queued_run_is_interrupted() {
        assert_eq!(turn_verdict(true, false, false, true, false), (false, false, true));
    }

    #[test]
    fn run_queue_fresh_turn_is_active_and_not_queued() {
        assert_eq!(turn_verdict(true, true, false, true, false), (true, false, false));
        assert_eq!(turn_verdict(true, true, false, true, true), (true, false, false));
    }

    #[test]
    fn run_queue_open_plan_is_never_interrupted() {
        assert_eq!(turn_verdict(true, false, true, true, false), (false, false, false));
        assert_eq!(turn_verdict(true, false, true, true, true), (false, false, false));
    }

    #[test]
    fn run_queue_closed_turn_is_nothing() {
        assert_eq!(turn_verdict(false, false, false, true, true), (false, false, false));
    }
}
