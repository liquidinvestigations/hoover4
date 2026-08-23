//! The `list_document_entities` card: what the tool found, and the way into each card.
//!
//! **Only a rule-found value is a link.** The explainer card is fetched with the rule
//! that accepted the value, so a value no rule produced has no card to open. The tool
//! answers in two tiers for exactly that reason — a language model's reading of the prose
//! against a validator's arithmetic — and this card keeps the two apart: the structured
//! tier is clickable, the model tier is text with a line saying why.
//!
//! **A link needs the dataset, and the tool does not name one.** It answers with the
//! collection and the content hash; the viewer is addressed by dataset and hash. The
//! dataset comes from the rest of the conversation, where a search result or a citation
//! named it for the same hash. When nothing in the conversation did, the values render as
//! text under a line that says so — an unopenable value has to look unopenable, because a
//! link that resolves for some values and silently does nothing for others is worse than
//! no link at all.
//!
//! Every string here is a text node — see the module docstring in `tool_cards/mod.rs`.

use std::collections::HashMap;

use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use crate::components::chat_components::tool_cards::{
    json_str, tool_content, tool_failure, CardShell,
};
use crate::routes::Route;

/// One document's answer, in the shape the card renders it.
#[derive(Debug, Clone, PartialEq)]
struct DocumentEntities {
    collectionname: String,
    file_hash: String,
    /// The rule scanner's tier: value and the rule that accepted it.
    structured: Vec<(String, String)>,
    /// The NER tier, flattened across its types. No rule, so no card.
    model_found: Vec<String>,
    error: String,
}

/// Both shapes the tool has answered in: a batch of documents, and — in a conversation
/// recorded before the tool was batched — one document at the top level. A card that read
/// only the newer shape would render nothing for a transcript that is still perfectly
/// readable.
fn parse_documents(content: &serde_json::Value) -> Vec<DocumentEntities> {
    match content.get("documents").and_then(|d| d.as_array()) {
        Some(items) => items.iter().map(parse_document).collect(),
        None => vec![parse_document(content)],
    }
}

fn parse_document(v: &serde_json::Value) -> DocumentEntities {
    let structured = v
        .get("structured")
        .and_then(|s| s.as_array())
        .map(|items| {
            items
                .iter()
                .filter(|e| !json_str(e, "rule_id").is_empty())
                .map(|e| (json_str(e, "value"), json_str(e, "rule_id")))
                .filter(|(value, _)| !value.is_empty())
                .collect()
        })
        .unwrap_or_default();
    let model_found = v
        .get("entities")
        .and_then(|e| e.as_object())
        .map(|types| {
            types
                .values()
                .filter_map(|list| list.as_array())
                .flatten()
                .filter_map(|value| value.as_str())
                .filter(|value| !value.is_empty())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    DocumentEntities {
        collectionname: json_str(v, "collectionname"),
        file_hash: json_str(v, "file_hash"),
        structured,
        model_found,
        error: json_str(v, "error"),
    }
}

#[component]
pub fn EntitiesCard(
    tool_input: String,
    tool_output: String,
    running: bool,
    /// Every `file_hash` this conversation has named a dataset for. Without an entry a
    /// document's values cannot be addressed and are rendered as plain text.
    #[props(default)]
    datasets: HashMap<String, String>,
) -> Element {
    // Open by default: the links are the point of the card, and a route nobody can see
    // until they click "Expand" is a route nobody uses.
    let expanded = use_signal(|| true);

    let content = tool_content(&tool_output);
    let documents = content.as_ref().map(parse_documents).unwrap_or_default();
    let failure = content.as_ref().and_then(tool_failure);
    let note = content.as_ref().map(|c| json_str(c, "note")).unwrap_or_default();

    let asked_for = serde_json::from_str::<serde_json::Value>(&tool_input)
        .ok()
        .and_then(|v| {
            v.get("documents")
                .and_then(|d| d.as_array())
                .map(Vec::len)
                .or(Some(1))
        })
        .unwrap_or(1);
    let count = if running { asked_for } else { documents.len().max(1) };
    let label = format!(
        "listed entities \u{b7} {count} document{}",
        if count == 1 { "" } else { "s" }
    );
    let openable: usize = documents
        .iter()
        .filter(|d| datasets.contains_key(&d.file_hash))
        .map(|d| d.structured.len())
        .sum();

    rsx! {
        CardShell {
            chip: "list_document_entities".to_string(),
            label,
            running,
            expanded,
            failure,
            badges: rsx! {
                if !running && openable > 0 {
                    span {
                        style: "flex-shrink: 0; font-size: 11px; color: #78350F; \
                                background: #FDE68A; border-radius: 999px; padding: 1px 8px;",
                        "{openable} with a card"
                    }
                }
            },
            div {
                style: "margin-top: 8px; display: flex; flex-direction: column; gap: 10px;",
                if !note.is_empty() {
                    div { style: "font-size: 12px; font-style: italic;", "{note}" }
                }
                for document in documents.clone() {
                    DocumentEntityRow {
                        key: "{document.file_hash}",
                        document: document.clone(),
                        collection_dataset: datasets.get(&document.file_hash).cloned(),
                    }
                }
            }
        }
    }
}

#[component]
fn DocumentEntityRow(
    document: DocumentEntities,
    collection_dataset: Option<String>,
) -> Element {
    let identifier = collection_dataset.map(|collection_dataset| DocumentIdentifier {
        collection_dataset,
        file_hash: document.file_hash.clone(),
    });
    // Enough of the hash to tell two documents of one collection apart in a card that
    // lists several, without a line of hexadecimal across the transcript.
    let short_hash: String = document.file_hash.chars().take(10).collect();

    rsx! {
        div {
            style: "background: white; border: 1px solid #FDE68A; border-radius: 8px; \
                    padding: 7px 9px;",
            div {
                style: "font-size: 11px; font-family: ui-monospace, monospace; \
                        color: #92400E; margin-bottom: 5px;",
                "{document.collectionname} \u{b7} {short_hash}"
            }
            if !document.error.is_empty() {
                div { style: "font-size: 12px; color: #991B1B;", "{document.error}" }
            }
            if !document.structured.is_empty() {
                div {
                    style: "display: flex; flex-wrap: wrap; gap: 6px;",
                    for (value, rule_id) in document.structured.clone() {
                        if let Some(identifier) = identifier.clone() {
                            Link {
                                key: "s{value}",
                                to: Route::entity_card(identifier, value.clone()),
                                title: "Open the card for this value ({rule_id})",
                                style: "border: 1px solid #C7D2FE; background: #EEF2FF; \
                                        border-radius: 999px; padding: 1px 9px; \
                                        font-size: 12px; color: #3730A3; \
                                        text-decoration: none; word-break: break-all;",
                                "{value}"
                            }
                        } else {
                            span {
                                key: "s{value}",
                                title: "{rule_id}",
                                style: "border: 1px solid #E5E7EB; background: #F8FAFC; \
                                        border-radius: 999px; padding: 1px 9px; \
                                        font-size: 12px; color: #64748B; \
                                        word-break: break-all;",
                                "{value}"
                            }
                        }
                    }
                }
                if identifier.is_none() {
                    div {
                        style: "font-size: 11px; color: #92400E; margin-top: 4px;",
                        "No card: this conversation never named the dataset these values \
                         came from, and the viewer is addressed by dataset."
                    }
                }
            }
            if !document.model_found.is_empty() {
                div {
                    style: "display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px;",
                    for value in document.model_found.clone() {
                        span {
                            key: "m{value}",
                            style: "border: 1px solid #E5E7EB; background: #F8FAFC; \
                                    border-radius: 999px; padding: 1px 9px; font-size: 12px; \
                                    color: #64748B; word-break: break-all;",
                            "{value}"
                        }
                    }
                }
                div {
                    style: "font-size: 11px; color: #92400E; margin-top: 4px;",
                    "Names, organisations and places above are a model's reading of the \
                     prose. No rule validated them, so there is nothing to explain and \
                     they open nothing."
                }
            }
            if document.structured.is_empty() && document.model_found.is_empty()
                && document.error.is_empty() {
                div {
                    style: "font-size: 12px; color: #92400E;",
                    "Nothing extracted from this document."
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The tool answered with one document at the top level before it was batched, and
    /// those conversations are still readable.
    #[test]
    fn both_answer_shapes_parse() {
        let single = serde_json::json!({
            "collectionname": "testdata",
            "file_hash": "abc",
            "entities": {"PER": ["Ana"], "LOC": []},
            "structured": [{"value": "AD12", "rule_id": "bank.iban", "entity_type": "bank_account"}],
        });
        let parsed = parse_documents(&single);
        assert_eq!(parsed.len(), 1);
        assert_eq!(parsed[0].structured, vec![("AD12".to_string(), "bank.iban".to_string())]);
        assert_eq!(parsed[0].model_found, vec!["Ana".to_string()]);

        let batched = serde_json::json!({ "documents": [single.clone(), single] });
        assert_eq!(parse_documents(&batched).len(), 2);
    }

    /// A value with no rule behind it has no card, so it must not reach the linking
    /// branch at all — the tier it arrived in is not enough on its own.
    #[test]
    fn a_structured_value_without_a_rule_is_not_offered_a_card() {
        let document = serde_json::json!({
            "structured": [
                {"value": "AD12", "rule_id": "bank.iban"},
                {"value": "1971-11-30", "rule_id": ""},
            ],
        });
        let parsed = parse_document(&document);
        assert_eq!(parsed.structured.len(), 1, "only the value naming a rule");
        assert_eq!(parsed.structured[0].0, "AD12");
    }
}
