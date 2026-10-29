//! Placement: the move of a complete file from the upload space into the dataset folder.
//!
//! Every path step opens a folder through the descriptor of its parent with
//! `O_NOFOLLOW`, beneath the dataset root that `open_dataset_folder` opened from the
//! mount root. A symbolic link on the way refuses the path. A publish never replaces an
//! entry: it uses `renameat2(RENAME_NOREPLACE)`, or `linkat`, which also refuses an
//! existing name, on a file system without that flag.
//!
//! The journal records the method, the source identity and a token before the first
//! change in the dataset folder, and the published identity with the state `Placed`. On
//! the same file system the data file is renamed. Across file systems the bytes go to the
//! reserved part name of the file, then the part is renamed. The part name holds the batch
//! id and the file number, and the journal records it before it exists, so the journal
//! proves the ownership of a part with that name.
//!
//! | Found at recovery | Action |
//! |---|---|
//! | The destination has the recorded identity. | Mark it placed and remove the source. |
//! | No destination, the source remains. | Remove an owned part and place again. |
//! | Another entry holds the destination, the source remains. | Reject the file and keep that entry. |
//! | Another entry or no entry, no source. | Reject the file as not recovered. Change nothing in the dataset. |

use std::fs::File;
use std::os::fd::{AsFd, OwnedFd};

use common::uploads::{part_name, path_names, NOT_RECOVERED_MESSAGE, PATH_EXISTS_MESSAGE};
use rustix::fs::{AtFlags, Mode, OFlags, RenameFlags, Timespec, Timestamps};
use rustix::io::Errno;

use super::fsutil::{self, Found, WalkError};
use super::journal::{FileJournal, FileState, Manifest, PlaceMethod, PlacePhase, Placement, Space};
use super::{random_id, Service, Target};

/// The open flags of a data file or a part file. A symbolic link is refused.
const FILE_RW: OFlags = OFlags::RDWR.union(OFlags::NOFOLLOW).union(OFlags::CLOEXEC);

/// Publish `old` in `old_dir` as `new` in `new_dir` without replacing an entry. An
/// existing destination gives `Errno::EXIST`.
pub fn rename_noreplace(old_dir: &OwnedFd, old: &str, new_dir: &OwnedFd, new: &str) -> Result<(), Errno> {
    match rustix::fs::renameat_with(old_dir, old, new_dir, new, RenameFlags::NOREPLACE) {
        Err(Errno::INVAL) | Err(Errno::NOSYS) | Err(Errno::OPNOTSUPP) => {
            // `linkat` refuses an existing name too. The source name goes after the link.
            rustix::fs::linkat(old_dir, old, new_dir, new, AtFlags::empty())?;
            rustix::fs::unlinkat(old_dir, old, AtFlags::empty())
        }
        other => other,
    }
}

fn set_mtime(fd: impl AsFd, mtime_ms: i64) -> anyhow::Result<()> {
    let at = Timespec { tv_sec: mtime_ms.div_euclid(1000), tv_nsec: (mtime_ms.rem_euclid(1000) * 1_000_000) as _ };
    rustix::fs::futimens(fd, &Timestamps { last_access: at, last_modification: at })?;
    Ok(())
}

impl Service {
    fn files_fd(&self, batch_id: &str) -> anyhow::Result<OwnedFd> {
        fsutil::open_space_dir(&self.space.files_dir(batch_id))
    }

    /// Remove the owned part file of a copy placement, when it exists.
    fn remove_owned_part(&self, manifest: &Manifest, file: &FileJournal, root: Option<&OwnedFd>) -> anyhow::Result<()> {
        let (Some(root), Some(placement)) = (root, file.placement.as_ref()) else { return Ok(()) };
        if placement.method != PlaceMethod::Copy {
            return Ok(());
        }
        let names = path_names(&manifest.files[file.file_no as usize].path);
        let parents = &names[..names.len() - 1];
        if let Ok(Some(parent)) = fsutil::open_folders(root, parents, false) {
            match rustix::fs::unlinkat(&parent, part_name(&manifest.batch_id, file.file_no), AtFlags::empty()) {
                Ok(()) => fsutil::sync_fd(&parent)?,
                Err(Errno::NOENT) => {}
                Err(e) => return Err(e.into()),
            }
        }
        Ok(())
    }

    /// End a file as rejected: remove its source bytes and an owned part. Nothing else in
    /// the dataset folder changes.
    pub fn reject(&self, manifest: &Manifest, file: &mut FileJournal, root: Option<&OwnedFd>, reason: &str) -> anyhow::Result<()> {
        self.remove_owned_part(manifest, file, root)?;
        fsutil::remove_file(&self.space.data(&manifest.batch_id, file.file_no))?;
        file.state = FileState::Rejected;
        file.error = reason.to_string();
        file.version += 1;
        self.save_file(&manifest.batch_id, file, "place.rejected")?;
        tracing::info!("upload batch {} file {} rejected: {reason}", manifest.batch_id, file.file_no);
        Ok(())
    }

    fn mark_placed(&self, manifest: &Manifest, file: &mut FileJournal, dev: u64, ino: u64) -> anyhow::Result<()> {
        if let Some(placement) = file.placement.as_mut() {
            placement.dest_dev = Some(dev);
            placement.dest_ino = Some(ino);
        }
        file.state = FileState::Placed;
        file.error.clear();
        file.version += 1;
        self.save_file(&manifest.batch_id, file, "place.placed")?;
        // A copy leaves the source, and a link fallback can leave it after a crash.
        fsutil::remove_file(&self.space.data(&manifest.batch_id, file.file_no))?;
        Ok(())
    }

    /// Place one complete file, or continue an interrupted placement. Without a target
    /// the file is rejected, because the owner may no longer write the dataset. The
    /// caller holds the file lock or the exclusive batch lock. An error leaves the
    /// journal at its last durable phase for a later attempt.
    pub fn place(&self, manifest: &Manifest, file: &mut FileJournal, target: Option<&Target>) -> anyhow::Result<()> {
        if !matches!(file.state, FileState::Complete | FileState::Placing) {
            return Ok(());
        }
        let Some(target) = target else {
            return self.reject(manifest, file, None, common::uploads::NO_PERMISSION_MESSAGE);
        };
        let root = self.open_target_root(target)?;
        let entry = manifest.files[file.file_no as usize].clone();
        let names = path_names(&entry.path);
        let (last, parents) = names.split_last().ok_or_else(|| anyhow::anyhow!("a destination path has a name"))?;
        let data_name = Space::data_name(file.file_no);
        let files_dir = self.files_fd(&manifest.batch_id)?;

        if file.state == FileState::Placing {
            let placement = file.placement.clone().ok_or_else(|| anyhow::anyhow!("a placing file has a placement record"))?;
            let source = fsutil::stat_entry(&files_dir, &data_name)?;
            match fsutil::find(&root, &names)? {
                Found::Entry { dev, ino, .. }
                    if (placement.method == PlaceMethod::Rename && dev == placement.src_dev && ino == placement.src_ino)
                        || (placement.method == PlaceMethod::Copy && Some(ino) == placement.part_ino) =>
                {
                    return self.mark_placed(manifest, file, dev, ino);
                }
                Found::Entry { .. } | Found::Blocked => {
                    if source.is_some() {
                        return self.reject(manifest, file, Some(&root), PATH_EXISTS_MESSAGE);
                    }
                    return self.reject(manifest, file, None, NOT_RECOVERED_MESSAGE);
                }
                Found::Absent => {
                    self.remove_owned_part(manifest, file, Some(&root))?;
                    if source.is_none() {
                        return self.reject(manifest, file, None, NOT_RECOVERED_MESSAGE);
                    }
                    file.state = FileState::Complete;
                }
            }
        }

        let parent = match fsutil::open_folders(&root, parents, true) {
            Ok(Some(parent)) => parent,
            Ok(None) => anyhow::bail!("a created folder is missing"),
            Err(WalkError::Blocked) => return self.reject(manifest, file, Some(&root), PATH_EXISTS_MESSAGE),
            Err(WalkError::Io(e)) => return Err(e.into()),
        };
        if fsutil::stat_entry(&parent, last)?.is_some() {
            return self.reject(manifest, file, Some(&root), PATH_EXISTS_MESSAGE);
        }
        let Some((_, src_dev, src_ino, src_size)) = fsutil::stat_entry(&files_dir, &data_name)? else {
            return self.reject(manifest, file, None, NOT_RECOVERED_MESSAGE);
        };
        if src_size != entry.size {
            return self.reject(manifest, file, None, NOT_RECOVERED_MESSAGE);
        }
        let parent_dev = rustix::fs::fstat(&parent)?.st_dev as u64;
        let method = if parent_dev == src_dev { PlaceMethod::Rename } else { PlaceMethod::Copy };
        file.state = FileState::Placing;
        file.placement = Some(Placement {
            token: random_id(),
            method,
            phase: PlacePhase::Prepared,
            src_dev,
            src_ino,
            part_ino: None,
            dest_dev: None,
            dest_ino: None,
        });
        file.version += 1;
        self.save_file(&manifest.batch_id, file, "place.prepared")?;

        match method {
            PlaceMethod::Rename => {
                let source = rustix::fs::openat(&files_dir, data_name.as_str(), FILE_RW, Mode::empty())?;
                set_mtime(&source, entry.mtime_ms)?;
                match rename_noreplace(&files_dir, &data_name, &parent, last) {
                    Ok(()) => {}
                    Err(Errno::EXIST) => return self.reject(manifest, file, Some(&root), PATH_EXISTS_MESSAGE),
                    Err(e) => return Err(e.into()),
                }
                self.faults.hit("place.renamed")?;
                fsutil::sync_fd(&parent)?;
                fsutil::sync_fd(&files_dir)?;
                self.faults.hit("place.synced")?;
                self.mark_placed(manifest, file, src_dev, src_ino)
            }
            PlaceMethod::Copy => {
                let part = part_name(&manifest.batch_id, file.file_no);
                match rustix::fs::unlinkat(&parent, part.as_str(), AtFlags::empty()) {
                    Ok(()) | Err(Errno::NOENT) => {}
                    Err(e) => return Err(e.into()),
                }
                let part_fd = rustix::fs::openat(
                    &parent,
                    part.as_str(),
                    OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
                    Mode::from_raw_mode(0o664),
                )?;
                fsutil::sync_fd(&parent)?;
                self.faults.hit("copy.part_created")?;
                let part_ino = rustix::fs::fstat(&part_fd)?.st_ino as u64;
                if let Some(placement) = file.placement.as_mut() {
                    placement.phase = PlacePhase::PartCreated;
                    placement.part_ino = Some(part_ino);
                }
                self.save_file(&manifest.batch_id, file, "place.part_recorded")?;
                let mut source = File::from(rustix::fs::openat(&files_dir, data_name.as_str(), FILE_RW, Mode::empty())?);
                let mut part_file = File::from(part_fd);
                std::io::copy(&mut source, &mut part_file)?;
                part_file.sync_all()?;
                set_mtime(&part_file, entry.mtime_ms)?;
                part_file.sync_all()?;
                self.faults.hit("copy.part_synced")?;
                match rename_noreplace(&parent, &part, &parent, last) {
                    Ok(()) => {}
                    Err(Errno::EXIST) => return self.reject(manifest, file, Some(&root), PATH_EXISTS_MESSAGE),
                    Err(e) => return Err(e.into()),
                }
                self.faults.hit("place.renamed")?;
                fsutil::sync_fd(&parent)?;
                self.faults.hit("place.synced")?;
                self.mark_placed(manifest, file, parent_dev, part_ino)
            }
        }
    }
}
