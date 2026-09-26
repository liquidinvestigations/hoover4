//! LLM catalog / AI-status DTOs shared between frontend and backend.

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct LlmModelItem {
    pub provider: String,
    pub model_id: String,
    pub display_name: String,
    pub context_window: u32,
    pub price_in_milli: u32,
    pub price_out_milli: u32,
    pub supports_tools: bool,
    pub supports_vision: bool,
    pub is_reasoning: bool,
    pub is_allowed: bool,
    /// RFC3339; empty when never confirmed.
    pub fetched_at: String,
    /// Median latency over the last 14 days of `llm_call_events`, 0 when none.
    pub median_latency_ms: u32,
    pub call_count_14d: u64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct LlmProviderHealth {
    pub provider: String,
    pub ok: bool,
    pub model_count: u32,
    pub freshest_fetched_at: String,
    pub stale: bool,
    pub error: String,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminLlmPage {
    pub providers: Vec<LlmProviderHealth>,
    pub models: Vec<LlmModelItem>,
    pub default_chat_model: String,
    pub summarization_model: String,
    /// The model each agent profile runs on, keyed by the profile's setting key. A
    /// profile absent from this map, or present with an empty value, runs on
    /// `default_chat_model`. Unset means "use the default", so a deployment that never
    /// touches these keys behaves exactly as it did before they existed.
    #[serde(default)]
    pub profile_models: std::collections::BTreeMap<String, String>,
    /// True when a catalog refresh is currently running in-process.
    pub refresh_in_flight: bool,
    /// True when `LLM_BASE_URL` is unset. Chat is disabled.
    pub llm_configured: bool,
    /// The thinking switch, `server_settings.llm_thinking`. True when the row is absent.
    #[serde(default = "default_true")]
    pub thinking: bool,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AiCapabilityStatus {
    pub name: String,
    pub configured_provider: String,
    pub serving_provider: String,
    pub serving_model: String,
    pub reachable: bool,
    pub detail: String,
    /// Circuit open remaining seconds.
    ///
    /// **Always 0 today, read it as "n/a", not as "closed".** The breakers live in the
    /// worker (`tasks/remote.py`) and in each MCP server's own process
    /// (`agent_common/rerank.py`); the website has no channel to any of them, so nothing
    /// can fill this in. It is not rendered for that reason. Wiring it up means exposing
    /// breaker state on those services' `/health` and aggregating here, until then, a
    /// zero here says nothing about whether a circuit is open.
    pub circuit_open_remaining_s: u32,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AiShardDimCheck {
    pub collection: String,
    pub table: String,
    pub knn_dims: u32,
    pub matches_probe: bool,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AiTrafficRow {
    pub username: String,
    pub calls: u64,
    pub errors: u64,
    pub median_latency_ms: u32,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AiServiceUse {
    pub service: String,
    pub calls_24h: u64,
    pub errors_24h: u64,
    pub busy_seconds_24h: f64,
    /// Rough use%: busy_seconds / (24h), capped at 100.
    pub use_pct: f64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminAiStatus {
    pub capabilities: Vec<AiCapabilityStatus>,
    pub embeddings_serving_model: String,
    pub embeddings_serving_dim: u32,
    pub fingerprint_local: String,
    pub fingerprint_ai_server: String,
    pub fingerprint_match: bool,
    /// Did the GPU AI server answer its `/health` at all?
    ///
    /// Separates the two reasons the AI-server fingerprint is blank. A deployment that
    /// runs without the GPU tier has no fingerprint to compare and nothing is wrong;
    /// a deployment that expects one and cannot reach it is a fault. Reporting both as
    /// an incomplete match made the normal state of a CPU-only host read as breakage.
    #[serde(default)]
    pub ai_server_present: bool,
    pub shard_dims: Vec<AiShardDimCheck>,
    pub browser_live_sessions: u32,
    pub browser_max_sessions: u32,
    pub browser_detail: String,
    pub recent_traffic: Vec<AiTrafficRow>,
    pub service_use: Vec<AiServiceUse>,
    pub llm_configured: bool,
}

/// One allowed model for the chat picker (subset of the catalog).
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatModelChoice {
    pub provider: String,
    pub model_id: String,
    pub display_name: String,
    pub context_window: u32,
    pub supports_tools: bool,
    pub supports_vision: bool,
    pub is_reasoning: bool,
    pub median_latency_ms: u32,
    pub is_default: bool,
}

/// One row of the error counts report on `/admin/llm`: failed attempts of one step and
/// error class, and runs that ended early, counted over 24 hours, 7 days and 30 days.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ErrorCountRow {
    /// `model`, `tool` or `title` for a step, `run` for an agent run.
    pub source: String,
    pub class: String,
    pub d1: u64,
    pub d7: u64,
    pub d30: u64,
}

/// One failed attempt of the recent error log on `/admin/llm`.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ErrorLogRow {
    /// Unix time in milliseconds.
    pub time_ms: i64,
    pub source: String,
    pub username: String,
    /// The tool name of a tool step, the model id of a model or title step.
    pub name: String,
    pub class: String,
    /// The first 500 characters of the error.
    pub error: String,
}

/// One tool of the tool call report on `/admin/llm`, in three windows.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ToolTableRow {
    pub tool: String,
    pub calls_24h: u64,
    pub err_pct_24h: f64,
    pub avg_ms_24h: f64,
    pub calls_7d: u64,
    pub err_pct_7d: f64,
    pub avg_ms_7d: f64,
    pub calls_30d: u64,
    pub err_pct_30d: f64,
    pub avg_ms_30d: f64,
}

/// One user of the top users report on `/admin/llm`, in the window the admin selects.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct TopUserRow {
    pub username: String,
    pub tool_calls: u64,
    pub tool_ms: u64,
    /// Model and title calls.
    pub model_calls: u64,
    pub model_ms: u64,
    pub tokens_in: u64,
    pub tokens_out: u64,
}
