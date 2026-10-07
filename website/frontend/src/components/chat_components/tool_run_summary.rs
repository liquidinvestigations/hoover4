//! The one-line summary of a run of consecutive tool rows in the transcript.
//!
//! The transcript shows each run of tool rows collapsed behind this line, and the line
//! expands to the cards. The line counts what the calls did, in a fixed order of kinds,
//! then the failed calls, then the time the run took. The time is always shown.

use common::chat_types::ChatMessageItem;

use crate::components::chat_components::tool_cards::{tool_content, tool_failure};

/// One kind of call on the summary line. The line lists the kinds in this order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum Kind {
    Search,
    Read,
    WebSearch,
    WebRead,
    Browser,
    Entities,
    Cite,
    WebCite,
    Skill,
    Note,
    Todo,
    Instruction,
    Other,
}

impl Kind {
    fn of(tool_name: &str) -> Kind {
        match tool_name {
            "search_collections" | "search_passages" | "folder_search" => Kind::Search,
            "read_documents" | "read_more" | "doc_search_text" | "doc_sources"
            | "doc_metadata" | "doc_email" | "doc_diff_sources" | "pdf_search"
            | "get_document_text" => Kind::Read,
            "web_search" => Kind::WebSearch,
            "read_page" => Kind::WebRead,
            "list_document_entities" => Kind::Entities,
            "cite_documents" => Kind::Cite,
            "cite_pages" => Kind::WebCite,
            "write_todo" | "edit_todo" | "mark_todo" | "read_todo" => Kind::Todo,
            "search_skills" | "read_skill" | "read_tool" | "search_agent_tools" => Kind::Skill,
            "write_note" => Kind::Note,
            name if name.starts_with("browser_") => Kind::Browser,
            _ => Kind::Other,
        }
    }

    /// The phrase for `n` of this kind's unit.
    fn phrase(self, n: u64) -> String {
        let s = |one: &str, many: &str| if n == 1 { one.to_string() } else { many.to_string() };
        match self {
            Kind::Search => format!("searched {n} {}", s("term", "terms")),
            Kind::Read => format!("read {n} {}", s("document", "documents")),
            Kind::WebSearch => format!("searched the web for {n} {}", s("term", "terms")),
            Kind::WebRead => format!("read {n} web {}", s("page", "pages")),
            Kind::Browser => format!("{n} browser {}", s("action", "actions")),
            Kind::Entities => format!("listed the entities of {n} {}", s("document", "documents")),
            Kind::Cite => format!("cited {n} {}", s("document", "documents")),
            Kind::WebCite => format!("cited {n} web {}", s("page", "pages")),
            Kind::Skill => format!("read {n} {} and tool texts", s("skill", "skills")),
            Kind::Note => format!("saved {n} {}", s("note", "notes")),
            Kind::Todo => format!("{n} todo list {}", s("call", "calls")),
            Kind::Instruction => format!("{n} {} to the agent", s("instruction", "instructions")),
            Kind::Other => format!("{n} other {}", s("call", "calls")),
        }
    }
}

/// The arguments object of a stored tool row.
fn arguments(tool_input: &str) -> serde_json::Value {
    let root: serde_json::Value = serde_json::from_str(tool_input).unwrap_or_default();
    match root.get("input") {
        Some(inner) if inner.is_object() => inner.clone(),
        _ => root,
    }
}

/// The count of items in the argument `key`: the length of a list, 1 for a non-empty
/// string, and 0 otherwise.
fn items(args: &serde_json::Value, key: &str) -> u64 {
    match args.get(key) {
        Some(serde_json::Value::Array(list)) => list.len() as u64,
        Some(serde_json::Value::String(text)) if !text.trim().is_empty() => 1,
        _ => 0,
    }
}

/// What one call adds to its kind's count. A call whose arguments name no unit counts 1.
fn units(kind: Kind, args: &serde_json::Value) -> u64 {
    let n = match kind {
        Kind::Search | Kind::WebSearch => items(args, "queries") + items(args, "query"),
        Kind::Read | Kind::Entities => items(args, "file_hash") + items(args, "documents"),
        Kind::WebRead => items(args, "urls") + items(args, "url"),
        Kind::Cite => items(args, "citations"),
        Kind::WebCite => items(args, "pages"),
        _ => 1,
    };
    n.max(1)
}

/// True when the stored result of a tool row says that the call failed.
fn failed(message: &ChatMessageItem) -> bool {
    tool_content(&message.tool_output)
        .as_ref()
        .and_then(tool_failure)
        .is_some()
}

/// Milliseconds since 1970 of a stored time: `2026-09-26 23:31:52.213`, or the same with a
/// `T`. The zone is ignored, because every row of a transcript has the same one.
pub fn timestamp_ms(text: &str) -> Option<i64> {
    let b = text.trim().as_bytes();
    if b.len() < 19 {
        return None;
    }
    let num = |from: usize, to: usize| -> Option<i64> {
        std::str::from_utf8(&b[from..to]).ok()?.parse::<i64>().ok()
    };
    let (year, month, day) = (num(0, 4)?, num(5, 7)?, num(8, 10)?);
    let (hour, minute, second) = (num(11, 13)?, num(14, 16)?, num(17, 19)?);
    let mut millis = 0;
    if b.len() > 20 && b[19] == b'.' {
        let digits: String = text.trim()[20..].chars().take_while(char::is_ascii_digit).take(3).collect();
        if !digits.is_empty() {
            millis = format!("{digits:0<3}").parse::<i64>().ok()?;
        }
    }
    // Days from 1970-01-01 to the date, by the proleptic Gregorian calendar.
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    let days = era * 146_097 + doe - 719_468;
    Some(((days * 24 + hour) * 60 + minute) * 60_000 + second * 1000 + millis)
}

/// `8m12s`, `45s` or `1h02m`.
pub fn duration_text(ms: i64) -> String {
    let secs = (ms.max(0) + 500) / 1000;
    let (h, m, s) = (secs / 3600, secs / 60 % 60, secs % 60);
    if h > 0 {
        format!("{h}h{m:02}m")
    } else if m > 0 {
        format!("{m}m{s:02}s")
    } else {
        format!("{s}s")
    }
}

/// The time a run of tool rows took: from the row before the run, which is the question or
/// the text the agent wrote before its first call, to the last row of the run. `None` when
/// a time cannot be read.
pub fn run_duration_ms(before: Option<&ChatMessageItem>, rows: &[ChatMessageItem]) -> Option<i64> {
    let end = rows.iter().filter_map(|m| timestamp_ms(&m.created_ms)).max()?;
    let start = before
        .and_then(|m| timestamp_ms(&m.created_ms))
        .or_else(|| rows.iter().filter_map(|m| timestamp_ms(&m.created_ms)).min())?;
    Some(end - start)
}

/// The summary line of a run of tool rows, for example `Searched 20 terms, read 8
/// documents, 2 failed, took 8m12s`. `duration_ms` is `None` when no time could be read,
/// and the line then says so.
pub fn tool_run_summary(rows: &[ChatMessageItem], duration_ms: Option<i64>) -> String {
    let mut counts: Vec<(Kind, u64)> = Vec::new();
    let mut failures = 0u64;
    for row in rows {
        if row.role == common::chat_types::ChatRole::Assistant { continue; }
        let kind = if row.role.is_instruction() {
            Kind::Instruction
        } else {
            Kind::of(&row.tool_name)
        };
        let n = units(kind, &arguments(&row.tool_input));
        match counts.iter_mut().find(|(k, _)| *k == kind) {
            Some((_, total)) => *total += n,
            None => counts.push((kind, n)),
        }
        if failed(row) {
            failures += 1;
        }
    }
    counts.sort_by_key(|(kind, _)| *kind);
    let mut parts: Vec<String> = counts.into_iter().map(|(kind, n)| kind.phrase(n)).collect();
    if failures > 0 {
        parts.push(format!("{failures} failed"));
    }
    parts.push(match duration_ms {
        Some(ms) => format!("took {}", duration_text(ms)),
        None => "time not recorded".to_string(),
    });
    let line = parts.join(", ");
    let mut chars = line.chars();
    match chars.next() {
        Some(first) => first.to_uppercase().chain(chars).collect(),
        None => line,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::chat_types::ChatRole;

    fn tool(tool_name: &str, tool_input: &str, tool_output: &str, created_ms: &str) -> ChatMessageItem {
        ChatMessageItem {
            seq: 0,
            role: ChatRole::Tool,
            content: String::new(),
            tool_name: tool_name.to_string(),
            tool_input: tool_input.to_string(),
            tool_output: tool_output.to_string(),
            doc_refs: String::new(),
            created_at: String::new(),
            created_ms: created_ms.to_string(),
            agent_duration_ms: 0,
            retry_errors: String::new(),
            reasoning: String::new(),
            context_tokens: 0,
            peak_context_tokens: 0,
            context_window: 0,
            streaming: false,
            usage_json: String::new(),
        }
    }

    #[test]
    fn a_run_counts_terms_and_documents_in_kind_order_then_failures_then_time() {
        let rows = vec![
            tool("read_documents", r#"{"collectionname": "enron", "file_hash": ["a", "b", "c"]}"#, "{}", "2026-09-26 23:33:18.542"),
            tool("search_collections", r#"{"queries": ["x", "y", "z"]}"#, "{}", "2026-09-26 23:32:05.106"),
            tool("search_collections", r#"{"query": "w"}"#, r#"{"success": false, "error": "repeated_call"}"#, "2026-09-26 23:32:13.452"),
            tool("write_todo", r#"{"goal": "g", "steps": ["a"]}"#, "{}", "2026-09-26 23:31:57.414"),
        ];
        let before = tool("", "", "", "2026-09-26 23:31:52.213");
        let ms = run_duration_ms(Some(&before), &rows);
        assert_eq!(ms, Some(86_329));
        assert_eq!(
            tool_run_summary(&rows, ms),
            "Searched 4 terms, read 3 documents, 1 todo list call, 1 failed, took 1m26s"
        );
    }

    #[test]
    fn the_time_crosses_midnight_and_a_missing_time_is_named() {
        let rows = vec![tool("read_documents", r#"{"file_hash": "a"}"#, "{}", "2026-09-27 00:14:08.500")];
        let before = tool("", "", "", "2026-09-26 23:31:52.213");
        assert_eq!(run_duration_ms(Some(&before), &rows).map(duration_text), Some("42m16s".to_string()));
        assert_eq!(tool_run_summary(&rows, None), "Read 1 document, time not recorded");
    }

    #[test]
    fn durations_read_as_seconds_minutes_or_hours() {
        assert_eq!(duration_text(4_400), "4s");
        assert_eq!(duration_text(492_000), "8m12s");
        assert_eq!(duration_text(3_720_000), "1h02m");
    }

    #[test]
    fn a_timestamp_reads_with_a_t_and_without_a_fraction() {
        assert_eq!(timestamp_ms("1970-01-01T00:00:01Z"), Some(1000));
        assert_eq!(timestamp_ms("1970-01-02 00:00:00.5"), Some(86_400_500));
        assert_eq!(timestamp_ms("not a time"), None);
    }

    #[test]
    fn web_calls_and_unknown_tools_have_their_own_phrases() {
        let rows = vec![
            tool("web_search", r#"{"queries": ["a"]}"#, "{}", ""),
            tool("read_page", r#"{"urls": ["https://a.example", "https://b.example"]}"#, "{}", ""),
            tool("whois_lookup", r#"{"domains": ["a.example"]}"#, "{}", ""),
        ];
        assert_eq!(
            tool_run_summary(&rows, Some(5_000)),
            "Searched the web for 1 term, read 2 web pages, 1 other call, took 5s"
        );
    }

    #[test]
    fn earlier_answers_do_not_count_as_calls_and_page_citations_count_pages() {
        let mut earlier = tool("", "", "", "");
        earlier.role = ChatRole::Assistant;
        earlier.content = "Earlier answer".into();
        let rows = vec![earlier, tool("cite_pages", r#"{"pages":[{"url":"https://a.example"},{"url":"https://b.example"}]}"#, "{}", "")];
        assert_eq!(tool_run_summary(&rows, Some(1_000)), "Cited 2 web pages, took 1s");
    }
}
