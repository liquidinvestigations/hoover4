//! Sliding-window rate limiting, in-process.
//!
//! Two limiters share one implementation: chat messages
//! ([`RateLimitKind::ChatMessage`], called by the chat API) and API calls
//! ([`RateLimitKind::ApiCall`], enforced by the session middleware on
//! authenticated server-function requests).
//!
//! **The window ladder.** One per-minute number `X`
//! (`HOOVER4_RATE_{CHAT,API}_PER_MINUTE`) drives everything; longer windows
//! enforce a decaying sustained rate, so a burst is fine and sustained abuse is
//! not. A request is allowed only if *every* window still has budget:
//!
//! | window | budget in window        | env factor (default)   |
//! |--------|-------------------------|------------------------|
//! | 1 min  | `X`                     | — (the base rate)      |
//! | 10 min | `10X`                   | `…_W10M_FACTOR` (1.00) |
//! | 30 min | `22.5X`                 | `…_W30M_FACTOR` (0.75) |
//! | 1 h    | `30X`                   | `…_W1H_FACTOR`  (0.50) |
//! | 6 h    | `108X`                  | `…_W6H_FACTOR`  (0.30) |
//! | 24 h   | `288X`                  | `…_W24H_FACTOR` (0.20) |
//!
//! A factor of `0` disables that window. Defaults: chat `X = 40` (~10x the
//! fastest substantive chat turn measured on the dev GPU, 16.2 s), API
//! `X = 1000` (~10x a fast sweep of every route, on the order of 100 calls —
//! see `main_services/ops/Readme.md` for the measured numbers).
//!
//! **Why in-process and not Redis.** The counters follow the
//! `PERM_CACHE`/`SYNC_CACHE` idiom from `session_middleware.rs`: a
//! `Mutex<HashMap<String, VecDeque<Instant>>>`, pruned on access. Redis is
//! running and would be the textbook choice, but the website has no Redis
//! dependency today and the container is started with
//! `--maxmemory-policy allkeys-lru`, so it would silently evict rate-limit
//! counters under memory pressure — a limiter that quietly stops limiting is
//! worse than none. The in-process design is correct only while the website is
//! a single container; scaling it out needs a shared store, and that is the
//! point at which Redis gets its own database index and eviction policy.
//!
//! **Failure mode: fail open.** If the limiter itself errors (poisoned mutex,
//! a clock surprise), it logs and *allows* the request. A rate limiter that
//! starts refusing every request because of an internal bug takes the site
//! down; one that briefly stops limiting does not.

use std::collections::{HashMap, VecDeque};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

/// Which limiter a call is subject to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RateLimitKind {
    ChatMessage,
    /// Long-poll reads of an in-flight chat turn. Cheap queries, but each request can
    /// be HELD for up to 15 s, so the budget is about concurrency as much as rate.
    ChatPoll,
    ApiCall,
}

/// Refusal details: how long to wait, and which window produced the refusal
/// (for logs and the admin page).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RateLimitError {
    pub retry_after_seconds: u64,
    pub window: &'static str,
}

impl std::fmt::Display for RateLimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "rate limit exceeded ({} window), retry after {} s",
            self.window, self.retry_after_seconds
        )
    }
}

impl std::error::Error for RateLimitError {}

struct Window {
    name: &'static str,
    duration: Duration,
    /// Env suffix for the factor, e.g. `W30M_FACTOR`; empty for the base window.
    env_suffix: &'static str,
    default_factor: f64,
}

const WINDOWS: &[Window] = &[
    Window { name: "1min", duration: Duration::from_secs(60), env_suffix: "", default_factor: 1.0 },
    Window { name: "10min", duration: Duration::from_secs(600), env_suffix: "W10M_FACTOR", default_factor: 1.0 },
    Window { name: "30min", duration: Duration::from_secs(1800), env_suffix: "W30M_FACTOR", default_factor: 0.75 },
    Window { name: "1h", duration: Duration::from_secs(3600), env_suffix: "W1H_FACTOR", default_factor: 0.5 },
    Window { name: "6h", duration: Duration::from_secs(6 * 3600), env_suffix: "W6H_FACTOR", default_factor: 0.3 },
    Window { name: "24h", duration: Duration::from_secs(24 * 3600), env_suffix: "W24H_FACTOR", default_factor: 0.2 },
];

struct LimiterConfig {
    per_minute: u64,
    /// Resolved factors, same order as [`WINDOWS`].
    factors: Vec<f64>,
}

fn env_f64(name: &str, default: f64) -> f64 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.trim().parse::<f64>().ok())
        .filter(|v| v.is_finite() && *v >= 0.0)
        .unwrap_or(default)
}

fn env_u64(name: &str, default: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.trim().parse::<u64>().ok())
        .unwrap_or(default)
}

fn load_config(kind: RateLimitKind) -> LimiterConfig {
    let (base, default_x) = match kind {
        RateLimitKind::ChatMessage => ("HOOVER4_RATE_CHAT", 40),
        RateLimitKind::ChatPoll => ("HOOVER4_RATE_CHAT_POLL", 240),
        RateLimitKind::ApiCall => ("HOOVER4_RATE_API", 1000),
    };
    LimiterConfig {
        per_minute: env_u64(&format!("{base}_PER_MINUTE"), default_x),
        factors: WINDOWS
            .iter()
            .map(|w| {
                if w.env_suffix.is_empty() {
                    w.default_factor
                } else {
                    env_f64(&format!("{base}_{}", w.env_suffix), w.default_factor)
                }
            })
            .collect(),
    }
}

static CHAT_CONFIG: LazyLock<LimiterConfig> = LazyLock::new(|| load_config(RateLimitKind::ChatMessage));
static CHAT_POLL_CONFIG: LazyLock<LimiterConfig> = LazyLock::new(|| load_config(RateLimitKind::ChatPoll));
static API_CONFIG: LazyLock<LimiterConfig> = LazyLock::new(|| load_config(RateLimitKind::ApiCall));

static CHAT_COUNTERS: LazyLock<Mutex<HashMap<String, VecDeque<Instant>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));
static CHAT_POLL_COUNTERS: LazyLock<Mutex<HashMap<String, VecDeque<Instant>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));
static API_COUNTERS: LazyLock<Mutex<HashMap<String, VecDeque<Instant>>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// Hard cap on stored timestamps per user: the largest window's budget at the
/// default rate is ~288X events; anything beyond that is a bug or an attack on
/// the limiter itself, and pruning it costs nothing but precision.
const MAX_TRACKED_EVENTS: usize = 400_000;

const MAX_WINDOW: Duration = Duration::from_secs(24 * 3600);

fn config_for(kind: RateLimitKind) -> &'static LimiterConfig {
    match kind {
        RateLimitKind::ChatMessage => &CHAT_CONFIG,
        RateLimitKind::ChatPoll => &CHAT_POLL_CONFIG,
        RateLimitKind::ApiCall => &API_CONFIG,
    }
}

fn counters_for(kind: RateLimitKind) -> &'static Mutex<HashMap<String, VecDeque<Instant>>> {
    match kind {
        RateLimitKind::ChatMessage => &CHAT_COUNTERS,
        RateLimitKind::ChatPoll => &CHAT_POLL_COUNTERS,
        RateLimitKind::ApiCall => &API_COUNTERS,
    }
}

/// Window budget: `X * window_minutes * factor`, floored. The 1-minute window
/// is exactly `X`.
fn budget(per_minute: u64, window: &Window, factor: f64) -> u64 {
    if factor <= 0.0 {
        return 0;
    }
    let minutes = window.duration.as_secs() as f64 / 60.0;
    (per_minute as f64 * minutes * factor).floor() as u64
}

/// Check the windows and, if all have budget, record one event for `username`.
///
/// Fails open: an internal error is logged and the call returns `Ok(())`.
pub fn check_and_record(username: &str, kind: RateLimitKind) -> Result<(), RateLimitError> {
    fail_open(
        try_check_and_record(counters_for(kind), config_for(kind), username),
        username,
    )
}

/// The fail-open rule, separated so it is testable: an internal error is
/// logged and the request is allowed.
fn fail_open(
    result: anyhow::Result<Result<(), RateLimitError>>,
    username: &str,
) -> Result<(), RateLimitError> {
    match result {
        Ok(r) => r,
        Err(e) => {
            tracing::error!("rate limiter internal error for {username} (failing open): {e}");
            Ok(())
        }
    }
}

fn try_check_and_record(
    counters: &Mutex<HashMap<String, VecDeque<Instant>>>,
    config: &LimiterConfig,
    username: &str,
) -> anyhow::Result<Result<(), RateLimitError>> {
    let mut counters = counters
        .lock()
        .map_err(|e| anyhow::anyhow!("counter mutex poisoned: {e}"))?;

    let now = Instant::now();
    let events = counters.entry(username.to_string()).or_default();

    // Prune events older than the longest window (and bound the map: a user
    // idle for 24h has an empty deque and can be forgotten on the next pass).
    while events
        .front()
        .is_some_and(|t| now.duration_since(*t) >= MAX_WINDOW)
    {
        events.pop_front();
    }

    // Every enabled window must still have budget. On refusal, report the
    // smallest wait across the failing windows.
    let mut refusal: Option<RateLimitError> = None;
    for (window, &factor) in WINDOWS.iter().zip(config.factors.iter()) {
        if factor <= 0.0 {
            continue; // window disabled
        }
        let budget = budget(config.per_minute, window, factor);
        let in_window = events
            .iter()
            .rev()
            .take_while(|t| now.duration_since(**t) < window.duration)
            .count() as u64;
        if in_window >= budget {
            // Wait until the oldest event inside this window ages out of it.
            let oldest_in_window = events
                .iter()
                .rev()
                .take_while(|t| now.duration_since(**t) < window.duration)
                .last()
                .copied();
            let retry_after = oldest_in_window
                .map(|t| {
                    window
                        .duration
                        .saturating_sub(now.duration_since(t))
                        .as_secs()
                        .max(1)
                })
                .unwrap_or(1);
            let candidate = RateLimitError {
                retry_after_seconds: retry_after,
                window: window.name,
            };
            refusal = match refusal {
                Some(r) if r.retry_after_seconds <= candidate.retry_after_seconds => Some(r),
                _ => Some(candidate),
            };
        }
    }

    if let Some(r) = refusal {
        return Ok(Err(r));
    }

    if events.len() >= MAX_TRACKED_EVENTS {
        // Bound memory without failing the request: drop the oldest half.
        let drop = events.len() / 2;
        events.drain(..drop);
    }
    events.push_back(now);
    Ok(Ok(()))
}

/// Current usage of `username` against each window, for the admin UI:
/// `(window name, events in window, budget)`.
pub fn window_usage(username: &str, kind: RateLimitKind) -> Vec<(&'static str, u64, u64)> {
    let config = config_for(kind);
    let now = Instant::now();
    let snapshot: Vec<Instant> = match counters_for(kind).lock() {
        Ok(counters) => counters.get(username).map(|e| e.iter().copied().collect()).unwrap_or_default(),
        Err(_) => return Vec::new(),
    };
    WINDOWS
        .iter()
        .zip(config.factors.iter())
        .filter(|(_, factor)| **factor > 0.0)
        .map(|(window, &factor)| {
            let in_window = snapshot
                .iter()
                .rev()
                .take_while(|t| now.duration_since(**t) < window.duration)
                .count() as u64;
            (window.name, in_window, budget(config.per_minute, window, factor))
        })
        .collect()
}

/// The configured per-minute rate, for display.
pub fn per_minute_limit(kind: RateLimitKind) -> u64 {
    config_for(kind).per_minute
}

#[cfg(test)]
mod tests {
    use super::*;

    fn events_at(now: Instant, ages_seconds: &[u64]) -> VecDeque<Instant> {
        ages_seconds
            .iter()
            .map(|age| now.checked_sub(Duration::from_secs(*age)).unwrap_or(now))
            .collect()
    }

    fn test_window(secs: u64, name: &'static str) -> Window {
        Window {
            name,
            duration: Duration::from_secs(secs),
            env_suffix: "",
            default_factor: 1.0,
        }
    }

    #[test]
    fn budget_ladder() {
        assert_eq!(budget(40, &test_window(60, "1min"), 1.0), 40);
        assert_eq!(budget(40, &test_window(600, "10min"), 1.0), 400);
        assert_eq!(budget(40, &test_window(1800, "30min"), 0.75), 900);
        assert_eq!(budget(40, &test_window(3600, "1h"), 0.5), 1200);
        assert_eq!(budget(40, &test_window(6 * 3600, "6h"), 0.3), 4320);
        assert_eq!(budget(40, &test_window(24 * 3600, "24h"), 0.2), 11520);
        assert_eq!(budget(40, &test_window(1800, "30min"), 0.0), 0);
    }

    /// The case a naive single-window implementation gets wrong: no single
    /// minute exceeds X, but the sustained rate beats the 30-minute decay.
    #[test]
    fn sustained_rate_is_refused_by_the_longer_window() {
        let username = format!("test-sustained-{}", std::process::id());
        let config = &*CHAT_CONFIG;
        let window_30m = &WINDOWS[2];
        let budget_30m = budget(config.per_minute, window_30m, config.factors[2]);

        // Fill the 30-minute window to exactly its budget, spread out so no
        // single minute is over X.
        let mut counters = CHAT_COUNTERS.lock().unwrap_or_else(|e| e.into_inner());
        let now = Instant::now();
        let spread: Vec<u64> = (0..budget_30m)
            .map(|i| 60 + (i * 1740 / budget_30m.max(1)))
            .collect();
        counters.insert(username.clone(), events_at(now, &spread));
        drop(counters);

        let err = check_and_record(&username, RateLimitKind::ChatMessage)
            .expect_err("sustained rate above 0.75X must be refused");
        assert_eq!(err.window, "30min");
        assert!(err.retry_after_seconds >= 1);

        // Cleanup so other tests are unaffected.
        CHAT_COUNTERS
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(&username);
    }

    #[test]
    fn burst_within_budget_is_allowed() {
        let username = format!("test-burst-{}", std::process::id());
        for _ in 0..5 {
            check_and_record(&username, RateLimitKind::ChatMessage)
                .expect("a small burst must be allowed");
        }
        let usage = window_usage(&username, RateLimitKind::ChatMessage);
        assert_eq!(usage.first().map(|w| w.1), Some(5));
        CHAT_COUNTERS
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .remove(&username);
    }

    /// Poison a mutex deliberately: the limiter must fail open, not refuse.
    /// Done on a local mutex so no shared test state is poisoned.
    #[test]
    fn poisoned_mutex_fails_open() {
        let counters: Mutex<HashMap<String, VecDeque<Instant>>> = Mutex::new(HashMap::new());
        let _ = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = counters.lock().unwrap_or_else(|e| e.into_inner());
            panic!("deliberate poison");
        }));
        assert!(counters.is_poisoned());

        let result = try_check_and_record(&counters, &CHAT_CONFIG, "someone");
        assert!(result.is_err(), "the internal error must surface");
        assert_eq!(
            fail_open(result, "someone"),
            Ok(()),
            "a poisoned limiter must fail open"
        );
    }
}
