//! HTTP client for the research-agent service in `ai_services`.
//!
//! The website resolves permissions and hands the agent the resulting collection list;
//! the agent forwards it to the MCP servers, which enforce it. **This module is the
//! only place that decides what goes into `allowed_collections`**, and it never takes
//! that list from the request — always from
//! [`crate::db_utils::clickhouse_utils::list_permitted_collections`].

use std::time::Duration;

use serde::{Deserialize, Serialize};

/// Internal search agent (no internet tools). Defaults to the port
/// `ai_services/docker-compose.yaml` publishes on loopback.
pub fn agent_url() -> String {
    std::env::var("HOOVER4_AGENT_URL").unwrap_or_else(|_| "http://localhost:9099".to_string())
}

/// Full research agent (internet tools). Defaults to the port
/// `ai_services/docker-compose.yaml` publishes on loopback.
pub fn full_agent_url() -> String {
    std::env::var("HOOVER4_FULL_AGENT_URL").unwrap_or_else(|_| "http://localhost:9090".to_string())
}

fn agent_base_url(use_internet_tools: bool) -> String {
    if use_internet_tools {
        full_agent_url()
    } else {
        agent_url()
    }
}

/// An agent run can involve several LLM turns and several searches, so the timeout is
/// minutes rather than seconds. Still bounded: a hung agent must surface as an error
/// message in the transcript, not as a browser tab that spins forever.
fn agent_timeout() -> Duration {
    let secs = std::env::var("HOOVER4_AGENT_TIMEOUT_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(300);
    Duration::from_secs(secs.clamp(10, 3600))
}

#[derive(Debug, Clone, Serialize)]
pub struct AgentChatMessage {
    /// `human` or `ai` — the agent service's vocabulary, not ours.
    pub r#type: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize)]
struct AgentChatRequest<'a> {
    session_id: &'a str,
    user_id: &'a str,
    message_id: &'a str,
    query: &'a str,
    chat_history: &'a [AgentChatMessage],
    username: &'a str,
    allowed_collections: &'a [String],
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct AgentToolCall {
    /// `start` or `end`.
    #[serde(default)]
    pub phase: String,
    #[serde(default)]
    pub content: serde_json::Value,
}

impl AgentToolCall {
    /// Best-effort tool name out of the LangGraph event payload, whose shape differs
    /// between the start and end events.
    pub fn tool_name(&self) -> String {
        self.content
            .get("name")
            .or_else(|| self.content.get("tool"))
            .or_else(|| {
                self.content
                    .get("output")
                    .and_then(|o| o.get("name"))
            })
            .and_then(|v| v.as_str())
            .unwrap_or("tool")
            .to_string()
    }

    /// `tool_call_id` from an end event, when present.
    pub fn tool_call_id(&self) -> Option<&str> {
        self.content
            .get("output")
            .and_then(|o| o.get("tool_call_id"))
            .and_then(|v| v.as_str())
            .or_else(|| self.content.get("tool_call_id").and_then(|v| v.as_str()))
    }

    /// JSON arguments from a start (or end) event.
    pub fn input_json(&self) -> String {
        let raw = self
            .content
            .get("input")
            .cloned()
            .unwrap_or(serde_json::Value::Object(Default::default()));
        raw.to_string()
    }

    /// Full end-event payload as JSON (for storage / disclosure).
    pub fn output_json(&self) -> String {
        self.content.to_string()
    }

    /// One-line summary for the transcript. The full payload can be a whole search
    /// result set, which belongs in the agent's context window, not in the UI.
    pub fn summary(&self, max_chars: usize) -> String {
        let raw = self
            .content
            .get("input")
            .or_else(|| self.content.get("output"))
            .cloned()
            .unwrap_or_else(|| self.content.clone());
        let text = match raw {
            serde_json::Value::String(s) => s,
            other => other.to_string(),
        };
        if text.chars().count() > max_chars {
            format!("{}\u{2026}", text.chars().take(max_chars).collect::<String>())
        } else {
            text
        }
    }
}

/// One completed tool call: a start event paired with its end event.
#[derive(Debug, Clone)]
pub struct PairedToolCall {
    pub tool_name: String,
    pub tool_input: String,
    pub tool_output: String,
    pub summary: String,
}

/// Pair LangGraph start/end tool events into one row each.
///
/// LangGraph emits them in order. Prefer `tool_call_id` when the end payload carries
/// one; otherwise match by FIFO order.
pub fn pair_tool_calls(calls: &[AgentToolCall], summary_chars: usize) -> Vec<PairedToolCall> {
    let mut pending: Vec<(Option<String>, AgentToolCall)> = Vec::new();
    let mut paired = Vec::new();

    for call in calls {
        match call.phase.as_str() {
            "start" => {
                pending.push((call.tool_call_id().map(str::to_string), call.clone()));
            }
            "end" => {
                let id = call.tool_call_id().map(str::to_string);
                let start = if let Some(ref tid) = id {
                    if let Some(pos) = pending.iter().position(|(sid, _)| sid.as_ref() == Some(tid))
                    {
                        Some(pending.remove(pos).1)
                    } else {
                        pending.pop().map(|(_, c)| c)
                    }
                } else {
                    pending.pop().map(|(_, c)| c)
                };

                let tool_name = {
                    let from_end = call.tool_name();
                    if from_end != "tool" {
                        from_end
                    } else if let Some(ref s) = start {
                        s.tool_name()
                    } else {
                        "tool".to_string()
                    }
                };
                let tool_input = start
                    .as_ref()
                    .map(|s| s.input_json())
                    .filter(|s| s != "{}")
                    .unwrap_or_else(|| call.input_json());
                paired.push(PairedToolCall {
                    tool_name,
                    tool_input,
                    tool_output: call.output_json(),
                    summary: call.summary(summary_chars),
                });
            }
            _ => {}
        }
    }
    paired
}

#[derive(Debug, Clone, Deserialize, Default)]
pub struct AgentChatResult {
    #[serde(default)]
    pub answer: String,
    #[serde(default)]
    pub reasoning: String,
    #[serde(default)]
    pub tool_calls: Vec<AgentToolCall>,
}

/// Ask the agent a question on behalf of `username`, bounded by `allowed_collections`.
///
/// `use_internet_tools` selects the full research agent (`HOOVER4_FULL_AGENT_URL`)
/// instead of the internal search agent (`HOOVER4_AGENT_URL`).
pub async fn ask_agent(
    username: &str,
    session_id: &str,
    message_id: &str,
    query: &str,
    history: &[AgentChatMessage],
    allowed_collections: &[String],
    use_internet_tools: bool,
) -> anyhow::Result<AgentChatResult> {
    let base = agent_base_url(use_internet_tools);
    let body = AgentChatRequest {
        session_id,
        // The agent's `user_id` is only a tracing correlation key; the ACL that matters
        // travels in `allowed_collections`.
        user_id: username,
        message_id,
        query,
        chat_history: history,
        username,
        allowed_collections,
    };

    let client = reqwest::Client::builder().timeout(agent_timeout()).build()?;
    let response = client
        .post(format!("{base}/chat"))
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("AI agent unreachable at {base}: {e}"))?;

    let status = response.status();
    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("AI agent returned {status}: {}", text.chars().take(500).collect::<String>());
    }

    Ok(response.json::<AgentChatResult>().await?)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn call(phase: &str, json: serde_json::Value) -> AgentToolCall {
        AgentToolCall {
            phase: phase.to_string(),
            content: json,
        }
    }

    #[test]
    fn tool_name_reads_either_shape() {
        assert_eq!(
            call("start", serde_json::json!({"name": "search_collections"})).tool_name(),
            "search_collections"
        );
        assert_eq!(
            call("end", serde_json::json!({"output": {"name": "list_collections"}})).tool_name(),
            "list_collections"
        );
        assert_eq!(call("start", serde_json::json!({})).tool_name(), "tool");
    }

    #[test]
    fn summary_prefers_input_then_output_then_whole_payload() {
        assert_eq!(call("start", serde_json::json!({"input": "q"})).summary(50), "q");
        assert_eq!(call("end", serde_json::json!({"output": "r"})).summary(50), "r");
        assert_eq!(call("start", serde_json::json!({"x": 1})).summary(50), "{\"x\":1}");
    }

    #[test]
    fn summary_truncates_long_payloads() {
        let long = serde_json::json!({ "input": "z".repeat(100) });
        let s = call("start", long).summary(10);
        assert_eq!(s.chars().count(), 11);
        assert!(s.ends_with('\u{2026}'));
    }

    #[test]
    fn pair_start_end_by_order() {
        let calls = vec![
            call("start", serde_json::json!({"input": {"query": "water"}})),
            call(
                "end",
                serde_json::json!({
                    "output": {"name": "search_collections", "content": {"results": []}},
                    "input": {}
                }),
            ),
        ];
        let paired = pair_tool_calls(&calls, 400);
        assert_eq!(paired.len(), 1);
        assert_eq!(paired[0].tool_name, "search_collections");
        assert!(paired[0].tool_input.contains("water"));
    }

    #[test]
    fn timeout_is_clamped_into_a_sane_range() {
        assert!(agent_timeout() >= Duration::from_secs(10));
        assert!(agent_timeout() <= Duration::from_secs(3600));
    }
}
