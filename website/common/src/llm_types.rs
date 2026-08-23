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
