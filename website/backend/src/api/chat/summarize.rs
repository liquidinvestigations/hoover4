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

    // Unset `LLM_MODEL` disables the summariser entirely, and used to do so in complete
    // silence — every conversation kept its truncated first message as a title, no
    // summary ever appeared on the homepage cards, and nothing anywhere said why. Say
    // it once per turn rather than making the next person bisect the chat page.
    let Some(model) = llm_model() else {
        tracing::warn!(
            "chat summariser disabled: LLM_MODEL is unset, so titles stay as the \
             truncated first message and summaries stay empty. Set LLM_MODEL / \
             LLM_BASE_URL on the website service."
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
    let title: String = strip_label(lines.next()?).chars().take(80).collect();
    let summary = lines
        .map(strip_label)
        .collect::<Vec<_>>()
        .join(" ");
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
