//! Best-effort writers for `llm_call_events` / `ai_service_telemetry` from the website.

use crate::db_auth::{insert_row, now};

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize)]
struct LlmCallEventRow {
    #[serde(with = "clickhouse::serde::time::datetime")]
    event_time: time::OffsetDateTime,
    username: String,
    session_id: String,
    kind: String,
    provider: String,
    model_id: String,
    prompt_tokens: u32,
    completion_tokens: u32,
    reasoning_tokens: u32,
    reply_bytes: u32,
    latency_ms: u32,
    ok: u8,
    error: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Serialize)]
struct AiServiceTelemetryRow {
    #[serde(with = "clickhouse::serde::time::datetime")]
    event_time: time::OffsetDateTime,
    service: String,
    provider: String,
    username: String,
    session_id: String,
    latency_ms: u32,
    ok: u8,
    detail: String,
}

fn telemetry_username(username: &str) -> String {
    let raw = username.trim();
    if raw.is_empty() || raw == "guest" || raw.starts_with("guest-") {
        "guest".into()
    } else {
        raw.to_string()
    }
}

fn provider_label() -> String {
    if let Ok(name) = std::env::var("LLM_PROVIDER_NAME") {
        if !name.trim().is_empty() {
            return name;
        }
    }
    let base = std::env::var("LLM_BASE_URL").unwrap_or_default();
    let host = base
        .trim_start_matches("https://")
        .trim_start_matches("http://")
        .split('/')
        .next()
        .unwrap_or("unknown");
    let parts: Vec<_> = host.split('.').collect();
    if parts.len() >= 2 {
        parts[parts.len() - 2].to_string()
    } else {
        host.to_string()
    }
}

/// Record one LLM call made by the website itself (summariser / title). Never raises.
pub async fn record_llm_call(
    username: &str,
    session_id: &str,
    kind: &str,
    model_id: &str,
    latency_ms: u32,
    reply_bytes: u32,
    ok: bool,
    error: &str,
) {
    let row = LlmCallEventRow {
        event_time: now(),
        username: telemetry_username(username),
        session_id: session_id.to_string(),
        kind: kind.to_string(),
        provider: provider_label(),
        model_id: model_id.to_string(),
        prompt_tokens: 0,
        completion_tokens: 0,
        reasoning_tokens: 0,
        reply_bytes,
        latency_ms,
        ok: if ok { 1 } else { 0 },
        error: error.chars().take(500).collect(),
    };
    if let Err(e) = insert_row("llm_call_events", &row).await {
        tracing::warn!("llm_call_events insert failed: {e:#}");
    }
    let telem = AiServiceTelemetryRow {
        event_time: now(),
        service: "llm".into(),
        provider: provider_label(),
        username: telemetry_username(username),
        session_id: session_id.to_string(),
        latency_ms,
        ok: if ok { 1 } else { 0 },
        detail: model_id.to_string(),
    };
    let _ = insert_row("ai_service_telemetry", &telem).await;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn guests_collapse_to_literal_guest() {
        assert_eq!(telemetry_username(""), "guest");
        assert_eq!(telemetry_username("guest"), "guest");
        assert_eq!(telemetry_username("guest-abc"), "guest");
        assert_eq!(telemetry_username("ann"), "ann");
    }
}
