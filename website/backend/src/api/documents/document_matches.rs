//! Assemble header and body navigation targets with explicit count completeness.

use std::collections::{BTreeSet};
use common::{current_user::CurrentUser, search_result::DocumentIdentifier};
use common::document_matches::{DocumentMatches, DocumentMatchTarget, MatchCompleteness};
use super::search_document_text::{document_hit_texts, highlight_email_headers, DOCUMENT_HIT_ROW_LIMIT};

pub async fn get_document_matches(user: &CurrentUser, identifier: DocumentIdentifier, find_query: String) -> anyhow::Result<DocumentMatches> {
    crate::auth::permissions::assert_can_read(user, &identifier.collection_dataset).await?;
    let mut targets = Vec::new();
    if let Some(mut envelope) = super::get_email_graph::get_email_envelope(user, identifier.clone()).await? {
        envelope.header_highlights = highlight_email_headers(user, &identifier, &find_query, &envelope).await?;
        targets.extend(common::document_matches::header_targets(&envelope));
    }
    let rows = document_hit_texts(&identifier, &find_query).await?;
    let mut completeness = if rows.len() >= DOCUMENT_HIT_ROW_LIMIT { MatchCompleteness::AtLeast } else { MatchCompleteness::Complete };
    super::search_document_itemcount::visit_validated_pages(&identifier, rows, |source, page, spans| {
        let Some(spans) = spans else { completeness = MatchCompleteness::Unavailable; return; };
        let ordinals: BTreeSet<u64> = spans.iter().filter(|span| span.is_highlighted).map(|span| span.index).collect();
        targets.extend(ordinals.into_iter().map(|ordinal| DocumentMatchTarget::Body { extracted_by: source.clone(), page_id: page, ordinal }));
    }).await?;
    let header_count = targets.iter().take_while(|target| matches!(target, DocumentMatchTarget::Header { .. })).count();
    targets[header_count..].sort_by(|a, b| match (a, b) {
        (DocumentMatchTarget::Body { extracted_by: a, page_id: ap, ordinal: ao }, DocumentMatchTarget::Body { extracted_by: b, page_id: bp, ordinal: bo }) => (a, ap, ao).cmp(&(b, bp, bo)),
        _ => std::cmp::Ordering::Equal,
    });
    Ok(DocumentMatches { document_identifier: identifier, find_query, targets, completeness })
}
