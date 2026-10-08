//! The document error section of the Errors/Failures page.
//!
//! Reads `processing_errors` of each collection. A failed run of a task writes one row,
//! so a task that failed in three runs has three rows for one document. The section
//! shows one row for each document and task, with the newest error and the count of
//! failed runs. A row with an empty hash is an error of a dataset step.
//!
//! With no collection selected, the section reads every collection whose database is
//! ready and merges the results. Each collection returns at most the rows up to the end
//! of the requested page, so one page costs one bounded query for each collection.

use std::collections::{BTreeMap, BTreeSet};

use common::current_user::CurrentUser;
use common::processing_types::{
    DocumentErrorFilter, DocumentErrorRow, DocumentErrorStat, DocumentErrorsPage,
    DOCUMENT_ERRORS_PAGE_SIZE,
};

use crate::api::admin::processing::{first_line, format_ts};
use crate::auth::guard;
use crate::db_auth::collections;
use crate::db_utils::clickhouse_utils::get_collection_client;

/// The errors of each document and task, newest first, under the filters. Every filter
/// value is bound, in the order the text names them.
const PAIRS: &str = "\
    SELECT collection_dataset, hash, task_name, count() AS runs, \
           toInt64(toUnixTimestamp(max(timestamp))) AS last_seen, \
           argMax(error_logs, timestamp) AS error \
    FROM processing_errors FINAL \
    WHERE (? = '' OR collection_dataset = ?) AND (? = '' OR task_name = ?) \
      AND (? = '' OR positionCaseInsensitiveUTF8(error_logs, ?) > 0) \
    GROUP BY collection_dataset, hash, task_name";

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct PairRow {
    collection_dataset: String,
    hash: String,
    task_name: String,
    runs: u64,
    last_seen: i64,
    error: String,
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct StatRow {
    collection_dataset: String,
    task_name: String,
    documents: u64,
    last_seen: i64,
}

fn bind_filter(mut query: clickhouse::query::Query, filter: &DocumentErrorFilter) -> clickhouse::query::Query {
    for value in [&filter.collection_dataset, &filter.task_name, &filter.search] {
        query = query.bind(value.as_str()).bind(value.as_str());
    }
    query
}

/// The collections the section reads: the selected one, or every ready collection.
async fn selected_collections(filter: &DocumentErrorFilter) -> anyhow::Result<Vec<String>> {
    let names: Vec<String> = if filter.collectionname.is_empty() {
        collections::list_collections().await?.into_iter().map(|c| c.collectionname).collect()
    } else {
        vec![filter.collectionname.clone()]
    };
    let mut ready = Vec::new();
    for name in names {
        if collections::collection_db_ready(&name).await? {
            ready.push(name);
        }
    }
    Ok(ready)
}

/// One page of document errors with the statistics of every match. `page` starts at 1.
pub async fn admin_list_document_errors(
    user: &CurrentUser,
    filter: DocumentErrorFilter,
    page: u32,
) -> anyhow::Result<DocumentErrorsPage> {
    guard::require_admin(user)?;
    let filter = DocumentErrorFilter { search: filter.search.trim().to_string(), ..filter };
    let page = page.max(1);
    let end = u64::from(page) * u64::from(DOCUMENT_ERRORS_PAGE_SIZE);
    let mut stats = Vec::new();
    let mut rows = Vec::new();
    let mut total = 0u64;
    let mut datasets = BTreeSet::new();
    let mut tasks = BTreeSet::new();

    for collectionname in selected_collections(&filter).await? {
        let client = get_collection_client(&collectionname);
        let choices: Vec<(String, String)> = client
            .query("SELECT DISTINCT collection_dataset, task_name FROM processing_errors")
            .fetch_all()
            .await?;
        for (dataset, task) in choices {
            datasets.insert(dataset);
            tasks.insert(task);
        }
        stats.extend(
            bind_filter(
                client.query(&format!(
                    "SELECT collection_dataset, task_name, count() AS documents, \
                            max(last_seen) AS last_seen \
                     FROM ({PAIRS}) GROUP BY collection_dataset, task_name"
                )),
                &filter,
            )
            .fetch_all::<StatRow>()
            .await?,
        );
        total += bind_filter(client.query(&format!("SELECT count() FROM ({PAIRS})")), &filter)
            .fetch_one::<u64>()
            .await?;
        let mut pairs = bind_filter(
            client.query(&format!(
                "SELECT * FROM ({PAIRS}) ORDER BY last_seen DESC, collection_dataset, hash, task_name LIMIT ?"
            )),
            &filter,
        )
        .bind(end)
        .fetch_all::<PairRow>()
        .await?;
        let hashes: Vec<String> = pairs.iter().map(|r| r.hash.clone()).filter(|h| !h.is_empty()).collect();
        let paths: BTreeMap<String, String> = if hashes.is_empty() {
            BTreeMap::new()
        } else {
            client
                .query("SELECT hash, any(path) FROM vfs_files WHERE hash IN ? GROUP BY hash")
                .bind(&hashes)
                .fetch_all::<(String, String)>()
                .await?
                .into_iter()
                .collect()
        };
        rows.extend(pairs.drain(..).map(|r| DocumentErrorRow {
            path: paths.get(&r.hash).cloned(),
            collection_dataset: r.collection_dataset,
            task_name: r.task_name,
            runs: r.runs,
            last_seen: format_ts(r.last_seen),
            error: first_line(&r.error, 400),
            hash: r.hash,
        }));
    }

    // RFC 3339 in UTC sorts as text in time order.
    rows.sort_by(|a, b| {
        b.last_seen
            .cmp(&a.last_seen)
            .then_with(|| a.collection_dataset.cmp(&b.collection_dataset))
            .then_with(|| a.hash.cmp(&b.hash))
            .then_with(|| a.task_name.cmp(&b.task_name))
    });
    let start = (end - u64::from(DOCUMENT_ERRORS_PAGE_SIZE)) as usize;
    let rows: Vec<DocumentErrorRow> = rows.into_iter().skip(start).take(DOCUMENT_ERRORS_PAGE_SIZE as usize).collect();

    let mut stats: Vec<DocumentErrorStat> = stats
        .into_iter()
        .map(|s| DocumentErrorStat {
            collection_dataset: s.collection_dataset,
            task_name: s.task_name,
            documents: s.documents,
            last_seen: format_ts(s.last_seen),
        })
        .collect();
    stats.sort_by(|a, b| b.documents.cmp(&a.documents).then_with(|| a.collection_dataset.cmp(&b.collection_dataset)).then_with(|| a.task_name.cmp(&b.task_name)));

    Ok(DocumentErrorsPage {
        stats,
        total,
        rows,
        dataset_choices: datasets.into_iter().collect(),
        task_choices: tasks.into_iter().collect(),
    })
}
