//! Short title + summary for a chat session, via vLLM's OpenAI-compatible API.
//!
//! Deliberately does **not** go through the agent: that would drag MCP tools into a
//! summarisation call. Failures are logged and ignored — a failed summariser must never
//! fail a chat turn. The caller falls back to [`common::chat_types::title_from_message`].

use serde::{Deserialize, Serialize};

fn llm_base_url() -> String {
    std::env::var("LLM_BASE_URL").unwrap_or_else(|_| "http://hoover4-vllm:8000/v1".into())
}

fn llm_api_key() -> String {
    std::env::var("LLM_API_KEY").unwrap_or_else(|_| "hoover4-local-key".into())
}

fn llm_model() -> Option<String> {
    // Never hardcode a model name — Plan 1 changes LLM_MODEL (e.g. qwen3-4b → qwen3.5-2b).
    std::env::var("LLM_MODEL").ok().filter(|s| !s.trim().is_empty())
}

#[derive(Debug, Serialize)]
struct ChatCompletionRequest<'a> {
    model: &'a str,
    messages: Vec<ChatMessage<'a>>,
    temperature: f32,
    max_tokens: u32,
}

#[derive(Debug, Serialize)]
struct ChatMessage<'a> {
    role: &'a str,
    content: &'a str,
}

#[derive(Debug, Deserialize)]
struct ChatCompletionResponse {
    choices: Vec<Choice>,
}

#[derive(Debug, Deserialize)]
struct Choice {
    message: ChoiceMessage,
}

#[derive(Debug, Deserialize)]
struct ChoiceMessage {
    content: Option<String>,
}

#[derive(Debug, Clone)]
pub struct SessionTitleSummary {
    pub title: String,
    pub summary: String,
}

/// Ask the local LLM for a short title and a 1–2 sentence summary of the first turn.
///
/// Returns `None` on any failure so the caller can keep the `title_from_message` fallback.
pub async fn generate_title_and_summary(
    user_message: &str,
    assistant_answer: &str,
) -> Option<SessionTitleSummary> {
    let prompt = format!(
        "Given this chat turn, reply with exactly two lines:\n\
         Line 1: a short title (max 8 words, no quotes).\n\
         Line 2: a one-or-two sentence summary of what was asked and answered.\n\n\
         User: {user_message}\n\nAssistant: {assistant_answer}"
    );

    let model = llm_model()?;
    let body = ChatCompletionRequest {
        model: &model,
        messages: vec![
            ChatMessage {
                role: "system",
                content: "You write short titles and summaries for an investigative-search chat. No markdown.",
            },
            ChatMessage {
                role: "user",
                content: &prompt,
            },
        ],
        temperature: 0.2,
        max_tokens: 120,
    };

    let url = format!("{}/chat/completions", llm_base_url().trim_end_matches('/'));
    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            tracing::warn!("chat summariser: client build failed: {e}");
            return None;
        }
    };

    let response = match client
        .post(&url)
        .bearer_auth(llm_api_key())
        .json(&body)
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            tracing::warn!("chat summariser: request failed: {e}");
            return None;
        }
    };

    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        tracing::warn!("chat summariser: {status}: {}", text.chars().take(200).collect::<String>());
        return None;
    }

    let parsed: ChatCompletionResponse = match response.json().await {
        Ok(p) => p,
        Err(e) => {
            tracing::warn!("chat summariser: bad JSON: {e}");
            return None;
        }
    };

    let raw = parsed
        .choices
        .first()
        .and_then(|c| c.message.content.as_ref())
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())?;

    // Strip optional <think>…</think> blocks some local models emit.
    let cleaned = strip_think_blocks(&raw);
    let mut lines = cleaned.lines().map(str::trim).filter(|l| !l.is_empty());
    let title = lines.next()?.chars().take(80).collect::<String>();
    let summary = lines.collect::<Vec<_>>().join(" ");
    if title.is_empty() {
        return None;
    }
    Some(SessionTitleSummary {
        title: title.clone(),
        summary: if summary.is_empty() {
            title
        } else {
            summary.chars().take(400).collect()
        },
    })
}

fn strip_think_blocks(s: &str) -> String {
    let mut out = String::new();
    let mut rest = s;
    while let Some(start) = rest.find("<think>") {
        out.push_str(&rest[..start]);
        if let Some(end) = rest[start..].find("</think>") {
            rest = &rest[start + end + "</think>".len()..];
        } else {
            rest = "";
            break;
        }
    }
    out.push_str(rest);
    out
}
