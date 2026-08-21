//! HTTP client for the research-agent services in `main_services/agents`.
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
    std::env::var("HOOVER4_AGENT_URL").unwrap_or_else(|_| "http://localhost:21936".to_string())
}

/// Full research agent (internet tools). Defaults to the port
/// `ai_services/docker-compose.yaml` publishes on loopback.
pub fn full_agent_url() -> String {
    std::env::var("HOOVER4_FULL_AGENT_URL").unwrap_or_else(|_| "http://localhost:21937".to_string())
}

fn agent_base_url(use_internet_tools: bool) -> String {
    if use_internet_tools {
        full_agent_url()
    } else {
        agent_url()
    }
}

/// How long the agent may stay **silent** before the run is called dead.
///
/// This bounds the gap between two bytes, not the length of the run. A total-request
/// timeout is the wrong bound for a streamed agent: a healthy turn that calls a slow
/// provider a dozen times outlives any total worth setting, and cutting it produces a
/// `reqwest` body error — `error decoding response body` — that reads like a corrupt
/// stream and hides the fact that a deadline was hit. Silence is the real symptom of a
/// hung agent, and the longest legitimate gap is one LLM call.
fn agent_idle_timeout() -> Duration {
    let secs = std::env::var("HOOVER4_AGENT_TIMEOUT_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(300);
    Duration::from_secs(secs.clamp(10, 3600))
}

/// Absolute ceiling on one agent call, however chatty it stays. The idle timeout cannot
/// catch an agent that loops forever while emitting events, so this is the backstop —
/// the same half hour the ingest side gives a research run.
fn agent_total_timeout() -> Duration {
    let secs = std::env::var("HOOVER4_AGENT_TOTAL_TIMEOUT_SECONDS")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(1_800);
    Duration::from_secs(secs.clamp(60, 21_600))
}

/// Total attempts per turn, including the first. Retries cover the whole class of
/// failure — unreachable, 5xx, timeout, malformed body — rather than a curated list,
/// because from the user's seat they are one thing ("it did not answer") and the local
/// GPU stack fails transiently in all four ways: vLLM still loading, an MCP server
/// restarting, a browser session that died.
pub fn agent_attempts() -> u32 {
    std::env::var("HOOVER4_AGENT_ATTEMPTS")
        .ok()
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(4)
        .clamp(1, 8)
}

/// How many times a turn may be replayed **after** the agent has already streamed
/// events to the user. Bounded much harder than [`agent_attempts`] because the unit of
/// waste is different: a pre-event failure costs a connection, while a mid-stream break
/// throws away everything the agent has done — the turn that killed chat with
/// `agent stream broke` was thirteen provider calls and eighteen minutes of work —
/// and the replay repeats all of it. One is the most
/// that can be spent without turning a slow turn into an unbounded one; `0` disables
/// mid-stream replay entirely.
pub fn agent_stream_resumes() -> u32 {
    std::env::var("HOOVER4_AGENT_STREAM_RESUMES")
        .ok()
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(1)
        .clamp(0, 2)
}

/// Delay before the first retry. Doubles each time: 2s, 4s, 8s by default.
pub fn agent_retry_base() -> Duration {
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
    #[serde(skip_serializing_if = "Option::is_none")]
    llm_model: Option<&'a str>,
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
    /// The agent's own id for one tool invocation, present on both the start and the end.
    ///
    /// This is the identity that pairs them. `tool_call_id` is the model's id and is
    /// absent from a start event entirely, and pairing by tool name and arrival order
    /// puts the second of two concurrent calls to one tool with the first one's result —
    /// silently, and in the shape of a card whose answer belongs to another question.
    pub fn run_id(&self) -> Option<&str> {
        self.content
            .get("run_id")
            .and_then(|v| v.as_str())
            .filter(|v| !v.is_empty())
    }

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
                // run_id first: it is the only identity a start event carries, and it is
                // what keeps two concurrent calls to one tool apart. tool_call_id is the
                // fallback for a transcript recorded before run_id was emitted.
                let identity = call
                    .run_id()
                    .or_else(|| call.tool_call_id())
                    .map(str::to_string);
                pending.push((identity, call.clone()));
            }
            "end" => {
                let id = call
                    .run_id()
                    .or_else(|| call.tool_call_id())
                    .map(str::to_string);
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

// ---------------------------------------------------------------------------
// Streaming: consume the agent's `/chat/stream` event feed.
// ---------------------------------------------------------------------------

/// One chunk from the agent's event stream (the `type` field of each SSE payload).
#[derive(Debug, Clone)]
pub enum AgentStreamEvent {
    Start,
    /// Model reasoning (never part of the answer body).
    Reasoning(String),
    /// Visible answer text. With `LLM_STREAMING` on this is per-token; off, one chunk
    /// per turn.
    Response(String),
    /// A tool call started. Payload is the LangGraph start event.
    StartTool(serde_json::Value),
    /// A tool call finished. Payload is the LangGraph end event.
    EndTool(serde_json::Value),
    /// The turn is over. Payload is the accumulated content, which the caller has
    /// already seen chunk by chunk — carried here only as a cross-check.
    End,
}

/// The connection carrying an in-flight agent run failed.
///
/// Carried as its own type so the caller can tell a transport break from an `error`
/// chunk the agent deliberately sent: the first may be worth replaying, the second
/// never is. `timeout` separates the two transport breaks that need opposite handling —
/// a deadline the website itself imposed will fire again on a replay, a dropped
/// connection may not.
#[derive(Debug, Clone)]
pub struct StreamTransportError {
    pub message: String,
    pub timeout: bool,
}

impl std::fmt::Display for StreamTransportError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for StreamTransportError {}

/// True when replaying the turn has any chance of a different outcome.
pub fn is_resumable_break(err: &anyhow::Error) -> bool {
    err.downcast_ref::<StreamTransportError>()
        .is_some_and(|e| !e.timeout)
}

/// Every message in an error's `source` chain, outermost first.
///
/// `reqwest::Error`'s own `Display` is a category — "error decoding response body" is
/// what a *timeout* mid-body prints, and what a truncated stream prints, and what a
/// genuine decode failure prints. The chain is where the three become distinguishable,
/// so nothing here logs `{e}` alone.
fn error_chain(err: &(dyn std::error::Error + 'static)) -> String {
    let mut parts = vec![err.to_string()];
    let mut source = err.source();
    while let Some(inner) = source {
        parts.push(inner.to_string());
        source = inner.source();
    }
    parts.join(" <- ")
}

/// The last `max_chars` characters of `text`. Characters, not bytes: the buffer holds
/// arbitrary extracted content and a byte slice can land mid-codepoint.
fn tail_chars(text: &str, max_chars: usize) -> String {
    let total = text.chars().count();
    text.chars().skip(total.saturating_sub(max_chars)).collect()
}

fn parse_stream_event(chunk: &serde_json::Value) -> Option<AgentStreamEvent> {
    let kind = chunk.get("type")?.as_str()?;
    let content = chunk.get("content").cloned().unwrap_or(serde_json::Value::Null);
    match kind {
        "start" | "start_reasoning" | "start_response" => Some(AgentStreamEvent::Start),
        "reasoning" => Some(AgentStreamEvent::Reasoning(
            content.as_str().unwrap_or_default().to_string(),
        )),
        "response" => Some(AgentStreamEvent::Response(
            content.as_str().unwrap_or_default().to_string(),
        )),
        "start_tool" => Some(AgentStreamEvent::StartTool(content)),
        "end_tool" => Some(AgentStreamEvent::EndTool(content)),
        "end" => Some(AgentStreamEvent::End),
        // `error` chunks are turned into `Err` by the caller before this is invoked.
        _ => None,
    }
}

/// Stream one agent attempt, invoking `on_event` per chunk. Returns once the stream
/// ends. Cancellation is the caller aborting the task this runs in, which also drops
/// the in-flight HTTP request.
///
/// An `error` chunk is delivered as `Err` from this function; transport errors mid-
/// stream likewise, as a [`StreamTransportError`]. A caller that has already received
/// events may replay the turn only for a transport break the connection caused
/// ([`is_resumable_break`]), and must fold the prose it already collected out of the
/// answer first — the model may have produced visible content and a replay repeats it.
pub async fn ask_agent_stream_once(
    username: &str,
    session_id: &str,
    message_id: &str,
    query: &str,
    history: &[AgentChatMessage],
    allowed_collections: &[String],
    use_internet_tools: bool,
    llm_model: Option<&str>,
    on_event: &mut (impl FnMut(AgentStreamEvent) + Send),
) -> anyhow::Result<()> {
    use futures::StreamExt;

    let base = agent_base_url(use_internet_tools);
    let body = AgentChatRequest {
        session_id,
        user_id: username,
        message_id,
        query,
        chat_history: history,
        username,
        allowed_collections,
        llm_model,
    };

    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .read_timeout(agent_idle_timeout())
        .timeout(agent_total_timeout())
        .build()?;
    let started = std::time::Instant::now();
    let response = client
        .post(format!("{base}/chat/stream"))
        .json(&body)
        .send()
        .await
        .map_err(|e| anyhow::anyhow!("AI agent unreachable at {base}: {e}"))?;
    let status = response.status();
    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("AI agent returned {status}: {}", text.chars().take(500).collect::<String>());
    }

    // The feed is SSE-shaped (`data: {json}\n\n`) over text/plain. The classification and
    // the logging happen here, where the `reqwest::Error` still exists; the consumer below
    // only ever sees a [`StreamTransportError`], which is what makes it testable without
    // a socket.
    let stream = response.bytes_stream().map(move |item| {
        item.map_err(|e| {
            // The one place that knows what actually failed. A turn that dies here leaves
            // nothing else behind — the agent keeps running, its own log says the run went
            // fine, and every `llm_call_events` row says `ok`. Without the source chain and
            // the elapsed time, the next reader cannot tell a deadline from a truncated
            // stream from a bad frame, which is exactly the position `agent stream broke`
            // was reported from.
            let timeout = e.is_timeout();
            let elapsed = started.elapsed().as_secs_f64();
            tracing::error!(
                "agent stream broke after {elapsed:.1}s: timeout={timeout} body={body} \
                 decode={decode} connect={connect} chain=[{chain}]",
                body = e.is_body(),
                decode = e.is_decode(),
                connect = e.is_connect(),
                chain = error_chain(&e),
            );
            let message = if timeout {
                format!("agent stream timed out after {elapsed:.0}s of silence")
            } else {
                format!("agent stream broke: {}", error_chain(&e))
            };
            StreamTransportError { message, timeout }
        })
    });
    consume_event_stream(stream, on_event).await
}

/// Split an SSE-shaped byte stream into events, invoking `on_event` per chunk.
///
/// Separate from the HTTP call so a broken stream can be exercised in a test: the only
/// way this loop failed in production was mid-stream, and reconstructing that with a real
/// socket costs more than it proves.
async fn consume_event_stream<B, S>(
    stream: S,
    on_event: &mut (impl FnMut(AgentStreamEvent) + Send),
) -> anyhow::Result<()>
where
    B: AsRef<[u8]>,
    S: futures::Stream<Item = Result<B, StreamTransportError>>,
{
    use futures::StreamExt;

    let mut stream = std::pin::pin!(stream);
    let mut buffer = String::new();
    let mut bytes_seen: usize = 0;
    let mut frames_seen: usize = 0;
    while let Some(item) = stream.next().await {
        let bytes = match item {
            Ok(bytes) => bytes,
            Err(e) => {
                // Logged again from here with what the *consumer* knows — how much of the
                // answer had arrived and what the half-frame on the wire looked like. A
                // stream cut cleanly between frames and one cut inside a payload are
                // different faults and print differently.
                tracing::error!(
                    "agent stream ended early after {bytes_seen} bytes and {frames_seen} \
                     frames: {e} undecoded_tail={tail:?}",
                    tail = tail_chars(&buffer, 400),
                );
                return Err(anyhow::Error::new(e));
            }
        };
        let bytes = bytes.as_ref();
        bytes_seen += bytes.len();
        buffer.push_str(&String::from_utf8_lossy(bytes));
        while let Some(pos) = buffer.find("\n\n") {
            frames_seen += 1;
            let frame = buffer[..pos].to_string();
            buffer = buffer[pos + 2..].to_string();
            for line in frame.lines() {
                let Some(payload) = line.strip_prefix("data: ") else {
                    continue;
                };
                let json = match serde_json::from_str::<serde_json::Value>(payload) {
                    Ok(json) => json,
                    Err(e) => {
                        // ERROR, not WARN: a frame the website cannot read is a step of
                        // the answer silently dropped, and the payload is the only
                        // evidence of what the agent sent. `.chars()`, not a byte slice:
                        // cutting at byte 400 lands inside a multi-byte character on any
                        // non-ASCII payload and panics — in the spawned stream task,
                        // where the turn simply stops with no answer.
                        let head: String = payload.chars().take(400).collect();
                        tracing::error!(
                            "unparseable agent stream frame ({} bytes) at {e}: {head:?}",
                            payload.len(),
                        );
                        continue;
                    }
                };
                if let Some(kind) = json.get("type").and_then(|t| t.as_str()) {
                    if kind == "error" {
                        let msg = json
                            .get("content")
                            .and_then(|c| c.as_str())
                            .unwrap_or("unknown agent error");
                        anyhow::bail!("{msg}");
                    }
                }
                if let Some(event) = parse_stream_event(&json) {
                    on_event(event);
                }
            }
        }
    }
    Ok(())
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

    /// Two interleaved calls to the SAME tool must stay two calls, each with its own
    /// result.
    ///
    /// This is the shape the models actually produce — two `search_collections` starts
    /// milliseconds apart, then two ends in whatever order the tools finished — and
    /// pairing by name and arrival order gets it wrong in the way that is hardest to
    /// see: both cards render, both look plausible, and each shows the other's answer.
    #[test]
    fn interleaved_calls_to_one_tool_keep_their_own_results() {
        let calls = vec![
            call("start", serde_json::json!({
                "name": "search_collections", "run_id": "run-a",
                "input": {"query": "water rights"},
            })),
            call("start", serde_json::json!({
                "name": "search_collections", "run_id": "run-b",
                "input": {"query": "pipeline easement"},
            })),
            // The second call finishes first, which is the whole point: arrival order
            // is not call order.
            call("end", serde_json::json!({
                "run_id": "run-b",
                "output": {"name": "search_collections", "content": {"hit": "easement"}},
                "input": {},
            })),
            call("end", serde_json::json!({
                "run_id": "run-a",
                "output": {"name": "search_collections", "content": {"hit": "water"}},
                "input": {},
            })),
        ];
        let paired = pair_tool_calls(&calls, 400);
        assert_eq!(paired.len(), 2, "two calls must survive as two rows");
        assert!(paired[0].tool_input.contains("pipeline easement"), "{paired:?}");
        assert!(paired[0].tool_output.contains("easement"), "{paired:?}");
        assert!(paired[1].tool_input.contains("water rights"), "{paired:?}");
        assert!(paired[1].tool_output.contains("water"), "{paired:?}");
    }

    /// A transcript recorded by an agent image that emitted no run_id still renders.
    #[test]
    fn a_stream_without_run_ids_still_pairs() {
        let calls = vec![
            call("start", serde_json::json!({"input": {"query": "water"}})),
            call("end", serde_json::json!({
                "output": {"name": "search_collections", "content": {"results": []}},
                "input": {},
            })),
        ];
        assert_eq!(pair_tool_calls(&calls, 400).len(), 1);
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
        assert!(agent_idle_timeout() >= Duration::from_secs(10));
        assert!(agent_idle_timeout() <= Duration::from_secs(3600));
    }

    #[test]
    fn the_absolute_cap_outlasts_the_silence_bound() {
        // If the total were the shorter of the two it would fire first on every long
        // turn, and the idle bound — the one that describes a hung agent — would never
        // be reached. That inversion is what cut a healthy 18-minute turn at 300 s.
        assert!(
            agent_total_timeout() > agent_idle_timeout(),
            "total {:?} must outlast idle {:?}",
            agent_total_timeout(),
            agent_idle_timeout(),
        );
    }

    #[test]
    fn mid_stream_replays_are_bounded_to_at_most_one_by_default() {
        // A replay repeats every provider call the turn has made. The bound is what
        // keeps a six-minute turn from becoming a half-hour one.
        assert!(agent_stream_resumes() <= 2);
    }

    #[test]
    fn a_deadline_is_not_replayed_but_a_dropped_connection_is() {
        let dropped = anyhow::Error::new(StreamTransportError {
            message: "agent stream broke: connection reset".to_string(),
            timeout: false,
        });
        let deadline = anyhow::Error::new(StreamTransportError {
            message: "agent stream timed out after 300s of silence".to_string(),
            timeout: true,
        });
        assert!(is_resumable_break(&dropped));
        // Replaying a deadline spends the whole turn again to hit the same deadline.
        assert!(!is_resumable_break(&deadline));
        // An `error` chunk the agent sent deliberately is not a transport failure.
        assert!(!is_resumable_break(&anyhow::anyhow!("tool refused the call")));
    }

    #[test]
    fn the_tail_is_cut_by_characters_so_a_diacritic_cannot_panic() {
        assert_eq!(tail_chars("abcdef", 3), "def");
        assert_eq!(tail_chars("ăîș", 2), "îș");
        assert_eq!(tail_chars("ab", 10), "ab");
    }

    #[tokio::test]
    async fn a_break_mid_stream_keeps_the_events_that_already_arrived() {
        // The `agent stream broke` failure: frames are delivered, then the connection
        // dies. The
        // events before the break are real work and must reach the caller, and the error
        // must arrive classified so the caller can decide whether to replay.
        let chunks: Vec<Result<&[u8], StreamTransportError>> = vec![
            Ok(b"data: {\"type\": \"start\"}\n\n"),
            Ok(b"data: {\"type\": \"response\", \"content\": \"partial\"}\n\n"),
            Ok(b"data: {\"type\": \"resp"),
            Err(StreamTransportError {
                message: "agent stream broke: connection closed before message completed"
                    .to_string(),
                timeout: false,
            }),
        ];
        let mut seen = Vec::new();
        let err = consume_event_stream(futures::stream::iter(chunks), &mut |e| seen.push(e))
            .await
            .expect_err("a broken stream must fail the attempt");

        assert_eq!(seen.len(), 2, "events before the break are kept");
        assert!(matches!(seen[1], AgentStreamEvent::Response(ref s) if s == "partial"));
        assert!(is_resumable_break(&err), "a dropped connection is replayable");
    }

    #[tokio::test]
    async fn an_error_chunk_ends_the_stream_without_being_replayable() {
        let chunks: Vec<Result<&[u8], StreamTransportError>> = vec![Ok(
            b"data: {\"type\": \"error\", \"content\": \"the model refused\"}\n\n",
        )];
        let err = consume_event_stream(futures::stream::iter(chunks), &mut |_| {})
            .await
            .expect_err("an error chunk fails the attempt");
        assert_eq!(err.to_string(), "the model refused");
        assert!(!is_resumable_break(&err));
    }

    #[tokio::test]
    async fn a_frame_split_across_chunks_is_reassembled() {
        let chunks: Vec<Result<&[u8], StreamTransportError>> = vec![
            Ok(b"data: {\"type\": \"resp"),
            Ok(b"onse\", \"content\": \"hello\"}\n\ndata: {\"type\": \"end\"}\n\n"),
        ];
        let mut seen = Vec::new();
        consume_event_stream(futures::stream::iter(chunks), &mut |e| seen.push(e))
            .await
            .expect("a complete stream succeeds");
        assert_eq!(seen.len(), 2);
        assert!(matches!(seen[0], AgentStreamEvent::Response(ref s) if s == "hello"));
    }
}
