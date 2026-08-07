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
    if let Ok(key) = std::env::var("LLM_API_KEY") {
        return key;
    }
    // deploy.py bind-mounts the active provider's key file (hoover4.ini stores host
    // paths, never values); the env var names the in-container path.
    if let Ok(path) = std::env::var("LLM_API_KEY_FILE") {
        if let Ok(key) = std::fs::read_to_string(&path) {
            let key = key.trim();
            if !key.is_empty() {
                return key.to_string();
            }
        }
    }
    "hoover4-local-key".into()
}

async fn llm_model() -> Option<String> {
    // Prefer the admin-configured summarisation model; fall back to LLM_MODEL env.
    let from_settings = crate::api::admin::llm::summarization_model().await;
    if !from_settings.trim().is_empty() {
        return Some(from_settings);
    }
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
    /// `stop` when the model finished, `length` when it hit `max_tokens`. A truncated
    /// completion is not a title — see [`generate_title_and_summary`].
    #[serde(default)]
    finish_reason: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ChoiceMessage {
    content: Option<String>,
    /// Reasoning models return their scratchpad on this separate channel. It is never
    /// the answer, and a model cut off mid-thought echoes it into `content` as well.
    #[serde(default)]
    reasoning_content: Option<String>,
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
    generate_title_and_summary_for(user_message, assistant_answer, "", "").await
}

/// Same as [`generate_title_and_summary`], with telemetry attribution.
pub async fn generate_title_and_summary_for(
    user_message: &str,
    assistant_answer: &str,
    username: &str,
    session_id: &str,
) -> Option<SessionTitleSummary> {
    let started = std::time::Instant::now();
    let prompt = format!(
        "Given this chat turn, reply with exactly two lines:\n\
         Line 1: a short title (max 8 words, no quotes).\n\
         Line 2: a one-or-two sentence summary of what was asked and answered.\n\n\
         User: {user_message}\n\nAssistant: {assistant_answer}"
    );

    // Prefer admin-configured summarisation model; unset disables the summariser.
    let Some(model) = llm_model().await else {
        tracing::warn!(
            "chat summariser disabled: no summarisation model configured \
             (llm_summarization_model / LLM_MODEL), so titles stay as the \
             truncated first message and summaries stay empty."
        );
        return None;
    };
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
        // Budget for a *reasoning* model, not for two lines of output. At 120 the
        // configured provider (nemotron-3-super) spent the entire allowance thinking,
        // came back `finish_reason: "length"` with its scratchpad mirrored into
        // `content`, and the sidebar filled up with titles reading "We need to output
        // exactly two lines: line1 short title max 8 words…". The reply is still two
        // lines; the thinking in front of it is what needs the room.
        max_tokens: 512,
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
            crate::api::chat::llm_events::record_llm_call(
                username,
                session_id,
                "title",
                &model,
                started.elapsed().as_millis() as u32,
                0,
                false,
                &e.to_string(),
            )
            .await;
            return None;
        }
    };

    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        tracing::warn!("chat summariser: {status}: {}", text.chars().take(200).collect::<String>());
        crate::api::chat::llm_events::record_llm_call(
            username,
            session_id,
            "title",
            &model,
            started.elapsed().as_millis() as u32,
            0,
            false,
            &format!("{status}"),
        )
        .await;
        return None;
    }

    let parsed: ChatCompletionResponse = match response.json().await {
        Ok(p) => p,
        Err(e) => {
            tracing::warn!("chat summariser: bad JSON: {e}");
            return None;
        }
    };

    let choice = parsed.choices.first()?;
    // A completion cut off at `max_tokens` is not a title. Falling back to
    // `title_from_message` shows the user's own words, which is always better than half
    // a sentence — or, when the model was still thinking, than its scratchpad.
    if choice.finish_reason.as_deref() == Some("length") {
        tracing::warn!("chat summariser: model hit max_tokens; keeping the fallback title");
        return None;
    }
    let raw = choice
        .message
        .content
        .as_ref()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())?;

    // Reasoning is never the answer. A model that mirrors its scratchpad into `content`
    // has told us nothing usable, and the fallback title is the honest outcome.
    if let Some(reasoning) = choice.message.reasoning_content.as_deref() {
        if !reasoning.trim().is_empty() && raw == reasoning.trim() {
            tracing::warn!("chat summariser: model returned only its reasoning; keeping the fallback title");
            return None;
        }
    }

    // Strip optional <think>…</think> blocks some local models emit.
    let cleaned = strip_think_blocks(&raw);
    let mut lines = cleaned.lines().map(str::trim).filter(|l| !l.is_empty());
    let title: String = strip_label(lines.next()?).chars().take(80).collect();
    let summary = lines
        .map(strip_label)
        .collect::<Vec<_>>()
        .join(" ");
    if title.is_empty() {
        return None;
    }
    let result = SessionTitleSummary {
        title: title.clone(),
        summary: if summary.is_empty() {
            title.clone()
        } else {
            summary.chars().take(400).collect()
        },
    };
    crate::api::chat::llm_events::record_llm_call(
        username,
        session_id,
        "title",
        &model,
        started.elapsed().as_millis() as u32,
        result.title.len() as u32 + result.summary.len() as u32,
        true,
        "",
    )
    .await;
    Some(result)
}

/// Drop a `Title:` / `**Summary:**` style label the model prefixed to a line.
///
/// The prompt asks for two bare lines and Qwen3.5 answers with
/// `**Title:** Water Testing Document Identified` anyway. Labelling is the model being
/// helpful, but it lands verbatim in the sidebar, so it is stripped here rather than by
/// escalating the prompt — prompt wording is not a reliable parser.
fn strip_label(line: &str) -> String {
    const LABELS: [&str; 4] = ["title", "summary", "line 1", "line 2"];

    let trimmed = line.trim();
    // The emphasis can sit outside the colon (`**Title:**`) or inside it (`**Title**:`),
    // so the label is identified by stripping decoration from everything before the
    // first colon rather than by matching a fixed prefix.
    if let Some(colon) = trimmed.find(':') {
        let head: String = trimmed[..colon]
            .chars()
            .filter(|c| !matches!(c, '*' | '#' | '_'))
            .collect();
        if LABELS.contains(&head.trim().to_ascii_lowercase().as_str()) {
            return trimmed[colon + 1..]
                .trim()
                .trim_start_matches('*')
                .trim_matches('*')
                .trim()
                .to_string();
        }
    }
    // Not a label — a colon in ordinary prose ("Danube: a summary") must survive. Only
    // decoration wrapping the whole line is noise.
    trimmed
        .trim_start_matches('#')
        .trim()
        .trim_matches('*')
        .trim()
        .to_string()
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bold_label_is_stripped() {
        // Verbatim from a live Qwen3.5-2B run: the prompt asks for two bare lines and
        // the model labels them anyway.
        assert_eq!(
            strip_label("**Title:** Water Testing Document Identified"),
            "Water Testing Document Identified"
        );
        assert_eq!(
            strip_label("**Summary:** Search results located a PDF file."),
            "Search results located a PDF file."
        );
    }

    #[test]
    fn labels_are_stripped_in_every_spelling_the_model_uses() {
        for line in [
            "Title: Water levels",
            "title: Water levels",
            "**Title**: Water levels",
            "## Title: Water levels",
            "Line 1: Water levels",
        ] {
            assert_eq!(strip_label(line), "Water levels", "failed on {line:?}");
        }
    }

    #[test]
    fn an_unlabelled_line_keeps_its_text() {
        assert_eq!(strip_label("Water levels on the Danube"), "Water levels on the Danube");
        assert_eq!(strip_label("  spaced out  "), "spaced out");
    }

    #[test]
    fn emphasis_around_a_whole_line_is_dropped_but_inner_text_survives() {
        assert_eq!(strip_label("**Water levels**"), "Water levels");
        // A colon that is not a label must not truncate the title.
        assert_eq!(strip_label("Danube: a summary"), "Danube: a summary");
    }

    #[test]
    fn think_blocks_are_removed() {
        assert_eq!(strip_think_blocks("<think>hmm</think>Answer"), "Answer");
        assert_eq!(strip_think_blocks("no think here"), "no think here");
        // An unterminated block must not leave the whole response in place.
        assert_eq!(strip_think_blocks("before<think>never closed"), "before");
    }
}
