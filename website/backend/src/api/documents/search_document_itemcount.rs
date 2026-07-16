use common::{
    current_user::CurrentUser,
    document_sources::{DocumentSourceItem, ItemHitCounts},
    search_result::DocumentIdentifier,
};

use crate::api::documents::{
    search_document_pdf::search_document_pdf,
    search_document_text::search_document_text_for_hit_count,
};
use crate::auth::permissions;

pub async fn search_document_item_count(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
    find_query: String,
    sources: Vec<DocumentSourceItem>,
) -> anyhow::Result<ItemHitCounts> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    if find_query.is_empty() {
        return Ok(ItemHitCounts(Vec::new()));
    }
    if sources.is_empty() {
        return Ok(ItemHitCounts(Vec::new()));
    }
    tracing::info!(
        "SEARCHING FOR ITEM HIT COUNTS FOR DOCUMENT: {:?} FIND={} , {} sources",
        document_identifier,
        &find_query,
        sources.len()
    );

    let has_pdf = sources
        .iter()
        .any(|source| matches!(source, DocumentSourceItem::Pdf(_)));
    let has_txt = sources
        .iter()
        .any(|source| matches!(source, DocumentSourceItem::Text(_)));
    let has_email = sources
        .iter()
        .filter(|source| matches!(source, DocumentSourceItem::Email(_)))
        .collect::<Vec<_>>()
        .first()
        .cloned()
        .cloned();

    let doc_id = document_identifier.clone();
    let query = find_query.clone();
    let pdf_task = if has_pdf {
        let user = user.clone();
        let doc_id = doc_id.clone();
        let query = query.clone();
        Some(tokio::task::spawn(async move {
            search_document_pdf(&user, doc_id, query).await
        }))
    } else {
        None
    };

    let txt_task = if has_txt {
        let user = user.clone();
        let doc_id = doc_id.clone();
        let query = query.clone();
        Some(tokio::task::spawn(async move {
            search_document_text_for_hit_count(&user, doc_id, query).await
        }))
    } else {
        None
    };
    let _txt_search = if let Some(txt_task) = txt_task {
        txt_task.await.unwrap_or(Ok(vec![])).unwrap_or_default()
    } else {
        vec![]
    };
    let _pdf_count = if let Some(pdf_task) = pdf_task {
        if let Ok(Ok(pdf_search)) = pdf_task.await {
            pdf_search.results.len() as u64
        } else {
            0
        }
    } else {
        0
    };

    let mut rv = vec![];
    for source in sources {
        let _document_source_extracted_by = match &source {
            DocumentSourceItem::Text(item) => item.extracted_by.clone(),
            _ => "".to_string(),
        };
        match &source {
            DocumentSourceItem::Pdf(_i) => {
                rv.push((source, _pdf_count));
            }
            DocumentSourceItem::Text(_i) => {
                let mut _txt = 0;
                for hits in _txt_search.iter() {
                    if hits.extracted_by == _document_source_extracted_by {
                        _txt += hits.hit_count;
                    }
                }
                rv.push((source, _txt));
            }
            _ => {
                rv.push((source, 0));
            }
        }
    }

    if let Some(email) = has_email {
        let txt_entry = rv.iter().find(|(item, _)| matches!(item, DocumentSourceItem::Text(_x) if _x.extracted_by == "email_parser"));
        rv.push((email, *txt_entry.map(|(_, count)| count).unwrap_or(&0)));
    }

    Ok(ItemHitCounts(rv))
}
