//! The size and the dates of one document for a chat or board card.
//!
//! A stored citation holds neither, so the card reads them here with one Manticore point
//! query over the shard tables of the document's collection. These are the attributes that
//! the search sort reads, so a chat card and a search card of one document show the same
//! text. The `FROM` list holds every shard table, so the query needs no shard assignment
//! lookup. The query is uncached: each card sends its own statement, so a cache row would
//! serve no second request.

use common::current_user::CurrentUser;
use common::search_query::DATE_UNKNOWN;
use common::search_result::{DocumentCardFacts, DocumentIdentifier};

use crate::api::search::search_sql::shard_table_name;
use crate::auth::permissions;
use crate::db_utils::clickhouse_utils::{list_shards, resolve_collection};
use crate::db_utils::manticore_match::quoted_manticore_string;
use crate::db_utils::manticore_utils::manticore_search_sql_uncached;

#[derive(Debug, serde::Deserialize)]
struct FactsRow {
    file_size_bytes: i64,
    date_min: i64,
    date_max: i64,
}

/// The size and the dates of a document that the caller can read. A document that the
/// search index does not hold yet gives three `None` values.
pub async fn get_document_card_facts(
    user: &CurrentUser,
    document_identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentCardFacts> {
    permissions::assert_can_read(user, &document_identifier.collection_dataset).await?;
    let collectionname = resolve_collection(&document_identifier.collection_dataset).await?;
    let shards = list_shards(&collectionname).await?;
    if shards.is_empty() {
        return Ok(DocumentCardFacts::default());
    }
    let tables = shards.iter().map(|shard| shard_table_name(shard)).collect::<anyhow::Result<Vec<_>>>()?;
    let sql = format!(
        "SELECT file_size_bytes, date_min, date_max FROM {} WHERE collection_dataset = {} AND file_hash = {} LIMIT 1",
        tables.join(", "),
        quoted_manticore_string(&document_identifier.collection_dataset),
        quoted_manticore_string(&document_identifier.file_hash),
    );
    let result = manticore_search_sql_uncached::<FactsRow>(sql).await?;
    Ok(result.hits.hits.into_iter().next().map(|hit| facts_of(&hit._source)).unwrap_or_default())
}

/// The values of one shard row, with the unknown sentinels as `None`, as
/// `search_for_results` maps them.
fn facts_of(row: &FactsRow) -> DocumentCardFacts {
    DocumentCardFacts {
        file_size_bytes: (row.file_size_bytes >= 0).then_some(row.file_size_bytes),
        date_min: (row.date_min != DATE_UNKNOWN).then_some(row.date_min),
        date_max: (row.date_max != DATE_UNKNOWN).then_some(row.date_max),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_unknown_sentinels_are_none() {
        let known = facts_of(&FactsRow { file_size_bytes: 0, date_min: 10, date_max: 20 });
        assert_eq!(known, DocumentCardFacts { file_size_bytes: Some(0), date_min: Some(10), date_max: Some(20) });
        let unknown = facts_of(&FactsRow { file_size_bytes: -1, date_min: DATE_UNKNOWN, date_max: DATE_UNKNOWN });
        assert_eq!(unknown, DocumentCardFacts::default());
    }
}
