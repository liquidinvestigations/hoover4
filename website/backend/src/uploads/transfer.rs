//! The transfer operations behind the tus routes, and the acknowledged-prefix digest.
//!
//! Each operation takes the shared batch lock and then the exclusive file lock, so it
//! never runs beside a commit of the batch or another operation on the same file. The
//! acknowledged offset is the `offset` of the file journal. Bytes beyond it in the data
//! file came from a request that did not finish, and the next operation truncates them.

use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};
use std::sync::Arc;

use common::uploads::PrefixDigest;

use super::fsutil::{self, Lock};
use super::journal::{self, batch_state, FileJournal, FileState, Manifest, RequestRecord};
use super::{Service, UploadError, UploadResult};

/// The text of a `PATCH` whose bytes pass the declared length or the chunk limit.
pub const OVERFLOW_MESSAGE: &str = "The request has more bytes than the file or the chunk limit allows.";
/// The text of a creation whose `Upload-Length` differs from the manifest.
pub const LENGTH_MESSAGE: &str = "Upload-Length differs from the size in the upload list.";
/// The text of an offset that differs from the acknowledged offset.
pub const OFFSET_MESSAGE: &str = "Upload-Offset differs from the acknowledged offset.";
/// The text of a change to a complete file.
pub const COMPLETE_MESSAGE: &str = "This file is complete.";

/// Split a tus upload id `<batch_id>-<file_no>`.
pub fn parse_upload_id(id: &str) -> Option<(String, u32)> {
    let (batch, file) = id.split_once('-')?;
    if !journal::valid_batch_id(batch) || file.is_empty() || !file.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    Some((batch.to_string(), file.parse().ok()?))
}

/// The state of one transfer that the tus responses report.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransferInfo {
    pub offset: u64,
    pub length: u64,
    pub expires_ms: i64,
    /// True when every byte is durable. The caller starts placement.
    pub complete: bool,
}

/// How a `PATCH` body ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BodyEnd {
    /// The body ended normally.
    Complete,
    /// The connection or the body stream failed. The received prefix is kept.
    Interrupted,
    /// The body passed its limit. No byte of the request is kept.
    Overflow,
}

/// One `PATCH` in progress. It holds the batch and file locks until it ends.
pub struct PatchSession {
    service: Arc<Service>,
    manifest: Manifest,
    file: FileJournal,
    data: File,
    start: u64,
    written: u64,
    limit: u64,
    _batch_lock: Lock,
    _file_lock: Lock,
}

impl PatchSession {
    /// Append bytes. Returns `false` and writes nothing when the bytes pass the limit.
    pub fn write(&mut self, bytes: &[u8]) -> anyhow::Result<bool> {
        if self.written + bytes.len() as u64 > self.limit {
            return Ok(false);
        }
        self.data.write_all(bytes)?;
        self.written += bytes.len() as u64;
        Ok(true)
    }

    /// End the request. The kept bytes are synchronized before the journal records them.
    pub fn finish(mut self, end: BodyEnd) -> UploadResult<TransferInfo> {
        let service = self.service.clone();
        let entry_size = self.manifest.files[self.file.file_no as usize].size;
        if end == BodyEnd::Overflow {
            self.data.set_len(self.start).map_err(anyhow::Error::from)?;
            self.data.sync_all().map_err(anyhow::Error::from)?;
            return Err(UploadError::new(413, OVERFLOW_MESSAGE));
        }
        self.data.sync_all().map_err(anyhow::Error::from)?;
        service.faults.hit("patch.synced")?;
        self.file.offset = self.start + self.written;
        self.file.last_activity_ms = service.clock.now_ms();
        let complete = self.file.offset == entry_size;
        if complete {
            self.file.state = FileState::Complete;
            self.file.version += 1;
        }
        service.save_file(&self.manifest.batch_id, &self.file, "patch.journal")?;
        if complete {
            // A failed row write stays in the journal and the next flush repeats it.
            if let Err(e) = service.flush_files(&self.manifest, std::slice::from_mut(&mut self.file)) {
                tracing::warn!("upload batch {} file {}: the staged row waits: {e:#}", self.manifest.batch_id, self.file.file_no);
            }
        }
        Ok(service.transfer_info(&self.manifest, &self.file))
    }
}

impl Service {
    /// The manifest and journal of a batch that `username` owns. Another owner gives 403.
    /// A removed journal gives 410 for the owner.
    pub fn owned_batch(&self, username: &str, batch_id: &str) -> UploadResult<(Manifest, journal::BatchJournal)> {
        if !journal::valid_batch_id(batch_id) {
            return Err(UploadError::not_found());
        }
        let Some(manifest) = journal::read_manifest(&self.space, batch_id)? else {
            if let Some(done) = fsutil::read_json::<journal::DoneRecord>(&self.space.done_record(batch_id))? {
                if done.username != username {
                    return Err(UploadError::forbidden());
                }
                return Err(UploadError::ended(410));
            }
            return Err(UploadError::not_found());
        };
        if manifest.username != username {
            return Err(UploadError::forbidden());
        }
        let Some(mut batch) = journal::read_batch(&self.space, batch_id)? else {
            return Err(UploadError::not_found());
        };
        if !batch.files_recorded {
            // Only the client of the request record received this id. Complete its rows
            // before any change.
            let record = fsutil::read_json::<RequestRecord>(&self.space.request_record(&manifest.request_key))?;
            if record.map(|r| r.batch_id) != Some(batch_id.to_string()) {
                return Err(UploadError::not_found());
            }
            let _lock = fsutil::lock(&self.space.batch_lock(batch_id), true, true)?;
            if let Some(mut current) = journal::read_batch(&self.space, batch_id)? {
                self.record_manifest(&manifest, &mut current)?;
                batch = current;
            }
        }
        Ok((manifest, batch))
    }

    /// Refuse a mutation when the owner may no longer write the target of the batch.
    pub fn require_target(&self, manifest: &Manifest) -> UploadResult<super::Target> {
        self.current_target(manifest)?.ok_or_else(UploadError::no_permission)
    }

    fn file_entry(manifest: &Manifest, file_no: u32) -> UploadResult<&journal::ManifestFile> {
        manifest.files.get(file_no as usize).ok_or_else(UploadError::not_found)
    }

    /// Take the shared batch lock and the exclusive file lock, in that order.
    fn lock_file(&self, batch_id: &str, file_no: u32) -> UploadResult<(Lock, Lock)> {
        let batch = fsutil::lock(&self.space.batch_lock(batch_id), false, true)?
            .ok_or_else(|| anyhow::anyhow!("the batch lock was not taken"))?;
        if !self.space.batch_journal(batch_id).exists() {
            return Err(UploadError::ended(410));
        }
        let file = fsutil::lock(&self.space.file_lock(batch_id, file_no), true, true)?
            .ok_or_else(|| anyhow::anyhow!("the file lock was not taken"))?;
        Ok((batch, file))
    }

    /// Refuse a transfer change when the batch no longer accepts bytes.
    fn require_open(&self, batch_id: &str) -> UploadResult<()> {
        let batch = journal::read_batch(&self.space, batch_id)?.ok_or_else(|| UploadError::ended(410))?;
        if batch.state != batch_state::UPLOADING || self.space.stopping(batch_id).exists() {
            return Err(UploadError::ended(409));
        }
        Ok(())
    }

    /// The tus state of a file.
    pub fn transfer_info(&self, manifest: &Manifest, file: &FileJournal) -> TransferInfo {
        let length = manifest.files[file.file_no as usize].size;
        let offset = match file.state {
            FileState::Pending | FileState::NotSent => file.offset,
            _ => length,
        };
        TransferInfo {
            offset,
            length,
            expires_ms: file.last_activity_ms + self.limits.abandon_hours as i64 * 3_600_000,
            complete: matches!(file.state, FileState::Complete),
        }
    }

    /// Remove bytes beyond the acknowledged offset of a pending file. The caller holds
    /// the file lock or the exclusive batch lock.
    pub fn truncate_unacknowledged(&self, batch_id: &str, file: &FileJournal) -> anyhow::Result<()> {
        if file.state != FileState::Pending {
            return Ok(());
        }
        let path = self.space.data(batch_id, file.file_no);
        match std::fs::metadata(&path) {
            Ok(meta) if meta.len() > file.offset => {
                let data = std::fs::OpenOptions::new().write(true).open(&path)?;
                data.set_len(file.offset)?;
                data.sync_all()?;
            }
            Ok(_) => {}
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
            Err(e) => return Err(e.into()),
        }
        Ok(())
    }

    /// tus `POST`: create the transfer of one manifest file, or return the existing one.
    /// It never truncates acknowledged bytes. A zero-byte file is complete at once.
    pub fn tus_create(&self, username: &str, batch_id: &str, file_no: u32, length: u64) -> UploadResult<TransferInfo> {
        let (manifest, _) = self.owned_batch(username, batch_id)?;
        let entry = Self::file_entry(&manifest, file_no)?;
        if entry.size != length {
            return Err(UploadError::new(400, LENGTH_MESSAGE));
        }
        self.require_target(&manifest)?;
        let _locks = self.lock_file(batch_id, file_no)?;
        self.require_open(batch_id)?;
        let mut file = journal::read_file(&self.space, &manifest, file_no)?;
        match file.state {
            FileState::NotSent | FileState::Rejected => return Err(UploadError::ended(410)),
            FileState::Pending => {
                std::fs::OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(self.space.data(batch_id, file_no))
                    .map_err(anyhow::Error::from)?;
                fsutil::sync_dir(&self.space.files_dir(batch_id))?;
                self.truncate_unacknowledged(batch_id, &file)?;
                if length == 0 {
                    file.state = FileState::Complete;
                    file.version += 1;
                    file.last_activity_ms = self.clock.now_ms();
                    self.save_file(batch_id, &file, "create.complete")?;
                    if let Err(e) = self.flush_files(&manifest, std::slice::from_mut(&mut file)) {
                        tracing::warn!("upload batch {batch_id} file {file_no}: the staged row waits: {e:#}");
                    }
                }
            }
            FileState::Complete | FileState::Placing | FileState::Placed => {}
        }
        Ok(self.transfer_info(&manifest, &file))
    }

    /// tus `HEAD`: the acknowledged offset. It needs no current upload target.
    pub fn tus_head(&self, username: &str, batch_id: &str, file_no: u32) -> UploadResult<TransferInfo> {
        let (manifest, _) = self.owned_batch(username, batch_id)?;
        Self::file_entry(&manifest, file_no)?;
        let _locks = self.lock_file(batch_id, file_no)?;
        let file = journal::read_file(&self.space, &manifest, file_no)?;
        if matches!(file.state, FileState::NotSent | FileState::Rejected) {
            return Err(UploadError::ended(410));
        }
        self.truncate_unacknowledged(batch_id, &file)?;
        Ok(self.transfer_info(&manifest, &file))
    }

    /// tus `PATCH`: check the request and open the data file at the acknowledged offset.
    /// `content_length` is `None` for a chunked body.
    pub fn tus_patch_open(
        self: &Arc<Self>,
        username: &str,
        batch_id: &str,
        file_no: u32,
        offset: u64,
        content_length: Option<u64>,
    ) -> UploadResult<PatchSession> {
        let (manifest, _) = self.owned_batch(username, batch_id)?;
        let size = Self::file_entry(&manifest, file_no)?.size;
        self.require_target(&manifest)?;
        let (batch_lock, file_lock) = self.lock_file(batch_id, file_no)?;
        self.require_open(batch_id)?;
        let file = journal::read_file(&self.space, &manifest, file_no)?;
        match file.state {
            FileState::Pending => {}
            FileState::NotSent | FileState::Rejected => return Err(UploadError::ended(410)),
            _ => return Err(UploadError::new(409, COMPLETE_MESSAGE)),
        }
        self.truncate_unacknowledged(batch_id, &file)?;
        if offset != file.offset {
            return Err(UploadError::new(409, OFFSET_MESSAGE));
        }
        let limit = self.limits.chunk_bytes.min(size - file.offset);
        if content_length.is_some_and(|n| n > limit) {
            return Err(UploadError::new(413, OVERFLOW_MESSAGE));
        }
        let mut data = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(false)
            .open(self.space.data(batch_id, file_no))
            .map_err(anyhow::Error::from)?;
        data.seek(SeekFrom::Start(file.offset)).map_err(anyhow::Error::from)?;
        Ok(PatchSession {
            service: self.clone(),
            start: file.offset,
            manifest,
            file,
            data,
            written: 0,
            limit,
            _batch_lock: batch_lock,
            _file_lock: file_lock,
        })
    }

    /// tus `DELETE`: end an incomplete transfer and remove its bytes. A complete or placed
    /// file stays.
    pub fn tus_terminate(&self, username: &str, batch_id: &str, file_no: u32) -> UploadResult<()> {
        let (manifest, _) = self.owned_batch(username, batch_id)?;
        Self::file_entry(&manifest, file_no)?;
        self.require_target(&manifest)?;
        let _locks = self.lock_file(batch_id, file_no)?;
        let mut file = journal::read_file(&self.space, &manifest, file_no)?;
        match file.state {
            FileState::NotSent | FileState::Rejected => return Ok(()),
            FileState::Pending => {}
            _ => return Err(UploadError::new(409, COMPLETE_MESSAGE)),
        }
        self.require_open(batch_id)?;
        file.state = FileState::NotSent;
        file.version += 1;
        file.last_activity_ms = self.clock.now_ms();
        self.save_file(batch_id, &file, "terminate.journal")?;
        fsutil::remove_file(&self.space.data(batch_id, file_no))?;
        if let Err(e) = self.flush_files(&manifest, std::slice::from_mut(&mut file)) {
            tracing::warn!("upload batch {batch_id} file {file_no}: the not_sent row waits: {e:#}");
        }
        Ok(())
    }

    /// The SHA-256 of the acknowledged prefix of an incomplete file, for the check of a
    /// reselected file before resume. Only the owner may read it.
    pub fn prefix_digest(&self, username: &str, batch_id: &str, file_no: u32) -> UploadResult<PrefixDigest> {
        use sha2::Digest;
        let (manifest, _) = self.owned_batch(username, batch_id)?;
        let length = Self::file_entry(&manifest, file_no)?.size;
        let _locks = self.lock_file(batch_id, file_no)?;
        let file = journal::read_file(&self.space, &manifest, file_no)?;
        match file.state {
            FileState::Pending => {}
            FileState::NotSent | FileState::Rejected => return Err(UploadError::ended(410)),
            _ => return Err(UploadError::new(409, COMPLETE_MESSAGE)),
        }
        self.truncate_unacknowledged(batch_id, &file)?;
        let mut hasher = sha2::Sha256::new();
        if file.offset > 0 {
            let mut data = File::open(self.space.data(batch_id, file_no)).map_err(anyhow::Error::from)?;
            let mut left = file.offset;
            let mut buffer = vec![0u8; 1 << 20];
            while left > 0 {
                let want = left.min(buffer.len() as u64) as usize;
                let n = data.read(&mut buffer[..want]).map_err(anyhow::Error::from)?;
                if n == 0 {
                    return Err(anyhow::anyhow!("the data file is shorter than its acknowledged offset").into());
                }
                hasher.update(&buffer[..n]);
                left -= n as u64;
            }
        }
        Ok(PrefixDigest { file_no, offset: file.offset, length, sha256: hex::encode(hasher.finalize()) })
    }

    /// Place one file after its last byte arrived, while the batch is open. A batch whose
    /// owner may no longer write it keeps the file complete, and commit rejects it.
    pub fn place_after_transfer(&self, batch_id: &str, file_no: u32) -> anyhow::Result<()> {
        let Some(manifest) = journal::read_manifest(&self.space, batch_id)? else { return Ok(()) };
        let locks = self.lock_file(batch_id, file_no);
        let Ok(_locks) = locks else { return Ok(()) };
        let mut file = journal::read_file(&self.space, &manifest, file_no)?;
        if !matches!(file.state, FileState::Complete | FileState::Placing) {
            return Ok(());
        }
        let Some(target) = self.current_target(&manifest)? else { return Ok(()) };
        self.place(&manifest, &mut file, Some(&target))?;
        self.flush_files(&manifest, std::slice::from_mut(&mut file))
    }
}
