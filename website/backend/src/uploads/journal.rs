//! The durable journal of the upload space.
//!
//! The journal owns request-id reservations, path reservations, transfer offsets,
//! transfer activity and placement progress. ClickHouse holds a copy for history and
//! processing. Each record is one JSON file, written by [`super::fsutil::write_json`].
//!
//! ```text
//! <space>/
//!   locks/request-<key>.lock          lock of one (user, request id)
//!   locks/dataset-<dataset>.lock      lock of the reservations of one dataset
//!   requests/<key>.json               RequestRecord: the batch of one (user, request id)
//!   datasets/<dataset>/live/<batch>   empty marker: the batch reserves its manifest paths
//!   batches/<batch>/manifest.json     Manifest, immutable after begin
//!   batches/<batch>/batch.json        BatchJournal
//!   batches/<batch>/batch.lock        lock of the batch
//!   batches/<batch>/stopping          empty marker: commit refuses new PATCH requests
//!   batches/<batch>/files/<n>.json    FileJournal. Absent means pending at offset 0.
//!   batches/<batch>/files/<n>.data    the received bytes of file n
//!   batches/<batch>/files/<n>.lock    lock of file n
//!   done/<batch>.json                 DoneRecord of a batch whose journal was removed
//! ```
//!
//! Lock order: request, then dataset, then batch, then file. A file lock is taken only
//! while the batch lock is held, shared or exclusive. A holder of the exclusive batch lock
//! therefore owns every file of the batch and takes no file lock.

use std::path::{Path, PathBuf};

/// The `upload_files.state` values that the website writes.
pub mod file_state {
    pub const PENDING: &str = "pending";
    pub const STAGED: &str = "staged";
    pub const PLACED: &str = "placed";
    pub const REJECTED: &str = "rejected";
    pub const NOT_SENT: &str = "not_sent";
}

/// The `upload_batches.state` values that the website writes.
pub mod batch_state {
    pub const UPLOADING: &str = "uploading";
    pub const COMMITTING: &str = "committing";
    pub const QUEUED: &str = "queued";
    pub const CANCELLED: &str = "cancelled";
}

/// The paths of the upload space.
#[derive(Debug, Clone)]
pub struct Space {
    pub root: PathBuf,
}

impl Space {
    pub fn locks(&self) -> PathBuf {
        self.root.join("locks")
    }
    pub fn requests(&self) -> PathBuf {
        self.root.join("requests")
    }
    pub fn batches(&self) -> PathBuf {
        self.root.join("batches")
    }
    pub fn done(&self) -> PathBuf {
        self.root.join("done")
    }
    pub fn datasets(&self) -> PathBuf {
        self.root.join("datasets")
    }
    pub fn request_lock(&self, key: &str) -> PathBuf {
        self.locks().join(format!("request-{key}.lock"))
    }
    pub fn request_record(&self, key: &str) -> PathBuf {
        self.requests().join(format!("{key}.json"))
    }
    pub fn dataset_lock(&self, dataset: &str) -> PathBuf {
        self.locks().join(format!("dataset-{dataset}.lock"))
    }
    pub fn live_dir(&self, dataset: &str) -> PathBuf {
        self.datasets().join(dataset).join("live")
    }
    pub fn batch_dir(&self, batch_id: &str) -> PathBuf {
        self.batches().join(batch_id)
    }
    pub fn files_dir(&self, batch_id: &str) -> PathBuf {
        self.batch_dir(batch_id).join("files")
    }
    pub fn manifest(&self, batch_id: &str) -> PathBuf {
        self.batch_dir(batch_id).join("manifest.json")
    }
    pub fn batch_journal(&self, batch_id: &str) -> PathBuf {
        self.batch_dir(batch_id).join("batch.json")
    }
    pub fn batch_lock(&self, batch_id: &str) -> PathBuf {
        self.batch_dir(batch_id).join("batch.lock")
    }
    pub fn stopping(&self, batch_id: &str) -> PathBuf {
        self.batch_dir(batch_id).join("stopping")
    }
    pub fn file_journal(&self, batch_id: &str, file_no: u32) -> PathBuf {
        self.files_dir(batch_id).join(format!("{file_no}.json"))
    }
    pub fn data_name(file_no: u32) -> String {
        format!("{file_no}.data")
    }
    pub fn data(&self, batch_id: &str, file_no: u32) -> PathBuf {
        self.files_dir(batch_id).join(Self::data_name(file_no))
    }
    pub fn file_lock(&self, batch_id: &str, file_no: u32) -> PathBuf {
        self.files_dir(batch_id).join(format!("{file_no}.lock"))
    }
    pub fn done_record(&self, batch_id: &str) -> PathBuf {
        self.done().join(format!("{batch_id}.json"))
    }
}

/// True for a batch id of 32 lowercase hex characters.
pub fn valid_batch_id(batch_id: &str) -> bool {
    batch_id.len() == 32 && batch_id.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

/// True for a dataset id that is safe as a folder name of the upload space.
pub fn valid_dataset_id(dataset: &str) -> bool {
    !dataset.is_empty()
        && dataset.len() <= 200
        && dataset.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// The binding of one (user, request id) to one batch.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct RequestRecord {
    pub username: String,
    pub request_id: String,
    pub batch_id: String,
    pub manifest_digest: String,
}

/// One file of a manifest.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct ManifestFile {
    pub file_no: u32,
    /// The destination path, in the form of `vfs_files.path`.
    pub path: String,
    pub size: u64,
    /// The declared modification time in milliseconds, or the begin time.
    pub mtime_ms: i64,
}

/// The immutable manifest of a batch.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Manifest {
    pub batch_id: String,
    pub username: String,
    pub request_id: String,
    pub request_key: String,
    pub collection: String,
    pub upload_dataset: String,
    pub folder: String,
    pub manifest_digest: String,
    pub created_ms: i64,
    pub files: Vec<ManifestFile>,
}

impl Manifest {
    pub fn byte_count(&self) -> u64 {
        self.files.iter().map(|f| f.size).sum()
    }
}

/// The mutable state of a batch.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct BatchJournal {
    pub batch_id: String,
    /// One of [`batch_state`].
    pub state: String,
    /// The version of this record. Each change raises it by one. The `upload_batches`
    /// row of this version has `row_version` equal to it.
    pub version: u64,
    /// The highest version that ClickHouse holds.
    pub db_version: u64,
    /// True after the `upload_files` rows of the manifest are in ClickHouse.
    pub files_recorded: bool,
    /// Batch activity, in milliseconds: begin and commit. File activity is in the file
    /// records.
    pub last_activity_ms: i64,
    /// The activity time that ClickHouse holds in `last_write_at`.
    pub mirrored_activity_ms: i64,
    pub committed_ms: i64,
    pub finished_ms: i64,
    pub error: String,
    /// The time of the last queue notification that Temporal accepted, or 0.
    pub notified_ms: i64,
}

/// The transfer and placement state of one file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FileState {
    /// Bytes may still arrive.
    Pending,
    /// Every declared byte is durable in the upload space.
    Complete,
    /// Placement started. The placement record says how far.
    Placing,
    /// The file is in the dataset folder.
    Placed,
    /// The file did not reach the dataset folder, for the reason in `error`.
    Rejected,
    /// The transfer ended before the file was complete.
    NotSent,
}

impl FileState {
    /// The `upload_files.state` value of this state.
    pub fn row_state(self) -> &'static str {
        match self {
            FileState::Pending => file_state::PENDING,
            FileState::Complete | FileState::Placing => file_state::STAGED,
            FileState::Placed => file_state::PLACED,
            FileState::Rejected => file_state::REJECTED,
            FileState::NotSent => file_state::NOT_SENT,
        }
    }
}

/// How placement publishes a file.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlaceMethod {
    /// The upload space and the folder are on one file system.
    Rename,
    /// The two are on different file systems. The bytes go through the reserved part name.
    Copy,
}

/// How far a placement went. Each phase is durable before the next file change.
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PlacePhase {
    /// The method, the source identity and the token are recorded. For a copy, the part
    /// name of this batch and file may exist from this phase on.
    Prepared,
    /// The part file exists with the recorded inode.
    PartCreated,
}

/// The placement record of one file.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct Placement {
    pub token: String,
    pub method: PlaceMethod,
    pub phase: PlacePhase,
    pub src_dev: u64,
    pub src_ino: u64,
    pub part_ino: Option<u64>,
    /// The device and inode of the published file, set with the state `Placed`.
    pub dest_dev: Option<u64>,
    pub dest_ino: Option<u64>,
}

/// The journal record of one file.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct FileJournal {
    pub file_no: u32,
    pub state: FileState,
    /// The acknowledged offset. The bytes before it are synchronized.
    pub offset: u64,
    pub last_activity_ms: i64,
    /// The version of this record. Version 1 is the manifest row of `begin`.
    pub version: u64,
    pub db_version: u64,
    pub error: String,
    pub placement: Option<Placement>,
}

impl FileJournal {
    /// The record of a file before its first byte.
    pub fn initial(file_no: u32, created_ms: i64) -> Self {
        FileJournal {
            file_no,
            state: FileState::Pending,
            offset: 0,
            last_activity_ms: created_ms,
            version: 1,
            db_version: 1,
            error: String::new(),
            placement: None,
        }
    }
}

/// What remains of a batch after its journal is removed.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct DoneRecord {
    pub batch_id: String,
    pub username: String,
    pub collection: String,
    pub upload_dataset: String,
    /// The last state that the website wrote.
    pub state: String,
}

/// Read the manifest of a batch.
pub fn read_manifest(space: &Space, batch_id: &str) -> anyhow::Result<Option<Manifest>> {
    super::fsutil::read_json(&space.manifest(batch_id))
}

/// Read the journal of a batch.
pub fn read_batch(space: &Space, batch_id: &str) -> anyhow::Result<Option<BatchJournal>> {
    super::fsutil::read_json(&space.batch_journal(batch_id))
}

/// Read the journal of a file, or its initial record.
pub fn read_file(space: &Space, manifest: &Manifest, file_no: u32) -> anyhow::Result<FileJournal> {
    Ok(super::fsutil::read_json(&space.file_journal(&manifest.batch_id, file_no))?
        .unwrap_or_else(|| FileJournal::initial(file_no, manifest.created_ms)))
}

/// The batch ids that hold a live marker in one dataset.
pub fn live_batches(space: &Space, dataset: &str) -> anyhow::Result<Vec<String>> {
    list_names(&space.live_dir(dataset))
}

/// The names in a folder of the upload space, sorted. A missing folder gives none.
pub fn list_names(dir: &Path) -> anyhow::Result<Vec<String>> {
    let mut out = Vec::new();
    match std::fs::read_dir(dir) {
        Ok(entries) => {
            for entry in entries {
                let entry = entry?;
                if let Some(name) = entry.file_name().to_str() {
                    if !name.starts_with('.') {
                        out.push(name.to_string());
                    }
                }
            }
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => return Err(e.into()),
    }
    out.sort();
    Ok(out)
}
