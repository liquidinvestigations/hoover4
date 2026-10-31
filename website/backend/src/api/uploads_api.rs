//! The server functions of the upload pages: the upload targets, the batch list, the
//! batch detail and the file list for "Continue upload".
//!
//! The transfer itself uses the `/_upload/` routes (`server_extra::uploads` and
//! `server_extra::tus`). The functions here only read.
//!
//! Access follows `db_auth::uploads`. The upload page and the file browser button use
//! [`upload_targets`](crate::db_auth::uploads::upload_targets). The batch pages use
//! [`can_read_upload_history`](crate::db_auth::uploads::can_read_upload_history), which
//! does not need a current upload target, so history stays readable after uploads end.
//! A batch id is a lookup key. Each function reads the batch row first and then checks
//! the reader, so a batch that the reader may not read gives 403 and a missing batch 404.
//!
//! The detail page reads the outcome evidence with the rule of `classify_outcome` in
//! `main_services/processing/database/uploads.py`. The reads join `upload_files` inside
//! ClickHouse, so no hash or path list travels in a query.

use std::collections::{HashMap, HashSet};

use common::current_user::CurrentUser;
use common::upload_pages::{
    file_state, sort_file_rows, IngestedEvidence, ResumeFile, UploadBatchCursor, UploadBatchDetail,
    UploadBatchPage, UploadBatchRow, UploadCounts, UploadFileRow, UploadFileState, PAGE_ROWS,
};
use common::uploads::{LimitsResponse, UploadTargetInfo};

use crate::auth::guard;
use crate::db_utils::clickhouse_utils::{collection_db_name, get_collection_client};

/// The most member levels below an uploaded file that the outcome follows. The worker
/// uses the same bound (`DESCENDANT_LEVELS`).
const DESCENDANT_LEVELS: usize = 16;
/// The longest error text that the detail page receives for one file.
const ERROR_CHARS: usize = 2000;
/// The refusal of a batch page for a reader without history access.
const NO_HISTORY: &str = "forbidden: you cannot read the upload history of this collection";

/// The limits and the current upload targets of the user. A collection with two upload
/// datasets is listed in `conflicts` and has no target.
pub async fn upload_page_info(user: &CurrentUser) -> anyhow::Result<LimitsResponse> {
    let limits = crate::uploads::limits_from_env()?;
    let found = crate::db_auth::uploads::upload_targets(&user.username).await?;
    Ok(LimitsResponse {
        limits,
        targets: found
            .targets
            .into_iter()
            .map(|t| UploadTargetInfo { collection: t.collectionname, dataset: t.collection_dataset })
            .collect(),
        conflicts: found.conflicts.into_iter().map(|c| c.collectionname).collect(),
    })
}

/// True for a ClickHouse error that names a missing database or table. A collection
/// without the database has no batches.
fn is_missing_storage(err: &clickhouse::error::Error) -> bool {
    let text = err.to_string();
    text.contains("UNKNOWN_DATABASE") || text.contains("UNKNOWN_TABLE")
}

/// The collections whose batch history the user may read, sorted: every live collection
/// for an administrator, else the live collections of the flagged memberships.
async fn readable_collections(user: &CurrentUser) -> anyhow::Result<Vec<String>> {
    let live: Vec<String> = crate::db_auth::collections::list_collections()
        .await?
        .into_iter()
        .map(|c| c.collectionname)
        .collect();
    if user.is_admin {
        return Ok(live);
    }
    let flagged = crate::db_auth::uploads::uploader_collections(&user.username).await?;
    Ok(live.into_iter().filter(|c| flagged.contains(c)).collect())
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct BatchListRow {
    batch_id: String,
    upload_dataset: String,
    folder: String,
    username: String,
    state: String,
    file_count: u32,
    byte_count: u64,
    created_ms: i64,
}

const BATCH_COLUMNS: &str = "batch_id, upload_dataset, folder, username, state, file_count, \
     byte_count, toUnixTimestamp64Milli(created_at) AS created_ms";

fn list_row(collection: &str, row: BatchListRow) -> UploadBatchRow {
    UploadBatchRow {
        collection: collection.to_string(),
        batch_id: row.batch_id,
        upload_dataset: row.upload_dataset,
        folder: row.folder,
        username: row.username,
        state: row.state,
        file_count: row.file_count,
        byte_count: row.byte_count,
        created_ms: row.created_ms,
    }
}

/// The newest batches of one collection before `before`, at most `limit`.
async fn batches_before(
    collection: &str,
    before: Option<&UploadBatchCursor>,
    limit: usize,
) -> anyhow::Result<Vec<UploadBatchRow>> {
    collection_db_name(collection)?;
    let filter = if before.is_some() {
        "WHERE (toUnixTimestamp64Milli(created_at), batch_id) < ({cms:Int64}, {cb:String})"
    } else {
        ""
    };
    let sql = format!(
        "SELECT {BATCH_COLUMNS} FROM upload_batches FINAL {filter} \
         ORDER BY created_at DESC, batch_id DESC LIMIT {limit}"
    );
    let mut query = get_collection_client(collection).query(&sql);
    if let Some(cursor) = before {
        query = query.param("cms", cursor.created_ms).param("cb", &cursor.batch_id);
    }
    match query.fetch_all::<BatchListRow>().await {
        Ok(rows) => Ok(rows.into_iter().map(|r| list_row(collection, r)).collect()),
        Err(e) if is_missing_storage(&e) => Ok(Vec::new()),
        Err(e) => Err(e.into()),
    }
}

/// Merge the newest rows of the listed collections into one page, newest first by creation
/// time and batch id. Returns the page and the cursor of the next page.
pub fn merge_batch_pages(
    mut rows: Vec<UploadBatchRow>,
    page_rows: usize,
) -> (Vec<UploadBatchRow>, Option<UploadBatchCursor>) {
    rows.sort_by(|a, b| (b.created_ms, &b.batch_id).cmp(&(a.created_ms, &a.batch_id)));
    let more = rows.len() > page_rows;
    rows.truncate(page_rows);
    let next = if more {
        rows.last().map(|r| UploadBatchCursor { created_ms: r.created_ms, batch_id: r.batch_id.clone() })
    } else {
        None
    };
    (rows, next)
}

/// One page of the batch list. An empty `collection` lists every readable collection.
/// A collection that the user may not read gives 403.
pub async fn list_upload_batches(
    user: &CurrentUser,
    collection: String,
    before: Option<UploadBatchCursor>,
) -> anyhow::Result<UploadBatchPage> {
    let collections = readable_collections(user).await?;
    let listed: Vec<String> = if collection.is_empty() {
        collections.clone()
    } else if collections.contains(&collection) {
        vec![collection]
    } else {
        anyhow::bail!(NO_HISTORY);
    };
    let mut rows = Vec::new();
    for name in &listed {
        rows.extend(batches_before(name, before.as_ref(), PAGE_ROWS + 1).await?);
    }
    let (rows, next) = merge_batch_pages(rows, PAGE_ROWS);
    Ok(UploadBatchPage { rows, next, collections })
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct BatchDetailRow {
    batch_id: String,
    upload_dataset: String,
    folder: String,
    username: String,
    state: String,
    file_count: u32,
    byte_count: u64,
    created_ms: i64,
    op_id: String,
    error: String,
}

/// Read a batch row, then check the reader. A missing collection database or batch is
/// not found. A batch that the reader may not read is forbidden.
async fn readable_batch(user: &CurrentUser, collection: &str, batch_id: &str) -> anyhow::Result<BatchDetailRow> {
    collection_db_name(collection).map_err(|_| anyhow::anyhow!("upload {}", guard::NOT_FOUND))?;
    let rows = get_collection_client(collection)
        .query(&format!(
            "SELECT {BATCH_COLUMNS}, op_id, error FROM upload_batches FINAL WHERE batch_id = {{b:String}}"
        ))
        .param("b", batch_id)
        .fetch_all::<BatchDetailRow>()
        .await;
    let row = match rows {
        Ok(mut rows) => rows.pop(),
        Err(e) if is_missing_storage(&e) => None,
        Err(e) => return Err(e.into()),
    };
    let Some(row) = row else {
        anyhow::bail!("upload {}", guard::NOT_FOUND);
    };
    if !crate::db_auth::uploads::can_read_upload_history(user, collection).await? {
        anyhow::bail!(NO_HISTORY);
    }
    Ok(row)
}

#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct FileStoreRow {
    file_no: u32,
    path: String,
    size_bytes: u64,
    state: String,
    file_hash: String,
    error: String,
    mtime_s: i64,
}

async fn batch_files(collection: &str, batch_id: &str) -> anyhow::Result<Vec<FileStoreRow>> {
    Ok(get_collection_client(collection)
        .query(
            "SELECT file_no, path, size_bytes, state, file_hash, error, \
                    toInt64(toUnixTimestamp(client_mtime)) AS mtime_s \
             FROM upload_files FINAL WHERE batch_id = {b:String} ORDER BY file_no",
        )
        .param("b", batch_id)
        .fetch_all::<FileStoreRow>()
        .await?)
}

/// The SQL of member level `k` below the ingested files of the batch: rows of the
/// uploaded root hash and a hash at that level. Level 0 is the roots.
///
/// Each root and member pair appears once. A shared member affects every containing
/// uploaded root, as `_descendants` in `database/uploads.py` records it.
fn level_sql(k: usize) -> String {
    if k == 0 {
        return "SELECT DISTINCT file_hash AS root, file_hash AS hash FROM upload_files FINAL \
                WHERE batch_id = {b:String} AND state = 'ingested' AND file_hash != ''"
            .to_string();
    }
    let up = k - 1;
    let earlier: String = (0..k)
        .map(|j| format!(" AND (l.root, v.hash) NOT IN (SELECT root, hash FROM l{j})"))
        .collect();
    format!(
        "SELECT DISTINCT l.root AS root, v.hash AS hash FROM \
              (SELECT DISTINCT container_hash, hash FROM vfs_files FINAL \
               WHERE collection_dataset = {{ds:String}} AND is_deleted = 0 AND hash != '' \
                 AND container_hash IN (SELECT hash FROM l{up})) AS v \
            INNER JOIN l{up} AS l ON v.container_hash = l.hash \
            WHERE 1{earlier}"
    )
}

/// `WITH l0 AS (...), ..., l<depth> AS (...)`.
fn levels_with(depth: usize) -> String {
    let parts: Vec<String> = (0..=depth).map(|k| format!("l{k} AS ({})", level_sql(k))).collect();
    format!("WITH {}", parts.join(", "))
}

/// The deepest member level with a row, at most [`DESCENDANT_LEVELS`].
async fn member_depth(client: &clickhouse::Client, dataset: &str, batch_id: &str) -> anyhow::Result<usize> {
    let mut depth = 0;
    while depth < DESCENDANT_LEVELS {
        let next = depth + 1;
        let count: u64 = client
            .query(&format!("{} SELECT count() FROM l{next}", levels_with(next)))
            .param("b", batch_id)
            .param("ds", dataset)
            .fetch_one()
            .await?;
        if count == 0 {
            break;
        }
        depth = next;
    }
    Ok(depth)
}

/// The facts of each uploaded root hash, aggregated over the root and its members.
#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
struct RootRow {
    root: String,
    root_planned: u64,
    unfinished: u8,
    failing: u8,
    error: String,
}

/// The plans, plan completion and current errors of each root. An error is current under
/// the rule of the document viewer: the latest operation that listed a plan of the hash
/// wrote it, or it has no operation id and no operation listed a plan of the hash.
fn roots_sql(depth: usize) -> String {
    let members: Vec<String> = (0..=depth).map(|k| format!("SELECT root, hash FROM l{k}")).collect();
    format!(
        "{levels}, \
         members AS ({members}), \
         plans AS (SELECT DISTINCT item_hash, plan_hash FROM processing_plan_hits FINAL \
                   WHERE collection_dataset = {{ds:String}} \
                     AND item_hash IN (SELECT hash FROM members)), \
         plan_state AS (SELECT p.item_hash AS hash, uniqExact(p.plan_hash) AS planned, \
                               uniqExactIf(p.plan_hash, f.plan_hash != '') AS done \
                        FROM plans AS p \
                        LEFT JOIN (SELECT DISTINCT plan_hash FROM processing_plan_finished FINAL \
                                   WHERE collection_dataset = {{ds:String}} \
                                     AND plan_hash IN (SELECT plan_hash FROM plans)) AS f \
                          ON f.plan_hash = p.plan_hash \
                        GROUP BY p.item_hash), \
         latest AS (SELECT p.item_hash AS item_hash, argMax(o.op_id, o.listed_at) AS op_id \
                    FROM plans AS p \
                    INNER JOIN operation_plans AS o FINAL \
                      ON o.plan_hash = p.plan_hash AND o.collection_dataset = {{ds:String}} \
                    GROUP BY p.item_hash), \
         failing AS (SELECT e.hash AS hash, \
                            any(substring(concat(e.task_name, ': ', e.error_logs), 1, {ERROR_CHARS})) AS error \
                     FROM processing_errors AS e FINAL \
                     LEFT JOIN latest AS l ON l.item_hash = e.hash \
                     WHERE e.collection_dataset = {{ds:String}} AND e.hash != '' \
                       AND e.hash IN (SELECT hash FROM members) AND e.op_id = l.op_id \
                     GROUP BY e.hash) \
         SELECT m.root AS root, \
                maxIf(ps.planned, m.hash = m.root) AS root_planned, \
                toUInt8(max(ps.planned > ps.done)) AS unfinished, \
                toUInt8(max(fl.hash != '')) AS failing, \
                anyIf(fl.error, fl.hash != '') AS error \
         FROM members AS m \
         LEFT JOIN plan_state AS ps ON ps.hash = m.hash \
         LEFT JOIN failing AS fl ON fl.hash = m.hash \
         GROUP BY m.root \
         SETTINGS join_use_nulls = 0",
        levels = levels_with(depth),
        members = members.join(" UNION ALL "),
    )
}

/// The paths of ingested files with a live top-level `vfs_files` row, with its hash, and
/// the paths with a `vfs_nodes` row. An uploaded archive has a node of kind `container`.
async fn published_paths(
    client: &clickhouse::Client,
    dataset: &str,
    batch_id: &str,
) -> anyhow::Result<(HashMap<String, String>, HashSet<String>)> {
    const INGESTED: &str =
        "(SELECT path FROM upload_files FINAL WHERE batch_id = {b:String} AND state = 'ingested')";
    let vfs: Vec<(String, String)> = client
        .query(&format!(
            "SELECT path, hash FROM vfs_files FINAL \
             WHERE collection_dataset = {{ds:String}} AND container_hash = '' AND is_deleted = 0 \
               AND path IN {INGESTED}"
        ))
        .param("b", batch_id)
        .param("ds", dataset)
        .fetch_all()
        .await?;
    let nodes: Vec<String> = client
        .query(&format!(
            "SELECT DISTINCT path FROM vfs_nodes FINAL \
             WHERE collection_dataset = {{ds:String}} AND container_hash = '' \
               AND kind IN ('file', 'container') AND path IN {INGESTED}"
        ))
        .param("b", batch_id)
        .param("ds", dataset)
        .fetch_all()
        .await?;
    Ok((vfs.into_iter().collect(), nodes.into_iter().collect()))
}

/// The detail page of one batch. `page` selects 200 rows of the file table.
pub async fn upload_batch_detail(
    user: &CurrentUser,
    collection: String,
    batch_id: String,
    page: u32,
) -> anyhow::Result<UploadBatchDetail> {
    let batch = readable_batch(user, &collection, &batch_id).await?;
    let files = batch_files(&collection, &batch_id).await?;
    let client = get_collection_client(&collection);
    let dataset = batch.upload_dataset.clone();

    let mut roots: HashMap<String, RootRow> = HashMap::new();
    let mut vfs = HashMap::new();
    let mut nodes = HashSet::new();
    if files.iter().any(|f| f.state == "ingested") {
        let depth = member_depth(&client, &dataset, &batch_id).await?;
        let rows: Vec<RootRow> = client
            .query(&roots_sql(depth))
            .param("b", &batch_id)
            .param("ds", &dataset)
            .fetch_all()
            .await?;
        roots = rows.into_iter().map(|r| (r.root.clone(), r)).collect();
        (vfs, nodes) = published_paths(&client, &dataset, &batch_id).await?;
    }

    let mut counts = UploadCounts::default();
    let mut rows: Vec<UploadFileRow> = Vec::with_capacity(files.len());
    for f in files {
        let root = roots.get(&f.file_hash);
        let evidence = (f.state == "ingested").then(|| IngestedEvidence {
            published: !f.file_hash.is_empty()
                && vfs.get(&f.path) == Some(&f.file_hash)
                && nodes.contains(&f.path),
            planned: root.map_or(0, |r| r.root_planned),
            unfinished: root.is_some_and(|r| r.unfinished > 0),
            failing: root.is_some_and(|r| r.failing > 0),
        });
        let state = file_state(&f.state, evidence);
        counts.add(state);
        let error = if !f.error.is_empty() {
            f.error
        } else if state == UploadFileState::Errors {
            root.map(|r| r.error.clone()).unwrap_or_default()
        } else {
            String::new()
        };
        rows.push(UploadFileRow {
            file_no: f.file_no,
            path: f.path,
            size_bytes: f.size_bytes,
            state,
            error,
            file_hash: f.file_hash,
        });
    }
    sort_file_rows(&mut rows);
    let page_count = rows.len().div_ceil(PAGE_ROWS).max(1) as u32;
    let page = page.min(page_count - 1);
    let start = page as usize * PAGE_ROWS;
    let files: Vec<UploadFileRow> = rows.into_iter().skip(start).take(PAGE_ROWS).collect();

    Ok(UploadBatchDetail {
        is_owner: batch.username == user.username,
        op_id: (user.is_admin && !batch.op_id.is_empty()).then(|| batch.op_id.clone()),
        error: batch.error.clone(),
        batch: UploadBatchRow {
            collection,
            batch_id: batch.batch_id,
            upload_dataset: batch.upload_dataset,
            folder: batch.folder,
            username: batch.username,
            state: batch.state,
            file_count: batch.file_count,
            byte_count: batch.byte_count,
            created_ms: batch.created_ms,
        },
        counts,
        files,
        page,
        page_count,
    })
}

/// The manifest of an `uploading` batch, for "Continue upload". Only the owner receives
/// it. Another reader gets 403, and a batch in another state gets the ended text.
pub async fn upload_batch_resume_files(
    user: &CurrentUser,
    collection: String,
    batch_id: String,
) -> anyhow::Result<Vec<ResumeFile>> {
    let batch = readable_batch(user, &collection, &batch_id).await?;
    if batch.username != user.username {
        anyhow::bail!("forbidden: this upload belongs to another user");
    }
    if batch.state != "uploading" {
        return Err(guard::InvalidInput(common::uploads::ENDED_MESSAGE.to_string()).into());
    }
    let folder = batch.folder.clone();
    Ok(batch_files(&collection, &batch_id)
        .await?
        .into_iter()
        .map(|f| ResumeFile {
            file_no: f.file_no,
            relative_path: common::upload_pages::relative_to_folder(&folder, &f.path),
            size: f.size_bytes,
            mtime_s: f.mtime_s,
            state: f.state,
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn row(collection: &str, batch_id: &str, created_ms: i64) -> UploadBatchRow {
        UploadBatchRow {
            collection: collection.into(),
            batch_id: batch_id.into(),
            upload_dataset: "d".into(),
            folder: "/".into(),
            username: "u".into(),
            state: "completed".into(),
            file_count: 1,
            byte_count: 1,
            created_ms,
        }
    }

    #[test]
    fn pages_of_several_collections_merge_newest_first_with_a_cursor() {
        let rows = vec![row("a", "01", 10), row("b", "02", 30), row("a", "03", 20), row("b", "00", 30)];
        let (page, next) = merge_batch_pages(rows.clone(), 3);
        let ids: Vec<&str> = page.iter().map(|r| r.batch_id.as_str()).collect();
        assert_eq!(ids, vec!["02", "00", "03"]);
        assert_eq!(next, Some(UploadBatchCursor { created_ms: 20, batch_id: "03".into() }));
        let (page, next) = merge_batch_pages(rows, 4);
        assert_eq!(page.len(), 4);
        assert_eq!(next, None);
    }

    #[test]
    fn the_level_queries_chain_from_the_ingested_files() {
        let sql = levels_with(2);
        assert!(sql.starts_with("WITH l0 AS (SELECT DISTINCT file_hash AS root"));
        assert!(sql.contains("l1 AS (SELECT DISTINCT l.root AS root, v.hash AS hash FROM"));
        assert!(sql.contains("container_hash IN (SELECT hash FROM l1)"));
        // Each root and member pair appears at its first reachable level.
        assert!(sql.contains(
            "WHERE 1 AND (l.root, v.hash) NOT IN (SELECT root, hash FROM l0) AND (l.root, v.hash) NOT IN (SELECT root, hash FROM l1)"
        ));
        assert!(!sql.contains("l3"));
        let roots = roots_sql(1);
        assert!(roots.contains("members AS (SELECT root, hash FROM l0 UNION ALL SELECT root, hash FROM l1)"));
        assert!(roots.ends_with("SETTINGS join_use_nulls = 0"));
    }
}

#[cfg(test)]
mod live_member_tests {
    use super::*;

    #[tokio::test]
    #[ignore = "requires the local ClickHouse service"]
    async fn shared_members_reach_every_uploaded_archive() {
        let db = format!("upload_review_{}", crate::uploads::random_id());
        let admin = crate::db_utils::clickhouse_utils::get_global_client();
        admin.query(&format!("CREATE DATABASE {db}")).execute().await.unwrap();
        let client = admin.clone().with_database(&db);
        let result = async {
            client.query("CREATE TABLE upload_files (batch_id String, state String, file_hash String) ENGINE=ReplacingMergeTree ORDER BY (batch_id, file_hash)").execute().await?;
            client.query("CREATE TABLE vfs_files (collection_dataset String, container_hash String, hash String, is_deleted UInt8) ENGINE=ReplacingMergeTree ORDER BY (collection_dataset, container_hash, hash)").execute().await?;
            client.query("INSERT INTO upload_files VALUES ('b','ingested','a'),('b','ingested','b')").execute().await?;
            client.query("INSERT INTO vfs_files VALUES ('ds','a','shared',0),('ds','b','shared',0),('ds','a','b',0),('ds','b','child',0),('ds','child','b',0)").execute().await?;
            let depth = member_depth(&client, "ds", "b").await?;
            assert_eq!(depth, 2);
            let sql = format!("{} SELECT root, hash FROM l1 UNION ALL SELECT root, hash FROM l2", levels_with(depth));
            let mut pairs: Vec<(String, String)> = client.query(&sql).param("b", "b").param("ds", "ds").fetch_all().await?;
            pairs.sort();
            assert_eq!(pairs, vec![("a".into(), "b".into()), ("a".into(), "child".into()),
                ("a".into(), "shared".into()), ("b".into(), "child".into()), ("b".into(), "shared".into())]);
            Ok::<_, anyhow::Error>(())
        }.await;
        admin.query(&format!("DROP DATABASE {db}")).execute().await.unwrap();
        result.unwrap();
    }
}
