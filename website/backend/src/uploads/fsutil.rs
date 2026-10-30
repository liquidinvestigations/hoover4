//! File operations of the upload space: atomic journal writes, folder synchronization,
//! process-independent locks, and the descriptor walk beneath a dataset folder.
//!
//! Every function here blocks. Callers run them on a blocking thread.

use std::fs::File;
use std::io::Write;
use std::os::fd::{AsFd, OwnedFd};
use std::path::Path;
use std::sync::Mutex;

use rustix::fs::{AtFlags, FileType, FlockOperation, Mode, OFlags, CWD};
use rustix::io::Errno;

/// The error text of a simulated crash at a failure point.
pub const SIMULATED_CRASH: &str = "simulated crash at failure point";

/// Failure points for crash tests. One armed point returns an error once, which leaves
/// the files in the state that a killed process leaves. Production code arms none.
#[derive(Default)]
pub struct Faults {
    armed: Mutex<Option<String>>,
}

impl Faults {
    /// Arm one failure point. The next [`Faults::hit`] with this name fails.
    pub fn arm(&self, name: &str) {
        *self.armed.lock().unwrap_or_else(|e| e.into_inner()) = Some(name.to_string());
    }

    /// The name of the armed point that has not failed yet.
    pub fn pending(&self) -> Option<String> {
        self.armed.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// Fail when `name` is armed.
    pub fn hit(&self, name: &str) -> anyhow::Result<()> {
        let mut armed = self.armed.lock().unwrap_or_else(|e| e.into_inner());
        if armed.as_deref() == Some(name) {
            *armed = None;
            anyhow::bail!("{SIMULATED_CRASH} {name}");
        }
        Ok(())
    }
}

/// True when the error comes from a simulated crash.
pub fn is_simulated_crash(err: &anyhow::Error) -> bool {
    err.to_string().contains(SIMULATED_CRASH)
}

/// Synchronize a folder, so a create, a rename or a removal in it is durable.
pub fn sync_dir(path: &Path) -> anyhow::Result<()> {
    let fd = rustix::fs::open(path, OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC, Mode::empty())?;
    rustix::fs::fsync(&fd)?;
    Ok(())
}

/// Synchronize the folder of an open descriptor.
pub fn sync_fd(fd: impl AsFd) -> anyhow::Result<()> {
    rustix::fs::fsync(fd)?;
    Ok(())
}

/// Create a folder and its parents in the upload space, and synchronize each parent of a
/// created folder.
pub fn ensure_dir(path: &Path) -> anyhow::Result<()> {
    if path.is_dir() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        ensure_dir(parent)?;
    }
    match std::fs::create_dir(path) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(e) => return Err(e.into()),
    }
    if let Some(parent) = path.parent() {
        sync_dir(parent)?;
    }
    Ok(())
}

/// Replace `dir/name` with `bytes` atomically: write a temporary file, synchronize it,
/// rename it over the name, and synchronize the folder. The caller holds the lock of the
/// record, so one temporary name for each record is enough.
pub fn atomic_write(dir: &Path, name: &str, bytes: &[u8], faults: &Faults, point: &str) -> anyhow::Result<()> {
    replace_unsynced(dir, name, bytes, faults, point)?;
    faults.hit(&format!("{point}.before_sync"))?;
    sync_dir(dir)?;
    Ok(())
}

/// The first part of [`atomic_write`]: write and synchronize a temporary file and rename
/// it over the name, without the synchronization of the folder. After a crash the folder
/// holds the new record or the earlier one, each complete. A caller that writes several
/// records synchronizes the folder once after the last.
pub fn replace_unsynced(dir: &Path, name: &str, bytes: &[u8], faults: &Faults, point: &str) -> anyhow::Result<()> {
    let temp = dir.join(format!(".{name}.tmp"));
    {
        let mut file = File::create(&temp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
    }
    faults.hit(&format!("{point}.before_rename"))?;
    std::fs::rename(&temp, dir.join(name))?;
    Ok(())
}

/// Read a JSON journal record. A missing file gives `None`.
pub fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> anyhow::Result<Option<T>> {
    match std::fs::read(path) {
        Ok(bytes) => Ok(Some(serde_json::from_slice(&bytes).map_err(|e| {
            anyhow::anyhow!("the journal record {} is not valid: {e}", path.display())
        })?)),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(e) => Err(e.into()),
    }
}

/// Write a JSON journal record atomically.
pub fn write_json<T: serde::Serialize>(path: &Path, value: &T, faults: &Faults, point: &str) -> anyhow::Result<()> {
    let dir = path.parent().ok_or_else(|| anyhow::anyhow!("a journal path has a folder"))?;
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| anyhow::anyhow!("a journal path has a name"))?;
    atomic_write(dir, name, &serde_json::to_vec(value)?, faults, point)
}

/// Remove a file and synchronize its folder. A missing file is not an error.
pub fn remove_file(path: &Path) -> anyhow::Result<bool> {
    match std::fs::remove_file(path) {
        Ok(()) => {
            if let Some(parent) = path.parent() {
                sync_dir(parent)?;
            }
            Ok(true)
        }
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(e) => Err(e.into()),
    }
}

/// Remove a file without a synchronization of its folder. A missing file is not an
/// error. The caller uses it only where a crash that keeps the file changes no recovery
/// action.
pub fn remove_file_unsynced(path: &Path) -> anyhow::Result<()> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e.into()),
    }
}

/// A held `flock` lock. The lock ends when the value is dropped.
///
/// `flock` locks belong to the open file, so they exclude other processes that open the
/// same lock file, and other descriptors of this process.
pub struct Lock {
    _fd: OwnedFd,
}

/// Take a lock on `path`, creating the lock file when needed. `exclusive` selects an
/// exclusive or a shared lock. With `wait = false` a held lock gives `None`.
pub fn lock(path: &Path, exclusive: bool, wait: bool) -> anyhow::Result<Option<Lock>> {
    let fd = rustix::fs::open(
        path,
        OFlags::CREATE | OFlags::RDWR | OFlags::CLOEXEC,
        Mode::from_raw_mode(0o600),
    )
    .map_err(|e| anyhow::anyhow!("cannot open the lock file {}: {e}", path.display()))?;
    let operation = match (exclusive, wait) {
        (true, true) => FlockOperation::LockExclusive,
        (true, false) => FlockOperation::NonBlockingLockExclusive,
        (false, true) => FlockOperation::LockShared,
        (false, false) => FlockOperation::NonBlockingLockShared,
    };
    loop {
        match rustix::fs::flock(&fd, operation) {
            Ok(()) => return Ok(Some(Lock { _fd: fd })),
            Err(Errno::WOULDBLOCK) if !wait => return Ok(None),
            Err(Errno::INTR) => continue,
            Err(e) => anyhow::bail!("cannot lock {}: {e}", path.display()),
        }
    }
}

/// Take a lock on `path` and wait at most `wait` for it. A lock that another holder keeps
/// for longer gives `None`. The function tries the lock without blocking and sleeps
/// between attempts, because `flock` itself has no time limit.
pub fn lock_within(path: &Path, exclusive: bool, wait: std::time::Duration) -> anyhow::Result<Option<Lock>> {
    let deadline = std::time::Instant::now() + wait;
    let mut pause = std::time::Duration::from_millis(5);
    loop {
        if let Some(lock) = lock(path, exclusive, false)? {
            return Ok(Some(lock));
        }
        let now = std::time::Instant::now();
        if now >= deadline {
            return Ok(None);
        }
        std::thread::sleep(pause.min(deadline - now));
        pause = (pause * 2).min(std::time::Duration::from_millis(100));
    }
}

/// The open flags of a folder in a dataset. A symbolic link is refused.
const DIRECTORY: OFlags = OFlags::RDONLY
    .union(OFlags::DIRECTORY)
    .union(OFlags::NOFOLLOW)
    .union(OFlags::CLOEXEC);

/// What a destination path finds in a dataset folder.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Found {
    /// No entry at the path, and every folder above it is a real folder or absent.
    Absent,
    /// An entry, with its device and inode.
    Entry { dev: u64, ino: u64, size: u64 },
    /// A folder above the path is a file or a symbolic link.
    Blocked,
}

/// Open the folder `names` beneath `root` without following a symbolic link. With
/// `create`, missing folders are created with `mkdirat`. `Ok(None)` means that a folder
/// is absent and `create` is false. A file or a link on the way is an error of kind
/// [`Blocked`].
pub fn open_folders(root: &OwnedFd, names: &[&str], create: bool) -> Result<Option<OwnedFd>, WalkError> {
    let mut fd = rustix::fs::openat(root, ".", DIRECTORY, Mode::empty()).map_err(WalkError::Io)?;
    for name in names {
        let next = match rustix::fs::openat(&fd, *name, DIRECTORY, Mode::empty()) {
            Ok(next) => next,
            Err(Errno::NOENT) if create => {
                match rustix::fs::mkdirat(&fd, *name, Mode::from_raw_mode(0o775)) {
                    Ok(()) | Err(Errno::EXIST) => {}
                    Err(e) => return Err(WalkError::Io(e)),
                }
                rustix::fs::fsync(&fd).map_err(WalkError::Io)?;
                rustix::fs::openat(&fd, *name, DIRECTORY, Mode::empty()).map_err(|e| match e {
                    Errno::NOTDIR | Errno::LOOP => WalkError::Blocked,
                    other => WalkError::Io(other),
                })?
            }
            Err(Errno::NOENT) => return Ok(None),
            Err(Errno::NOTDIR) | Err(Errno::LOOP) => return Err(WalkError::Blocked),
            Err(e) => return Err(WalkError::Io(e)),
        };
        fd = next;
    }
    Ok(Some(fd))
}

/// The error of [`open_folders`].
#[derive(Debug)]
pub enum WalkError {
    /// A file or a symbolic link stands where a folder must be.
    Blocked,
    Io(Errno),
}

impl std::fmt::Display for WalkError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            WalkError::Blocked => write!(f, "a file or a link stands where a folder must be"),
            WalkError::Io(e) => write!(f, "{e}"),
        }
    }
}

impl std::error::Error for WalkError {}

/// The entry `name` in the folder `dir`, without following a symbolic link.
pub fn stat_entry(dir: impl AsFd, name: &str) -> anyhow::Result<Option<(FileType, u64, u64, u64)>> {
    match rustix::fs::statat(dir, name, AtFlags::SYMLINK_NOFOLLOW) {
        Ok(st) => Ok(Some((
            FileType::from_raw_mode(st.st_mode),
            st.st_dev as u64,
            st.st_ino as u64,
            st.st_size as u64,
        ))),
        Err(Errno::NOENT) => Ok(None),
        Err(e) => Err(e.into()),
    }
}

/// What the destination `names` finds beneath `root`. Nothing is created.
pub fn find(root: &OwnedFd, names: &[&str]) -> anyhow::Result<Found> {
    let Some((last, parents)) = names.split_last() else {
        anyhow::bail!("a destination path has a name");
    };
    let parent = match open_folders(root, parents, false) {
        Ok(Some(fd)) => fd,
        Ok(None) => return Ok(Found::Absent),
        Err(WalkError::Blocked) => return Ok(Found::Blocked),
        Err(WalkError::Io(e)) => return Err(e.into()),
    };
    Ok(match stat_entry(&parent, last)? {
        None => Found::Absent,
        Some((_, dev, ino, size)) => Found::Entry { dev, ino, size },
    })
}

/// The free bytes of the file system of an open folder, for an unprivileged writer.
pub fn free_bytes(dir: impl AsFd) -> anyhow::Result<u64> {
    let st = rustix::fs::fstatvfs(dir)?;
    Ok(st.f_bavail.saturating_mul(st.f_frsize))
}

/// Open a plain folder of the upload space.
pub fn open_space_dir(path: &Path) -> anyhow::Result<OwnedFd> {
    Ok(rustix::fs::openat(CWD, path, OFlags::RDONLY | OFlags::DIRECTORY | OFlags::CLOEXEC, Mode::empty())?)
}
