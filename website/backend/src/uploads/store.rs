//! The production implementations of the receiver traits: the ClickHouse rows, the
//! Temporal queue notification and the permission check of `db_auth::uploads`.
//!
//! The receiver calls them on blocking threads, so each one runs its async work with
//! `Handle::block_on` on the runtime that started the receiver.

use tokio::runtime::Handle;

use super::{
    queue_workflow_id, BatchRecord, BatchStore, FileRecord, QueueNotifier, Target, TargetLookup,
    UploadAccess, QUEUE_SIGNAL, QUEUE_TASK_QUEUE, QUEUE_WORKFLOW_TYPE,
};
use crate::db_utils::clickhouse_utils::get_collection_client;

fn millis(ms: i64) -> time::OffsetDateTime {
    time::OffsetDateTime::from_unix_timestamp_nanos(ms as i128 * 1_000_000)
        .unwrap_or(time::OffsetDateTime::UNIX_EPOCH)
}

#[derive(clickhouse::Row, serde::Serialize)]
struct BatchRow<'a> {
    batch_id: &'a str,
    upload_dataset: &'a str,
    folder: &'a str,
    username: &'a str,
    manifest_digest: &'a str,
    request_id: &'a str,
    state: &'a str,
    file_count: u32,
    byte_count: u64,
    op_id: &'a str,
    error: &'a str,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    created_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    last_write_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    committed_at: time::OffsetDateTime,
    #[serde(with = "clickhouse::serde::time::datetime64::millis")]
    finished_at: time::OffsetDateTime,
    row_version: u64,
}

#[derive(clickhouse::Row, serde::Serialize)]
struct FileRow<'a> {
    batch_id: &'a str,
    file_no: u32,
    path: &'a str,
    size_bytes: u64,
    content_digest: &'a str,
    placement_token: &'a str,
    #[serde(with = "clickhouse::serde::time::datetime")]
    client_mtime: time::OffsetDateTime,
    state: &'a str,
    file_hash: &'a str,
    error: &'a str,
    row_version: u64,
}

/// `upload_batches` and `upload_files` in the database of the collection.
pub struct ClickHouseStore {
    handle: Handle,
}

impl ClickHouseStore {
    pub fn new(handle: Handle) -> Self {
        ClickHouseStore { handle }
    }
}

/// Write one batch row. Public for the live tests.
pub async fn insert_batch(collection: &str, row: &BatchRecord) -> anyhow::Result<()> {
    crate::db_utils::clickhouse_utils::collection_db_name(collection)?;
    let client = get_collection_client(collection);
    let mut insert = client.insert::<BatchRow>("upload_batches").await?;
    insert
        .write(&BatchRow {
            batch_id: &row.batch_id,
            upload_dataset: &row.upload_dataset,
            folder: &row.folder,
            username: &row.username,
            manifest_digest: &row.manifest_digest,
            request_id: &row.request_id,
            state: &row.state,
            file_count: row.file_count,
            byte_count: row.byte_count,
            op_id: "",
            error: &row.error,
            created_at: millis(row.created_ms),
            last_write_at: millis(row.last_write_ms),
            committed_at: millis(row.committed_ms),
            finished_at: millis(row.finished_ms),
            row_version: row.row_version,
        })
        .await?;
    insert.end().await?;
    Ok(())
}

/// Write file rows in one insert. Public for the live tests.
pub async fn insert_files(collection: &str, rows: &[FileRecord]) -> anyhow::Result<()> {
    crate::db_utils::clickhouse_utils::collection_db_name(collection)?;
    let client = get_collection_client(collection);
    let mut insert = client.insert::<FileRow>("upload_files").await?;
    for row in rows {
        insert
            .write(&FileRow {
                batch_id: &row.batch_id,
                file_no: row.file_no,
                path: &row.path,
                size_bytes: row.size_bytes,
                content_digest: "",
                placement_token: &row.placement_token,
                client_mtime: time::OffsetDateTime::from_unix_timestamp(row.client_mtime_s.clamp(0, u32::MAX as i64))
                    .unwrap_or(time::OffsetDateTime::UNIX_EPOCH),
                state: &row.state,
                file_hash: "",
                error: &row.error,
                row_version: row.row_version,
            })
            .await?;
    }
    insert.end().await?;
    Ok(())
}

impl BatchStore for ClickHouseStore {
    fn write_batch(&self, collection: &str, row: &BatchRecord) -> anyhow::Result<()> {
        self.handle.block_on(insert_batch(collection, row))
    }

    fn write_files(&self, collection: &str, rows: &[FileRecord]) -> anyhow::Result<()> {
        self.handle.block_on(insert_files(collection, rows))
    }

    fn batch_state(&self, collection: &str, upload_dataset: &str, batch_id: &str) -> anyhow::Result<Option<String>> {
        crate::db_utils::clickhouse_utils::collection_db_name(collection)?;
        self.handle.block_on(async {
            let rows = get_collection_client(collection)
                .query("SELECT state FROM upload_batches FINAL WHERE upload_dataset = ? AND batch_id = ?")
                .bind(upload_dataset)
                .bind(batch_id)
                .fetch_all::<String>()
                .await?;
            Ok(rows.into_iter().next())
        })
    }

    fn dataset_live(&self, upload_dataset: &str) -> anyhow::Result<bool> {
        self.handle.block_on(async {
            let live = crate::db_utils::clickhouse_utils::get_global_client()
                .query("SELECT count() FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0")
                .bind(upload_dataset)
                .fetch_one::<u64>()
                .await?;
            Ok(live > 0)
        })
    }

    fn dataset_removal_live(&self, upload_dataset: &str) -> anyhow::Result<bool> {
        self.handle.block_on(async {
            let live = crate::db_utils::clickhouse_utils::get_global_client()
                .query(
                    "SELECT count() FROM operations FINAL WHERE collection_dataset = ? \
                     AND kind IN ('delete_dataset', 'purge_dataset') AND state IN ('pending', 'queued', 'running')",
                )
                .bind(upload_dataset)
                .fetch_one::<u64>()
                .await?;
            Ok(live > 0)
        })
    }
}

/// The body of the signal-with-start request. It holds ids only: no path enters a
/// Temporal payload.
pub fn signal_with_start_body(collection: &str, upload_dataset: &str, batch_id: &str) -> serde_json::Value {
    serde_json::json!({
        "workflowType": { "name": QUEUE_WORKFLOW_TYPE },
        "taskQueue": { "name": QUEUE_TASK_QUEUE },
        "input": [ { "collectionname": collection, "upload_dataset": upload_dataset } ],
        "signalInput": [ { "batch_id": batch_id } ],
    })
}

/// Signal-with-start of `UploadQueue` over the Temporal HTTP API. The installed server
/// answers 200 with the run id, for a new execution and for a running one.
pub struct TemporalNotifier {
    handle: Handle,
}

impl TemporalNotifier {
    pub fn new(handle: Handle) -> Self {
        TemporalNotifier { handle }
    }
}

impl QueueNotifier for TemporalNotifier {
    fn notify(&self, collection: &str, upload_dataset: &str, batch_id: &str) -> anyhow::Result<()> {
        let base = crate::temporal_ready::temporal_base_url();
        let url = format!(
            "{base}/api/v1/namespaces/default/workflows/{}/signal-with-start/{QUEUE_SIGNAL}",
            queue_workflow_id(upload_dataset)
        );
        let body = signal_with_start_body(collection, upload_dataset, batch_id);
        self.handle.block_on(async move {
            crate::temporal_ready::wait_for_temporal().await?;
            let response = crate::temporal_ready::start_client().post(&url).json(&body).send().await?;
            if !response.status().is_success() {
                let status = response.status();
                let text = response.text().await.unwrap_or_default();
                anyhow::bail!("signal-with-start of the upload queue failed ({status}): {text}");
            }
            Ok(())
        })
    }
}

/// The permission check of `db_auth::uploads` with the mounts of this process.
pub struct DbAccess {
    handle: Handle,
}

impl DbAccess {
    pub fn new(handle: Handle) -> Self {
        DbAccess { handle }
    }
}

impl UploadAccess for DbAccess {
    fn target(&self, username: &str, collection: &str) -> anyhow::Result<TargetLookup> {
        let targets = self.handle.block_on(crate::db_auth::uploads::upload_targets(username))?;
        if let Some(conflict) = targets.conflicts.iter().find(|c| c.collectionname == collection) {
            return Ok(TargetLookup::Conflict(conflict.datasets.clone()));
        }
        if let Some(unavailable) = targets.unavailable.iter().find(|u| u.collectionname == collection) {
            return Ok(TargetLookup::Unavailable {
                upload_dataset: unavailable.collection_dataset.clone(),
                reason: unavailable.reason.clone(),
            });
        }
        let Some(target) = targets.targets.into_iter().find(|t| t.collectionname == collection) else {
            return Ok(TargetLookup::None);
        };
        let mount = crate::dataset_mounts::mount_named(&target.mount_name)?;
        Ok(TargetLookup::Target(Target {
            collection: target.collectionname,
            upload_dataset: target.collection_dataset,
            dataset_path: target.dataset_path,
            mount,
        }))
    }
}
