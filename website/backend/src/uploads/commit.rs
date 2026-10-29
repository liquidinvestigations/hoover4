//! `commit`, the end of a transfer, startup recovery and the hourly sweep.
//!
//! `commit` writes the stop marker, so every later `PATCH` gets 409. It then takes the
//! exclusive batch lock, which waits for each active `PATCH`, and records `committing`.
//! It answers without waiting for placement. [`Service::finish`] then marks each
//! incomplete file `not_sent` and removes its bytes, places each complete file, and
//! records `queued`, or `cancelled` when no file was placed. A `queued` batch is a durable
//! dispatch record: the sweep signals its queue again until an operation claims it.
//!
//! | Journal state at the sweep | Action |
//! |---|---|
//! | no manifest or no batch journal | `begin` stopped before it answered. Remove the batch folder. |
//! | rows not recorded, no request record for the batch | `begin` never answered. Remove the batch. |
//! | rows not recorded, request record present | Write the rows. |
//! | `uploading`, journal activity older than `abandon_hours` | Commit as a stop. |
//! | `uploading` | Truncate unacknowledged bytes, place complete files, mirror activity. |
//! | `committing`, at startup or older than 10 minutes | Finish the commit. |
//! | `queued`, ClickHouse still `queued` | Signal the queue again. |
//! | `queued` and claimed, or `cancelled` | Keep a done record and remove the journal. |
//!
//! A batch whose exclusive lock is held is busy and is skipped, so the sweep never
//! touches an active transfer, copy or commit.

use common::uploads::CommitResponse;

use super::fsutil;
use super::journal::{self, batch_state, BatchJournal, DoneRecord, FileJournal, FileState, Manifest};
use super::{detail_address, Service, UploadError, UploadResult, COMMIT_RETRY_MS};

/// What the sweep did to one batch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SweepOutcome {
    Busy,
    Removed,
    Uploading,
    Stopped,
    Committed,
    Waiting,
    Notified,
    Archived,
}

/// The counts of one sweep.
#[derive(Debug, Default, Clone)]
pub struct SweepReport {
    pub outcomes: Vec<(String, SweepOutcome)>,
    pub failures: Vec<(String, String)>,
}

impl std::fmt::Display for SweepReport {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let count = |o: SweepOutcome| self.outcomes.iter().filter(|(_, x)| *x == o).count();
        write!(
            f,
            "{} batches: {} busy, {} removed, {} uploading, {} stopped, {} committed, {} waiting, {} notified, {} archived, {} failed",
            self.outcomes.len() + self.failures.len(),
            count(SweepOutcome::Busy),
            count(SweepOutcome::Removed),
            count(SweepOutcome::Uploading),
            count(SweepOutcome::Stopped),
            count(SweepOutcome::Committed),
            count(SweepOutcome::Waiting),
            count(SweepOutcome::Notified),
            count(SweepOutcome::Archived),
            self.failures.len(),
        )
    }
}

impl Service {
    /// End the transfer of a batch. A repeated commit returns the same answer. The
    /// caller then runs [`Service::finish`].
    pub fn commit(&self, username: &str, batch_id: &str) -> UploadResult<CommitResponse> {
        let (manifest, batch) = match self.owned_batch(username, batch_id) {
            Ok(found) => found,
            Err(e) if e.status == 410 => {
                let done = fsutil::read_json::<DoneRecord>(&self.space.done_record(batch_id))?
                    .ok_or_else(UploadError::not_found)?;
                return Ok(CommitResponse {
                    batch_id: batch_id.to_string(),
                    state: done.state,
                    detail: detail_address(&done.collection, batch_id),
                });
            }
            Err(e) => return Err(e),
        };
        let mut state = batch.state.clone();
        if state == batch_state::UPLOADING {
            self.require_target(&manifest)?;
            let marker = self.space.stopping(batch_id);
            if !marker.exists() {
                std::fs::File::create(&marker).map_err(anyhow::Error::from)?;
                fsutil::sync_dir(&self.space.batch_dir(batch_id))?;
            }
            self.faults.hit("commit.stop_marker")?;
            let _lock = fsutil::lock(&self.space.batch_lock(batch_id), true, true)?;
            let mut batch = journal::read_batch(&self.space, batch_id)?.ok_or_else(|| UploadError::ended(410))?;
            if batch.state == batch_state::UPLOADING {
                self.mark_committing(&mut batch)?;
            }
            self.flush_batch(&manifest, &mut batch)?;
            state = batch.state.clone();
            tracing::info!("upload batch {batch_id} committed by its owner");
        }
        Ok(CommitResponse {
            batch_id: batch_id.to_string(),
            state,
            detail: detail_address(&manifest.collection, batch_id),
        })
    }

    fn mark_committing(&self, batch: &mut BatchJournal) -> anyhow::Result<()> {
        let now = self.clock.now_ms();
        batch.state = batch_state::COMMITTING.to_string();
        batch.committed_ms = now;
        batch.last_activity_ms = now;
        batch.version += 1;
        self.save_batch(batch, "commit.committing")
    }

    /// Finish a `committing` batch, and signal the queue of a `queued` batch that has no
    /// accepted signal yet. It waits for the exclusive batch lock.
    pub fn finish(&self, batch_id: &str) -> anyhow::Result<()> {
        let Some(lock) = fsutil::lock(&self.space.batch_lock(batch_id), true, true)? else { return Ok(()) };
        let (Some(manifest), Some(mut batch)) = (
            journal::read_manifest(&self.space, batch_id)?,
            journal::read_batch(&self.space, batch_id)?,
        ) else {
            return Ok(());
        };
        self.finish_locked(&manifest, &mut batch)?;
        drop(lock);
        self.release_reservation(&manifest)
    }

    /// The commit work under the exclusive batch lock. The holder owns every file of the
    /// batch, so it takes no file lock.
    fn finish_locked(&self, manifest: &Manifest, batch: &mut BatchJournal) -> anyhow::Result<()> {
        self.flush_batch(manifest, batch)?;
        if batch.state == batch_state::COMMITTING {
            let target = self.current_target(manifest)?;
            let root = match &target {
                Some(t) => Some(self.open_target_root(t)?),
                None => None,
            };
            let mut files: Vec<FileJournal> = Vec::with_capacity(manifest.files.len());
            for entry in &manifest.files {
                let mut file = journal::read_file(&self.space, manifest, entry.file_no)?;
                match file.state {
                    FileState::Pending => {
                        fsutil::remove_file(&self.space.data(&manifest.batch_id, file.file_no))?;
                        file.state = FileState::NotSent;
                        file.version += 1;
                        self.save_file(&manifest.batch_id, &file, "finish.not_sent")?;
                    }
                    FileState::Complete | FileState::Placing => {
                        if target.is_some() {
                            self.place(manifest, &mut file, target.as_ref())?;
                        } else {
                            self.reject(manifest, &mut file, root.as_ref(), common::uploads::NO_PERMISSION_MESSAGE)?;
                        }
                    }
                    FileState::Placed | FileState::Rejected | FileState::NotSent => {}
                }
                files.push(file);
            }
            self.flush_files(manifest, &mut files)?;
            let placed = files.iter().filter(|f| f.state == FileState::Placed).count();
            let now = self.clock.now_ms();
            if placed > 0 {
                batch.state = batch_state::QUEUED.to_string();
            } else {
                batch.state = batch_state::CANCELLED.to_string();
                batch.finished_ms = now;
            }
            batch.version += 1;
            self.save_batch(batch, "finish.state")?;
            self.flush_batch(manifest, batch)?;
            tracing::info!(
                "upload batch {} is {}: {placed} of {} files placed",
                manifest.batch_id,
                batch.state,
                manifest.files.len()
            );
        }
        if batch.state == batch_state::QUEUED && batch.notified_ms == 0 {
            self.notify_queue(manifest, batch)?;
        }
        Ok(())
    }

    fn notify_queue(&self, manifest: &Manifest, batch: &mut BatchJournal) -> anyhow::Result<()> {
        self.notifier.notify(&manifest.collection, &manifest.upload_dataset, &manifest.batch_id)?;
        self.faults.hit("finish.notified")?;
        batch.notified_ms = self.clock.now_ms();
        // `notified_ms` is not part of the ClickHouse row, so the version stays.
        self.save_batch(batch, "finish.notified_ms")
    }

    /// Remove the live marker of a batch that no longer reserves its paths.
    fn release_reservation(&self, manifest: &Manifest) -> anyhow::Result<()> {
        let state = journal::read_batch(&self.space, &manifest.batch_id)?.map(|b| b.state);
        if matches!(state.as_deref(), Some(batch_state::UPLOADING) | Some(batch_state::COMMITTING)) {
            return Ok(());
        }
        let _dataset = fsutil::lock(&self.space.dataset_lock(&manifest.upload_dataset), true, true)?;
        fsutil::remove_file(&self.space.live_dir(&manifest.upload_dataset).join(&manifest.batch_id))?;
        Ok(())
    }

    /// Startup recovery (`startup = true`) and the hourly sweep. Each batch is handled
    /// under its exclusive lock, taken without waiting.
    pub fn sweep(&self, startup: bool) -> anyhow::Result<SweepReport> {
        let mut report = SweepReport::default();
        for batch_id in journal::list_names(&self.space.batches())? {
            if !journal::valid_batch_id(&batch_id) {
                continue;
            }
            match self.sweep_batch(&batch_id, startup) {
                Ok(outcome) => report.outcomes.push((batch_id, outcome)),
                Err(e) => {
                    tracing::error!("upload sweep of batch {batch_id} failed: {e:#}");
                    report.failures.push((batch_id, format!("{e:#}")));
                }
            }
        }
        // A live marker without its batch reserves nothing.
        for dataset in journal::list_names(&self.space.datasets())? {
            for batch_id in journal::live_batches(&self.space, &dataset)? {
                if !self.space.batch_dir(&batch_id).exists() {
                    let _dataset = fsutil::lock(&self.space.dataset_lock(&dataset), true, true)?;
                    fsutil::remove_file(&self.space.live_dir(&dataset).join(&batch_id))?;
                }
            }
        }
        Ok(report)
    }

    /// The sweep of one batch.
    pub fn sweep_batch(&self, batch_id: &str, startup: bool) -> anyhow::Result<SweepOutcome> {
        let Some(lock) = fsutil::lock(&self.space.batch_lock(batch_id), true, false)? else {
            return Ok(SweepOutcome::Busy);
        };
        let manifest = journal::read_manifest(&self.space, batch_id)?;
        let batch = journal::read_batch(&self.space, batch_id)?;
        let (Some(manifest), Some(mut batch)) = (manifest.clone(), batch) else {
            // `begin` stopped before its batch journal, so no request record, marker or
            // row names this batch.
            if let Some(manifest) = manifest {
                fsutil::remove_file(&self.space.live_dir(&manifest.upload_dataset).join(batch_id))?;
            }
            self.remove_batch_dir(batch_id)?;
            return Ok(SweepOutcome::Removed);
        };
        if !batch.files_recorded {
            let record = fsutil::read_json::<journal::RequestRecord>(&self.space.request_record(&manifest.request_key))?;
            if record.map(|r| r.batch_id) != Some(batch_id.to_string()) {
                drop(lock);
                let _dataset = fsutil::lock(&self.space.dataset_lock(&manifest.upload_dataset), true, true)?;
                fsutil::remove_file(&self.space.live_dir(&manifest.upload_dataset).join(batch_id))?;
                self.remove_batch_dir(batch_id)?;
                return Ok(SweepOutcome::Removed);
            }
            self.record_manifest(&manifest, &mut batch)?;
        }
        self.flush_batch(&manifest, &mut batch)?;
        let mut pending_rows: Vec<FileJournal> = Vec::new();
        for entry in &manifest.files {
            let file = journal::read_file(&self.space, &manifest, entry.file_no)?;
            if file.db_version < file.version {
                pending_rows.push(file);
            }
        }
        self.flush_files(&manifest, &mut pending_rows)?;

        let now = self.clock.now_ms();
        let outcome = match batch.state.as_str() {
            batch_state::UPLOADING => {
                let mut activity = batch.last_activity_ms;
                let target = self.current_target(&manifest)?;
                for entry in &manifest.files {
                    let mut file = journal::read_file(&self.space, &manifest, entry.file_no)?;
                    activity = activity.max(file.last_activity_ms);
                    self.truncate_unacknowledged(batch_id, &file)?;
                    if target.is_some() && matches!(file.state, FileState::Complete | FileState::Placing) {
                        self.place(&manifest, &mut file, target.as_ref())?;
                        self.flush_files(&manifest, std::slice::from_mut(&mut file))?;
                    }
                }
                if now - activity > self.limits.abandon_hours as i64 * 3_600_000 {
                    let marker = self.space.stopping(batch_id);
                    if !marker.exists() {
                        std::fs::File::create(&marker)?;
                        fsutil::sync_dir(&self.space.batch_dir(batch_id))?;
                    }
                    self.mark_committing(&mut batch)?;
                    self.flush_batch(&manifest, &mut batch)?;
                    tracing::info!("upload batch {batch_id} had no transfer for {} hours and is committed", self.limits.abandon_hours);
                    self.finish_locked(&manifest, &mut batch)?;
                    SweepOutcome::Stopped
                } else {
                    if activity > batch.mirrored_activity_ms {
                        batch.mirrored_activity_ms = activity;
                        batch.version += 1;
                        self.save_batch(&batch, "sweep.activity")?;
                        self.flush_batch(&manifest, &mut batch)?;
                    }
                    SweepOutcome::Uploading
                }
            }
            batch_state::COMMITTING => {
                if startup || now - batch.committed_ms > COMMIT_RETRY_MS {
                    self.finish_locked(&manifest, &mut batch)?;
                    SweepOutcome::Committed
                } else {
                    SweepOutcome::Waiting
                }
            }
            batch_state::QUEUED => {
                let stored = self.store.batch_state(&manifest.collection, &manifest.upload_dataset, batch_id)?;
                match stored.as_deref() {
                    Some(batch_state::QUEUED) | None => {
                        self.notify_queue(&manifest, &mut batch)?;
                        SweepOutcome::Notified
                    }
                    Some(_) => {
                        self.reconcile_claimed(&manifest, stored.as_deref())?;
                        self.archive(&manifest, &batch)?;
                        SweepOutcome::Archived
                    }
                }
            }
            _ => {
                self.archive(&manifest, &batch)?;
                SweepOutcome::Archived
            }
        };
        drop(lock);
        if self.space.batch_dir(batch_id).exists() {
            self.release_reservation(&manifest)?;
        } else {
            let _dataset = fsutil::lock(&self.space.dataset_lock(&manifest.upload_dataset), true, true)?;
            fsutil::remove_file(&self.space.live_dir(&manifest.upload_dataset).join(batch_id))?;
        }
        Ok(outcome)
    }

    /// The hook for batches that an operation claimed. The `ingest_upload` operation of
    /// the next change settles their terminal states, including after a failed or
    /// cancelled operation. The website keeps no transfer state for them.
    fn reconcile_claimed(&self, _manifest: &Manifest, _stored_state: Option<&str>) -> anyhow::Result<()> {
        Ok(())
    }

    /// Keep a done record and remove the journal, the data and the request record of a
    /// batch whose transfer ended. The caller holds the exclusive batch lock.
    fn archive(&self, manifest: &Manifest, batch: &BatchJournal) -> anyhow::Result<()> {
        let done = DoneRecord {
            batch_id: manifest.batch_id.clone(),
            username: manifest.username.clone(),
            collection: manifest.collection.clone(),
            upload_dataset: manifest.upload_dataset.clone(),
            state: batch.state.clone(),
        };
        fsutil::write_json(&self.space.done_record(&manifest.batch_id), &done, &self.faults, "archive.done")?;
        let request = self.space.request_record(&manifest.request_key);
        if fsutil::read_json::<journal::RequestRecord>(&request)?.is_some_and(|r| r.batch_id == manifest.batch_id) {
            fsutil::remove_file(&request)?;
        }
        self.remove_batch_dir(&manifest.batch_id)
    }

    fn remove_batch_dir(&self, batch_id: &str) -> anyhow::Result<()> {
        match std::fs::remove_dir_all(self.space.batch_dir(batch_id)) {
            Ok(()) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
        fsutil::sync_dir(&self.space.batches())
    }
}
