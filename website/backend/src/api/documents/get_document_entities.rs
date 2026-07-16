//! Endpoint for retrieving per-document entities (grouped with counts).

use clickhouse::Row;
use common::{
    current_user::CurrentUser,
    document_entities::{DocumentEntitiesResponse, DocumentEntityItem, DocumentEntityType},
    search_result::DocumentIdentifier,
};
use futures::{StreamExt, stream::FuturesUnordered};
use serde::Deserialize;

use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::get_clickhouse_client;

#[derive(Debug, Clone, Deserialize, Row)]
struct EntityRow {
    pub entity_type: String,
    pub value: String,
    pub hit_count: u64,
}

fn normalize_entity_type(s: &str) -> DocumentEntityType {
    let t = s.trim().to_lowercase();
    match t.as_str() {
        // Migration says entity_type is free-form (person, org, email, url, etc.)
        // UI expects PER/ORG/LOC/MISC grouping.
        "per" | "person" | "people" => DocumentEntityType::Per,
        "org" | "organization" | "organisation" => DocumentEntityType::Org,
        "loc" | "location" => DocumentEntityType::Loc,
        "misc" => DocumentEntityType::Misc,
        _ => DocumentEntityType::Unknown,
    }
}

pub async fn get_document_entities(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentEntitiesResponse> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;

    let _ents = _get_document_entities(document_identifier.clone()).await?;
    
    // these ents maybe don't match properly, so let's skip them and fix match count

    let mut fut = FuturesUnordered::new();
    for item in _ents.items {
        fut.push(_adjust_hit_item_count(user, document_identifier.clone(), item));
    }
    let mut v2 = vec![];
    while let Some(item) =  fut.next().await {
        let item = item?;
        if item.hit_count > 0 {
            v2.push(item);
        }
    }
    v2.sort_by_key(|item| {
        (item.entity_type, item.hit_count, item.value.clone())
    });
    v2.reverse();

    Ok(DocumentEntitiesResponse{items:v2})
}

async fn _adjust_hit_item_count(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier, 
    mut item: DocumentEntityItem,
) -> anyhow::Result<DocumentEntityItem> {
    let find_query = format!("\"{}\"", item.value);
    use crate::api::documents::search_document_text::search_document_text_for_hit_count;

    let _counts = search_document_text_for_hit_count(user, document_identifier, find_query).await?;
    let _count_sum = _counts.into_iter().map(|x| x.hit_count).sum::<u64>();
    item.hit_count = _count_sum;
    
    Ok(item)
}

async fn _get_document_entities(
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentEntitiesResponse> {
    let client = get_clickhouse_client();

    // Match migration schema:
    // - entity_type: String
    // - entity_values: Array(String)
    // We explode values via ARRAY JOIN and count occurrences.
    let sql = r#"
        SELECT
            entity_type as entity_type,
            entity_value as value,
            count() as hit_count
        FROM entity_hit
        ARRAY JOIN entity_values AS entity_value
        WHERE collection_dataset = ? AND file_hash = ?
        GROUP BY entity_type, entity_value
        ORDER BY hit_count DESC
        LIMIT 500
    "#;

    let rows: Vec<EntityRow> = client
        .query(sql)
        .bind(&document_identifier.collection_dataset)
        .bind(&document_identifier.file_hash)
        .fetch_all()
        .await?;

    let mut items = Vec::new();
    for r in rows {
        let value = r.value.trim().to_string();
        if value.is_empty() {
            continue;
        }
        let entity_type = normalize_entity_type(&r.entity_type);
        let hit_count = r.hit_count;

        items.push(DocumentEntityItem {
            entity_type,
            value,
            hit_count,
        });
    }

    Ok(DocumentEntitiesResponse { items })
}
