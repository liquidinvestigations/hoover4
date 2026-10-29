//! The dataset mounts, read from `HOOVER4_DATASET_MOUNTS`, and folder access beneath them.
//!
//! `deploy.py` renders the value from the `[dataset_mount.*]` sections of `hoover4.ini`
//! into the generated Compose overlay of the worker and the website. It is a JSON list of
//! objects with the fields `name`, `path` (the container path) and `writable`.
//!
//! A missing or empty value gives one mount named `testdata` at `DATASETS_MOUNT_PATH`
//! (`/testdata` when that is also empty), which is not writable. A value that is set and
//! malformed is an error. The worker mounts that inferred mount read-write, but the website
//! mounts it read-only, so the website never creates folders or accepts uploads in it.
//!
//! `main_services/processing/tasks/dataset_mounts.py` holds the same parser. Both unit
//! tests read `dataset_mounts_cases.json` beside that file. Change the two parsers together.
//!
//! A path in the list is not proof that a path beneath it stays inside the mount. The
//! folder functions below open every path component with `O_NOFOLLOW` through a directory
//! descriptor, so a symbolic link anywhere on the way is refused. The folder functions
//! block. A caller in a server function runs them through [`blocking`].

use std::ffi::CStr;
use std::os::fd::{AsFd, OwnedFd};

use rustix::fs::{FileType, Mode, OFlags, CWD};

pub const LEGACY_MOUNT_NAME: &str = "testdata";
pub const LEGACY_MOUNT_PATH: &str = "/testdata";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DatasetMount {
    pub name: String,
    pub path: String,
    pub writable: bool,
}

fn within(path: &str, root: &str) -> bool {
    path == root || path.starts_with(&format!("{root}/"))
}

/// `path` with repeated and trailing separators and `.` and `..` parts removed, as
/// Python's `posixpath.normpath` returns it for a path that starts with one `/`.
fn normalized(path: &str) -> String {
    let mut parts: Vec<&str> = Vec::new();
    for part in path.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            other => parts.push(other),
        }
    }
    format!("/{}", parts.join("/"))
}

fn valid_name(name: &str) -> bool {
    (1..=32).contains(&name.len())
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

/// Returns the mounts that `value` names, or the legacy mount when `value` is empty.
pub fn parse_dataset_mounts(
    value: Option<&str>,
    legacy_path: Option<&str>,
) -> Result<Vec<DatasetMount>, String> {
    let value = value.unwrap_or("");
    if value.trim().is_empty() {
        let path = legacy_path.map(str::trim).filter(|p| !p.is_empty());
        return Ok(vec![DatasetMount {
            name: LEGACY_MOUNT_NAME.to_string(),
            path: path.unwrap_or(LEGACY_MOUNT_PATH).to_string(),
            writable: false,
        }]);
    }
    let items: serde_json::Value = serde_json::from_str(value)
        .map_err(|e| format!("HOOVER4_DATASET_MOUNTS is not JSON: {e}"))?;
    let items = items
        .as_array()
        .filter(|a| !a.is_empty())
        .ok_or("HOOVER4_DATASET_MOUNTS must be a non-empty JSON list")?;
    let mut mounts: Vec<DatasetMount> = Vec::new();
    for (index, item) in items.iter().enumerate() {
        let fields = item.as_object().filter(|o| {
            o.len() == 3 && ["name", "path", "writable"].iter().all(|k| o.contains_key(*k))
        });
        let Some(fields) = fields else {
            return Err(format!(
                "HOOVER4_DATASET_MOUNTS item {index} must have exactly the fields name, path and writable"
            ));
        };
        let name = fields["name"]
            .as_str()
            .filter(|n| valid_name(n))
            .ok_or_else(|| {
                format!("HOOVER4_DATASET_MOUNTS item {index}: the name must match [a-z0-9_]{{1,32}}")
            })?;
        let path = fields["path"]
            .as_str()
            .filter(|p| p.starts_with('/') && !p.starts_with("//") && normalized(p) == *p)
            .ok_or_else(|| {
                format!("HOOVER4_DATASET_MOUNTS item {index}: the path must be absolute and normalized")
            })?;
        let writable = fields["writable"].as_bool().ok_or_else(|| {
            format!("HOOVER4_DATASET_MOUNTS item {index}: writable must be true or false")
        })?;
        for other in &mounts {
            if other.name == name {
                return Err(format!("HOOVER4_DATASET_MOUNTS names {name:?} twice"));
            }
            if within(path, &other.path) || within(&other.path, path) {
                return Err(format!(
                    "HOOVER4_DATASET_MOUNTS paths {:?} and {path:?} overlap",
                    other.path
                ));
            }
        }
        mounts.push(DatasetMount {
            name: name.to_string(),
            path: path.to_string(),
            writable,
        });
    }
    Ok(mounts)
}

/// Reads the dataset mounts from the environment of this process.
pub fn dataset_mounts() -> anyhow::Result<Vec<DatasetMount>> {
    let value = std::env::var("HOOVER4_DATASET_MOUNTS").ok();
    let legacy = std::env::var("DATASETS_MOUNT_PATH").ok();
    parse_dataset_mounts(value.as_deref(), legacy.as_deref()).map_err(anyhow::Error::msg)
}

/// Returns the configured mount with this name.
pub fn mount_named(name: &str) -> anyhow::Result<DatasetMount> {
    dataset_mounts()?
        .into_iter()
        .find(|m| m.name == name)
        .ok_or_else(|| anyhow::anyhow!("{name:?} is not a configured dataset mount"))
}

/// Run blocking filesystem work on the blocking thread pool. A Dioxus server function
/// does not run on the multi-threaded runtime, and `spawn_blocking` moves the work off it.
pub async fn blocking<T: Send + 'static>(
    work: impl FnOnce() -> anyhow::Result<T> + Send + 'static,
) -> anyhow::Result<T> {
    tokio::task::spawn_blocking(work).await?
}

const DIRECTORY: OFlags = OFlags::RDONLY
    .union(OFlags::DIRECTORY)
    .union(OFlags::NOFOLLOW)
    .union(OFlags::CLOEXEC);

/// True when a folder name is one path component that does not start with a full stop.
pub fn is_safe_folder_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 128
        && !name.starts_with('.')
        && !name.contains('/')
        && !name.contains('\\')
        && !name.contains('\0')
}

/// Open the root folder of a mount. Each component of the path is opened through the
/// descriptor of its parent with `O_NOFOLLOW`, so a symbolic link on the way is refused.
pub fn open_mount_root(mount: &DatasetMount) -> anyhow::Result<OwnedFd> {
    let mut fd = rustix::fs::openat(CWD, "/", DIRECTORY, Mode::empty())?;
    for part in mount.path.split('/').filter(|p| !p.is_empty()) {
        fd = rustix::fs::openat(&fd, part, DIRECTORY, Mode::empty()).map_err(|e| {
            anyhow::anyhow!("cannot open the dataset mount {}: {e}", mount.path)
        })?;
    }
    Ok(fd)
}

/// Open one folder directly beneath a mount root. A symbolic link is refused.
pub fn open_folder(root: impl AsFd, name: &str) -> anyhow::Result<OwnedFd> {
    if !is_safe_folder_name(name) {
        anyhow::bail!("{name:?} is not a folder name");
    }
    Ok(rustix::fs::openat(root, name, DIRECTORY, Mode::empty())?)
}

fn entry_names(fd: &OwnedFd) -> anyhow::Result<Vec<(String, FileType)>> {
    let mut out = Vec::new();
    for entry in rustix::fs::Dir::read_from(fd)? {
        let entry = entry?;
        let name: &CStr = entry.file_name();
        let bytes = name.to_bytes();
        if bytes == b"." || bytes == b".." {
            continue;
        }
        if let Ok(name) = std::str::from_utf8(bytes) {
            out.push((name.to_string(), entry.file_type()));
        }
    }
    Ok(out)
}

/// The direct subfolders of a mount that have a safe name, with the count of their own
/// entries, sorted by name. Symbolic links are not listed.
pub fn list_folders(mount: &DatasetMount) -> anyhow::Result<Vec<(String, u64)>> {
    let root = open_mount_root(mount)?;
    let mut out = Vec::new();
    for (name, kind) in entry_names(&root)? {
        if !is_safe_folder_name(&name) {
            continue;
        }
        // Some file systems report an unknown type. The open with O_NOFOLLOW and
        // O_DIRECTORY then decides.
        if kind != FileType::Directory && kind != FileType::Unknown {
            continue;
        }
        let Ok(folder) = open_folder(&root, &name) else {
            continue;
        };
        let count = entry_names(&folder).map(|e| e.len() as u64).unwrap_or(0);
        out.push((name, count));
    }
    out.sort();
    Ok(out)
}

/// Refuse a read-only mount, including the inferred one, before any folder is created.
pub fn require_writable(mount: &DatasetMount) -> anyhow::Result<()> {
    if !mount.writable {
        anyhow::bail!(
            "the dataset mount {} is read-only, so no folder can be created in it",
            mount.name
        );
    }
    Ok(())
}

/// Create an empty folder directly beneath a writable mount. Refuses a read-only mount
/// and a name that exists.
pub fn create_folder(mount: &DatasetMount, name: &str) -> anyhow::Result<()> {
    require_writable(mount)?;
    if !is_safe_folder_name(name) {
        anyhow::bail!("{name:?} is not a folder name");
    }
    let root = open_mount_root(mount)?;
    match rustix::fs::mkdirat(&root, name, Mode::from_raw_mode(0o775)) {
        Ok(()) => {}
        Err(rustix::io::Errno::EXIST) => anyhow::bail!("{name:?} already exists in {}", mount.name),
        Err(e) => anyhow::bail!("cannot create {name:?} in {}: {e}", mount.name),
    }
    // Verify that the new entry is a real folder and not a link created in between.
    open_folder(&root, name)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Reads the shared cases. A checkout of the whole repository holds them beside the
    /// Python parser. The website container mounts the Python tasks folder at the folder
    /// that `HOOVER4_TEMPORAL_READINESS_PY` names, and the test reads the cases from there.
    fn shared_cases() -> serde_json::Value {
        let mut candidates = vec![std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../main_services/processing/tasks/dataset_mounts_cases.json")];
        if let Ok(py) = std::env::var("HOOVER4_TEMPORAL_READINESS_PY") {
            if let Some(dir) = std::path::Path::new(&py).parent() {
                candidates.insert(0, dir.join("dataset_mounts_cases.json"));
            }
        }
        for path in &candidates {
            if let Ok(text) = std::fs::read_to_string(path) {
                return serde_json::from_str(&text).expect("the shared cases are JSON");
            }
        }
        panic!("dataset_mounts_cases.json not found in {candidates:?}");
    }

    #[test]
    fn the_shared_cases_parse_as_in_python() {
        let cases = shared_cases();
        let cases = cases["cases"].as_array().expect("cases list");
        assert!(cases.len() >= 5);
        for case in cases {
            let id = case["id"].as_str().unwrap();
            let parsed = parse_dataset_mounts(case["value"].as_str(), case["legacy_path"].as_str());
            if case["error"].as_bool() == Some(true) {
                assert!(parsed.is_err(), "{id}: accepted {parsed:?}");
                continue;
            }
            let expected: Vec<DatasetMount> = case["mounts"]
                .as_array()
                .unwrap()
                .iter()
                .map(|m| DatasetMount {
                    name: m["name"].as_str().unwrap().to_string(),
                    path: m["path"].as_str().unwrap().to_string(),
                    writable: m["writable"].as_bool().unwrap(),
                })
                .collect();
            assert_eq!(parsed.as_ref().ok(), Some(&expected), "{id}: {parsed:?}");
        }
    }

    fn scratch(label: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "hoover4-dataset-mounts-{label}-{}-{}",
            std::process::id(),
            rand::random::<u64>()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn mount(path: &std::path::Path, writable: bool) -> DatasetMount {
        DatasetMount {
            name: "test".to_string(),
            path: path.to_str().unwrap().to_string(),
            writable,
        }
    }

    #[test]
    fn a_folder_is_created_in_a_writable_mount_and_refused_in_a_read_only_one() {
        let root = scratch("create");
        create_folder(&mount(&root, true), "new folder").unwrap();
        assert!(root.join("new folder").is_dir());
        assert!(create_folder(&mount(&root, true), "new folder").is_err());
        let refused = create_folder(&mount(&root, false), "other").unwrap_err();
        assert!(refused.to_string().contains("read-only"), "{refused}");
        assert!(!root.join("other").exists());
        for bad in ["", ".hidden", "a/b", "..", "a\\b"] {
            assert!(create_folder(&mount(&root, true), bad).is_err(), "{bad:?}");
        }
        std::fs::remove_dir_all(&root).unwrap();
    }

    #[test]
    fn symbolic_links_are_neither_listed_nor_followed() {
        let root = scratch("links");
        let outside = scratch("outside");
        std::fs::create_dir(root.join("real")).unwrap();
        std::fs::write(root.join("real/file.txt"), "x").unwrap();
        std::fs::write(root.join("plain file"), "x").unwrap();
        std::os::unix::fs::symlink(&outside, root.join("escape")).unwrap();
        let listed = list_folders(&mount(&root, true)).unwrap();
        assert_eq!(listed, vec![("real".to_string(), 1)]);
        let root_fd = open_mount_root(&mount(&root, true)).unwrap();
        assert!(open_folder(&root_fd, "escape").is_err());

        // A mount path that passes through a link is refused as a whole.
        let alias = scratch("alias");
        std::os::unix::fs::symlink(&root, alias.join("root")).unwrap();
        let through_link = mount(&alias.join("root"), true);
        assert!(list_folders(&through_link).is_err());
        assert!(create_folder(&through_link, "x").is_err());
        assert!(!root.join("x").exists());

        for dir in [root, outside, alias] {
            std::fs::remove_dir_all(dir).unwrap();
        }
    }

    #[test]
    fn the_inferred_mount_refuses_new_folders() {
        let legacy = parse_dataset_mounts(None, Some("/testdata")).unwrap();
        assert!(require_writable(&legacy[0]).is_err());
    }

    #[test]
    fn folder_names_cannot_escape_the_mount() {
        assert!(is_safe_folder_name("emails"));
        for bad in ["", "..", ".hidden", "a/b", "a\\b", "/etc", "a\0b"] {
            assert!(!is_safe_folder_name(bad), "{bad:?} was accepted");
        }
    }
}
