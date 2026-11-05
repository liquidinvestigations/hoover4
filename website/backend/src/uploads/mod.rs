//! The upload receiver: `begin`, the tus subset, placement into the dataset folder,
//! `commit`, startup recovery and the hourly sweep.
//!
//! A batch is one upload of one person into one folder of the upload dataset of a
//! collection. Its files arrive in the upload space, the website volume
//! `hoover4-upload-tmp` mounted at [`DEFAULT_SPACE`]. Each complete file moves into the
//! dataset folder without replacing an existing entry. `commit` ends the transfer, and a
//! Temporal signal wakes the `UploadQueue` workflow of the dataset.
//!
//! The durable journal in the upload space ([`journal`]) is the source of transfer
//! state. ClickHouse holds a copy in `upload_batches` and `upload_files` for history and
//! for the worker. Every journal change raises the version of its record, and the
//! ClickHouse row of a version carries that version as `row_version`. A record whose
//! ClickHouse version is below its journal version is written again by the next flush,
//! a repeated request or the sweep.
//!
//! A transfer request writes no row. It queues its batch in the [`RowQueue`], and one
//! flusher thread writes the changed rows of a batch at most once every
//! [`ROW_FLUSH_INTERVAL`], in one insert for each table. `begin`, the end of a commit
//! ([`Service::finish`]), a stop and the sweep write their rows themselves, also in one
//! insert for each table.
//!
//! The functions of [`Service`] block, and the HTTP handlers run them on the blocking
//! thread pool, outside the Dioxus server-function runtime. The clock, the ClickHouse
//! store, the queue notifier, the permission check and the free-space reader are traits,
//! so the tests replace each one.

pub mod begin;
pub mod commit;
pub mod fsutil;
pub mod journal;
pub mod placement;
pub mod store;
pub mod transfer;

#[cfg(test)]
mod tests;

use std::collections::{BTreeSet, HashMap};
use std::os::fd::{BorrowedFd, OwnedFd};
use std::path::PathBuf;
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::time::{Duration, Instant};

use common::uploads::UploadLimits;

use crate::dataset_mounts::DatasetMount;
use fsutil::Faults;
use journal::{BatchJournal, FileJournal, Manifest, Space};

/// The container path of the upload space.
pub const DEFAULT_SPACE: &str = "/upload-tmp";

/// The Temporal workflow type that the queue notification starts.
pub const QUEUE_WORKFLOW_TYPE: &str = "UploadQueue";
/// The task queue of the `UploadQueue` workflow.
pub const QUEUE_TASK_QUEUE: &str = "processing-common-queue";
/// The signal that the queue notification sends.
pub const QUEUE_SIGNAL: &str = "upload_committed";

/// The workflow id of the queue of one upload dataset.
pub fn queue_workflow_id(upload_dataset: &str) -> String {
    format!("upload-queue-{upload_dataset}")
}

/// The batch detail page of the website.
pub fn detail_address(collection: &str, batch_id: &str) -> String {
    format!("/uploads/{collection}/{batch_id}")
}

/// The tus address of one file.
pub fn upload_url(batch_id: &str, file_no: u32) -> String {
    format!("/_upload/files/{batch_id}-{file_no}")
}

/// A `committing` batch older than this is committed again by the sweep.
pub const COMMIT_RETRY_MS: i64 = 10 * 60 * 1000;

/// A `PATCH` body that gives no byte for this time ends as interrupted, and its
/// synchronized prefix stays. A client that lost its network without a FIN or a RST then
/// releases the batch and file locks. The design names no configuration key for it.
pub const PATCH_IDLE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(60);

/// The longest wait of a request or of a stop for a batch or file lock that another
/// request holds. It is longer than [`PATCH_IDLE_TIMEOUT`], so a `HEAD` after a stalled
/// `PATCH` gets its answer when that `PATCH` ends. A longer hold answers 423, and the
/// client tries again.
pub const LOCK_WAIT: std::time::Duration = std::time::Duration::from_secs(75);

/// The shortest time between two row writes of one batch by the row flusher.
pub const ROW_FLUSH_INTERVAL: Duration = Duration::from_secs(2);

/// The rows of one batch that changed after the row flusher last wrote the batch.
#[derive(Default)]
struct PendingRows {
    batch: bool,
    files: BTreeSet<u32>,
    /// When the flusher last took the rows of this batch.
    taken: Option<Instant>,
}

/// The rows of one batch that one flush writes.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DueRows {
    pub batch_id: String,
    /// True when the batch row changed.
    pub batch: bool,
    pub files: BTreeSet<u32>,
}

/// The batches whose rows wait for the flusher. The queue is in memory. A lost entry
/// loses no row, because the journal keeps `db_version` below `version` until a commit,
/// a stop or the sweep writes the row.
#[derive(Default)]
pub struct RowQueue {
    state: Mutex<HashMap<String, PendingRows>>,
    wake: Condvar,
}

impl RowQueue {
    /// Queue the batch row (`None`) or one file row of a batch.
    pub fn mark(&self, batch_id: &str, file_no: Option<u32>) {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        let entry = state.entry(batch_id.to_string()).or_default();
        match file_no {
            Some(n) => {
                entry.files.insert(n);
            }
            None => entry.batch = true,
        }
        drop(state);
        self.wake.notify_one();
    }

    /// Take the rows of one batch whose last flush is at least [`ROW_FLUSH_INTERVAL`]
    /// before `now`. Otherwise give the time of the next due batch, or `None` when no
    /// row waits.
    pub fn take_due(&self, now: Instant) -> Result<DueRows, Option<Instant>> {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        Self::take_locked(&mut state, now)
    }

    fn take_locked(state: &mut HashMap<String, PendingRows>, now: Instant) -> Result<DueRows, Option<Instant>> {
        // An entry without rows is kept only to space the flushes of its batch.
        state.retain(|_, p| p.batch || !p.files.is_empty() || p.taken.is_some_and(|t| now < t + ROW_FLUSH_INTERVAL));
        let mut next: Option<Instant> = None;
        for (batch_id, pending) in state.iter_mut() {
            if !pending.batch && pending.files.is_empty() {
                continue;
            }
            let due = pending.taken.map_or(now, |t| t + ROW_FLUSH_INTERVAL);
            if due <= now {
                pending.taken = Some(now);
                return Ok(DueRows {
                    batch_id: batch_id.clone(),
                    batch: std::mem::take(&mut pending.batch),
                    files: std::mem::take(&mut pending.files),
                });
            }
            next = Some(next.map_or(due, |n: Instant| n.min(due)));
        }
        Err(next)
    }

    /// Wait for the next due batch and take its rows.
    pub fn wait_due(&self) -> DueRows {
        let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        loop {
            let now = Instant::now();
            let wait = match Self::take_locked(&mut state, now) {
                Ok(due) => return due,
                Err(Some(next)) => next.saturating_duration_since(now),
                Err(None) => Duration::from_secs(60),
            };
            state = self.wake.wait_timeout(state, wait).unwrap_or_else(|e| e.into_inner()).0;
        }
    }
}

/// The time source. The tests use a clock that they move by hand.
pub trait Clock: Send + Sync {
    fn now_ms(&self) -> i64;
}

/// The wall clock.
pub struct SystemClock;

impl Clock for SystemClock {
    fn now_ms(&self) -> i64 {
        (time::OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000) as i64
    }
}

/// The current upload target of a user: one upload dataset of a collection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Target {
    pub collection: String,
    pub upload_dataset: String,
    pub dataset_path: String,
    pub mount: DatasetMount,
}

/// The answer of [`UploadAccess::target`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TargetLookup {
    Target(Target),
    /// The user may not upload into the dataset, or it is not an upload dataset of the
    /// collection.
    None,
    /// The user may upload into `upload_dataset`, but its folder does not open now, for
    /// example because the mount is not available. This is not a permission change.
    Unavailable { upload_dataset: String, reason: String },
}

/// The text of a mutation while the dataset folder of the batch does not open.
pub const FOLDER_UNAVAILABLE_MESSAGE: &str = "The upload folder is not available now. Try again later.";

/// The error of [`Service::current_target`] when the dataset folder does not open. The
/// files of the batch stay, and placement repeats later.
#[derive(Debug)]
pub struct FolderUnavailable(pub String);

impl std::fmt::Display for FolderUnavailable {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "the upload folder does not open: {}", self.0)
    }
}

impl std::error::Error for FolderUnavailable {}

/// The permission check of every mutation: the uploader membership, the dataset setting
/// and the mounted destination.
pub trait UploadAccess: Send + Sync {
    fn target(&self, username: &str, collection: &str, dataset: &str) -> anyhow::Result<TargetLookup>;
}

/// One `upload_batches` row.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BatchRecord {
    pub batch_id: String,
    pub upload_dataset: String,
    pub folder: String,
    pub username: String,
    pub manifest_digest: String,
    pub request_id: String,
    pub state: String,
    pub file_count: u32,
    pub byte_count: u64,
    pub error: String,
    pub created_ms: i64,
    pub last_write_ms: i64,
    pub committed_ms: i64,
    pub finished_ms: i64,
    pub row_version: u64,
}

/// One `upload_files` row.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FileRecord {
    pub batch_id: String,
    pub file_no: u32,
    pub path: String,
    pub size_bytes: u64,
    pub placement_token: String,
    pub client_mtime_s: i64,
    pub state: String,
    pub error: String,
    pub row_version: u64,
}

/// The ClickHouse copy of the journal.
pub trait BatchStore: Send + Sync {
    fn write_batch(&self, collection: &str, row: &BatchRecord) -> anyhow::Result<()>;
    fn write_files(&self, collection: &str, rows: &[FileRecord]) -> anyhow::Result<()>;
    /// The stored state of a batch, or `None` when no row exists.
    fn batch_state(&self, collection: &str, upload_dataset: &str, batch_id: &str) -> anyhow::Result<Option<String>>;
    /// Whether the registry proves collection deletion. Errors preserve its journals.
    fn collection_deleted(&self, _collection: &str) -> anyhow::Result<bool> {
        Ok(false)
    }
    /// Whether the dataset has a live registry row. The sweep stops the transfers of a
    /// deleted dataset.
    fn dataset_live(&self, _upload_dataset: &str) -> anyhow::Result<bool> {
        Ok(true)
    }
    /// Whether a `delete_dataset` or `purge_dataset` operation of the dataset is pending,
    /// queued or running. `begin` refuses a new batch while one is.
    fn latest_dataset_removal(&self, _upload_dataset: &str) -> anyhow::Result<String> {
        Ok(String::new())
    }
    fn dataset_removal_live(&self, _upload_dataset: &str) -> anyhow::Result<bool> {
        Ok(false)
    }
}

/// The wake-up of the queue workflow of a dataset.
pub trait QueueNotifier: Send + Sync {
    fn notify(&self, collection: &str, upload_dataset: &str, batch_id: &str) -> anyhow::Result<()>;
}

/// The free space of a folder.
pub trait FreeSpace: Send + Sync {
    fn free_bytes(&self, dir: BorrowedFd<'_>) -> anyhow::Result<u64>;
}

/// `statvfs` of the real file system.
pub struct StatvfsFreeSpace;

impl FreeSpace for StatvfsFreeSpace {
    fn free_bytes(&self, dir: BorrowedFd<'_>) -> anyhow::Result<u64> {
        fsutil::free_bytes(dir)
    }
}

/// A refusal or a failure of an upload route, with its HTTP status.
#[derive(Debug)]
pub struct UploadError {
    pub status: u16,
    pub message: String,
    pub refusal: Option<common::uploads::BeginRefusal>,
}

impl UploadError {
    pub fn new(status: u16, message: impl Into<String>) -> Self {
        UploadError { status, message: message.into(), refusal: None }
    }

    pub fn forbidden() -> Self {
        UploadError::new(403, "forbidden: this upload belongs to another user")
    }

    pub fn no_permission() -> Self {
        UploadError::new(403, common::uploads::NO_PERMISSION_MESSAGE)
    }

    pub fn ended(status: u16) -> Self {
        UploadError::new(status, common::uploads::ENDED_MESSAGE)
    }

    pub fn not_found() -> Self {
        UploadError::new(404, "not found")
    }

    /// Another request holds a lock of the batch or the file for longer than
    /// [`LOCK_WAIT`].
    pub fn busy() -> Self {
        UploadError::new(423, BUSY_MESSAGE)
    }
}

/// The text of a request that waited [`LOCK_WAIT`] for another request of the same upload.
pub const BUSY_MESSAGE: &str = "Another request of this upload is still running. Try again later.";

impl From<anyhow::Error> for UploadError {
    fn from(err: anyhow::Error) -> Self {
        if err.downcast_ref::<FolderUnavailable>().is_some() {
            tracing::warn!("upload request refused for now: {err:#}");
            return UploadError::new(503, FOLDER_UNAVAILABLE_MESSAGE);
        }
        UploadError::new(500, format!("{err:#}"))
    }
}

pub type UploadResult<T> = Result<T, UploadError>;

/// The receiver. One value serves the process. The tests build their own.
pub struct Service {
    pub space: Space,
    pub limits: UploadLimits,
    pub clock: Arc<dyn Clock>,
    pub store: Arc<dyn BatchStore>,
    pub notifier: Arc<dyn QueueNotifier>,
    pub access: Arc<dyn UploadAccess>,
    pub free_space: Arc<dyn FreeSpace>,
    pub faults: Faults,
    /// The longest wait for a lock that another request holds. [`LOCK_WAIT`] in
    /// production. The tests use a short wait.
    pub lock_wait: std::time::Duration,
    /// The rows that wait for the flusher.
    pub rows: RowQueue,
}

/// A whole number from the environment, or the default when it is unset or empty.
fn env_number(name: &str, default: u64) -> anyhow::Result<u64> {
    match std::env::var(name) {
        Ok(v) if !v.trim().is_empty() => v
            .trim()
            .parse::<u64>()
            .map_err(|_| anyhow::anyhow!("{name} is not a whole number: {v:?}")),
        _ => Ok(default),
    }
}

/// The limits from `HOOVER4_UPLOAD_*`, which `deploy.py` renders from `[uploads]`.
pub fn limits_from_env() -> anyhow::Result<UploadLimits> {
    let d = UploadLimits::default();
    let limits = UploadLimits {
        max_batch_files: env_number("HOOVER4_UPLOAD_MAX_BATCH_FILES", d.max_batch_files)?,
        max_batch_bytes: env_number("HOOVER4_UPLOAD_MAX_BATCH_BYTES", d.max_batch_bytes)?,
        max_file_bytes: env_number("HOOVER4_UPLOAD_MAX_FILE_BYTES", d.max_file_bytes)?,
        chunk_bytes: env_number("HOOVER4_UPLOAD_CHUNK_BYTES", d.chunk_bytes)?,
        abandon_hours: env_number("HOOVER4_UPLOAD_ABANDON_HOURS", d.abandon_hours)?,
        ..d
    };
    if limits.chunk_bytes == 0 {
        anyhow::bail!("HOOVER4_UPLOAD_CHUNK_BYTES must be above 0");
    }
    Ok(limits)
}

/// The upload space path from `HOOVER4_UPLOAD_SPACE`, or [`DEFAULT_SPACE`].
pub fn space_from_env() -> PathBuf {
    match std::env::var("HOOVER4_UPLOAD_SPACE") {
        Ok(v) if !v.trim().is_empty() => PathBuf::from(v.trim()),
        _ => PathBuf::from(DEFAULT_SPACE),
    }
}

static SERVICE: OnceLock<Result<Arc<Service>, String>> = OnceLock::new();
/// The multi-threaded runtime that started the receiver. Background work of a request
/// runs there, because a Dioxus server function runs on a runtime that a spawned task
/// does not outlive.
static RUNTIME: OnceLock<tokio::runtime::Handle> = OnceLock::new();

/// The receiver of this process. An error names the reason that uploads are not served.
pub fn service() -> UploadResult<Arc<Service>> {
    match SERVICE.get() {
        Some(Ok(service)) => Ok(service.clone()),
        Some(Err(reason)) => Err(UploadError::new(503, format!("Uploads are not available: {reason}"))),
        None => Err(UploadError::new(503, "Uploads are not available: the receiver has not started")),
    }
}

/// The passes of [`stop_dataset_transfers`] over batches whose lock another request held.
const STOP_PASSES: usize = 10;

/// Stop the transfers of an upload dataset after its deletion or purge was dispatched.
/// The stop runs in the background, so the dispatch does not wait for a request of an
/// upload. Each pass waits at most [`LOCK_WAIT`] for each batch, and a busy batch is
/// tried again in the next pass, up to [`STOP_PASSES`] passes. Without a receiver in this
/// process there is nothing to stop. A failure is logged, and the next sweep stops the
/// transfers of a deleted dataset.
///
/// A cancelled deletion does not restore the uploads that this stop ended.
pub fn stop_dataset_transfers(upload_dataset: &str, reason: &'static str) {
    let (Ok(service), Some(runtime)) = (service(), RUNTIME.get()) else { return };
    let dataset = upload_dataset.to_string();
    runtime.spawn(async move {
        for _ in 0..STOP_PASSES {
            let worker = service.clone();
            let id = dataset.clone();
            match tokio::task::spawn_blocking(move || worker.stop_dataset(&id, reason)).await {
                Ok(Ok(stop)) => {
                    if stop.stopped > 0 {
                        tracing::info!("stopped {} upload batches of {dataset}: {reason}", stop.stopped);
                    }
                    if stop.busy == 0 {
                        return;
                    }
                    tracing::warn!("{} upload batches of {dataset} are busy, the stop tries again", stop.busy);
                }
                Ok(Err(e)) => {
                    tracing::error!("stopping the upload batches of {dataset} failed: {e:#}");
                    return;
                }
                Err(e) => {
                    tracing::error!("stopping the upload batches of {dataset} panicked: {e}");
                    return;
                }
            }
        }
    });
}

/// Build the receiver of this process, recover the journal, and start the hourly sweep.
/// Called once at startup on the multi-threaded runtime.
pub fn start() {
    let handle = tokio::runtime::Handle::current();
    let _ = RUNTIME.set(handle.clone());
    let built = (|| -> anyhow::Result<Service> {
        let service = Service {
            space: Space { root: space_from_env() },
            limits: limits_from_env()?,
            clock: Arc::new(SystemClock),
            store: Arc::new(store::ClickHouseStore::new(handle.clone())),
            notifier: Arc::new(store::TemporalNotifier::new(handle.clone())),
            access: Arc::new(store::DbAccess::new(handle.clone())),
            free_space: Arc::new(StatvfsFreeSpace),
            faults: Faults::default(),
            lock_wait: LOCK_WAIT,
            rows: RowQueue::default(),
        };
        service.prepare_space()?;
        Ok(service)
    })();
    let built = built.map(Arc::new).map_err(|e| format!("{e:#}"));
    if let Err(reason) = &built {
        tracing::error!("the upload receiver did not start: {reason}");
    }
    let started = built.as_ref().ok().cloned();
    let _ = SERVICE.set(built);
    let Some(service) = started else { return };
    // The flusher blocks on ClickHouse through `Handle::block_on`, so it runs on a thread
    // of its own outside the runtime.
    let flusher = service.clone();
    if let Err(e) = std::thread::Builder::new().name("upload-rows".to_string()).spawn(move || flusher.run_row_flusher()) {
        tracing::error!("the upload row flusher did not start, rows wait for the commit and the sweep: {e}");
    }
    tokio::spawn(async move {
        let mut startup = true;
        loop {
            let worker = service.clone();
            let result = tokio::task::spawn_blocking(move || worker.sweep(startup)).await;
            match result {
                Ok(Ok(report)) => tracing::info!("upload sweep: {report}"),
                Ok(Err(e)) => tracing::error!("upload sweep failed: {e:#}"),
                Err(e) => tracing::error!("upload sweep panicked: {e}"),
            }
            startup = false;
            tokio::time::sleep(std::time::Duration::from_secs(3600)).await;
        }
    });
}

impl Service {
    /// Create the folders of the upload space. The space itself must exist, because a
    /// folder created in the container layer instead of the volume loses its files on
    /// recreation.
    pub fn prepare_space(&self) -> anyhow::Result<()> {
        if !self.space.root.is_dir() {
            anyhow::bail!("the upload space {} does not exist", self.space.root.display());
        }
        for dir in [self.space.locks(), self.space.requests(), self.space.batches(), self.space.done(), self.space.datasets()] {
            fsutil::ensure_dir(&dir)?;
        }
        Ok(())
    }

    /// The batch row of the current journal.
    pub fn batch_record(&self, manifest: &Manifest, batch: &BatchJournal) -> BatchRecord {
        BatchRecord {
            batch_id: manifest.batch_id.clone(),
            upload_dataset: manifest.upload_dataset.clone(),
            folder: manifest.folder.clone(),
            username: manifest.username.clone(),
            manifest_digest: manifest.manifest_digest.clone(),
            request_id: manifest.request_id.clone(),
            state: batch.state.clone(),
            file_count: manifest.files.len() as u32,
            byte_count: manifest.byte_count(),
            error: batch.error.chars().take(2000).collect(),
            created_ms: manifest.created_ms,
            last_write_ms: batch.mirrored_activity_ms,
            committed_ms: batch.committed_ms,
            finished_ms: batch.finished_ms,
            row_version: batch.version,
        }
    }

    /// The file row of the current journal.
    pub fn file_record(&self, manifest: &Manifest, file: &FileJournal) -> FileRecord {
        let entry = &manifest.files[file.file_no as usize];
        FileRecord {
            batch_id: manifest.batch_id.clone(),
            file_no: file.file_no,
            path: entry.path.clone(),
            size_bytes: entry.size,
            placement_token: file.placement.as_ref().map(|p| p.token.clone()).unwrap_or_default(),
            client_mtime_s: entry.mtime_ms.div_euclid(1000),
            state: file.state.row_state().to_string(),
            error: file.error.chars().take(2000).collect(),
            row_version: file.version,
        }
    }

    /// Write the batch journal.
    pub fn save_batch(&self, batch: &BatchJournal, point: &str) -> anyhow::Result<()> {
        fsutil::write_json(&self.space.batch_journal(&batch.batch_id), batch, &self.faults, point)
    }

    /// Write a file journal.
    pub fn save_file(&self, batch_id: &str, file: &FileJournal, point: &str) -> anyhow::Result<()> {
        fsutil::write_json(&self.space.file_journal(batch_id, file.file_no), file, &self.faults, point)
    }

    /// Copy the batch row to ClickHouse when the journal holds a newer version. The caller
    /// holds the batch lock.
    pub fn flush_batch(&self, manifest: &Manifest, batch: &mut BatchJournal) -> anyhow::Result<()> {
        if batch.db_version >= batch.version {
            return Ok(());
        }
        self.store.write_batch(&manifest.collection, &self.batch_record(manifest, batch))?;
        self.faults.hit("db.batch_written")?;
        batch.db_version = batch.version;
        self.save_batch(batch, "batch.db_version")
    }

    /// Copy the given file rows to ClickHouse in one insert and record their versions.
    /// The caller holds the lock of each file or the exclusive batch lock.
    ///
    /// The journal records are written with one synchronization of their folder. A lost
    /// record keeps the earlier record, which differs only by a lower `db_version`, so the
    /// row is written again.
    pub fn flush_files(&self, manifest: &Manifest, files: &mut [FileJournal]) -> anyhow::Result<()> {
        let rows: Vec<FileRecord> = files
            .iter()
            .filter(|f| f.db_version < f.version)
            .map(|f| self.file_record(manifest, f))
            .collect();
        if rows.is_empty() {
            return Ok(());
        }
        self.store.write_files(&manifest.collection, &rows)?;
        self.faults.hit("db.files_written")?;
        let dir = self.space.files_dir(&manifest.batch_id);
        for file in files.iter_mut().filter(|f| f.db_version < f.version) {
            file.db_version = file.version;
            let name = format!("{}.json", file.file_no);
            fsutil::replace_unsynced(&dir, &name, &serde_json::to_vec(&*file)?, &self.faults, "file.db_version")?;
        }
        self.faults.hit("file.db_version.before_sync")?;
        fsutil::sync_dir(&dir)
    }

    /// Queue the batch row (`None`) or one file row for the flusher.
    pub fn queue_rows(&self, batch_id: &str, file_no: Option<u32>) {
        self.rows.mark(batch_id, file_no);
    }

    /// Write the queued rows of one batch from the journal as it is now: the file rows in
    /// one insert, then the batch row. The flusher holds no lock, so no request waits for
    /// the insert, and it records no `db_version`. A row of a later version that another
    /// writer stored first stays current, because the tables keep the row with the
    /// highest `row_version`.
    pub fn flush_queued(&self, due: &DueRows) -> anyhow::Result<()> {
        let Some(manifest) = journal::read_manifest(&self.space, &due.batch_id)? else { return Ok(()) };
        let mut rows = Vec::new();
        for &file_no in &due.files {
            if file_no as usize >= manifest.files.len() {
                continue;
            }
            let file = journal::read_file(&self.space, &manifest, file_no)?;
            if file.db_version < file.version {
                rows.push(self.file_record(&manifest, &file));
            }
        }
        if !rows.is_empty() {
            self.store.write_files(&manifest.collection, &rows)?;
        }
        if due.batch {
            if let Some(batch) = journal::read_batch(&self.space, &due.batch_id)? {
                if batch.db_version < batch.version {
                    self.store.write_batch(&manifest.collection, &self.batch_record(&manifest, &batch))?;
                }
            }
        }
        Ok(())
    }

    /// The loop of the flusher thread. A failed flush queues its rows again, so they are
    /// tried after the next interval.
    pub fn run_row_flusher(&self) {
        loop {
            let due = self.rows.wait_due();
            if let Err(e) = self.flush_queued(&due) {
                tracing::warn!("upload batch {}: the row write waits for the next flush: {e:#}", due.batch_id);
                if due.batch {
                    self.queue_rows(&due.batch_id, None);
                }
                for &file_no in &due.files {
                    self.queue_rows(&due.batch_id, Some(file_no));
                }
            }
        }
    }

    /// The target of a batch now, or `None` when the owner may no longer write it. The
    /// target must still be the dataset of the batch. A dataset folder that does not open
    /// is an error of type [`FolderUnavailable`], so no caller reads it as a lost
    /// permission and rejects the files.
    pub fn current_target(&self, manifest: &Manifest) -> anyhow::Result<Option<Target>> {
        if self.removal_changed(manifest)? {
            return Ok(None);
        }
        Ok(match self.access.target(&manifest.username, &manifest.collection, &manifest.upload_dataset)? {
            TargetLookup::Target(t) => Some(t),
            TargetLookup::Unavailable { reason, .. } => return Err(FolderUnavailable(reason).into()),
            TargetLookup::None => None,
        })
    }

    /// A removal dispatched after begin stops the batch, including a completed purge.
    pub fn removal_changed(&self, manifest: &Manifest) -> anyhow::Result<bool> {
        match &manifest.removal_op_id {
            Some(previous) => Ok(self.store.latest_dataset_removal(&manifest.upload_dataset)? != *previous),
            None => self.store.dataset_removal_live(&manifest.upload_dataset),
        }
    }

    /// Open the root folder of a target through directory descriptors.
    pub fn open_target_root(&self, target: &Target) -> anyhow::Result<OwnedFd> {
        let (_, fd) = crate::db_auth::uploads::open_dataset_folder(std::slice::from_ref(&target.mount), &target.dataset_path)?;
        Ok(fd)
    }
}

/// A random lowercase hex id of 32 characters.
pub fn random_id() -> String {
    let bytes: [u8; 16] = rand::random();
    hex::encode(bytes)
}

/// Lowercase hex SHA-256 of some bytes.
pub fn sha256_hex(bytes: &[u8]) -> String {
    use sha2::Digest;
    hex::encode(sha2::Sha256::digest(bytes))
}

/// An HTTP date, for `Upload-Expires`.
pub fn http_date(ms: i64) -> String {
    let t = std::time::UNIX_EPOCH + std::time::Duration::from_millis(ms.max(0) as u64);
    httpdate::fmt_http_date(t)
}
