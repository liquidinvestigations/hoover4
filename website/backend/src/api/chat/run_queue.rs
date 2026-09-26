//! The waiting state of an agent run, read from Temporal.
//!
//! A run makes each model call as one `model_step` activity on its model queue, and each
//! tool call as one `tool_call` activity on `agent-tool-queue`. A step that waits in its
//! queue for a free slot writes no row, so the turn stops advancing. When a turn is quiet,
//! [`step_state`] reads the pending activities of each run, and [`turn_verdict`] turns the
//! answer into the page's verdict.
//!
//! A scheduled activity also stays scheduled when no worker polls its queue. The caller
//! therefore counts a step as queued only while a worker polls that queue
//! ([`queue_has_poller`]).
//!
//! A failed, slow or refused read of Temporal gives [`StepState::Idle`] or `false`, and the
//! page then applies the stall window alone.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use crate::temporal_ready::temporal_base_url;

/// The longest wait for one describe request.
const DESCRIBE_TIMEOUT: Duration = Duration::from_secs(2);

/// How long one answer is kept for its workflow id or its queue. The poll steps every
/// 500 ms, so this bounds the describe requests to one for each quiet run and one for
/// each queue every 10 s in each process.
const CACHE_TTL: Duration = Duration::from_secs(10);

/// The activity of one model call.
const MODEL_STEP_ACTIVITY: &str = "model_step";

/// The activity of one tool call.
const TOOL_CALL_ACTIVITY: &str = "tool_call";

/// What the steps of one run do now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StepState {
    /// A model step or a tool step runs on a worker.
    Working,
    /// A model step waits in its queue for a free model slot.
    QueuedModel,
    /// A tool step waits in its queue for a free tool slot, and no step runs.
    QueuedTool,
    /// No step runs or waits, or the describe read failed.
    Idle,
}

/// The step state of one workflow, from its describe response.
///
/// A started `model_step` or `tool_call` gives `Working`. Otherwise a scheduled
/// `model_step` gives `QueuedModel`, then a scheduled `tool_call` gives `QueuedTool`.
/// Other activities are not read.
pub fn step_state(describe: &serde_json::Value) -> StepState {
    let Some(activities) = describe["pendingActivities"].as_array() else {
        return StepState::Idle;
    };
    let steps: Vec<(&str, &serde_json::Value)> = activities
        .iter()
        .filter_map(|a| {
            let name = a["activityType"]["name"].as_str()?;
            (name == MODEL_STEP_ACTIVITY || name == TOOL_CALL_ACTIVITY).then_some((name, &a["state"]))
        })
        .collect();
    if steps.iter().any(|(_, state)| is_started(state)) {
        return StepState::Working;
    }
    if steps
        .iter()
        .any(|(name, state)| *name == MODEL_STEP_ACTIVITY && is_scheduled(state))
    {
        return StepState::QueuedModel;
    }
    if steps
        .iter()
        .any(|(name, state)| *name == TOOL_CALL_ACTIVITY && is_scheduled(state))
    {
        return StepState::QueuedTool;
    }
    StepState::Idle
}

/// Temporal writes an enum as its full name, its short name or its number, by version.
fn state_is(state: &serde_json::Value, full: &str, short: &str, number: u64) -> bool {
    match state {
        serde_json::Value::String(s) => s == full || s.eq_ignore_ascii_case(short),
        serde_json::Value::Number(n) => n.as_u64() == Some(number),
        _ => false,
    }
}

fn is_scheduled(state: &serde_json::Value) -> bool {
    state_is(state, "PENDING_ACTIVITY_STATE_SCHEDULED", "Scheduled", 1)
}

fn is_started(state: &serde_json::Value) -> bool {
    state_is(state, "PENDING_ACTIVITY_STATE_STARTED", "Started", 2)
}

/// The page's verdict on an open turn: `(active, queued, interrupted)`.
///
/// `advancing` means a row of the turn moved within the stall window, or a step of the
/// turn runs on a worker. `has_rows` means the turn wrote a row at all. `queued_step`
/// means a step of the turn waits for a slot on a queue that a worker polls.
pub fn turn_verdict(
    turn_open: bool,
    advancing: bool,
    plan_pending: bool,
    has_rows: bool,
    queued_step: bool,
) -> (bool, bool, bool) {
    let queued = turn_open && !plan_pending && queued_step;
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

type Cache<T> = Mutex<HashMap<String, (Instant, T)>>;

fn state_cache() -> &'static Cache<StepState> {
    static CACHE: OnceLock<Cache<StepState>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn poller_cache() -> &'static Cache<bool> {
    static CACHE: OnceLock<Cache<bool>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn cached<T: Copy>(cache: &Cache<T>, key: &str) -> Option<T> {
    let now = Instant::now();
    let mut entries = cache.lock().unwrap_or_else(|e| e.into_inner());
    entries.retain(|_, (at, _)| now.duration_since(*at) < CACHE_TTL);
    entries.get(key).map(|(_, value)| *value)
}

fn remember<T>(cache: &Cache<T>, key: &str, value: T) {
    cache
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .insert(key.to_string(), (Instant::now(), value));
}

/// GET one path of Temporal's HTTP API. An error, a timeout, a non-2xx status or a body
/// that is not JSON gives None. The request does not wait for Temporal's readiness,
/// because a page poll must not hold for it.
async fn get_json(path: &str) -> Option<serde_json::Value> {
    let url = format!("{}{path}", temporal_base_url());
    let response = match client().get(&url).send().await {
        Ok(response) if response.status().is_success() => response,
        Ok(response) => {
            tracing::debug!("GET {path}: {}", response.status());
            return None;
        }
        Err(e) => {
            tracing::debug!("GET {path}: {e}");
            return None;
        }
    };
    match response.json::<serde_json::Value>().await {
        Ok(body) => Some(body),
        Err(e) => {
            tracing::debug!("GET {path}: {e}");
            None
        }
    }
}

/// The step state of one workflow, kept [`CACHE_TTL`] for its id. A failed read is `Idle`.
pub async fn run_step_state(workflow_id: &str) -> StepState {
    if let Some(state) = cached(state_cache(), workflow_id) {
        return state;
    }
    let state = get_json(&format!("/api/v1/namespaces/default/workflows/{workflow_id}"))
        .await
        .map_or(StepState::Idle, |body| step_state(&body));
    remember(state_cache(), workflow_id, state);
    state
}

/// Whether a describe response of an activity task queue names a poller.
pub fn has_poller(describe: &serde_json::Value) -> bool {
    describe["pollers"]
        .as_array()
        .is_some_and(|pollers| !pollers.is_empty())
}

/// Whether a worker polls the activity task queue `task_queue`, from DescribeTaskQueue.
/// Kept [`CACHE_TTL`] for the queue. A failed read is false.
pub async fn queue_has_poller(task_queue: &str) -> bool {
    if let Some(answer) = cached(poller_cache(), task_queue) {
        return answer;
    }
    let answer = get_json(&format!(
        "/api/v1/namespaces/default/task-queues/{task_queue}?taskQueueType=TASK_QUEUE_TYPE_ACTIVITY"
    ))
    .await
    .is_some_and(|body| has_poller(&body));
    remember(poller_cache(), task_queue, answer);
    answer
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn describe(entries: &[(&str, serde_json::Value)]) -> serde_json::Value {
        let pending: Vec<_> = entries
            .iter()
            .enumerate()
            .map(|(i, (name, state))| {
                json!({"activityId": i.to_string(), "activityType": {"name": name}, "state": state})
            })
            .collect();
        json!({
            "workflowExecutionInfo": {"status": "WORKFLOW_EXECUTION_STATUS_RUNNING"},
            "pendingActivities": pending
        })
    }

    #[test]
    fn run_queue_started_model_step_is_working() {
        let d = describe(&[("model_step", json!("PENDING_ACTIVITY_STATE_STARTED"))]);
        assert_eq!(step_state(&d), StepState::Working);
        let d = describe(&[("model_step", json!("Started"))]);
        assert_eq!(step_state(&d), StepState::Working);
    }

    #[test]
    fn run_queue_scheduled_model_step_is_queued_model() {
        let d = describe(&[("model_step", json!("PENDING_ACTIVITY_STATE_SCHEDULED"))]);
        assert_eq!(step_state(&d), StepState::QueuedModel);
        let d = describe(&[("model_step", json!(1))]);
        assert_eq!(step_state(&d), StepState::QueuedModel);
    }

    #[test]
    fn run_queue_one_tool_started_one_scheduled_is_working() {
        let d = describe(&[("tool_call", json!(2)), ("tool_call", json!("Scheduled"))]);
        assert_eq!(step_state(&d), StepState::Working);
    }

    #[test]
    fn run_queue_all_tools_scheduled_is_queued_tool() {
        let d = describe(&[
            ("tool_call", json!("PENDING_ACTIVITY_STATE_SCHEDULED")),
            ("tool_call", json!("PENDING_ACTIVITY_STATE_SCHEDULED")),
        ]);
        assert_eq!(step_state(&d), StepState::QueuedTool);
    }

    #[test]
    fn run_queue_nothing_pending_is_idle() {
        assert_eq!(step_state(&json!({"pendingActivities": []})), StepState::Idle);
        assert_eq!(
            step_state(&json!({"workflowExecutionInfo": {"status": "WORKFLOW_EXECUTION_STATUS_RUNNING"}})),
            StepState::Idle
        );
    }

    #[test]
    fn run_queue_old_activity_name_is_idle() {
        let d = describe(&[("run_agent", json!("PENDING_ACTIVITY_STATE_SCHEDULED"))]);
        assert_eq!(step_state(&d), StepState::Idle);
        let d = describe(&[("open_run", json!(2))]);
        assert_eq!(step_state(&d), StepState::Idle);
    }

    #[test]
    fn run_queue_poller_list() {
        assert!(has_poller(&json!({"pollers": [{"identity": "27@worker"}]})));
        assert!(!has_poller(&json!({"pollers": []})));
        assert!(!has_poller(&json!({})));
    }

    #[test]
    fn run_queue_quiet_turn_with_a_queued_step_is_active_and_queued() {
        // turn_open, advancing, plan_pending, has_rows, queued_step
        assert_eq!(turn_verdict(true, false, false, true, true), (true, true, false));
        // Queued inside the stall window, after the quiet time.
        assert_eq!(turn_verdict(true, true, false, true, true), (true, true, false));
    }

    #[test]
    fn run_queue_stale_turn_without_a_queued_step_is_interrupted() {
        assert_eq!(turn_verdict(true, false, false, true, false), (false, false, true));
    }

    #[test]
    fn run_queue_fresh_turn_is_active_and_not_queued() {
        assert_eq!(turn_verdict(true, true, false, true, false), (true, false, false));
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
