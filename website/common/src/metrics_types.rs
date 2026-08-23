//! DTOs for the admin metrics pages, shared between frontend and backend.
//!
//! Data source: the rolling 24h `usage_events` / `api_events` tables (global
//! database, migrations `00014`/`00015`). Both are privacy-bounded by design:
//! who, which route class or function name, when, and for the API table how
//! long and how big. Never a URL, never a query string.

/// Count of events of one type over the last 24 h.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct UsageEventCount {
    pub event_type: String,
    pub count: u64,
}

/// Count of events for one user over the last 24 h.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct UserEventCount {
    pub username: String,
    pub count: u64,
}

/// One bucket of the hourly time series. `bucket` is an RFC 3339 timestamp.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct UsageTimePoint {
    pub bucket: String,
    pub count: u64,
}

/// The `usage_events` view: the six event counters, busiest users, and an
/// hourly series, all over the last 24 h.
#[derive(Debug, Clone, PartialEq, Default, serde::Serialize, serde::Deserialize)]
pub struct UsageMetrics {
    pub per_event_type: Vec<UsageEventCount>,
    pub per_user: Vec<UserEventCount>,
    pub series: Vec<UsageTimePoint>,
}

/// Aggregates for one handler / server-function name over the last 24 h.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ApiFunctionStats {
    pub function_name: String,
    pub calls: u64,
    pub errors: u64,
    /// `errors / calls`, 0 when there are no calls.
    pub error_rate: f64,
    pub p50_ms: u32,
    pub p95_ms: u32,
    pub max_ms: u32,
    pub bytes_in: u64,
    pub bytes_out: u64,
}

/// Everything the `/admin/metrics` page shows.
#[derive(Debug, Clone, PartialEq, Default, serde::Serialize, serde::Deserialize)]
pub struct AdminMetrics {
    pub usage: UsageMetrics,
    pub api: Vec<ApiFunctionStats>,
}

/// One chat session of the user, with its message and tool-call counts.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct UserLlmSession {
    pub session_id: String,
    pub title: String,
    pub created_at: String,
    pub message_count: u64,
    pub tool_calls: u64,
    /// Wall time the agent spent on this session. The GPU cost of it.
    pub agent_duration_ms: u64,
}

/// Usage of one rate-limit window: how many events the user has in it, and the
/// budget. Shown next to the LLM cost so an admin can see who is near a limit.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct RateWindowUsage {
    pub window: String,
    pub used: u64,
    pub budget: u64,
}

/// Everything the `/admin/users/:username/llm` page shows.
#[derive(Debug, Clone, PartialEq, Default, serde::Serialize, serde::Deserialize)]
pub struct AdminUserLlmMetrics {
    pub username: String,
    pub chat_messages: u64,
    pub tool_calls: u64,
    /// Summed `agent_duration_ms` over all sessions: how much agent (GPU) time
    /// this person consumed. What the chat rate limit exists to bound.
    pub agent_duration_ms_total: u64,
    pub sessions: Vec<UserLlmSession>,
    pub chat_limit: Vec<RateWindowUsage>,
    pub api_limit: Vec<RateWindowUsage>,
    /// The configured per-minute limits, for display next to the usage.
    pub chat_per_minute: u64,
    pub api_per_minute: u64,
}
