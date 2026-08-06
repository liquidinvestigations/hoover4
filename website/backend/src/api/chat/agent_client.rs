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

/// Total attempts per turn, including the first. Retries cover the whole class of
/// failure — unreachable, 5xx, timeout, malformed body — rather than a curated list,
/// because from the user's seat they are one thing ("it did not answer") and the local
/// GPU stack fails transiently in all four ways: vLLM still loading, an MCP server
/// restarting, a browser session that died.
fn agent_attempts() -> u32 {
    std::env::var("HOOVER4_AGENT_ATTEMPTS")
        .ok()
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(4)
        .clamp(1, 8)
}

/// Delay before the first retry. Doubles each time: 2s, 4s, 8s by default.
fn agent_retry_base() -> Duration {
    let ms = std::env::var("HOOVER4_AGENT_RETRY_BASE_MS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(2_000);
    Duration::from_millis(ms.clamp(100, 60_000))
}

/// Backoff before attempt `attempt` (1-based; attempt 1 never waits).
pub fn backoff_for_attempt(attempt: u32, base: Duration) -> Duration {
    if attempt <= 1 {
        return Duration::ZERO;
    }
    // Saturating shift: an operator setting attempts to 8 with a 60 s base must not
    // overflow into a nonsense delay.
    let factor = 1u64 << (attempt - 2).min(20);
    base.saturating_mul(factor.min(u32::MAX as u64) as u32)
}

/// Outcome of a retried agent call: the result, plus what the failed attempts said.
///
/// The errors are kept even on success — a turn that needed three tries is healthy
/// output but unhealthy infrastructure, and the transcript is where that shows up.
pub struct RetriedAgentCall {
    pub result: anyhow::Result<AgentChatResult>,
    pub attempt_errors: Vec<String>,
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

    /// The tool's actual result, for storage / disclosure.
    ///
    /// An end event is `{"output": {"content": <result>, "name": …, "tool_call_id": …},
    /// "input": {…}}`. Storing that whole envelope would put the arguments in the
    /// output pane twice over and bury the result under LangChain bookkeeping, so the
    /// result is unwrapped when it is where it is expected to be, and the envelope is
    /// kept only when it is not (an unfamiliar shape is better shown than dropped).
    pub fn output_json(&self) -> String {
        self.content
            .get("output")
            .and_then(|o| o.get("content"))
            .unwrap_or(&self.content)
            .to_string()
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

/// [`ask_agent`] with exponential backoff.
///
/// `should_stop` is polled between attempts so an admin killing the run from the live
/// chats panel does not have to wait out the remaining backoff. It cannot interrupt an
/// attempt already in flight — see `live_runs`.
#[allow(clippy::too_many_arguments)]
pub async fn ask_agent_with_retries(
    username: &str,
    session_id: &str,
    message_id: &str,
    query: &str,
    history: &[AgentChatMessage],
    allowed_collections: &[String],
    use_internet_tools: bool,
    mut on_attempt: impl FnMut(u32),
    should_stop: impl Fn() -> bool,
) -> RetriedAgentCall {
    let attempts = agent_attempts();
    let base = agent_retry_base();
    let mut attempt_errors: Vec<String> = Vec::new();

    for attempt in 1..=attempts {
        if attempt > 1 {
            if should_stop() {
                break;
            }
            tokio::time::sleep(backoff_for_attempt(attempt, base)).await;
            if should_stop() {
                break;
            }
        }
        on_attempt(attempt);

        match ask_agent(
            username,
            session_id,
            message_id,
            query,
            history,
            allowed_collections,
            use_internet_tools,
        )
        .await
        {
            Ok(result) => {
                return RetriedAgentCall {
                    result: Ok(result),
                    attempt_errors,
                }
            }
            Err(e) => {
                attempt_errors.push(format!("attempt {attempt}/{attempts}: {e}"));
            }
        }
    }

    // Every attempt failed (or a cancel cut the sequence short). The last message is
    // the most recent failure; the earlier ones travel separately so the UI can show
    // the sequence rather than only its least informative member.
    let last = attempt_errors
        .last()
        .cloned()
        .unwrap_or_else(|| "the agent call was cancelled before it ran".to_string());
    let earlier = attempt_errors
        .len()
        .checked_sub(1)
        .map(|n| attempt_errors[..n].to_vec())
        .unwrap_or_default();
    RetriedAgentCall {
        result: Err(anyhow::anyhow!("{last}")),
        attempt_errors: earlier,
    }
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
    fn output_json_unwraps_the_tool_result_from_the_langchain_envelope() {
        let end = call(
            "end",
            serde_json::json!({
                "output": {"content": {"results": [1]}, "name": "search_collections"},
                "input": {"query": "water"}
            }),
        );
        assert_eq!(end.output_json(), r#"{"results":[1]}"#);
    }

    #[test]
    fn output_json_keeps_an_unrecognised_payload_rather_than_dropping_it() {
        let odd = call("end", serde_json::json!({"something": "else"}));
        assert_eq!(odd.output_json(), r#"{"something":"else"}"#);
    }

    #[test]
    fn backoff_doubles_and_the_first_attempt_never_waits() {
        let base = Duration::from_secs(2);
        assert_eq!(backoff_for_attempt(1, base), Duration::ZERO);
        assert_eq!(backoff_for_attempt(2, base), Duration::from_secs(2));
        assert_eq!(backoff_for_attempt(3, base), Duration::from_secs(4));
        assert_eq!(backoff_for_attempt(4, base), Duration::from_secs(8));
    }

    #[test]
    fn backoff_does_not_overflow_at_the_configured_maximum() {
        // 8 attempts x a 60 s base is the widest the clamps allow; it must stay finite.
        let d = backoff_for_attempt(8, Duration::from_secs(60));
        assert_eq!(d, Duration::from_secs(60 * 64));
    }

    #[test]
    fn attempt_count_is_clamped_so_a_typo_cannot_hammer_the_gpu() {
        let n = agent_attempts();
        assert!((1..=8).contains(&n), "attempts out of range: {n}");
    }

    #[test]
    fn timeout_is_clamped_into_a_sane_range() {
        assert!(agent_timeout() >= Duration::from_secs(10));
        assert!(agent_timeout() <= Duration::from_secs(3600));
    }
}
