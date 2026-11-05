//! Stable navigation targets for one document and find query.

use serde::{Deserialize, Serialize};
use crate::search_result::DocumentIdentifier;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum DocumentMatchTarget {
    Header { field: String, occurrence: u32, start_char: u32, end_char: u32 },
    Body { extracted_by: String, page_id: u32, ordinal: u64 },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchCompleteness { Complete, AtLeast, Unavailable }

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentMatches {
    pub document_identifier: DocumentIdentifier,
    pub find_query: String,
    pub targets: Vec<DocumentMatchTarget>,
    pub completeness: MatchCompleteness,
}

/// Count each logical header occurrence once, including equal recipient values.
pub fn header_targets(envelope: &crate::email_graph::EmailEnvelope) -> Vec<DocumentMatchTarget> {
    let mut fields = vec![("subject", 0, envelope.subject.clone())];
    for (field, parties) in [("from", &envelope.from), ("to", &envelope.to), ("cc", &envelope.cc), ("bcc", &envelope.bcc)] {
        fields.extend(parties.iter().enumerate().map(|(i, party)| (field, i as u32, party.full())));
    }
    if let Some(date) = envelope.date_sent {
        fields.push(("date", 0, crate::document_provenance::format_epoch_utc(date)));
    }
    let mut targets = Vec::new();
    for (field, occurrence, text) in fields {
        let Some(spans) = envelope.header_highlights.get(&text) else { continue };
        if spans.iter().map(|span| span.text.as_str()).collect::<String>() != text { continue; }
        let mut offset = 0;
        for span in spans {
            let end = offset + span.text.chars().count() as u32;
            if span.is_highlighted {
                targets.push(DocumentMatchTarget::Header { field: field.into(), occurrence, start_char: offset, end_char: end });
            }
            offset = end;
        }
    }
    targets
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn old_response_shapes_keep_additive_defaults() {
        let tree: crate::storage_tree::CollectionNode = serde_json::from_str(r#"{"collectionname":"c","datasets":[]}"#).unwrap();
        assert!(tree.display_name.is_none());
        let facet: crate::search_result::SearchResultFacetItem = serde_json::from_str(r#"{"display_string":"x","original_value":{"String":"x"},"count":1}"#).unwrap();
        assert!(facet.descriptor.is_none());
        let graph: crate::email_graph::EmailGraph = serde_json::from_str(r#"{"nodes":[],"edges":[],"cluster_size":0,"truncated":false}"#).unwrap();
        assert!(!graph.cluster_size_complete);
        assert!(!graph.occurrences_truncated);
    }

    #[test]
    fn equal_recipient_values_keep_distinct_occurrences() {
        let party = crate::email_graph::EmailParty { address: "a@example.org".into(), display_name: String::new() };
        let mut envelope = crate::email_graph::EmailEnvelope { to: vec![party.clone(), party.clone()], ..Default::default() };
        envelope.header_highlights.insert(party.full(), vec![crate::text_highlight::HighlightTextSpan {
            text: party.full(), is_highlighted: true, index: 0,
        }]);
        let targets = header_targets(&envelope);
        assert_eq!(targets.len(), 2);
        assert_ne!(targets[0], targets[1]);
    }
}
