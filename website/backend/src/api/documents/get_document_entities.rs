//! Endpoint for retrieving per-document entities (grouped with counts).

use clickhouse::Row;
use common::{
    document_entities::{DocumentEntitiesResponse, DocumentEntityItem, DocumentEntityType},
    search_result::DocumentIdentifier,
};
use serde::Deserialize;

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
