//! Citations of chats and boards in chat answers.
//!
//! The agent tool `cite_chats_and_boards` gives a handle for each chat or board that an
//! answer uses: `[Cn]` for a chat and `[Bn]` for a board. The handles of a chat session are
//! numbered once for the session, like the document handles `[Dn]`. The transcript reads the
//! citations from the stored tool rows with [`extract_item_refs`]. Each card loads the chat or
//! the board again with the read rule of the person who reads the transcript.

use serde::{Deserialize, Serialize};

use crate::board_types::BoardListItem;
use crate::chat_types::ChatSessionItem;
use crate::url_param::UrlParam;

/// The highest handle number of each kind in one session.
pub const MAX_ITEM_HANDLE: u16 = 200;

/// The `kind` of a chat citation.
pub const KIND_CHAT: &str = "chat";
/// The `kind` of a board citation.
pub const KIND_BOARD: &str = "board";

/// One citation of a chat or a board, as the tool result holds it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChatItemRef {
    pub handle: String,
    /// [`KIND_CHAT`] or [`KIND_BOARD`].
    pub kind: String,
    /// The session id of a chat, or the board id.
    pub id: String,
    /// The title when the agent cited the item. The card shows the title that the item has now.
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub why: String,
}

impl ChatItemRef {
    /// The address that opens the item.
    pub fn path(&self) -> String {
        if self.kind == KIND_BOARD { board_path(&self.id, "") } else { chat_path(&self.id) }
    }
}

/// The kind that a handle names: `[C3]` names a chat and `[B1]` names a board. `None` for any
/// other text and for a number outside 1 to [`MAX_ITEM_HANDLE`].
pub fn handle_kind(handle: &str) -> Option<&'static str> {
    let inner = handle.strip_prefix('[')?.strip_suffix(']')?;
    let (kind, digits) = match inner.chars().next()? {
        'C' => (KIND_CHAT, &inner[1..]),
        'B' => (KIND_BOARD, &inner[1..]),
        _ => return None,
    };
    let number = digits.parse::<u16>().ok().filter(|_| digits.chars().all(|c| c.is_ascii_digit()))?;
    (1..=MAX_ITEM_HANDLE).contains(&number).then_some(kind)
}

/// The address of a chat page.
pub fn chat_path(session_id: &str) -> String {
    let none = UrlParam::<Option<u8>>(None).to_string();
    format!("/ai_chat/c/{session_id}/{none}/{none}")
}

/// The address of a board page. `node` selects a node, empty for none.
pub fn board_path(board_id: &str, node: &str) -> String {
    if node.is_empty() {
        format!("/ai_chat/boards/{board_id}")
    } else {
        format!("/ai_chat/boards/{board_id}?selected={node}")
    }
}

/// The chat and board citations of one stored tool result, through the stored wrappers. A
/// citation whose handle does not match its kind is left out.
pub fn extract_item_refs(output: &str) -> Vec<ChatItemRef> {
    fn collect(value: &serde_json::Value, depth: usize, out: &mut Vec<ChatItemRef>) {
        if depth > 8 {
            return;
        }
        match value {
            serde_json::Value::String(text) => {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(text) {
                    collect(&parsed, depth + 1, out);
                }
            }
            serde_json::Value::Array(items) => {
                for item in items {
                    collect(item, depth + 1, out);
                }
            }
            serde_json::Value::Object(object) => {
                if object.contains_key("handle") {
                    if let Ok(item) = serde_json::from_value::<ChatItemRef>(value.clone()) {
                        if handle_kind(&item.handle) == Some(item.kind.as_str()) && !item.id.is_empty() {
                            out.push(item);
                        }
                    }
                }
                for key in ["output", "content", "text", "citations", "structuredContent"] {
                    if let Some(child) = object.get(key) {
                        collect(child, depth + 1, out);
                    }
                }
            }
            _ => {}
        }
    }
    let mut out = Vec::new();
    if let Ok(value) = serde_json::from_str(output) {
        collect(&value, 0, &mut out);
    }
    out
}

/// One citation for each handle, the first that the conversation gave.
pub fn merge_item_refs(refs: Vec<ChatItemRef>) -> Vec<ChatItemRef> {
    let mut merged: Vec<ChatItemRef> = Vec::new();
    for item in refs {
        if !merged.iter().any(|kept| kept.handle == item.handle) {
            merged.push(item);
        }
    }
    merged
}

/// `text` with each citation handle of another conversation written as a label in round
/// brackets: `[D1]` becomes `(D1)` and `[D1, W2]` becomes `(D1, W2)`. The read tools of chats
/// and boards return such text, so a model does not copy a handle that names another source
/// in its own conversation.
pub fn handles_as_labels(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut rest = text;
    while let Some(open) = rest.find('[') {
        out.push_str(&rest[..open]);
        let after = &rest[open + 1..];
        match after.find(']') {
            Some(close) if is_handle_list(&after[..close]) => {
                out.push('(');
                out.push_str(&after[..close]);
                out.push(')');
                rest = &after[close + 1..];
            }
            _ => {
                out.push('[');
                rest = after;
            }
        }
    }
    out.push_str(rest);
    out
}

/// The citation handles of `text` in text order, each once: `[D1]`, `[W2]`, `[C1]`, `[B3]`. A
/// list such as `[D1, W2]` gives each of its handles.
pub fn text_handles(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut rest = text;
    while let Some(open) = rest.find('[') {
        let after = &rest[open + 1..];
        match after.find(']') {
            Some(close) if is_handle_list(&after[..close]) => {
                for value in after[..close].split(',') {
                    let handle = format!("[{}]", value.trim());
                    if !out.contains(&handle) {
                        out.push(handle);
                    }
                }
                rest = &after[close + 1..];
            }
            _ => rest = after,
        }
    }
    out
}

fn is_handle_list(inner: &str) -> bool {
    !inner.trim().is_empty()
        && inner.split(',').all(|value| {
            let value = value.trim();
            let mut chars = value.chars();
            matches!(chars.next(), Some('D' | 'W' | 'C' | 'B'))
                && value.len() > 1
                && chars.all(|c| c.is_ascii_digit())
        })
}

/// The cards of the cited chats and boards that the reader can read now. An item that the
/// reader cannot read is absent.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize)]
pub struct CitedItemCards {
    pub chats: Vec<ChatSessionItem>,
    pub boards: Vec<BoardListItem>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn handles_name_their_kind() {
        assert_eq!(handle_kind("[C1]"), Some(KIND_CHAT));
        assert_eq!(handle_kind("[B200]"), Some(KIND_BOARD));
        assert_eq!(handle_kind("[B201]"), None);
        assert_eq!(handle_kind("[C0]"), None);
        assert_eq!(handle_kind("[D1]"), None);
        assert_eq!(handle_kind("[C+1]"), None);
        assert_eq!(handle_kind("C1"), None);
    }

    #[test]
    fn nested_tool_text_gives_the_citations_of_matching_kinds() {
        let content = serde_json::json!({"success": true, "citations": [
            {"handle": "[C1]", "kind": "chat", "id": "s1", "title": "Budget"},
            {"handle": "[B1]", "kind": "board", "id": "b1", "title": "Who paid"},
            {"handle": "[B2]", "kind": "chat", "id": "s2", "title": "Wrong kind"},
            {"handle": "[C3]", "kind": "chat", "id": "", "title": "No id"},
        ]});
        let output = serde_json::json!({"output": {"content": content.to_string()}});
        let refs = extract_item_refs(&output.to_string());
        assert_eq!(refs.iter().map(|r| r.handle.as_str()).collect::<Vec<_>>(), vec!["[C1]", "[B1]"]);
        assert_eq!(refs[1].path(), "/ai_chat/boards/b1");
        assert_eq!(refs[0].path(), "/ai_chat/c/s1/9g==/9g==");
    }

    #[test]
    fn handles_of_another_conversation_become_labels() {
        assert_eq!(
            handles_as_labels("Paid [D1]. See [D2, W1] and [C1][B2], not [note] or [D] or [x1]."),
            "Paid (D1). See (D2, W1) and (C1)(B2), not [note] or [D] or [x1]."
        );
        assert_eq!(handles_as_labels("open [ only"), "open [ only");
        assert_eq!(text_handles("A [D1], B [D2, C1] [x] [D1] [B3]"), vec!["[D1]", "[D2]", "[C1]", "[B3]"]);
    }

    #[test]
    fn repeated_citations_keep_the_first() {
        let one = ChatItemRef { handle: "[C1]".into(), kind: "chat".into(), id: "s".into(), title: "A".into(), why: String::new() };
        let mut two = one.clone();
        two.why = "again".into();
        assert_eq!(merge_item_refs(vec![one.clone(), two]), vec![one]);
    }
}
