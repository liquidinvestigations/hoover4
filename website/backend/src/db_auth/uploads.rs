//! Upload permission: the current upload targets of a user, and the readers of upload history.
//!
//! A user may upload into dataset `d` of collection `c` when all three conditions hold. A
//! collection can have several upload datasets, and each one is a separate target.
//!
//! 1. `d` is a live disk dataset of `c` with the setting `uploads_enabled = 'true'`.
//! 2. The user has a live membership in a group `g` with `is_uploader = 1`.
//! 3. `g` holds a live row in `collection_group_permissions` for `c`.
//!
//! The dataset folder must also resolve beneath a writable dataset mount of this process.
//! A public collection gives no upload permission, and the administrator flag of a user
//! gives none either. An administrator uploads only through a flagged membership.
//!
//! Batch history has a separate rule. A user may read the batch history of `c` when the
//! user is an administrator, or has a flagged membership whose group holds a grant for
//! `c`. That rule does not depend on a current upload target, so history stays readable
//! after uploads are turned off, after the mount is removed and after the dataset is
//! deleted.
//!
//! Every ClickHouse query of these rules is in this module. `FINAL` applies to each table
//! of a join, and `clickhouse::Row` binds result fields by column name.

use std::collections::BTreeMap;
use std::os::fd::OwnedFd;

use common::current_user::CurrentUser;

use crate::dataset_mounts::{self, DatasetMount};
use crate::db_utils::clickhouse_utils::get_global_client;

/// The `dataset_settings` key that makes a disk dataset an upload dataset of its collection.
/// Its values are `true` and `false`.
pub const KEY_UPLOADS_ENABLED: &str = "uploads_enabled";

/// The live datasets whose newest `uploads_enabled` row says `true`. The value and the
/// deletion flag come from one row, chosen by `setting_version_us`, as
/// `tasks/dataset_config.py` reads a setting.
const ENABLED_DATASETS: &str = "SELECT collection_dataset FROM dataset_settings \
     WHERE key = 'uploads_enabled' GROUP BY collection_dataset \
     HAVING argMax((value, is_deleted), setting_version_us) = ('true', 0)";

/// One upload target: an upload dataset of a collection that the user may write now.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UploadTarget {
    pub collectionname: String,
    pub collection_dataset: String,
    pub dataset_path: String,
    /// The writable mount that holds the dataset folder.
    pub mount_name: String,
}

/// An upload dataset of a collection whose folder is beneath a writable mount but does
/// not open now. The permission stands, so the receiver keeps the files of its batches.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UploadUnavailable {
    pub collectionname: String,
    pub collection_dataset: String,
    /// The error of the folder open.
    pub reason: String,
}

/// [`upload_targets`] returns this value.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct UploadTargets {
    pub targets: Vec<UploadTarget>,
    /// Not targets now. The upload page does not list them.
    pub unavailable: Vec<UploadUnavailable>,
}

/// One upload dataset of a collection that the user may upload into, before the mount
/// check.
#[derive(Debug, Clone, PartialEq, Eq, clickhouse::Row, serde::Deserialize)]
pub struct UploadCandidate {
    pub collectionname: String,
    pub collection_dataset: String,
    pub dataset_path: String,
}

/// The live disk datasets with `uploads_enabled` of each collection in which the user has
/// conditions 2 and 3.
async fn upload_candidates(username: &str) -> anyhow::Result<Vec<UploadCandidate>> {
    let client = get_global_client();
    client
        .query(&format!(
            "SELECT DISTINCT p.collectionname AS collectionname, \
                    d.collection_dataset AS collection_dataset, \
                    d.dataset_path AS dataset_path \
             FROM user_group_membership AS m FINAL \
             INNER JOIN collection_group_permissions AS p FINAL ON p.groupname = m.groupname \
             INNER JOIN collections AS c FINAL ON c.collectionname = p.collectionname \
             INNER JOIN dataset AS d FINAL ON d.collectionname = p.collectionname \
             INNER JOIN ({ENABLED_DATASETS}) AS s ON s.collection_dataset = d.collection_dataset \
             WHERE m.username = ? AND m.is_deleted = 0 AND m.is_uploader = 1 \
               AND p.is_deleted = 0 AND c.is_deleted = 0 \
               AND d.is_deleted = 0 AND d.dataset_type = 'disk' \
             ORDER BY collectionname, collection_dataset"
        ))
        .bind(username)
        .fetch_all::<UploadCandidate>()
        .await
        .map_err(Into::into)
}

/// The live datasets of a collection that have `uploads_enabled`, sorted.
pub async fn upload_datasets_of_collection(collectionname: &str) -> anyhow::Result<Vec<String>> {
    let client = get_global_client();
    client
        .query(&format!(
            "SELECT d.collection_dataset AS collection_dataset FROM dataset AS d FINAL \
             INNER JOIN ({ENABLED_DATASETS}) AS s ON s.collection_dataset = d.collection_dataset \
             WHERE d.collectionname = ? AND d.is_deleted = 0 \
             ORDER BY collection_dataset"
        ))
        .bind(collectionname)
        .fetch_all::<String>()
        .await
        .map_err(Into::into)
}

/// Every live dataset that has `uploads_enabled`, in every collection.
pub async fn all_upload_datasets() -> anyhow::Result<std::collections::HashSet<String>> {
    let client = get_global_client();
    let rows: Vec<String> = client
        .query(&format!(
            "SELECT d.collection_dataset AS collection_dataset FROM dataset AS d FINAL \
             INNER JOIN ({ENABLED_DATASETS}) AS s ON s.collection_dataset = d.collection_dataset \
             WHERE d.is_deleted = 0"
        ))
        .fetch_all::<String>()
        .await?;
    Ok(rows.into_iter().collect())
}

/// The registry facts of one live dataset that the upload setting checks.
#[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
pub struct DatasetUploadFacts {
    pub collectionname: String,
    pub dataset_type: String,
    pub dataset_path: String,
}

/// The collection, type and path of a live dataset, or `None`.
pub async fn dataset_upload_facts(collection_dataset: &str) -> anyhow::Result<Option<DatasetUploadFacts>> {
    let client = get_global_client();
    let mut rows = client
        .query(
            "SELECT collectionname, dataset_type, dataset_path FROM dataset FINAL \
             WHERE collection_dataset = ? AND is_deleted = 0 AND collectionname != ''",
        )
        .bind(collection_dataset)
        .fetch_all::<DatasetUploadFacts>()
        .await?;
    Ok(rows.pop())
}

/// The collections in which the user has a flagged membership whose group holds a live
/// grant, sorted. A public collection is not listed unless such a grant exists.
pub async fn uploader_collections(username: &str) -> anyhow::Result<Vec<String>> {
    let client = get_global_client();
    client
        .query(
            "SELECT DISTINCT p.collectionname AS collectionname \
             FROM user_group_membership AS m FINAL \
             INNER JOIN collection_group_permissions AS p FINAL ON p.groupname = m.groupname \
             WHERE m.username = ? AND m.is_deleted = 0 AND m.is_uploader = 1 AND p.is_deleted = 0 \
             ORDER BY collectionname",
        )
        .bind(username)
        .fetch_all::<String>()
        .await
        .map_err(Into::into)
}

/// The history rule of one collection, given the uploader collections of the user.
fn history_readable(is_admin: bool, uploader_collections: &[String], collectionname: &str) -> bool {
    is_admin || uploader_collections.iter().any(|c| c == collectionname)
}

/// True when the user may read the upload batch history of the collection: an
/// administrator, or an uploader of the collection. A current upload target is not needed.
pub async fn can_read_upload_history(user: &CurrentUser, collectionname: &str) -> anyhow::Result<bool> {
    if user.is_admin {
        return Ok(true);
    }
    let collections = uploader_collections(&user.username).await?;
    Ok(history_readable(false, &collections, collectionname))
}

/// The writable mount whose path holds `dataset_path` strictly beneath it, and the folder
/// names from the mount root to the dataset folder. `None` for a read-only mount, for a
/// path in no mount, and for a path that is not absolute and normalized.
pub fn writable_mount_for<'a>(
    mounts: &'a [DatasetMount],
    dataset_path: &str,
) -> Option<(&'a DatasetMount, Vec<String>)> {
    if !dataset_path.starts_with('/') {
        return None;
    }
    let parts: Vec<&str> = dataset_path.split('/').skip(1).collect();
    if parts.iter().any(|p| p.is_empty() || *p == "." || *p == "..") {
        return None;
    }
    mounts.iter().filter(|m| m.writable).find_map(|m| {
        let rest = dataset_path.strip_prefix(m.path.trim_end_matches('/'))?;
        let rest = rest.strip_prefix('/')?;
        if rest.is_empty() {
            return None;
        }
        Some((m, rest.split('/').map(str::to_string).collect()))
    })
}

/// Open the dataset folder through directory descriptors from the root of its writable
/// mount. Each component is opened with `O_NOFOLLOW`, so a symbolic link refuses the path.
/// This function blocks.
pub fn open_dataset_folder(mounts: &[DatasetMount], dataset_path: &str) -> anyhow::Result<(DatasetMount, OwnedFd)> {
    let (mount, parts) = writable_mount_for(mounts, dataset_path)
        .ok_or_else(|| anyhow::anyhow!("{dataset_path} is not beneath a writable dataset mount"))?;
    let mut fd = dataset_mounts::open_mount_root(mount)?;
    for part in &parts {
        fd = dataset_mounts::open_folder(&fd, part)?;
    }
    Ok((mount.clone(), fd))
}

/// The targets of the candidate rows, sorted by collection and dataset. A candidate is a
/// target when `resolves` opens its folder and returns the mount name. `Ok(None)` from
/// `resolves` means that no writable mount holds the path, and the dataset is no target.
/// An error means that the folder does not open, and the dataset is unavailable.
pub fn targets_from_candidates(
    candidates: Vec<UploadCandidate>,
    resolves: impl Fn(&str) -> Result<Option<String>, String>,
) -> UploadTargets {
    let unique: BTreeMap<(String, String), UploadCandidate> = candidates
        .into_iter()
        .map(|c| ((c.collectionname.clone(), c.collection_dataset.clone()), c))
        .collect();
    let mut result = UploadTargets::default();
    for ((collectionname, _), dataset) in unique {
        match resolves(&dataset.dataset_path) {
            Ok(Some(mount_name)) => result.targets.push(UploadTarget {
                collectionname,
                collection_dataset: dataset.collection_dataset,
                dataset_path: dataset.dataset_path,
                mount_name,
            }),
            Ok(None) => {}
            Err(reason) => result.unavailable.push(UploadUnavailable {
                collectionname,
                collection_dataset: dataset.collection_dataset,
                reason,
            }),
        }
    }
    result
}

/// The current upload targets of a user, with the mounts of this process.
pub async fn upload_targets(username: &str) -> anyhow::Result<UploadTargets> {
    upload_targets_with_mounts(username, dataset_mounts::dataset_mounts()?).await
}

/// This function is [`upload_targets`] with a given mount list. The integration tests pass
/// a temporary writable mount.
pub async fn upload_targets_with_mounts(
    username: &str,
    mounts: Vec<DatasetMount>,
) -> anyhow::Result<UploadTargets> {
    let candidates = upload_candidates(username).await?;
    dataset_mounts::blocking(move || {
        Ok(targets_from_candidates(candidates, |path| {
            if writable_mount_for(&mounts, path).is_none() {
                return Ok(None);
            }
            open_dataset_folder(&mounts, path).map(|(mount, _)| Some(mount.name)).map_err(|e| format!("{e:#}"))
        }))
    })
    .await
}

#[cfg(test)]
mod tests {
    use super::*;

    fn candidate(collectionname: &str, dataset: &str, path: &str) -> UploadCandidate {
        UploadCandidate {
            collectionname: collectionname.to_string(),
            collection_dataset: dataset.to_string(),
            dataset_path: path.to_string(),
        }
    }

    fn mount(name: &str, path: &str, writable: bool) -> DatasetMount {
        DatasetMount { name: name.to_string(), path: path.to_string(), writable }
    }

    #[test]
    fn a_dataset_path_needs_a_writable_mount_above_it() {
        let mounts = vec![mount("corpus", "/testdata", false), mount("uploads", "/uploads", true)];
        let (m, parts) = writable_mount_for(&mounts, "/uploads/case 7").unwrap();
        assert_eq!((m.name.as_str(), parts), ("uploads", vec!["case 7".to_string()]));
        assert_eq!(writable_mount_for(&mounts, "/uploads/a/b").unwrap().1, vec!["a", "b"]);
        for refused in [
            "/testdata/enron",
            "/uploads",
            "/uploads/",
            "/uploadsx/a",
            "/uploads/../testdata/enron",
            "/uploads/./a",
            "/uploads//a",
            "uploads/a",
            "/elsewhere/a",
        ] {
            assert!(writable_mount_for(&mounts, refused).is_none(), "{refused:?}");
        }
        let legacy = dataset_mounts::parse_dataset_mounts(None, Some("/testdata")).unwrap();
        assert!(writable_mount_for(&legacy, "/testdata/enron").is_none());
    }

    #[test]
    fn a_collection_with_one_upload_dataset_in_a_writable_mount_is_a_target() {
        let resolved = targets_from_candidates(
            vec![
                candidate("press", "press_inbox", "/uploads/press"),
                candidate("legal", "legal_inbox", "/testdata/legal"),
            ],
            |path| Ok(path.starts_with("/uploads/").then(|| "uploads".to_string())),
        );
        assert_eq!(
            resolved.targets,
            vec![UploadTarget {
                collectionname: "press".to_string(),
                collection_dataset: "press_inbox".to_string(),
                dataset_path: "/uploads/press".to_string(),
                mount_name: "uploads".to_string(),
            }]
        );
    }

    #[test]
    fn a_folder_that_does_not_open_is_unavailable_and_not_a_lost_permission() {
        let resolved = targets_from_candidates(
            vec![candidate("press", "press_inbox", "/uploads/press")],
            |_| Err("cannot open the dataset mount /uploads: No such file or directory".to_string()),
        );
        assert!(resolved.targets.is_empty());
        assert_eq!(
            resolved.unavailable,
            vec![UploadUnavailable {
                collectionname: "press".to_string(),
                collection_dataset: "press_inbox".to_string(),
                reason: "cannot open the dataset mount /uploads: No such file or directory".to_string(),
            }]
        );
    }

    #[test]
    fn each_upload_dataset_of_a_collection_is_a_target() {
        let resolved = targets_from_candidates(
            vec![
                candidate("press", "press_b", "/uploads/b"),
                candidate("press", "press_a", "/uploads/a"),
                candidate("press", "press_a", "/uploads/a"),
                candidate("press", "press_c", "/uploads/c"),
            ],
            |path| if path == "/uploads/c" { Err("missing".to_string()) } else { Ok(Some("uploads".to_string())) },
        );
        let names: Vec<&str> = resolved.targets.iter().map(|t| t.collection_dataset.as_str()).collect();
        assert_eq!(names, vec!["press_a", "press_b"]);
        assert_eq!(resolved.unavailable.len(), 1);
        assert_eq!(resolved.unavailable[0].collection_dataset, "press_c");
    }

    #[test]
    fn history_needs_an_administrator_or_an_uploader_of_the_collection() {
        let uploads_in = vec!["press".to_string()];
        assert!(history_readable(false, &uploads_in, "press"));
        assert!(!history_readable(false, &uploads_in, "legal"));
        assert!(!history_readable(false, &[], "press"));
        assert!(history_readable(true, &[], "legal"));
    }

    fn scratch(label: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "hoover4-uploads-{label}-{}-{}",
            std::process::id(),
            rand::random::<u64>()
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn the_dataset_folder_opens_only_through_real_folders() {
        let root = scratch("open");
        let outside = scratch("outside");
        std::fs::create_dir_all(root.join("case/sub")).unwrap();
        std::os::unix::fs::symlink(&outside, root.join("escape")).unwrap();
        let root_path = root.to_str().unwrap().to_string();
        let mounts = vec![mount("uploads", &root_path, true)];
        assert!(open_dataset_folder(&mounts, &format!("{root_path}/case")).is_ok());
        assert!(open_dataset_folder(&mounts, &format!("{root_path}/case/sub")).is_ok());
        assert!(open_dataset_folder(&mounts, &format!("{root_path}/escape")).is_err());
        assert!(open_dataset_folder(&mounts, &format!("{root_path}/missing")).is_err());
        let read_only = vec![mount("uploads", &root_path, false)];
        assert!(open_dataset_folder(&read_only, &format!("{root_path}/case")).is_err());
        for dir in [root, outside] {
            std::fs::remove_dir_all(dir).unwrap();
        }
    }
}
