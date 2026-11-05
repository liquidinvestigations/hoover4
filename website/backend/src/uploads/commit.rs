//! `commit`, the end of a transfer, startup recovery and the hourly sweep.
//!
//! `commit` writes the stop marker, so every later `PATCH` gets 409. It then takes the
//! exclusive batch lock, which waits for each active `PATCH`, and records `committing`.
//! The wait ends after the lock wait of the service with 423. The marker stays, the
//! client may repeat the commit, and the sweep commits the batch. A `PATCH` ends at the
//! latest after the idle limit of its body. `commit` answers without waiting for
//! placement. [`Service::finish`] then marks each
//! incomplete file `not_sent` and removes its bytes, places each complete file, and
//! records `queued`, or `cancelled` when no file was placed. A `queued` batch is a durable
//! dispatch record: the sweep signals its queue again until an operation claims it.
//!
//! | Journal state at the sweep | Action |
//! |---|---|
//! | no manifest or no batch journal | `begin` stopped before it answered. Remove the batch folder. |
//! | rows not recorded, no request record for the batch | `begin` never answered. Remove the batch. |
//! | rows not recorded, request record present | Write the rows. |
//! | recorded Abort intent | Complete cancellation without queueing files. |
//! | `uploading` with the stop marker | Complete its recorded commit or legacy stop. |
//! | `uploading`, journal activity older than `abandon_hours` | Commit as a stop. |
//! | `uploading` | Truncate unacknowledged bytes, place complete files, mirror activity. |
//! | `committing`, at startup or older than 10 minutes | Finish the commit. |
//! | `queued`, ClickHouse still `queued` | Signal the queue again. |
//! | `queued` and claimed, or `cancelled` | Keep a done record and remove the journal. |
//!
//! A batch whose exclusive lock is held is busy and is skipped, so the sweep never
//! touches an active transfer, copy or commit.

use common::uploads::{CommitResponse, ABORTED_MESSAGE};

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

/// The result of [`Service::stop_dataset`].
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct DatasetStop {
    /// The batches that the call stopped.
    pub stopped: usize,
    /// The batches whose lock another request held for the whole lock wait.
    pub busy: usize,
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
            self.reserve_intent(batch_id, "commit")?;
            let marker = self.space.stopping(batch_id);
            if !marker.exists() {
                std::fs::File::create(&marker).map_err(anyhow::Error::from)?;
                fsutil::sync_dir(&self.space.batch_dir(batch_id))?;
            }
            self.faults.hit("commit.stop_marker")?;
            let _lock = fsutil::lock_within(&self.space.batch_lock(batch_id), true, self.lock_wait)?
                .ok_or_else(UploadError::busy)?;
            let mut batch = journal::read_batch(&self.space, batch_id)?.ok_or_else(|| UploadError::ended(410))?;
            if batch.state == batch_state::UPLOADING {
                self.mark_committing(&mut batch)?;
            }
            state = batch.state.clone();
            tracing::info!("upload batch {batch_id} committed by its owner");
        }
        Ok(CommitResponse {
            batch_id: batch_id.to_string(),
            state,
            detail: detail_address(&manifest.collection, batch_id),
        })
    }

    /// Reserve the terminal intent before waiting for active transfers.
    fn reserve_intent(&self, batch_id: &str, intent: &str) -> UploadResult<()> {
        let dir = self.space.batch_dir(batch_id);
        let _lock = fsutil::lock(&dir.join("intent.lock"), true, true)?;
        let path = dir.join("intent-v1.json");
        if let Some(previous) = fsutil::read_json::<String>(&path)? {
            if previous != intent {
                return Err(UploadError::ended(409));
            }
        } else {
            fsutil::write_json(&path, &intent, &self.faults, "terminal.intent")?;
        }
        Ok(())
    }

    fn abort_intended(&self, batch_id: &str) -> anyhow::Result<bool> {
        Ok(fsutil::read_json::<String>(&self.space.batch_dir(batch_id).join("intent-v1.json"))?
            .as_deref() == Some("abort"))
    }

    fn mark_committing(&self, batch: &mut BatchJournal) -> anyhow::Result<()> {
        let now = self.clock.now_ms();
        batch.state = batch_state::COMMITTING.to_string();
        batch.committed_ms = now;
        batch.last_activity_ms = now;
        batch.version += 1;
        self.save_batch(batch, "commit.committing")?;
        // A finish that fails leaves the batch `committing`, and the flusher writes that row.
        self.queue_rows(&batch.batch_id, None);
        Ok(())
    }

    /// Finish a `committing` batch, and signal the queue of a `queued` batch that has no
    /// accepted signal yet. It waits at most the lock wait of the service for the
    /// exclusive batch lock. A batch that stays busy is finished by the sweep.
    pub fn finish(&self, batch_id: &str) -> anyhow::Result<()> {
        let Some(lock) = fsutil::lock_within(&self.space.batch_lock(batch_id), true, self.lock_wait)? else {
            tracing::warn!("upload batch {batch_id} is busy, the sweep finishes its commit");
            return Ok(());
        };
        let (Some(manifest), Some(mut batch)) = (
            journal::read_manifest(&self.space, batch_id)?,
            journal::read_batch(&self.space, batch_id)?,
        ) else {
            return Ok(());
        };
        self.finish_locked(&manifest, &mut batch, None)?;
        drop(lock);
        self.release_reservation(&manifest)
    }

    /// The commit work under the exclusive batch lock. The holder owns every file of the
    /// batch, so it takes no file lock.
    ///
    /// `stop_reason` names the deletion or purge of the dataset. The batch then has no
    /// target, each complete file is rejected with that reason, and a batch without a
    /// placed file is `cancelled` with that reason as its error.
    ///
    /// Without a stop reason, only a lost permission or target rejects the complete
    /// files. A dataset folder that does not open is an error: the batch stays
    /// `committing` with its files, and the sweep tries again.
    fn finish_locked(&self, manifest: &Manifest, batch: &mut BatchJournal, stop_reason: Option<&str>) -> anyhow::Result<()> {
        if batch.state == batch_state::COMMITTING {
            let target = match stop_reason {
                Some(_) => None,
                None => self.current_target(manifest)?,
            };
            let reject_reason = stop_reason.unwrap_or(common::uploads::NO_PERMISSION_MESSAGE);
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
                            self.reject(manifest, &mut file, root.as_ref(), reject_reason)?;
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
                if let Some(reason) = stop_reason {
                    batch.error = reason.to_string();
                }
            }
            batch.version += 1;
            self.save_batch(batch, "finish.state")?;
            tracing::info!(
                "upload batch {} is {}: {placed} of {} files placed",
                manifest.batch_id,
                batch.state,
                manifest.files.len()
            );
        }
        // One batch row for the commit and its end, after the file rows, so the worker
        // reads the file rows of every `queued` batch.
        self.flush_batch(manifest, batch)?;
        if batch.state == batch_state::QUEUED && batch.notified_ms == 0 {
            self.notify_queue(manifest, batch)?;
        }
        Ok(())
    }

    fn notify_queue(&self, manifest: &Manifest, batch: &mut BatchJournal) -> anyhow::Result<()> {
        anyhow::ensure!(!self.store.collection_deleted(&manifest.collection)?, "The upload collection was deleted.");
        anyhow::ensure!(!self.abort_intended(&manifest.batch_id)?, "The upload was aborted.");
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
        if self.store.collection_deleted(&manifest.collection)? {
            for entry in &manifest.files {
                let file = journal::read_file(&self.space, &manifest, entry.file_no)?;
                self.remove_owned_part(&manifest, &file, None)?;
            }
            batch.state = batch_state::CANCELLED.to_string();
            self.archive(&manifest, &batch)?;
            drop(lock);
            self.release_reservation(&manifest)?;
            return Ok(SweepOutcome::Removed);
        }
        if self.abort_intended(batch_id)? {
            self.abort_locked(&manifest, &mut batch)?;
            drop(lock);
            self.release_reservation(&manifest)?;
            return Ok(SweepOutcome::Removed);
        }
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
        let in_transfer = matches!(batch.state.as_str(), batch_state::UPLOADING | batch_state::COMMITTING);
        if in_transfer && !self.store.dataset_live(&manifest.upload_dataset)? {
            self.stop_locked(&manifest, &mut batch, common::uploads::DATASET_DELETED_MESSAGE)?;
            drop(lock);
            self.release_reservation(&manifest)?;
            return Ok(SweepOutcome::Stopped);
        }
        if in_transfer && self.removal_changed(&manifest)? {
            self.stop_locked(&manifest, &mut batch, common::uploads::DATASET_PURGED_MESSAGE)?;
            drop(lock);
            self.release_reservation(&manifest)?;
            return Ok(SweepOutcome::Stopped);
        }
        let outcome = match batch.state.as_str() {
            batch_state::UPLOADING if self.space.stopping(batch_id).exists() => {
                // The owner asked for the commit, which did not record `committing`.
                self.reserve_intent(batch_id, "commit").map_err(|e| anyhow::anyhow!(e.message))?;
                self.mark_committing(&mut batch)?;
                tracing::info!("upload batch {batch_id} has the stop marker and is committed");
                self.finish_locked(&manifest, &mut batch, None)?;
                SweepOutcome::Committed
            }
            batch_state::UPLOADING => {
                let mut activity = batch.last_activity_ms;
                // A target that does not open now only delays placement.
                let target = match self.current_target(&manifest) {
                    Ok(target) => target,
                    Err(e) => {
                        tracing::warn!("upload batch {batch_id}: placement waits: {e:#}");
                        None
                    }
                };
                let mut placed: Vec<FileJournal> = Vec::new();
                for entry in &manifest.files {
                    let mut file = journal::read_file(&self.space, &manifest, entry.file_no)?;
                    activity = activity.max(file.last_activity_ms);
                    self.truncate_unacknowledged(batch_id, &file)?;
                    if target.is_some() && matches!(file.state, FileState::Complete | FileState::Placing) {
                        self.place(&manifest, &mut file, target.as_ref())?;
                        placed.push(file);
                    }
                }
                self.flush_files(&manifest, &mut placed)?;
                if now - activity > self.limits.abandon_hours as i64 * 3_600_000 {
                    self.reserve_intent(batch_id, "commit").map_err(|e| anyhow::anyhow!(e.message))?;
                    let marker = self.space.stopping(batch_id);
                    if !marker.exists() {
                        std::fs::File::create(&marker)?;
                        fsutil::sync_dir(&self.space.batch_dir(batch_id))?;
                    }
                    self.mark_committing(&mut batch)?;
                    tracing::info!("upload batch {batch_id} had no transfer for {} hours and is committed", self.limits.abandon_hours);
                    self.finish_locked(&manifest, &mut batch, None)?;
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
                    self.finish_locked(&manifest, &mut batch, None)?;
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

    /// The hook for batches that an operation claimed. It does nothing: the worker owns
    /// every state after the claim. The `UploadQueue` workflow settles the batches of an
    /// ended operation, and the operations supervisor wakes the queue of every dataset
    /// with a waiting or claimed batch (`tasks/P_upload/activities.py`,
    /// `recover_upload_queues`). The website keeps no transfer state for them.
    fn reconcile_claimed(&self, _manifest: &Manifest, _stored_state: Option<&str>) -> anyhow::Result<()> {
        Ok(())
    }

    /// End the transfer of a batch whose dataset was deleted or purged. The caller holds
    /// the exclusive batch lock.
    ///
    /// An `uploading` batch gets the stop marker and becomes `committing`. The commit then
    /// finishes without a target: pending files become `not_sent`, complete files are
    /// rejected with `reason`, and their bytes leave the upload space. The batch becomes
    /// `cancelled`, or `queued` when files were placed before the stop. The worker settles
    /// a `queued` batch of a deleted dataset as `failed`.
    fn stop_locked(&self, manifest: &Manifest, batch: &mut BatchJournal, reason: &str) -> anyhow::Result<()> {
        if batch.state == batch_state::UPLOADING {
            if self.abort_intended(&manifest.batch_id)? { return self.abort_locked(manifest, batch); }
            self.reserve_intent(&manifest.batch_id, "commit").map_err(|e| anyhow::anyhow!(e.message))?;
            let marker = self.space.stopping(&manifest.batch_id);
            if !marker.exists() {
                std::fs::File::create(&marker)?;
                fsutil::sync_dir(&self.space.batch_dir(&manifest.batch_id))?;
            }
            self.mark_committing(batch)?;
        }
        self.finish_locked(manifest, batch, Some(reason))?;
        tracing::info!("upload batch {} stopped: {reason}", manifest.batch_id);
        Ok(())
    }

    /// Stop every transfer of an upload dataset after its deletion or purge was
    /// dispatched. It waits at most the lock wait of the service for the lock of each
    /// batch, so an active `PATCH` ends first. A batch whose lock stays held is counted as
    /// busy and is not changed.
    pub fn stop_dataset(&self, upload_dataset: &str, reason: &str) -> anyhow::Result<DatasetStop> {
        let mut stop = DatasetStop::default();
        for batch_id in journal::list_names(&self.space.batches())? {
            if !journal::valid_batch_id(&batch_id) {
                continue;
            }
            let Some(manifest) = journal::read_manifest(&self.space, &batch_id)? else { continue };
            if manifest.upload_dataset != upload_dataset {
                continue;
            }
            let Some(lock) = fsutil::lock_within(&self.space.batch_lock(&batch_id), true, self.lock_wait)? else {
                stop.busy += 1;
                continue;
            };
            let Some(mut batch) = journal::read_batch(&self.space, &batch_id)? else { continue };
            if !matches!(batch.state.as_str(), batch_state::UPLOADING | batch_state::COMMITTING) {
                continue;
            }
            self.stop_locked(&manifest, &mut batch, reason)?;
            drop(lock);
            self.release_reservation(&manifest)?;
            stop.stopped += 1;
        }
        Ok(stop)
    }

    /// Abort an `uploading` batch for its owner. The stop marker refuses new bytes. Under
    /// the exclusive batch lock, each file that the batch placed or was placing leaves the
    /// dataset folder when its identity is the recorded one, and each folder that its
    /// placements created is removed when it is empty. Every file and the batch
    /// get the error [`ABORTED_MESSAGE`], the batch becomes `cancelled`, and its upload
    /// space is deleted. Nothing is queued for indexing.
    ///
    /// A repeated abort of an aborted batch succeeds. A batch whose commit started is 409.
    pub fn abort(&self, username: &str, batch_id: &str) -> UploadResult<()> {
        let (manifest, batch) = match self.owned_batch(username, batch_id) {
            Ok(found) => found,
            Err(e) if e.status == 410 => {
                let done = fsutil::read_json::<DoneRecord>(&self.space.done_record(batch_id))?
                    .ok_or_else(UploadError::not_found)?;
                if done.state == batch_state::CANCELLED {
                    return Ok(());
                }
                return Err(UploadError::ended(409));
            }
            Err(e) => return Err(e),
        };
        if batch.state != batch_state::UPLOADING {
            return Err(UploadError::ended(409));
        }
        self.reserve_intent(batch_id, "abort")?;
        self.faults.hit("abort.intent")?;
        let marker = self.space.stopping(batch_id);
        if !marker.exists() {
            std::fs::File::create(&marker).map_err(anyhow::Error::from)?;
            fsutil::sync_dir(&self.space.batch_dir(batch_id))?;
        }
        let lock = fsutil::lock_within(&self.space.batch_lock(batch_id), true, self.lock_wait)?
            .ok_or_else(UploadError::busy)?;
        let mut batch = journal::read_batch(&self.space, batch_id)?.ok_or_else(|| UploadError::ended(410))?;
        if batch.state != batch_state::UPLOADING {
            return Err(UploadError::ended(409));
        }
        self.abort_locked(&manifest, &mut batch)?;
        drop(lock);
        let _dataset = fsutil::lock(&self.space.dataset_lock(&manifest.upload_dataset), true, true)?;
        fsutil::remove_file(&self.space.live_dir(&manifest.upload_dataset).join(batch_id))?;
        Ok(())
    }

    fn abort_locked(&self, manifest: &Manifest, batch: &mut BatchJournal) -> anyhow::Result<()> {
        let mut files: Vec<FileJournal> = Vec::with_capacity(manifest.files.len());
        let mut removed: Vec<u32> = Vec::new();
        let mut folder = None;
        let mut created: Vec<String> = Vec::new();
        for entry in &manifest.files {
            let mut file = journal::read_file(&self.space, &manifest, entry.file_no)?;
            match file.state {
                FileState::Placed | FileState::Placing => {
                    if self.unplace(&manifest, &file)? {
                        removed.push(file.file_no);
                    }
                    if let Some(placement) = file.placement.as_ref() {
                        if folder.is_none() {
                            folder = placement.folder.clone();
                        }
                        created.extend(placement.created_folders.iter().cloned());
                    }
                    file.state = FileState::Rejected;
                }
                FileState::Pending | FileState::Complete => file.state = FileState::NotSent,
                FileState::Rejected | FileState::NotSent => {}
            }
            file.error = ABORTED_MESSAGE.to_string();
            file.version += 1;
            files.push(file);
        }
        if let Some(folder) = folder.as_ref() {
            self.remove_empty_folders(folder, &created)?;
        }
        self.flush_files(&manifest, &mut files)?;
        let now = self.clock.now_ms();
        batch.state = batch_state::CANCELLED.to_string();
        batch.committed_ms = now;
        batch.finished_ms = now;
        batch.last_activity_ms = now;
        batch.error = ABORTED_MESSAGE.to_string();
        batch.version += 1;
        self.save_batch(&batch, "abort.cancelled")?;
        self.flush_batch(manifest, batch)?;
        self.archive(manifest, batch)?;
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
