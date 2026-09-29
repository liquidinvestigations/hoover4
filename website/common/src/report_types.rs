//! The typed report of an agent run thread, as the worker writes it.
//!
//! The worker (`tasks/P_agent/reports.py`) writes two plan documents for each sub-agent
//! thread of a plan: `report`, a text body, and `report_data`, the JSON of [`ReportData`].
//! Model text (`final_answer`, `recent_text`) and the metadata that code wrote (the
//! evidence lists and the diagnostics) are separate fields, so a reader shows them apart.
//! A report from before the typed document has the text body only, which
//! [`parse_section_report`] returns as [`SectionReport::Legacy`].
//!
//! Every field has a default, so a report with a field that this reader does not know, or
//! without one that it knows, still reads.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// The `version` of the report shape this reader knows.
pub const REPORT_VERSION: u32 = 1;

/// Where a model text is in its thread.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct TextSource {
    pub thread_id: String,
    pub message_idx: i64,
}

/// Where an evidence entry is: its thread, its message, and its item in the message.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct EvidenceSource {
    pub thread_id: String,
    pub message_idx: i64,
    pub item_key: String,
}

/// One evidence entry of a tool result: a document read, a document a search found, a
/// citation, a note or an artifact.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct EvidenceEntry {
    pub version: u32,
    pub source: EvidenceSource,
    /// `document_read`, `discovery`, `citation`, `note` or `artifact`.
    pub kind: String,
    /// `ok`, `partial` or `error`.
    pub status: String,
    /// The identity of the item. Its keys depend on `kind`.
    pub reference: Map<String, Value>,
    /// The page or byte span of a read, when the result states it.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub range: Option<Map<String, Value>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl EvidenceEntry {
    /// A string value of the reference, or "".
    pub fn reference_str(&self, key: &str) -> &str {
        self.reference.get(key).and_then(Value::as_str).unwrap_or("")
    }
}

/// How the thread's newest run ended.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct ReportExecution {
    pub state: String,
    pub end_reason: String,
    /// True when the run did not complete with an answer.
    pub incomplete: bool,
    pub error: String,
}

/// One text that the model wrote.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct ReportText {
    pub source: Option<TextSource>,
    pub text: String,
    /// True when the final answer is a question to the person.
    pub asked: bool,
}

/// The citation check of the final answer against the session's citation results.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct CitationCheck {
    pub labels: Vec<String>,
    /// Labels that no successful citation result gives.
    pub unresolved: Vec<String>,
    /// Labels that results give for more than one document.
    pub conflicting: Vec<String>,
    pub unverified_quotes: Vec<Value>,
}

/// What code found about the run, apart from the model text.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ReportDiagnostics {
    pub failed_items: u64,
    pub unanswered_calls: Vec<Value>,
    pub legacy_tool_messages: u64,
    pub citation_check: CitationCheck,
    pub repair_round: bool,
    /// The entries of each list that the report left out.
    pub left_out: BTreeMap<String, u64>,
}

/// The typed report of one thread (`report_data`).
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
#[serde(default)]
pub struct ReportData {
    pub version: u32,
    pub thread_id: String,
    pub first_run_id: String,
    pub plan_run_id: String,
    pub section_node_id: String,
    pub execution: ReportExecution,
    pub final_answer: Option<ReportText>,
    pub recent_text: Vec<ReportText>,
    pub documents_read: Vec<EvidenceEntry>,
    pub documents_found: Vec<EvidenceEntry>,
    pub citations: Vec<EvidenceEntry>,
    pub notes: Vec<EvidenceEntry>,
    pub artifacts: Vec<EvidenceEntry>,
    pub diagnostics: ReportDiagnostics,
}

impl ReportData {
    /// The reads that returned text, whole or partial.
    pub fn successful_reads(&self) -> impl Iterator<Item = &EvidenceEntry> {
        self.documents_read.iter().filter(|e| e.status != "error")
    }

    /// The reads and citations that failed.
    pub fn failed_items(&self) -> impl Iterator<Item = &EvidenceEntry> {
        self.documents_read.iter().chain(self.citations.iter()).filter(|e| e.status == "error")
    }
}

/// The report of a section, as its documents give it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "shape", rename_all = "snake_case")]
pub enum SectionReport {
    /// A `report_data` document that parses.
    Typed { data: ReportData },
    /// Only the text `report` document: a report from before the typed document, or a
    /// typed document that does not parse.
    Legacy { text: String },
    /// No report document.
    Missing,
}

/// The report of a section from the body of its `report_data` document and of its
/// `report` document. The typed document wins when it parses.
pub fn parse_section_report(report_data: Option<&str>, report_text: Option<&str>) -> SectionReport {
    if let Some(body) = report_data {
        if let Ok(data) = serde_json::from_str::<ReportData>(body) {
            return SectionReport::Typed { data };
        }
    }
    match report_text {
        Some(text) => SectionReport::Legacy { text: text.to_string() },
        None => SectionReport::Missing,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const TYPED: &str = r#"{
        "version": 1, "thread_id": "t", "first_run_id": "r", "plan_run_id": "p",
        "section_node_id": "n",
        "execution": {"state": "completed", "end_reason": "step_budget", "incomplete": true,
                      "error": ""},
        "final_answer": null,
        "recent_text": [{"source": {"thread_id": "t", "message_idx": 3}, "text": "Draft."}],
        "documents_read": [
          {"version": 1, "source": {"thread_id": "t", "message_idx": 2, "item_key": "read:a:1"},
           "kind": "document_read", "status": "partial",
           "reference": {"collectionname": "c", "file_hash": "aaaa", "path": "/a.txt"},
           "range": {"page": 1, "start_bytes": 0, "end_bytes": 10, "total_bytes": 90}},
          {"version": 1, "source": {"thread_id": "t", "message_idx": 2, "item_key": "read:b:1"},
           "kind": "document_read", "status": "error", "reference": {"file_hash": "bbbb"},
           "error": "not found"}
        ],
        "documents_found": [], "citations": [], "notes": [], "artifacts": [],
        "diagnostics": {"failed_items": 1, "unanswered_calls": [], "legacy_tool_messages": 0,
                        "citation_check": {"labels": ["[D1]"], "unresolved": ["[D1]"],
                                           "conflicting": [], "unverified_quotes": []},
                        "repair_round": true, "left_out": {}, "a_new_key": 5}
    }"#;

    #[test]
    fn a_typed_report_keeps_model_text_and_metadata_apart() {
        let SectionReport::Typed { data } = parse_section_report(Some(TYPED), Some("text")) else {
            panic!("not typed");
        };
        assert_eq!(data.execution.end_reason, "step_budget");
        assert!(data.execution.incomplete);
        assert!(data.final_answer.is_none());
        assert_eq!(data.recent_text[0].text, "Draft.");
        assert_eq!(data.successful_reads().count(), 1);
        assert_eq!(data.failed_items().count(), 1);
        assert_eq!(data.documents_read[0].reference_str("path"), "/a.txt");
        assert_eq!(data.documents_read[1].source.item_key, "read:b:1");
        assert_eq!(data.diagnostics.citation_check.unresolved, vec!["[D1]".to_string()]);
    }

    #[test]
    fn a_report_with_only_text_reads_as_legacy() {
        assert_eq!(
            parse_section_report(None, Some("The old report.")),
            SectionReport::Legacy { text: "The old report.".into() }
        );
        assert_eq!(
            parse_section_report(Some("not json"), Some("The old report.")),
            SectionReport::Legacy { text: "The old report.".into() }
        );
        assert_eq!(parse_section_report(None, None), SectionReport::Missing);
    }

    #[test]
    fn a_report_with_missing_fields_reads_with_defaults() {
        let SectionReport::Typed { data } = parse_section_report(Some(r#"{"version": 1}"#), None)
        else {
            panic!("not typed");
        };
        assert_eq!(data.version, REPORT_VERSION);
        assert!(data.documents_read.is_empty());
        assert_eq!(data.diagnostics, ReportDiagnostics::default());
    }
}
