//! The task summaries of a chat transcript.
//!
//! A todo mutation row (`write_todo`, `edit_todo`, `mark_todo`) names the stored version
//! it produced. [`todo_summaries`] decides which of those rows show a task summary: a
//! successful row whose version is stored and whose visible state differs from the last
//! summary shown. Every todo call stays an inspectable tool row whether it shows a summary
//! or not.
//!
//! The visible state has two statuses. The store keeps older snapshots byte for byte, so
//! a legacy `in_progress` reads as pending and a legacy `cancelled` reads as done with
//! its note ([`display_status`]).

use std::collections::HashMap;

use crate::chat_types::{ChatMessageItem, ChatRole, TodoItemView, TodoSnapshot};

/// The todo tools whose rows can change the list.
pub const TODO_MUTATIONS: [&str; 3] = ["write_todo", "edit_todo", "mark_todo"];

/// The most words of a completion reason that a summary shows.
pub const REASON_WORDS: usize = 3;

/// Whether a row is a call to a tool that can change the todo list.
pub fn is_todo_mutation(message: &ChatMessageItem) -> bool {
    message.role == ChatRole::Tool && TODO_MUTATIONS.contains(&message.tool_name.as_str())
}

/// The status a reader sees: `pending` or `done`.
pub fn display_status(status: &str) -> &str {
    match status {
        "in_progress" => "pending",
        "cancelled" => "done",
        other => other,
    }
}

/// The first [`REASON_WORDS`] whitespace-separated words of a completion reason.
pub fn reason_label(note: &str) -> String {
    note.split_whitespace().take(REASON_WORDS).collect::<Vec<_>>().join(" ")
}

/// One item as a summary shows it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VisibleItem {
    pub id: String,
    pub text: String,
    pub done: bool,
    /// The shown reason of a done item, at most [`REASON_WORDS`] words. Empty otherwise.
    pub reason: String,
    /// The whole stored reason of a done item. Empty otherwise.
    pub full_reason: String,
    pub replaces_id: String,
}

impl VisibleItem {
    pub fn of(item: &TodoItemView) -> Self {
        let done = display_status(&item.status) == "done";
        VisibleItem {
            id: item.id.clone(),
            text: item.text.clone(),
            done,
            reason: if done { reason_label(&item.note) } else { String::new() },
            full_reason: if done { item.note.trim().to_string() } else { String::new() },
            replaces_id: item.replaces_id.clone(),
        }
    }
}

/// The part of a snapshot a summary shows: goal, item order, text, status, the shown
/// reason, and replacements. The version and the timestamp are not part of it.
pub fn visible_state(snapshot: &TodoSnapshot) -> (String, Vec<(String, String, bool, String, String)>) {
    let items = snapshot.items.iter().map(VisibleItem::of)
        .map(|item| (item.id, item.text, item.done, item.reason, item.replaces_id))
        .collect();
    (snapshot.goal.trim().to_string(), items)
}

/// The tool result object of a stored row: the `output.content` envelope, or the row
/// itself, with a JSON string decoded once.
fn result_object(tool_output: &str) -> serde_json::Value {
    let value = serde_json::from_str::<serde_json::Value>(tool_output).unwrap_or_default();
    let content = value.get("output").and_then(|output| output.get("content")).unwrap_or(&value).clone();
    match content {
        serde_json::Value::String(text) => serde_json::from_str(&text).unwrap_or(serde_json::Value::Null),
        other => other,
    }
}

/// The version a successful mutation row produced, or `None` for a failed, unreadable
/// or unfinished row.
pub fn mutation_version(message: &ChatMessageItem) -> Option<u32> {
    if !is_todo_mutation(message) {
        return None;
    }
    let result = result_object(&message.tool_output);
    let failed = result.get("success").and_then(|value| value.as_bool()) == Some(false)
        || result.get("error").is_some_and(|value| !value.is_null());
    if failed {
        return None;
    }
    result.get("version").and_then(|value| value.as_u64()).map(|version| version as u32)
}

/// The rows that show a task summary, by row index, with the snapshot each one shows.
///
/// Rows are read in transcript order. A successful mutation row whose snapshot is stored
/// shows a summary when the visible state differs from the last summary shown. A changed
/// goal always differs. A failed row, a read, a row whose snapshot has not arrived and a
/// row that changed nothing visible show none. When a snapshot arrives in a later poll,
/// the next call gives its row the summary at the row's own position.
pub fn todo_summaries(messages: &[ChatMessageItem], snapshots: &[TodoSnapshot]) -> HashMap<usize, TodoSnapshot> {
    let by_version: HashMap<u32, &TodoSnapshot> = snapshots.iter().map(|s| (s.version, s)).collect();
    let mut shown = None;
    let mut out = HashMap::new();
    for (index, message) in messages.iter().enumerate() {
        let Some(snapshot) = mutation_version(message).and_then(|version| by_version.get(&version)) else {
            continue;
        };
        let state = visible_state(snapshot);
        if shown.as_ref() != Some(&state) {
            out.insert(index, (*snapshot).clone());
            shown = Some(state);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn item(id: &str, text: &str, status: &str, note: &str) -> TodoItemView {
        TodoItemView { id: id.into(), text: text.into(), status: status.into(), note: note.into(),
                       replaces_id: String::new() }
    }

    fn snapshot(version: u32, goal: &str, items: Vec<TodoItemView>) -> TodoSnapshot {
        TodoSnapshot { version, goal: goal.into(), items }
    }

    fn row(seq: u32, tool: &str, output: &str) -> ChatMessageItem {
        let mut message: ChatMessageItem = serde_json::from_value(serde_json::json!({
            "seq": seq, "role": "Tool", "content": "", "tool_name": tool, "created_at": "",
        })).unwrap();
        message.tool_output = output.to_string();
        message
    }

    fn versioned(seq: u32, tool: &str, version: u32) -> ChatMessageItem {
        row(seq, tool, &serde_json::json!({"version": version}).to_string())
    }

    fn shown(summaries: &HashMap<usize, TodoSnapshot>) -> Vec<(usize, u32)> {
        let mut rows: Vec<_> = summaries.iter().map(|(index, s)| (*index, s.version)).collect();
        rows.sort();
        rows
    }

    #[test]
    fn the_reported_four_version_sequence_shows_two_summaries() {
        let texts = ["a", "b", "c", "d"];
        let pending = |texts: &[&str]| texts.iter().enumerate()
            .map(|(i, t)| item(&(i + 1).to_string(), t, "pending", "")).collect::<Vec<_>>();
        let started = |mut items: Vec<TodoItemView>| { items[0].status = "in_progress".into(); items };
        let revised = ["a2", "b2", "c", "d"];
        let snapshots = vec![
            snapshot(1, "g", pending(&texts)), snapshot(2, "g", started(pending(&texts))),
            snapshot(3, "g", pending(&revised)), snapshot(4, "g", started(pending(&revised))),
        ];
        let rows = vec![versioned(1, "write_todo", 1), versioned(2, "mark_todo", 2),
                        versioned(3, "write_todo", 3), versioned(4, "mark_todo", 4)];
        assert_eq!(shown(&todo_summaries(&rows, &snapshots)), vec![(0, 1), (2, 3)]);
        assert_eq!(rows.iter().filter(|r| is_todo_mutation(r)).count(), 4);
    }

    #[test]
    fn a_failed_an_unstored_and_an_identical_mutation_show_no_summary() {
        let snapshots = vec![snapshot(1, "g", vec![item("1", "a", "pending", "")])];
        let rows = vec![
            versioned(1, "write_todo", 1),
            row(2, "mark_todo", r#"{"success": false, "error": "a done step needs a short reason", "version": 1}"#),
            row(3, "edit_todo", "Error: 1 validation error for call[edit_todo]"),
            versioned(4, "write_todo", 1),
            versioned(5, "mark_todo", 2),
            versioned(6, "read_todo", 1),
        ];
        assert_eq!(shown(&todo_summaries(&rows, &snapshots)), vec![(0, 1)]);
    }

    #[test]
    fn a_snapshot_that_arrives_later_shows_its_summary_at_its_row() {
        let first = snapshot(1, "g", vec![item("1", "a", "pending", "")]);
        let rows = vec![versioned(1, "write_todo", 1), versioned(2, "mark_todo", 2)];
        assert_eq!(shown(&todo_summaries(&rows, &[first.clone()])), vec![(0, 1)]);
        let second = snapshot(2, "g", vec![item("1", "a", "done", "found")]);
        assert_eq!(shown(&todo_summaries(&rows, &[first, second])), vec![(0, 1), (1, 2)]);
    }

    #[test]
    fn a_reason_change_and_a_goal_change_are_visible() {
        let rows = vec![versioned(1, "write_todo", 1), versioned(2, "mark_todo", 2),
                        versioned(3, "mark_todo", 3), versioned(4, "write_todo", 4)];
        let snapshots = vec![
            snapshot(1, "g", vec![item("1", "a", "pending", "")]),
            snapshot(2, "g", vec![item("1", "a", "done", "found")]),
            snapshot(3, "g", vec![item("1", "a", "done", "not found")]),
            snapshot(4, "other goal", vec![item("1", "a", "done", "not found")]),
        ];
        assert_eq!(shown(&todo_summaries(&rows, &snapshots)), vec![(0, 1), (1, 2), (2, 3), (3, 4)]);
    }

    #[test]
    fn a_legacy_cancelled_item_reads_as_done_with_its_reason() {
        let visible = VisibleItem::of(&item("1", "a", "cancelled", "the source is gone now"));
        assert!(visible.done);
        assert_eq!(visible.reason, "the source is");
        assert_eq!(visible.full_reason, "the source is gone now");
        let legacy = VisibleItem::of(&item("2", "b", "done", ""));
        assert!(legacy.done && legacy.reason.is_empty());
    }

    #[test]
    fn a_stored_item_without_a_replacement_field_still_reads() {
        let items: Vec<TodoItemView> = serde_json::from_str(
            r#"[{"id":"1","text":"a","status":"done","note":"found"},{"id":"2","text":"b","status":"pending","note":"","replaces_id":"1"}]"#,
        ).unwrap();
        assert_eq!(items[0].replaces_id, "");
        assert_eq!(items[1].replaces_id, "1");
    }
}
