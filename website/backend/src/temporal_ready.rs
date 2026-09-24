//! Wait until Temporal and its database are ready before a workflow starts.
//!
//! A start that reaches Temporal while its Cassandra store restarts fails with
//! `shard status unknown`. Each website route that starts a workflow therefore calls
//! [`wait_for_temporal`] before its start request.
//!
//! One monitor task probes Temporal's HTTP API every second. One probe is four
//! requests, in this order, each with a timeout of `PROBE_TIMEOUT_SECONDS`:
//!
//! 1. `GET /api/v1/system-info`;
//! 2. `GET /api/v1/namespaces/default`, which reads Cassandra;
//! 3. `GET /api/v1/namespaces/default/workflows?pageSize=1`;
//! 4. `GET /api/v1/namespaces/default/workflows/collect-eta-samples`, which reads a
//!    history shard. A 404 counts as good only when its `details` hold a
//!    `NotFoundFailure`, which is the answer for an absent workflow. The 404 of an unknown
//!    route has no details, and it resets the good run.
//!
//! The monitor keeps the time of the first good probe of the current good run.
//! [`wait_for_temporal`] returns at once when that run is `READY_STABLE_SECONDS` old or
//! more. Otherwise it waits for it, up to `READY_DEADLINE_SECONDS` from its call, and then
//! returns `READY_ERROR_TEXT` with the monitor's last error.
//!
//! The constants and the error text are mirrored in
//! `main_services/processing/tasks/temporal_readiness.py`. Change both files together. A
//! unit test in each runtime reads the other file and compares the values.

use std::sync::OnceLock;
use std::time::Duration;

use tokio::sync::watch;
use tokio::time::Instant;

// Mirrored in main_services/processing/tasks/temporal_readiness.py.
pub const READY_STABLE_SECONDS: u64 = 5;
pub const READY_DEADLINE_SECONDS: u64 = 60;
pub const PROBE_INTERVAL_SECONDS: u64 = 1;
pub const PROBE_TIMEOUT_SECONDS: u64 = 5;
pub const COLLECTOR_WORKFLOW_ID: &str = "collect-eta-samples";
pub const READY_ERROR_TEXT: &str = "Temporal did not stay ready for 5 s within 60 s, so the workflow was not started. Last error: {last_error}";

/// The limit on each start request to Temporal's HTTP API. With the 60 s gate, a
/// website start takes at most 90 s, which is below the 600 s a `pending` operation row
/// gets before the sweep marks it `errored`.
pub const START_REQUEST_TIMEOUT_SECONDS: u64 = 30;

/// A good run counts only while its last good probe is this recent. A probe whose four
/// requests all wait for their timeout takes 20 s, and the run it extends must not
/// count as ready during that time.
const FRESH_SECONDS: u64 = PROBE_INTERVAL_SECONDS + PROBE_TIMEOUT_SECONDS;

/// The base URL of Temporal's HTTP API.
pub fn temporal_base_url() -> String {
    std::env::var("TEMPORAL_HTTP_URL").unwrap_or_else(|_| "http://localhost:21908".to_string())
}

/// The one HTTP client for workflow start requests, with the start timeout.
pub fn start_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(Duration::from_secs(START_REQUEST_TIMEOUT_SECONDS))
            .build()
            .expect("the start request client builds from constant settings")
    })
}

#[derive(Clone, Debug)]
struct Snapshot {
    good_since: Option<Instant>,
    last_good: Option<Instant>,
    last_error: String,
}

/// The readiness state that the monitor writes and the gate reads.
pub struct Readiness {
    state: watch::Sender<Snapshot>,
}

impl Default for Readiness {
    fn default() -> Self {
        Self::new()
    }
}

impl Readiness {
    pub fn new() -> Self {
        let (state, _) = watch::channel(Snapshot {
            good_since: None,
            last_good: None,
            last_error: "no probe finished".to_string(),
        });
        Self { state }
    }

    /// Record the result of one probe that finished at `now`.
    pub fn record(&self, now: Instant, result: Result<(), String>) {
        self.state.send_modify(|snapshot| match result {
            Ok(()) => {
                if snapshot.good_since.is_none() {
                    snapshot.good_since = Some(now);
                }
                snapshot.last_good = Some(now);
            }
            Err(error) => {
                snapshot.good_since = None;
                snapshot.last_good = None;
                snapshot.last_error = error;
            }
        });
    }

    /// Return when the good run is 5 s old, or the error text after 60 s.
    pub async fn wait(&self) -> anyhow::Result<()> {
        let stable = Duration::from_secs(READY_STABLE_SECONDS);
        let fresh = Duration::from_secs(FRESH_SECONDS);
        let deadline = Instant::now() + Duration::from_secs(READY_DEADLINE_SECONDS);
        let mut changes = self.state.subscribe();
        loop {
            let snapshot = changes.borrow_and_update().clone();
            let now = Instant::now();
            let is_fresh = snapshot
                .last_good
                .is_some_and(|last| now.saturating_duration_since(last) <= fresh);
            let ready_at = snapshot.good_since.filter(|_| is_fresh).map(|since| since + stable);
            if ready_at.is_some_and(|at| now >= at) {
                return Ok(());
            }
            if now >= deadline {
                anyhow::bail!(READY_ERROR_TEXT.replace("{last_error}", &snapshot.last_error));
            }
            let wake = ready_at.map_or(deadline, |at| at.min(deadline));
            tokio::select! {
                _ = changes.changed() => {}
                _ = tokio::time::sleep_until(wake) => {}
            }
        }
    }
}

async fn probe_get(http: &reqwest::Client, url: &str) -> Result<reqwest::Response, String> {
    http.get(url).send().await.map_err(|e| format!("GET {url}: {e}"))
}

fn has_not_found_failure(body: &serde_json::Value) -> bool {
    body.get("details")
        .and_then(serde_json::Value::as_array)
        .is_some_and(|details| {
            details.iter().any(|detail| {
                detail
                    .get("@type")
                    .and_then(serde_json::Value::as_str)
                    .is_some_and(|kind| kind.ends_with(".NotFoundFailure"))
            })
        })
}

/// Run the four probe requests in order. Return the first failure as text.
pub async fn probe(http: &reqwest::Client, base_url: &str) -> Result<(), String> {
    for path in [
        "/api/v1/system-info",
        "/api/v1/namespaces/default",
        "/api/v1/namespaces/default/workflows?pageSize=1",
    ] {
        let url = format!("{base_url}{path}");
        let response = probe_get(http, &url).await?;
        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(format!("GET {url}: {status}: {body}"));
        }
    }
    let url = format!("{base_url}/api/v1/namespaces/default/workflows/{COLLECTOR_WORKFLOW_ID}");
    let response = probe_get(http, &url).await?;
    let status = response.status();
    if status.is_success() {
        return Ok(());
    }
    let body = response.text().await.unwrap_or_default();
    if status == reqwest::StatusCode::NOT_FOUND
        && serde_json::from_str::<serde_json::Value>(&body).is_ok_and(|b| has_not_found_failure(&b))
    {
        return Ok(());
    }
    Err(format!("GET {url}: {status}: {body}"))
}

/// Probe `base_url` every second and record each result, for as long as the task runs.
pub async fn run_monitor(readiness: &Readiness, base_url: String) {
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(PROBE_TIMEOUT_SECONDS))
        .build()
        .expect("the probe client builds from constant settings");
    let mut ticks = tokio::time::interval(Duration::from_secs(PROBE_INTERVAL_SECONDS));
    ticks.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    loop {
        ticks.tick().await;
        let result = probe(&http, &base_url).await;
        readiness.record(Instant::now(), result);
    }
}

fn readiness() -> &'static Readiness {
    static READINESS: OnceLock<Readiness> = OnceLock::new();
    READINESS.get_or_init(Readiness::new)
}

/// Start the monitor task once. The website calls it at boot, and the gate calls it
/// again in case the boot call did not run.
pub fn start_monitor() {
    static STARTED: OnceLock<()> = OnceLock::new();
    STARTED.get_or_init(|| {
        tokio::spawn(run_monitor(readiness(), temporal_base_url()));
    });
}

/// Return when Temporal has been ready for 5 s. Return the error text after 60 s.
pub async fn wait_for_temporal() -> anyhow::Result<()> {
    start_monitor();
    readiness().wait().await
}

#[cfg(test)]
mod tests {
    use super::*;

    fn secs(n: u64) -> Duration {
        Duration::from_secs(n)
    }

    /// Advance the paused clock one probe interval at a time, recording `result(t)`.
    async fn feed(readiness: &Readiness, from: u64, to: u64, result: impl Fn(u64) -> Result<(), String>) {
        for t in from..to {
            readiness.record(Instant::now(), result(t));
            tokio::time::advance(secs(PROBE_INTERVAL_SECONDS)).await;
        }
    }

    #[tokio::test(start_paused = true)]
    async fn temporal_ready_after_five_seconds_of_good_probes() {
        let readiness = std::sync::Arc::new(Readiness::new());
        let start = Instant::now();
        let waiter = tokio::spawn({
            let readiness = readiness.clone();
            async move { readiness.wait().await }
        });
        feed(&readiness, 0, 6, |_| Ok(())).await;
        waiter.await.unwrap().unwrap();
        assert!(Instant::now() - start <= secs(6));
    }

    #[tokio::test(start_paused = true)]
    async fn temporal_ready_resets_on_a_bad_probe() {
        let readiness = Readiness::new();
        let start = Instant::now();
        // Good at 0 to 4 s, bad at 5 s, good from 6 s: the new run is 5 s old at 11 s.
        feed(&readiness, 0, 6, |t| if t == 5 { Err("bad".into()) } else { Ok(()) }).await;
        let at_six = tokio::time::timeout(secs(0), readiness.wait()).await;
        assert!(at_six.is_err(), "the run that the bad probe ended must not count");
        feed(&readiness, 6, 11, |_| Ok(())).await;
        readiness.record(Instant::now(), Ok(()));
        tokio::time::timeout(secs(0), readiness.wait()).await.unwrap().unwrap();
        assert_eq!(Instant::now() - start, secs(11));
    }

    #[tokio::test(start_paused = true)]
    async fn temporal_ready_deadline_returns_the_text_and_the_last_error() {
        let readiness = std::sync::Arc::new(Readiness::new());
        let start = Instant::now();
        let waiter = tokio::spawn({
            let readiness = readiness.clone();
            async move { readiness.wait().await }
        });
        feed(&readiness, 0, 61, |_| Err("shard status unknown".into())).await;
        let error = waiter.await.unwrap().unwrap_err().to_string();
        assert_eq!(
            error,
            "Temporal did not stay ready for 5 s within 60 s, so the workflow was not \
             started. Last error: shard status unknown"
        );
        assert!(Instant::now() - start >= secs(READY_DEADLINE_SECONDS));
    }

    #[tokio::test(start_paused = true)]
    async fn temporal_ready_monitor_run_six_seconds_old_returns_at_once() {
        let readiness = Readiness::new();
        feed(&readiness, 0, 7, |_| Ok(())).await;
        readiness.record(Instant::now(), Ok(()));
        tokio::time::timeout(secs(0), readiness.wait()).await.unwrap().unwrap();
    }

    #[tokio::test(start_paused = true)]
    async fn temporal_ready_stale_run_does_not_count() {
        let readiness = Readiness::new();
        feed(&readiness, 0, 7, |_| Ok(())).await;
        // No probe finishes for longer than one probe interval plus its timeout.
        tokio::time::advance(secs(FRESH_SECONDS + 1)).await;
        assert!(tokio::time::timeout(secs(0), readiness.wait()).await.is_err());
    }

    /// A stand-in for Temporal's HTTP API. `collector` answers the collector describe.
    async fn stand_in(collector: (u16, serde_json::Value)) -> (String, tokio::task::JoinHandle<()>) {
        use axum::{http::StatusCode, routing::get, Json, Router};
        let ok = || async { (StatusCode::OK, Json(serde_json::json!({}))) };
        let (code, body) = collector;
        let app = Router::new()
            .route("/api/v1/system-info", get(ok))
            .route("/api/v1/namespaces/default", get(ok))
            .route("/api/v1/namespaces/default/workflows", get(ok))
            .route(
                "/api/v1/namespaces/default/workflows/collect-eta-samples",
                get(move || {
                    let body = body.clone();
                    async move { (StatusCode::from_u16(code).unwrap(), Json(body)) }
                }),
            );
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        (format!("http://{address}"), server)
    }

    #[tokio::test]
    async fn temporal_ready_absent_collector_counts_as_good() {
        let (url, server) = stand_in((
            404,
            serde_json::json!({
                "code": 5,
                "message": "operation GetCurrentExecution encountered not found",
                "details": [{
                    "@type": "type.googleapis.com/temporal.api.errordetails.v1.NotFoundFailure"
                }],
            }),
        ))
        .await;
        assert_eq!(probe(&reqwest::Client::new(), &url).await, Ok(()));
        server.abort();
    }

    #[tokio::test]
    async fn temporal_ready_unknown_route_resets_the_good_run() {
        let (url, server) =
            stand_in((404, serde_json::json!({"code": 5, "message": "Not Found"}))).await;
        let result = probe(&reqwest::Client::new(), &url).await;
        assert!(result.is_err());
        let readiness = Readiness::new();
        readiness.record(Instant::now(), Ok(()));
        readiness.record(Instant::now(), result);
        assert!(readiness.state.borrow().good_since.is_none());
        server.abort();
    }

    #[tokio::test]
    async fn temporal_ready_other_describe_error_resets_the_good_run() {
        let (url, server) = stand_in((
            503,
            serde_json::json!({"code": 14, "message": "shard status unknown"}),
        ))
        .await;
        let result = probe(&reqwest::Client::new(), &url).await;
        assert!(result.as_ref().is_err_and(|e| e.contains("shard status unknown")));
        server.abort();
    }

    /// The Python copy of the constants. Reachable from a checkout of the whole
    /// repository. The website container mounts only `website/`, so the test reads the
    /// file named by `HOOVER4_TEMPORAL_READINESS_PY` when it is set, and skips otherwise.
    fn python_gate_source() -> Option<String> {
        if let Ok(path) = std::env::var("HOOVER4_TEMPORAL_READINESS_PY") {
            return std::fs::read_to_string(path).ok();
        }
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../main_services/processing/tasks/temporal_readiness.py");
        std::fs::read_to_string(path).ok()
    }

    /// The value of `NAME = value` in the Python file, with a parenthesised run of
    /// string literals joined into one string.
    fn python_value(source: &str, name: &str) -> String {
        let start = source
            .find(&format!("\n{name} = "))
            .unwrap_or_else(|| panic!("{name} not found in temporal_readiness.py"))
            + name.len()
            + 4;
        let rest = &source[start..];
        if let Some(block) = rest.strip_prefix('(') {
            let block = &block[..block.find("\n)").expect("closing bracket")];
            block
                .split('"')
                .enumerate()
                .filter(|(i, _)| i % 2 == 1)
                .map(|(_, part)| part)
                .collect()
        } else {
            rest.lines().next().unwrap().trim().trim_matches('"').to_string()
        }
    }

    #[test]
    fn temporal_ready_constants_match_the_python_gate() {
        let Some(source) = python_gate_source() else {
            eprintln!("skipping: temporal_readiness.py is not mounted here");
            return;
        };
        let numbers = [
            ("READY_STABLE_SECONDS", READY_STABLE_SECONDS),
            ("READY_DEADLINE_SECONDS", READY_DEADLINE_SECONDS),
            ("PROBE_INTERVAL_SECONDS", PROBE_INTERVAL_SECONDS),
            ("PROBE_TIMEOUT_SECONDS", PROBE_TIMEOUT_SECONDS),
        ];
        for (name, value) in numbers {
            assert_eq!(python_value(&source, name), value.to_string(), "{name}");
        }
        assert_eq!(python_value(&source, "COLLECTOR_WORKFLOW_ID"), COLLECTOR_WORKFLOW_ID);
        assert_eq!(python_value(&source, "READY_ERROR_TEXT"), READY_ERROR_TEXT);
    }
}
