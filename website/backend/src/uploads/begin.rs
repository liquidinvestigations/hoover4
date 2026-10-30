//! `begin`: check a manifest, reserve its paths and record the batch.
//!
//! `begin` runs every check of the page ([`common::uploads::check_manifest`]) and the two
//! checks that need the disk: existing paths and free space. The request lock makes a
//! repeated request id return its first batch. The dataset lock serializes the
//! reservation check of all batches of one dataset. A batch reserves its paths with its
//! live marker until commit has placed or released each file.
//!
//! The order of the durable writes is manifest, batch journal, live marker, request
//! record, ClickHouse file rows, ClickHouse batch row. Recovery completes or removes a
//! batch at each point between them, so `begin` never returns a partly recorded batch.

use std::collections::HashSet;
use std::os::fd::AsFd;

use common::uploads::{
    ancestors, check_manifest, normalize_folder, path_names, BatchFile, BeginRefusal, BeginRequest,
    BeginResponse, COLLISIONS_MESSAGE, PROBLEMS_MESSAGE, REQUEST_ID_REUSED_MESSAGE,
};

use super::fsutil::{self, Found};
use super::journal::{
    self, batch_state, BatchJournal, FileJournal, Manifest, ManifestFile, RequestRecord,
};
use super::{random_id, sha256_hex, upload_url, Service, TargetLookup, UploadError, UploadResult};

/// The text of a `begin` for a collection without an upload target of the user.
pub const NO_TARGET_MESSAGE: &str = "You cannot upload into this collection.";
/// The text of a `begin` for a collection with two upload datasets.
pub const CONFLICT_MESSAGE: &str =
    "This collection has two upload datasets. An administrator must disable one.";
/// The text of a `begin` while a deletion or a purge of the upload dataset is live.
pub const REMOVAL_MESSAGE: &str =
    "This upload dataset is being deleted or purged. Uploads into it can start after that operation ends.";
/// The text of a malformed request id.
pub const REQUEST_ID_MESSAGE: &str = "The request id must have 1 to 128 letters, digits, - or _.";

/// True for a client request id of 1 to 128 ASCII letters, digits, `-` and `_`.
pub fn valid_request_id(request_id: &str) -> bool {
    (1..=128).contains(&request_id.len())
        && request_id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

/// The digest of the owner, the destination and the ordered manifest of a request.
pub fn manifest_digest(username: &str, request: &BeginRequest, folder: &str) -> String {
    let files: Vec<(&str, u64, Option<i64>)> = request
        .files
        .iter()
        .map(|f| (f.path.as_str(), f.size, f.last_modified_ms))
        .collect();
    let canonical = serde_json::json!({
        "username": username,
        "collection": request.collection,
        "folder": folder,
        "files": files,
    });
    sha256_hex(canonical.to_string().as_bytes())
}

/// The key of one (user, request id) in the upload space.
pub fn request_key(username: &str, request_id: &str) -> String {
    sha256_hex(format!("{username}\0{request_id}").as_bytes())
}

fn refusal(status: u16, refusal: BeginRefusal) -> UploadError {
    UploadError { status, message: refusal.message.clone(), refusal: Some(refusal) }
}

/// The paths that the live batches of a dataset reserve: their files, and the folders
/// above those files.
pub struct Reservations {
    pub files: HashSet<String>,
    pub folders: HashSet<String>,
}

impl Reservations {
    /// True when `destination` equals a reserved file or folder, or is beneath a
    /// reserved file.
    pub fn conflicts(&self, destination: &str) -> bool {
        self.files.contains(destination)
            || self.folders.contains(destination)
            || ancestors(destination).iter().any(|a| self.files.contains(a))
    }
}

impl Service {
    /// The reservations of the live batches of a dataset. The caller holds the dataset lock.
    pub fn reservations(&self, dataset: &str) -> anyhow::Result<Reservations> {
        let mut out = Reservations { files: HashSet::new(), folders: HashSet::new() };
        for batch_id in journal::live_batches(&self.space, dataset)? {
            let (Some(manifest), Some(batch)) = (
                journal::read_manifest(&self.space, &batch_id)?,
                journal::read_batch(&self.space, &batch_id)?,
            ) else {
                continue;
            };
            if batch.state != batch_state::UPLOADING && batch.state != batch_state::COMMITTING {
                continue;
            }
            for file in &manifest.files {
                out.folders.extend(ancestors(&file.path));
                out.files.insert(file.path.clone());
            }
        }
        Ok(out)
    }

    /// Check, reserve and record a batch. A repeated request with the same manifest
    /// returns the first batch. The function blocks.
    pub fn begin(&self, username: &str, request: &BeginRequest) -> UploadResult<BeginResponse> {
        if !valid_request_id(&request.request_id) {
            return Err(UploadError::new(400, REQUEST_ID_MESSAGE));
        }
        let target = match self.access.target(username, &request.collection)? {
            TargetLookup::Target(target) => target,
            TargetLookup::Conflict(_) => return Err(UploadError::new(409, CONFLICT_MESSAGE)),
            TargetLookup::None => return Err(UploadError::new(403, NO_TARGET_MESSAGE)),
            TargetLookup::Unavailable { reason, .. } => return Err(anyhow::Error::from(super::FolderUnavailable(reason)).into()),
        };
        // The dispatch of a deletion or a purge stops the open batches. A batch that
        // began after that stop would continue into the removed dataset.
        if self.store.dataset_removal_live(&target.upload_dataset)? {
            return Err(UploadError::new(409, REMOVAL_MESSAGE));
        }
        if !journal::valid_dataset_id(&target.upload_dataset) {
            return Err(anyhow::anyhow!("the dataset id {:?} is not usable in the upload space", target.upload_dataset).into());
        }
        let check = check_manifest(&self.limits, &request.folder, &request.files);
        if !check.is_empty() {
            return Err(refusal(400, BeginRefusal {
                message: PROBLEMS_MESSAGE.to_string(),
                batch_problems: check.batch_problems,
                problems: check.problems,
                collisions: Vec::new(),
            }));
        }
        let folder = normalize_folder(&request.folder).map_err(|p| UploadError::new(400, p.message()))?;
        let destinations: Vec<String> = check.destinations.into_iter().flatten().collect();
        let digest = manifest_digest(username, request, &folder);
        let key = request_key(username, &request.request_id);

        let _request_lock = fsutil::lock(&self.space.request_lock(&key), true, true)?;
        if let Some(record) = fsutil::read_json::<RequestRecord>(&self.space.request_record(&key))? {
            if record.manifest_digest != digest {
                return Err(UploadError::new(409, REQUEST_ID_REUSED_MESSAGE));
            }
            return self.existing_batch(&record.batch_id);
        }

        let dataset_lock = fsutil::lock(&self.space.dataset_lock(&target.upload_dataset), true, true)?;
        let reservations = self.reservations(&target.upload_dataset)?;
        let root = self.open_target_root(&target)?;
        let mut collisions = Vec::new();
        for destination in &destinations {
            if reservations.conflicts(destination) {
                collisions.push(destination.clone());
                continue;
            }
            match fsutil::find(&root, &path_names(destination))? {
                Found::Absent => {}
                Found::Entry { .. } | Found::Blocked => collisions.push(destination.clone()),
            }
        }
        if !collisions.is_empty() {
            return Err(refusal(409, BeginRefusal {
                message: COLLISIONS_MESSAGE.to_string(),
                collisions,
                ..Default::default()
            }));
        }
        let needed: u64 = request.files.iter().map(|f| f.size).sum();
        let space_fd = fsutil::open_space_dir(&self.space.root)?;
        let free = self
            .free_space
            .free_bytes(space_fd.as_fd())?
            .min(self.free_space.free_bytes(root.as_fd())?);
        if free < needed {
            return Err(UploadError::new(507, common::uploads::free_space_message(free, needed)));
        }

        let now = self.clock.now_ms();
        let batch_id = random_id();
        let manifest = Manifest {
            batch_id: batch_id.clone(),
            username: username.to_string(),
            request_id: request.request_id.clone(),
            request_key: key.clone(),
            collection: request.collection.clone(),
            upload_dataset: target.upload_dataset.clone(),
            folder,
            manifest_digest: digest.clone(),
            created_ms: now,
            files: request
                .files
                .iter()
                .zip(destinations)
                .enumerate()
                .map(|(no, (file, path))| ManifestFile {
                    file_no: no as u32,
                    path,
                    size: file.size,
                    mtime_ms: file.last_modified_ms.unwrap_or(now),
                })
                .collect(),
        };
        let mut batch = BatchJournal {
            batch_id: batch_id.clone(),
            state: batch_state::UPLOADING.to_string(),
            version: 1,
            db_version: 0,
            files_recorded: false,
            last_activity_ms: now,
            mirrored_activity_ms: now,
            committed_ms: 0,
            finished_ms: 0,
            error: String::new(),
            notified_ms: 0,
        };
        fsutil::ensure_dir(&self.space.files_dir(&batch_id))?;
        // Held until the rows are written, so the sweep skips this batch as busy.
        let _batch_lock = fsutil::lock(&self.space.batch_lock(&batch_id), true, true)?;
        fsutil::write_json(&self.space.manifest(&batch_id), &manifest, &self.faults, "begin.manifest")?;
        self.save_batch(&batch, "begin.batch")?;
        let live = self.space.live_dir(&manifest.upload_dataset);
        fsutil::ensure_dir(&live)?;
        std::fs::File::create(live.join(&batch_id)).map_err(anyhow::Error::from)?;
        fsutil::sync_dir(&live)?;
        self.faults.hit("begin.live_marker")?;
        let record = RequestRecord {
            username: username.to_string(),
            request_id: request.request_id.clone(),
            batch_id: batch_id.clone(),
            manifest_digest: digest,
        };
        fsutil::write_json(&self.space.request_record(&key), &record, &self.faults, "begin.request")?;
        drop(dataset_lock);
        self.record_manifest(&manifest, &mut batch)?;
        tracing::info!("upload batch {batch_id} began: {} files into {}", manifest.files.len(), manifest.upload_dataset);
        Ok(response(&manifest))
    }

    /// The batch of a repeated request. The function completes the ClickHouse rows of an
    /// interrupted `begin` first.
    fn existing_batch(&self, batch_id: &str) -> UploadResult<BeginResponse> {
        let _batch_lock = fsutil::lock_within(&self.space.batch_lock(batch_id), true, self.lock_wait)?
            .ok_or_else(UploadError::busy)?;
        let (Some(manifest), Some(mut batch)) = (
            journal::read_manifest(&self.space, batch_id)?,
            journal::read_batch(&self.space, batch_id)?,
        ) else {
            return Err(UploadError::ended(409));
        };
        self.record_manifest(&manifest, &mut batch)?;
        Ok(response(&manifest))
    }

    /// Write the `upload_files` rows of the manifest in one insert, then the batch row.
    /// The caller holds the exclusive batch lock.
    pub fn record_manifest(&self, manifest: &Manifest, batch: &mut BatchJournal) -> anyhow::Result<()> {
        if !batch.files_recorded {
            let rows: Vec<_> = manifest
                .files
                .iter()
                .map(|f| self.file_record(manifest, &FileJournal::initial(f.file_no, manifest.created_ms)))
                .collect();
            self.store.write_files(&manifest.collection, &rows)?;
            self.faults.hit("begin.files_written")?;
            batch.files_recorded = true;
            self.save_batch(batch, "begin.files_recorded")?;
        }
        self.flush_batch(manifest, batch)
    }
}

fn response(manifest: &Manifest) -> BeginResponse {
    BeginResponse {
        batch_id: manifest.batch_id.clone(),
        files: manifest
            .files
            .iter()
            .map(|f| BatchFile {
                file_no: f.file_no,
                path: f.path.clone(),
                upload_url: upload_url(&manifest.batch_id, f.file_no),
            })
            .collect(),
    }
}
