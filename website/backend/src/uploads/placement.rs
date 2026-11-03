//! Placement: the move of a complete file from the upload space into the dataset folder.
//!
//! Every path step opens a folder through the descriptor of its parent with
//! `O_NOFOLLOW`, beneath the dataset root that `open_dataset_folder` opened from the
//! mount root. A symbolic link on the way refuses the path. A publish never replaces an
//! entry: it uses `renameat2(RENAME_NOREPLACE)`, or `linkat`, which also refuses an
//! existing name, on a file system without that flag.
//!
//! The journal records the method, the source identity and a token before the first
//! change in the dataset folder, and the published identity with the state `Placed`. Inside
//! one mount the data file is renamed. Across mounts, also two bind mounts of one file
//! system, the bytes go to the reserved part name of the file, then the part is renamed.
//! A rename that the kernel refuses with `EXDEV` changes the record to a copy before the
//! part exists. The part name holds the batch
//! id and the file number, and the journal records it before it exists, so the journal
//! proves the ownership of a part with that name.
//!
//! | Found at recovery | Action |
//! |---|---|
//! | The destination has the recorded identity. | Mark it placed and remove the source. |
//! | No destination, the source remains. | Remove an owned part and place again. |
//! | Another entry holds the destination, the source remains. | Reject the file and keep that entry. |
//! | Another entry or no entry, no source. | Reject the file as not recovered. Change nothing in the dataset. |
//!
//! The placement record also names the dataset folder. A rejection without a current
//! target, after a permission change or a dataset deletion, opens that folder to remove
//! an owned part. When the folder exists but does not open, the rejection fails and the
//! journal keeps the part record, so the sweep tries again.

use std::fs::File;
use std::os::fd::{AsFd, OwnedFd};

use common::uploads::{part_name, path_names, NOT_RECOVERED_MESSAGE, PATH_EXISTS_MESSAGE};
use rustix::fs::{AtFlags, Mode, OFlags, RenameFlags, Timespec, Timestamps};
use rustix::io::Errno;

use super::fsutil::{self, Found, WalkError};
use super::journal::{FileJournal, FileState, Manifest, PlaceMethod, PlacePhase, Placement, PlacementFolder, Space};
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

/// Open the dataset folder of a placement record from its mount root, each folder with
/// `O_NOFOLLOW`. `None` when the dataset folder or a folder above it no longer exists.
fn open_recorded_folder(folder: &PlacementFolder) -> anyhow::Result<Option<OwnedFd>> {
    let mount = crate::dataset_mounts::DatasetMount {
        name: folder.mount_name.clone(),
        path: folder.mount_path.clone(),
        writable: true,
    };
    let Some((_, parts)) = crate::db_auth::uploads::writable_mount_for(std::slice::from_ref(&mount), &folder.dataset_path) else {
        anyhow::bail!("{} is not beneath the mount {}", folder.dataset_path, folder.mount_path);
    };
    let mut fd = crate::dataset_mounts::open_mount_root(&mount)?;
    for part in &parts {
        fd = match rustix::fs::openat(&fd, part.as_str(), OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC, Mode::empty()) {
            Ok(next) => next,
            Err(Errno::NOENT) => return Ok(None),
            Err(e) => anyhow::bail!("cannot open {}: {e}", folder.dataset_path),
        };
    }
    Ok(Some(fd))
}

/// The mount id of an open folder, or `None` when the kernel does not report it.
fn mount_id(fd: &OwnedFd) -> Option<u64> {
    let st = rustix::fs::statx(fd, "", AtFlags::EMPTY_PATH, rustix::fs::StatxFlags::MNT_ID).ok()?;
    (st.stx_mask & rustix::fs::StatxFlags::MNT_ID.bits() != 0).then_some(st.stx_mnt_id)
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

    /// Remove the owned part file of a copy placement, when it exists. Without `root`,
    /// the dataset folder that the placement record names is opened. A folder that no
    /// longer exists holds no part. A folder that exists but does not open is an error.
    fn remove_owned_part(&self, manifest: &Manifest, file: &FileJournal, root: Option<&OwnedFd>) -> anyhow::Result<()> {
        let Some(placement) = file.placement.as_ref() else { return Ok(()) };
        if placement.method != PlaceMethod::Copy {
            return Ok(());
        }
        let opened;
        let root = match root {
            Some(root) => root,
            None => match placement.folder.as_ref() {
                Some(folder) => match open_recorded_folder(folder)? {
                    Some(fd) => {
                        opened = fd;
                        &opened
                    }
                    None => return Ok(()),
                },
                None => {
                    tracing::warn!(
                        "upload batch {} file {}: the placement record names no folder, a part {} can remain",
                        manifest.batch_id,
                        file.file_no,
                        part_name(&manifest.batch_id, file.file_no)
                    );
                    return Ok(());
                }
            },
        };
        let names = path_names(&manifest.files[file.file_no as usize].path);
        let parents = &names[..names.len() - 1];
        match fsutil::open_folders(root, parents, false) {
            Ok(Some(parent)) => {
                match rustix::fs::unlinkat(&parent, part_name(&manifest.batch_id, file.file_no), AtFlags::empty()) {
                    Ok(()) => fsutil::sync_fd(&parent)?,
                    Err(Errno::NOENT) => {}
                    Err(e) => return Err(e.into()),
                }
            }
            // An absent folder, or a file or a link in place of a folder, holds no part
            // that this placement created.
            Ok(None) | Err(WalkError::Blocked) => {}
            Err(WalkError::Io(e)) => return Err(e.into()),
        }
        Ok(())
    }

    /// Remove from the dataset folder what this batch published for one file of an
    /// aborted batch, and an owned part. An entry is removed only when its identity is
    /// the one that the placement record names: the recorded device and inode of a placed
    /// file, the source of an interrupted rename, or the part of an interrupted copy.
    /// Returns true when an entry was removed.
    pub(super) fn unplace(&self, manifest: &Manifest, file: &FileJournal) -> anyhow::Result<bool> {
        let Some(placement) = file.placement.as_ref() else { return Ok(false) };
        if !matches!(file.state, FileState::Placed | FileState::Placing) {
            return Ok(false);
        }
        let Some(folder) = placement.folder.as_ref() else { return Ok(false) };
        let Some(root) = open_recorded_folder(folder)? else { return Ok(false) };
        self.remove_owned_part(manifest, file, Some(&root))?;
        let names = path_names(&manifest.files[file.file_no as usize].path);
        let Some((last, parents)) = names.split_last() else { return Ok(false) };
        let parent = match fsutil::open_folders(&root, parents, false) {
            Ok(Some(parent)) => parent,
            Ok(None) | Err(WalkError::Blocked) => return Ok(false),
            Err(WalkError::Io(e)) => return Err(e.into()),
        };
        let Some((_, dev, ino, _)) = fsutil::stat_entry(&parent, last)? else { return Ok(false) };
        let ours = match (file.state, placement.method) {
            (FileState::Placed, _) => placement.dest_dev == Some(dev) && placement.dest_ino == Some(ino),
            (_, PlaceMethod::Rename) => dev == placement.src_dev && ino == placement.src_ino,
            (_, PlaceMethod::Copy) => placement.part_ino == Some(ino),
        };
        if !ours {
            return Ok(false);
        }
        match rustix::fs::unlinkat(&parent, *last, AtFlags::empty()) {
            Ok(()) => {}
            Err(Errno::NOENT) => return Ok(false),
            Err(e) => return Err(e.into()),
        }
        fsutil::sync_fd(&parent)?;
        Ok(true)
    }

    /// Remove the folders that the placements of an aborted batch created, deepest first,
    /// when they are empty. A folder that existed before the batch, or that holds an
    /// entry, stays.
    pub(super) fn remove_empty_folders(&self, folder: &PlacementFolder, created: &[String]) -> anyhow::Result<()> {
        let Some(root) = open_recorded_folder(folder)? else { return Ok(()) };
        let candidates: std::collections::BTreeSet<Vec<&str>> =
            created.iter().map(|path| path.split('/').collect()).collect();
        let mut ordered: Vec<Vec<&str>> = candidates.into_iter().collect();
        ordered.sort_by_key(|names| std::cmp::Reverse(names.len()));
        for names in ordered {
            let Some((last, parents)) = names.split_last() else { continue };
            let parent = match fsutil::open_folders(&root, parents, false) {
                Ok(Some(parent)) => parent,
                Ok(None) | Err(WalkError::Blocked) => continue,
                Err(WalkError::Io(e)) => return Err(e.into()),
            };
            match rustix::fs::unlinkat(&parent, *last, AtFlags::REMOVEDIR) {
                Ok(()) => fsutil::sync_fd(&parent)?,
                Err(Errno::NOTEMPTY) | Err(Errno::EXIST) | Err(Errno::NOENT) | Err(Errno::NOTDIR) => {}
                Err(e) => return Err(e.into()),
            }
        }
        Ok(())
    }

    /// End a file as rejected: remove its source bytes and an owned part. Without `root`,
    /// the part is found through the folder of the placement record. Nothing else in the
    /// dataset folder changes.
    pub fn reject(&self, manifest: &Manifest, file: &mut FileJournal, root: Option<&OwnedFd>, reason: &str) -> anyhow::Result<()> {
        self.remove_owned_part(manifest, file, root)?;
        self.reject_unchanged(manifest, file, reason)
    }

    /// End a file as rejected and remove its source bytes. Nothing in the dataset folder
    /// changes. Recovery uses it when the state of the folder does not prove a part.
    fn reject_unchanged(&self, manifest: &Manifest, file: &mut FileJournal, reason: &str) -> anyhow::Result<()> {
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
        // A copy leaves the source, and a link fallback can leave it after a crash. The
        // removal needs no synchronization: a source that a crash keeps belongs to a
        // placed file, which no recovery reads, and the archive of the batch removes it.
        fsutil::remove_file_unsynced(&self.space.data(&manifest.batch_id, file.file_no))?;
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
                    return self.reject_unchanged(manifest, file, NOT_RECOVERED_MESSAGE);
                }
                Found::Absent => {
                    self.remove_owned_part(manifest, file, Some(&root))?;
                    if source.is_none() {
                        return self.reject_unchanged(manifest, file, NOT_RECOVERED_MESSAGE);
                    }
                    file.state = FileState::Complete;
                }
            }
        }

        // The folders that this placement creates, kept for an abort. An interrupted
        // placement keeps the folders that its earlier attempt created.
        let mut created_folders = file.placement.as_ref().map(|p| p.created_folders.clone()).unwrap_or_default();
        for depth in 1..=parents.len() {
            match fsutil::open_folders(&root, &parents[..depth], false) {
                Ok(Some(_)) => continue,
                Ok(None) => {
                    for end in depth..=parents.len() {
                        let path = parents[..end].join("/");
                        if !created_folders.contains(&path) {
                            created_folders.push(path);
                        }
                    }
                }
                Err(WalkError::Blocked) => {}
                Err(WalkError::Io(e)) => return Err(e.into()),
            }
            break;
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
            return self.reject_unchanged(manifest, file, NOT_RECOVERED_MESSAGE);
        };
        if src_size != entry.size {
            return self.reject_unchanged(manifest, file, NOT_RECOVERED_MESSAGE);
        }
        let parent_dev = rustix::fs::fstat(&parent)?.st_dev as u64;
        // `rename` works only inside one mount. Two bind mounts of one file system have
        // one device and two mount ids, so the device alone does not choose the method.
        let same_mount = match (mount_id(&parent), mount_id(&files_dir)) {
            (Some(a), Some(b)) => a == b,
            _ => true,
        };
        let method = if parent_dev == src_dev && same_mount { PlaceMethod::Rename } else { PlaceMethod::Copy };
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
            folder: Some(PlacementFolder {
                mount_name: target.mount.name.clone(),
                mount_path: target.mount.path.clone(),
                dataset_path: target.dataset_path.clone(),
            }),
            created_folders,
        });
        file.version += 1;
        self.save_file(&manifest.batch_id, file, "place.prepared")?;

        if method == PlaceMethod::Rename {
            let source = rustix::fs::openat(&files_dir, data_name.as_str(), FILE_RW, Mode::empty())?;
            set_mtime(&source, entry.mtime_ms)?;
            match rename_noreplace(&files_dir, &data_name, &parent, last) {
                Ok(()) => {}
                Err(Errno::EXIST) => return self.reject(manifest, file, Some(&root), PATH_EXISTS_MESSAGE),
                Err(Errno::XDEV) => {
                    // Nothing changed in the dataset folder. The record becomes a copy
                    // before the part name can exist.
                    if let Some(placement) = file.placement.as_mut() {
                        placement.method = PlaceMethod::Copy;
                    }
                    file.version += 1;
                    self.save_file(&manifest.batch_id, file, "place.prepared")?;
                    return self.place_copy(manifest, file, &root, &files_dir, &parent, last, entry.mtime_ms, parent_dev);
                }
                Err(e) => return Err(e.into()),
            }
            self.faults.hit("place.renamed")?;
            fsutil::sync_fd(&parent)?;
            fsutil::sync_fd(&files_dir)?;
            self.faults.hit("place.synced")?;
            return self.mark_placed(manifest, file, src_dev, src_ino);
        }
        self.place_copy(manifest, file, &root, &files_dir, &parent, last, entry.mtime_ms, parent_dev)
    }

    /// The copy method of [`Service::place`]: copy the bytes to the reserved part name,
    /// synchronize them, and rename the part to the destination. The journal records the
    /// part before its bytes.
    #[allow(clippy::too_many_arguments)]
    fn place_copy(
        &self,
        manifest: &Manifest,
        file: &mut FileJournal,
        root: &OwnedFd,
        files_dir: &OwnedFd,
        parent: &OwnedFd,
        last: &str,
        mtime_ms: i64,
        parent_dev: u64,
    ) -> anyhow::Result<()> {
        let data_name = Space::data_name(file.file_no);
        let part = part_name(&manifest.batch_id, file.file_no);
        match rustix::fs::unlinkat(parent, part.as_str(), AtFlags::empty()) {
            Ok(()) | Err(Errno::NOENT) => {}
            Err(e) => return Err(e.into()),
        }
        let part_fd = rustix::fs::openat(
            parent,
            part.as_str(),
            OFlags::WRONLY | OFlags::CREATE | OFlags::EXCL | OFlags::NOFOLLOW | OFlags::CLOEXEC,
            Mode::from_raw_mode(0o664),
        )?;
        // The part name needs no synchronization here. A crash that loses it leaves no
        // part, and recovery finds the destination absent and places the file again. The
        // synchronization after the final rename makes the destination durable.
        self.faults.hit("copy.part_created")?;
        let part_ino = rustix::fs::fstat(&part_fd)?.st_ino as u64;
        if let Some(placement) = file.placement.as_mut() {
            placement.phase = PlacePhase::PartCreated;
            placement.part_ino = Some(part_ino);
        }
        self.save_file(&manifest.batch_id, file, "place.part_recorded")?;
        let mut source = File::from(rustix::fs::openat(files_dir, data_name.as_str(), FILE_RW, Mode::empty())?);
        let mut part_file = File::from(part_fd);
        std::io::copy(&mut source, &mut part_file)?;
        part_file.sync_all()?;
        set_mtime(&part_file, mtime_ms)?;
        part_file.sync_all()?;
        self.faults.hit("copy.part_synced")?;
        match rename_noreplace(parent, &part, parent, last) {
            Ok(()) => {}
            Err(Errno::EXIST) => return self.reject(manifest, file, Some(root), PATH_EXISTS_MESSAGE),
            Err(e) => return Err(e.into()),
        }
        self.faults.hit("place.renamed")?;
        fsutil::sync_fd(parent)?;
        self.faults.hit("place.synced")?;
        self.mark_placed(manifest, file, parent_dev, part_ino)
    }
}
