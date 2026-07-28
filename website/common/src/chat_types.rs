//! DTOs for the AI Chat page, shared between frontend and backend.

use crate::search_result::DocumentIdentifier;

/// A conversation, as shown in the history list / homepage cards.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatSessionItem {
    pub session_id: String,
    pub title: String,
    /// One-or-two sentence LLM summary for homepage cards. Empty until the first turn.
    #[serde(default)]
    pub summary: String,
    /// Collections this chat searches. Always a subset of the owner's permitted
    /// collections *at the time each message was sent* — it is re-checked per message,
    /// so a stale selection here cannot widen access.
    pub collections: Vec<String>,
    pub created_at: String,
    pub updated_at: String,
    pub message_count: u32,
}

/// Who produced one entry in the trajectory.
///
/// `Tool` and `Error` are first-class rather than folded into `Assistant` because the
/// point of showing a trajectory is being able to see what the agent actually did and
/// where it failed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum ChatRole {
    User,
    Assistant,
    Tool,
    Error,
}

impl ChatRole {
    /// Wire value stored in ClickHouse.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::Assistant => "assistant",
            Self::Tool => "tool",
            Self::Error => "error",
        }
    }

    /// Parse a stored value. Unknown values become `Error` rather than being dropped:
    /// a row we cannot interpret is still evidence that something happened, and hiding
    /// it would silently shorten a transcript.
    pub fn from_str(raw: &str) -> Self {
        match raw {
            "user" => Self::User,
            "assistant" => Self::Assistant,
            "tool" => Self::Tool,
            _ => Self::Error,
        }
    }

    /// Whether this entry is part of the conversation the LLM should be replayed, as
    /// opposed to a trace of how an answer was produced.
    pub fn is_conversational(&self) -> bool {
        matches!(self, Self::User | Self::Assistant)
    }
}

/// One document a tool step surfaced — enough to render a search-result card and open
/// the document preview (`DocumentIdentifier` = `collection_dataset` + `file_hash`).
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatDocRef {
    pub collection_dataset: String,
    pub file_hash: String,
    #[serde(default)]
    pub collectionname: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub page_id: Option<u32>,
    #[serde(default)]
    pub score: Option<f64>,
    #[serde(default)]
    pub snippet: String,
}

impl ChatDocRef {
    pub fn document_identifier(&self) -> DocumentIdentifier {
        DocumentIdentifier {
            collection_dataset: self.collection_dataset.clone(),
            file_hash: self.file_hash.clone(),
        }
    }

    /// Display title for a card: basename of `path`, or the file hash prefix.
    pub fn display_title(&self) -> String {
        if !self.path.is_empty() {
            self.path
                .rsplit('/')
                .next()
                .unwrap_or(self.path.as_str())
                .to_string()
        } else if self.file_hash.len() >= 12 {
            self.file_hash[..12].to_string()
        } else {
            self.file_hash.clone()
        }
    }
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatMessageItem {
    pub seq: u32,
    pub role: ChatRole,
    pub content: String,
    /// Set for `Tool` entries.
    pub tool_name: String,
    /// JSON arguments the model passed to the tool (role = tool).
    #[serde(default)]
    pub tool_input: String,
    /// JSON result, truncated to [`TOOL_PAYLOAD_CHARS`] (role = tool).
    #[serde(default)]
    pub tool_output: String,
    /// JSON array of [`ChatDocRef`] this step surfaced.
    #[serde(default)]
    pub doc_refs: String,
    pub created_at: String,
    /// Millisecond creation time (RFC3339 with fractional seconds when available).
    #[serde(default)]
    pub created_ms: String,
    /// Wall time the agent took to produce this row. 0 for user turns.
    #[serde(default)]
    pub agent_duration_ms: u32,
}

impl ChatMessageItem {
    /// Parsed [`ChatDocRef`] list, or empty when the column is blank / invalid.
    pub fn parsed_doc_refs(&self) -> Vec<ChatDocRef> {
        if self.doc_refs.is_empty() {
            return Vec::new();
        }
        serde_json::from_str(&self.doc_refs).unwrap_or_default()
    }
}

/// Result of [`send_message`](crate) / the matching server function.
///
/// When `retry_after_seconds` is `Some`, the rate limiter refused the turn and
/// `messages` is unchanged (nothing was written). The composer shows "try again in N s".
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatSendResult {
    pub messages: Vec<ChatMessageItem>,
    #[serde(default)]
    pub retry_after_seconds: Option<u64>,
}

/// A session plus its full trajectory.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatSessionDetail {
    pub session: ChatSessionItem,
    pub messages: Vec<ChatMessageItem>,
    /// The collections the owner may currently read — what the collection picker offers.
    /// Resolved fresh on every load, so a revoked permission disappears from the picker
    /// even in an old conversation.
    pub available_collections: Vec<String>,
}

/// Maximum length of one user message. Guards the agent's context window and keeps a
/// pasted document out of the chat table (that is what the collections are for).
pub const MAX_MESSAGE_CHARS: usize = 8_000;

/// How many characters of the first user message become the session title fallback.
pub const TITLE_CHARS: usize = 60;

/// Cap on `tool_output` (and a soft cap on `tool_input`) stored in `chat_messages`.
/// A `search_collections` result set with long snippets is large; this table is read on
/// every page load.
pub const TOOL_PAYLOAD_CHARS: usize = 12_000;

/// Derive a session title from its first user message.
pub fn title_from_message(message: &str) -> String {
    let flat: String = message.split_whitespace().collect::<Vec<_>>().join(" ");
    if flat.is_empty() {
        return "New chat".to_string();
    }
    if flat.chars().count() <= TITLE_CHARS {
        return flat;
    }
    format!("{}\u{2026}", flat.chars().take(TITLE_CHARS).collect::<String>())
}

/// Truncate a JSON/text payload for storage.
pub fn truncate_payload(text: &str, max_chars: usize) -> String {
    if text.chars().count() <= max_chars {
        return text.to_string();
    }
    format!("{}\u{2026}", text.chars().take(max_chars).collect::<String>())
}

/// Pull document references out of a completed tool call's name + input + output JSON.
///
/// Observed shapes (LangGraph tool events):
/// - start: `{"input": {…}}`
/// - end:   `{"output": {"content": …, "type": "tool", "name": "…", "tool_call_id": "…"}, …}`
///
/// `search_collections` content is `{"results":[{collection_dataset,file_hash,path,…}]}`.
/// `get_document_text` / `list_document_entities` / `show_document` content is a single
/// document object. Unknown tools are scanned for document-shaped objects generically.
pub fn extract_doc_refs(tool_name: &str, tool_output_json: &str) -> Vec<ChatDocRef> {
    let Ok(root) = serde_json::from_str::<serde_json::Value>(tool_output_json) else {
        return Vec::new();
    };
    let content = root
        .get("output")
        .and_then(|o| o.get("content"))
        .or_else(|| root.get("content"))
        .unwrap_or(&root);

    match tool_name {
        "search_collections" => extract_from_search_results(content),
        "get_document_text" | "list_document_entities" | "show_document" => {
            doc_ref_from_value(content).into_iter().collect()
        }
        _ => {
            // Generic: walk for document-shaped objects (have file_hash + a dataset key).
            let mut out = Vec::new();
            collect_document_shaped(content, &mut out);
            out
        }
    }
}

fn extract_from_search_results(content: &serde_json::Value) -> Vec<ChatDocRef> {
    let results = content
        .get("results")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    results.iter().filter_map(doc_ref_from_value).collect()
}

fn doc_ref_from_value(v: &serde_json::Value) -> Option<ChatDocRef> {
    let file_hash = v.get("file_hash")?.as_str()?.to_string();
    if file_hash.is_empty() {
        return None;
    }
    // Prefer collection_dataset (DocumentIdentifier key). Fall back to nothing rather
    // than inventing one from collectionname — a wrong dataset id opens the wrong doc.
    let collection_dataset = v
        .get("collection_dataset")
        .and_then(|x| x.as_str())
        .unwrap_or("")
        .to_string();
    if collection_dataset.is_empty() {
        // Still record path/hash so the disclosure UI can show something; the preview
        // card is only clickable when collection_dataset is set (frontend checks).
    }
    Some(ChatDocRef {
        collection_dataset,
        file_hash,
        collectionname: v
            .get("collectionname")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string(),
        path: v.get("path").and_then(|x| x.as_str()).unwrap_or("").to_string(),
        page_id: v.get("page_id").and_then(|x| x.as_u64()).map(|n| n as u32),
        score: v.get("score").and_then(|x| x.as_f64()),
        snippet: v
            .get("snippet")
            .and_then(|x| x.as_str())
            .unwrap_or("")
            .to_string(),
    })
}

fn collect_document_shaped(v: &serde_json::Value, out: &mut Vec<ChatDocRef>) {
    if let Some(r) = doc_ref_from_value(v) {
        out.push(r);
        return;
    }
    match v {
        serde_json::Value::Array(items) => {
            for item in items {
                collect_document_shaped(item, out);
            }
        }
        serde_json::Value::Object(map) => {
            for val in map.values() {
                collect_document_shaped(val, out);
            }
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roles_round_trip_through_their_wire_value() {
        for role in [ChatRole::User, ChatRole::Assistant, ChatRole::Tool, ChatRole::Error] {
            assert_eq!(ChatRole::from_str(role.as_str()), role);
        }
    }

    #[test]
    fn unknown_role_becomes_error_not_a_dropped_row() {
        assert_eq!(ChatRole::from_str("something_new"), ChatRole::Error);
        assert_eq!(ChatRole::from_str(""), ChatRole::Error);
    }

    #[test]
    fn only_user_and_assistant_replay_to_the_model() {
        assert!(ChatRole::User.is_conversational());
        assert!(ChatRole::Assistant.is_conversational());
        assert!(!ChatRole::Tool.is_conversational());
        assert!(!ChatRole::Error.is_conversational());
    }

    #[test]
    fn title_collapses_whitespace_and_truncates() {
        assert_eq!(title_from_message("  who   paid\nacme?  "), "who paid acme?");
        assert_eq!(title_from_message(""), "New chat");
        assert_eq!(title_from_message("   \n  "), "New chat");
        let long = "x".repeat(TITLE_CHARS + 10);
        let title = title_from_message(&long);
        assert_eq!(title.chars().count(), TITLE_CHARS + 1); // + the ellipsis
        assert!(title.ends_with('\u{2026}'));
    }

    #[test]
    fn title_of_exactly_the_limit_is_not_truncated() {
        let exact = "y".repeat(TITLE_CHARS);
        assert_eq!(title_from_message(&exact), exact);
    }

    #[test]
    fn extract_doc_refs_from_search_collections() {
        let output = r#"{
            "output": {
                "content": {
                    "success": true,
                    "results": [{
                        "collectionname": "testdata",
                        "collection_dataset": "testdata_testfiles",
                        "file_hash": "abc123",
                        "path": "/pdf-scans/PublicWaterMassMailing.pdf",
                        "page_id": 0,
                        "score": 2921.0,
                        "snippet": "water testing"
                    }]
                },
                "name": "search_collections"
            }
        }"#;
        let refs = extract_doc_refs("search_collections", output);
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].collection_dataset, "testdata_testfiles");
        assert_eq!(refs[0].file_hash, "abc123");
        assert_eq!(refs[0].display_title(), "PublicWaterMassMailing.pdf");
    }

    #[test]
    fn extract_doc_refs_from_get_document_text_without_dataset() {
        let output = r#"{
            "output": {
                "content": {
                    "collectionname": "testdata",
                    "file_hash": "abc123",
                    "path": "/x.pdf"
                },
                "name": "get_document_text"
            }
        }"#;
        let refs = extract_doc_refs("get_document_text", output);
        assert_eq!(refs.len(), 1);
        assert!(refs[0].collection_dataset.is_empty());
        assert_eq!(refs[0].file_hash, "abc123");
    }
}
