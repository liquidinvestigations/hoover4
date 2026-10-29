//! The upload path rules, the limit checks and the wire types of the `/_upload/` routes.
//!
//! The upload page runs [`check_manifest`] in WebAssembly before it sends `begin`, and
//! the `begin` route runs the same function on the server. The server adds the checks
//! that need the disk: existing paths and free space.
//!
//! A destination path has the form of `vfs_files.path`. It is the destination folder
//! joined with the relative path of the file, with one leading `/`, as in
//! `/press/2026/a.pdf`.

use std::collections::{BTreeMap, BTreeSet};

/// The most parts in the relative path of one file.
pub const MAX_SEGMENTS: usize = 64;
/// The most bytes in one name. This is the Linux file name limit.
pub const MAX_SEGMENT_BYTES: usize = 255;
/// The most bytes in a destination path. The folder scan stays inside the Temporal
/// payload limit with paths of this length.
pub const MAX_PATH_BYTES: usize = 1024;
/// The largest `begin` body, in bytes of serialized JSON.
pub const MANIFEST_MAX_BYTES: usize = 16 * 1024 * 1024;

/// The start of the reserved name of a placement copy in a dataset folder.
pub const PART_PREFIX: &str = ".hoover4-upload-";
/// The end of the reserved name of a placement copy in a dataset folder.
pub const PART_SUFFIX: &str = ".hoover4-part";

/// The name of the temporary copy of one file of a batch in its destination folder.
/// The name has a fixed short length, so it never passes the name limit.
pub fn part_name(batch_id: &str, file_no: u32) -> String {
    format!("{PART_PREFIX}{batch_id}-{file_no}{PART_SUFFIX}")
}

/// True for a name with either reserved part. An upload cannot use such a name. The
/// folder scan skips a name with both parts, the form of [`part_name`]
/// (`is_upload_part_name` in `main_services/processing/database/uploads.py`).
pub fn is_reserved_name(name: &str) -> bool {
    name.starts_with(PART_PREFIX) || name.ends_with(PART_SUFFIX)
}

/// A broken path rule.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PathProblem {
    Empty,
    EmptyName,
    TooManyParts,
    NameTooLong,
    DotName,
    ControlCharacter,
    Backslash,
    ReservedName,
    PathTooLong,
    FolderForm,
}

impl PathProblem {
    /// The text that the page and `begin` show for this rule.
    pub fn message(self) -> &'static str {
        match self {
            PathProblem::Empty => "The path is empty.",
            PathProblem::EmptyName => "The path has an empty name between two slashes.",
            PathProblem::TooManyParts => "The path has more than 64 parts.",
            PathProblem::NameTooLong => "A name in the path is longer than 255 bytes.",
            PathProblem::DotName => "A name in the path is . or ..",
            PathProblem::ControlCharacter => "The name holds a control character.",
            PathProblem::Backslash => "The name holds a backslash.",
            PathProblem::ReservedName => "The name is reserved for the upload service.",
            PathProblem::PathTooLong => "The path is longer than 1,024 bytes.",
            PathProblem::FolderForm => "The folder must start with / and use valid names.",
        }
    }
}

fn check_name(name: &str) -> Result<(), PathProblem> {
    if name.is_empty() {
        return Err(PathProblem::EmptyName);
    }
    if name == "." || name == ".." {
        return Err(PathProblem::DotName);
    }
    if name.len() > MAX_SEGMENT_BYTES {
        return Err(PathProblem::NameTooLong);
    }
    if name.contains('\\') {
        return Err(PathProblem::Backslash);
    }
    if name.chars().any(char::is_control) {
        return Err(PathProblem::ControlCharacter);
    }
    if is_reserved_name(name) {
        return Err(PathProblem::ReservedName);
    }
    Ok(())
}

/// Check a destination folder: `/`, or `/` followed by valid names joined by `/`.
/// Returns the folder without a trailing `/`, and `/` for the root.
pub fn normalize_folder(folder: &str) -> Result<String, PathProblem> {
    if folder == "/" || folder.is_empty() {
        return Ok("/".to_string());
    }
    let Some(rest) = folder.strip_prefix('/') else {
        return Err(PathProblem::FolderForm);
    };
    let rest = rest.strip_suffix('/').unwrap_or(rest);
    for name in rest.split('/') {
        check_name(name).map_err(|_| PathProblem::FolderForm)?;
    }
    Ok(format!("/{rest}"))
}

/// Check the relative path of one file and return its destination path beneath `folder`.
/// `folder` must come from [`normalize_folder`].
pub fn destination_path(folder: &str, relative: &str) -> Result<String, PathProblem> {
    if relative.is_empty() {
        return Err(PathProblem::Empty);
    }
    let names: Vec<&str> = relative.split('/').collect();
    if names.len() > MAX_SEGMENTS {
        return Err(PathProblem::TooManyParts);
    }
    for name in &names {
        check_name(name)?;
    }
    let destination = if folder == "/" {
        format!("/{relative}")
    } else {
        format!("{folder}/{relative}")
    };
    if destination.len() > MAX_PATH_BYTES {
        return Err(PathProblem::PathTooLong);
    }
    Ok(destination)
}

/// The names of a destination path from the dataset root, without the leading `/`.
pub fn path_names(destination: &str) -> Vec<&str> {
    destination.trim_start_matches('/').split('/').collect()
}

/// Bytes in binary units, for the limit messages: `512 B`, `482.1 KiB`, `10 GiB`.
pub fn format_upload_size(bytes: u64) -> String {
    const UNITS: [&str; 4] = ["KiB", "MiB", "GiB", "TiB"];
    if bytes < 1024 {
        return format!("{bytes} B");
    }
    let mut value = bytes as f64 / 1024.0;
    let mut unit = 0;
    while value >= 1024.0 && unit + 1 < UNITS.len() {
        value /= 1024.0;
        unit += 1;
    }
    let rounded = (value * 10.0).round() / 10.0;
    if rounded.fract() == 0.0 {
        format!("{} {}", rounded as u64, UNITS[unit])
    } else {
        format!("{rounded:.1} {}", UNITS[unit])
    }
}

/// A count with thousands separators, as the messages show it: `10,000`.
pub fn format_count(n: u64) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(c);
    }
    out
}

/// The limits of one deployment, from the `[uploads]` section of `hoover4.ini`, and the
/// fixed path limits.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct UploadLimits {
    pub max_batch_files: u64,
    pub max_batch_bytes: u64,
    pub max_file_bytes: u64,
    pub chunk_bytes: u64,
    pub abandon_hours: u64,
    pub manifest_max_bytes: u64,
    pub max_path_bytes: u64,
    pub max_segments: u64,
    pub max_segment_bytes: u64,
}

impl Default for UploadLimits {
    fn default() -> Self {
        UploadLimits {
            max_batch_files: 10_000,
            max_batch_bytes: 10 * 1024 * 1024 * 1024,
            max_file_bytes: 10 * 1024 * 1024 * 1024,
            chunk_bytes: 32 * 1024 * 1024,
            abandon_hours: 24,
            manifest_max_bytes: MANIFEST_MAX_BYTES as u64,
            max_path_bytes: MAX_PATH_BYTES as u64,
            max_segments: MAX_SEGMENTS as u64,
            max_segment_bytes: MAX_SEGMENT_BYTES as u64,
        }
    }
}

/// One upload target of the user: the upload dataset of a collection.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct UploadTargetInfo {
    pub collection: String,
    pub dataset: String,
}

/// The body of `GET /_upload/limits`.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct LimitsResponse {
    pub limits: UploadLimits,
    pub targets: Vec<UploadTargetInfo>,
    /// Collections with more than one upload dataset. They have no target.
    pub conflicts: Vec<String>,
}

/// One file of a `begin` manifest.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct BeginFile {
    /// The path relative to the destination folder.
    pub path: String,
    pub size: u64,
    /// `lastModified` of the browser `File`, in milliseconds since 1970.
    #[serde(default)]
    pub last_modified_ms: Option<i64>,
}

/// The body of `POST /_upload/begin`. The page measures its serialized size with
/// [`manifest_body_bytes`] before it sends it.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct BeginRequest {
    pub request_id: String,
    pub collection: String,
    pub folder: String,
    pub files: Vec<BeginFile>,
}

/// The number of bytes of the JSON body that the page sends for this manifest.
pub fn manifest_body_bytes(request: &BeginRequest) -> usize {
    serde_json::to_vec(request).map(|v| v.len()).unwrap_or(usize::MAX)
}

/// One accepted file of a batch.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct BatchFile {
    pub file_no: u32,
    pub path: String,
    /// The tus address of the file.
    pub upload_url: String,
}

/// The body of a successful `begin`.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct BeginResponse {
    pub batch_id: String,
    pub files: Vec<BatchFile>,
}

/// A file that breaks a rule, and the rule text.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct FileProblem {
    pub path: String,
    pub message: String,
}

/// The body of a refused `begin`.
#[derive(Debug, Clone, Default, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct BeginRefusal {
    pub message: String,
    /// The rules that the whole batch breaks.
    #[serde(default)]
    pub batch_problems: Vec<String>,
    /// The files that break a rule.
    #[serde(default)]
    pub problems: Vec<FileProblem>,
    /// Destination paths that exist in the folder or that another upload reserves.
    #[serde(default)]
    pub collisions: Vec<String>,
}

/// The body of a successful `commit`.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct CommitResponse {
    pub batch_id: String,
    pub state: String,
    pub detail: String,
}

/// The body of the acknowledged-prefix digest route.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub struct PrefixDigest {
    pub file_no: u32,
    pub offset: u64,
    pub length: u64,
    /// Lowercase hex SHA-256 of the first `offset` bytes.
    pub sha256: String,
}

/// The text of a refused `begin` with file problems.
pub const PROBLEMS_MESSAGE: &str = "Some files cannot be uploaded.";
/// The text of a refused `begin` with existing paths.
pub const COLLISIONS_MESSAGE: &str = "These paths exist in the folder:";
/// The text of a `begin` body above [`MANIFEST_MAX_BYTES`].
pub const MANIFEST_TOO_LARGE_MESSAGE: &str =
    "The list of files is too large. Upload fewer files at once.";
/// The text of a reused request id with a changed manifest.
pub const REQUEST_ID_REUSED_MESSAGE: &str = "This request id belongs to a different upload.";
/// The text of a refused mutation after the permission ended.
pub const NO_PERMISSION_MESSAGE: &str = "You no longer have upload permission for this collection.";
/// The text of a refused mutation after the batch or the file ended.
pub const ENDED_MESSAGE: &str = "This upload has ended.";
/// The error of a file whose destination exists at placement.
pub const PATH_EXISTS_MESSAGE: &str = "The path exists in the dataset folder.";
/// The error of a file that placement could not recover.
pub const NOT_RECOVERED_MESSAGE: &str = "The server could not recover this file.";
/// The error of an unplaced file and of its batch after the dataset was deleted.
pub const DATASET_DELETED_MESSAGE: &str = "The dataset was deleted during this upload.";
/// The error of an unplaced file and of its batch after the dataset was purged.
pub const DATASET_PURGED_MESSAGE: &str = "The dataset was purged during this upload.";
/// The text of a duplicate path in one manifest.
pub const SELECTED_TWICE_MESSAGE: &str = "Selected twice.";
/// The text of a path that is also a folder of another path of the manifest.
pub const FILE_AND_FOLDER_MESSAGE: &str = "The path is also a folder of another selected file.";

/// The text of the free space refusal.
pub fn free_space_message(free: u64, needed: u64) -> String {
    format!(
        "The server has {} free for uploads. This upload needs {}.",
        format_upload_size(free),
        format_upload_size(needed)
    )
}

/// The result of [`check_manifest`]. An empty value means that the page may send `begin`.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ManifestCheck {
    pub batch_problems: Vec<String>,
    pub problems: Vec<FileProblem>,
    /// The destination path of each file, in manifest order. A file with a problem has
    /// `None`.
    pub destinations: Vec<Option<String>>,
}

impl ManifestCheck {
    pub fn is_empty(&self) -> bool {
        self.batch_problems.is_empty() && self.problems.is_empty()
    }
}

/// Every check that does not need the disk: the file count, the total size, the size of
/// each file, the path rules, a path selected twice, and a path that is also a folder of
/// another file of the manifest.
pub fn check_manifest(limits: &UploadLimits, folder: &str, files: &[BeginFile]) -> ManifestCheck {
    let mut check = ManifestCheck::default();
    let count = files.len() as u64;
    if count == 0 {
        check.batch_problems.push("This upload has no files.".to_string());
    }
    if count > limits.max_batch_files {
        check.batch_problems.push(format!(
            "This upload has {} files. The limit is {}.",
            format_count(count),
            format_count(limits.max_batch_files)
        ));
    }
    let total: u64 = files.iter().fold(0u64, |sum, f| sum.saturating_add(f.size));
    if total > limits.max_batch_bytes {
        check.batch_problems.push(format!(
            "This upload has {}. The limit is {}.",
            format_upload_size(total),
            format_upload_size(limits.max_batch_bytes)
        ));
    }
    let folder = match normalize_folder(folder) {
        Ok(folder) => Some(folder),
        Err(problem) => {
            check.batch_problems.push(problem.message().to_string());
            None
        }
    };
    let mut seen: BTreeMap<String, usize> = BTreeMap::new();
    for (index, file) in files.iter().enumerate() {
        let mut problem: Option<String> = None;
        if file.size > limits.max_file_bytes {
            problem = Some(format!("Larger than {}.", format_upload_size(limits.max_file_bytes)));
        }
        let destination = match &folder {
            Some(folder) => match destination_path(folder, &file.path) {
                Ok(destination) => Some(destination),
                Err(rule) => {
                    problem.get_or_insert_with(|| rule.message().to_string());
                    None
                }
            },
            None => None,
        };
        if let Some(destination) = &destination {
            if seen.insert(destination.clone(), index).is_some() {
                problem.get_or_insert_with(|| SELECTED_TWICE_MESSAGE.to_string());
            }
        }
        if let Some(message) = problem {
            check.problems.push(FileProblem { path: file.path.clone(), message });
            check.destinations.push(None);
        } else {
            check.destinations.push(destination);
        }
    }
    // A file path that is the folder of another file cannot be both.
    let folders: BTreeSet<String> = seen.keys().flat_map(|p| ancestors(p)).collect();
    for (index, file) in files.iter().enumerate() {
        let Some(Some(destination)) = check.destinations.get(index).cloned() else {
            continue;
        };
        if folders.contains(&destination) {
            check.problems.push(FileProblem {
                path: file.path.clone(),
                message: FILE_AND_FOLDER_MESSAGE.to_string(),
            });
            check.destinations[index] = None;
        }
    }
    check
}

/// The folders above a destination path, without the root: `/a/b/c` gives `/a` and `/a/b`.
pub fn ancestors(destination: &str) -> Vec<String> {
    destination
        .match_indices('/')
        .map(|(pos, _)| pos)
        .filter(|pos| *pos > 0)
        .map(|pos| destination[..pos].to_string())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn file(path: &str, size: u64) -> BeginFile {
        BeginFile { path: path.to_string(), size, last_modified_ms: None }
    }

    #[test]
    fn a_valid_path_joins_the_folder() {
        assert_eq!(destination_path("/press", "2026/a.pdf").unwrap(), "/press/2026/a.pdf");
        assert_eq!(destination_path("/", "a b.txt").unwrap(), "/a b.txt");
        assert_eq!(normalize_folder("/press/").unwrap(), "/press");
        assert_eq!(normalize_folder("").unwrap(), "/");
        // Spaces, leading full stops and other scripts stay as the browser sent them.
        assert!(destination_path("/", ".gitignore").is_ok());
        assert!(destination_path("/", "Ärger/naïve café.txt").is_ok());
    }

    #[test]
    fn each_path_rule_refuses_its_case() {
        let cases = [
            ("", PathProblem::Empty),
            ("a//b", PathProblem::EmptyName),
            ("/a", PathProblem::EmptyName),
            ("a/", PathProblem::EmptyName),
            ("a/./b", PathProblem::DotName),
            ("../b", PathProblem::DotName),
            ("a\\b", PathProblem::Backslash),
            ("a\tb", PathProblem::ControlCharacter),
            ("a\0b", PathProblem::ControlCharacter),
            ("a\u{7f}b", PathProblem::ControlCharacter),
            (".hoover4-upload-x", PathProblem::ReservedName),
            ("x.hoover4-part", PathProblem::ReservedName),
            ("d/.hoover4-upload-0123-1.hoover4-part", PathProblem::ReservedName),
        ];
        for (path, expected) in cases {
            assert_eq!(destination_path("/f", path), Err(expected), "{path:?}");
        }
    }

    #[test]
    fn the_length_limits_count_bytes() {
        let name255 = "é".repeat(127) + "a"; // 255 bytes
        assert_eq!(name255.len(), 255);
        assert!(destination_path("/", &name255).is_ok());
        let name256 = "é".repeat(128);
        assert_eq!(destination_path("/", &name256), Err(PathProblem::NameTooLong));

        let parts64 = vec!["a"; 64].join("/");
        assert!(destination_path("/", &parts64).is_ok());
        let parts65 = vec!["a"; 65].join("/");
        assert_eq!(destination_path("/", &parts65), Err(PathProblem::TooManyParts));

        // `/`, 3 names of 255 bytes with 2 separators, `/`, and 255 more bytes give 1,024 bytes.
        let long = vec!["b".repeat(255); 3].join("/");
        let exact = format!("{long}/{}", "c".repeat(1024 - 1 - long.len() - 1));
        assert_eq!(destination_path("/", &exact).unwrap().len(), 1024);
        let over = format!("{exact}/d");
        assert_eq!(destination_path("/", &over), Err(PathProblem::PathTooLong));
        // The folder counts toward the limit.
        assert_eq!(destination_path("/f", &exact), Err(PathProblem::PathTooLong));
    }

    #[test]
    fn the_part_name_is_reserved_and_short() {
        let name = part_name(&"f".repeat(32), 9_999);
        assert!(is_reserved_name(&name));
        assert!(name.len() < MAX_SEGMENT_BYTES);
        assert!(!is_reserved_name("upload.part"));
    }

    #[test]
    fn the_manifest_check_lists_every_problem() {
        let limits = UploadLimits { max_batch_files: 3, max_batch_bytes: 100, max_file_bytes: 50, ..Default::default() };
        let files = vec![
            file("a.txt", 10),
            file("a.txt", 10),
            file("big.bin", 60),
            file("bad\tname", 1),
        ];
        let check = check_manifest(&limits, "/f", &files);
        assert_eq!(check.batch_problems, vec!["This upload has 4 files. The limit is 3.".to_string()]);
        let messages: Vec<(&str, &str)> =
            check.problems.iter().map(|p| (p.path.as_str(), p.message.as_str())).collect();
        assert_eq!(
            messages,
            vec![
                ("a.txt", SELECTED_TWICE_MESSAGE),
                ("big.bin", "Larger than 50 B."),
                ("bad\tname", "The name holds a control character."),
            ]
        );
    }

    #[test]
    fn a_file_that_is_a_folder_of_another_file_is_refused() {
        let check = check_manifest(&UploadLimits::default(), "/", &[file("a", 1), file("a/b", 1), file("c/d", 1)]);
        assert_eq!(check.problems, vec![FileProblem { path: "a".to_string(), message: FILE_AND_FOLDER_MESSAGE.to_string() }]);
        assert_eq!(check.destinations, vec![None, Some("/a/b".to_string()), Some("/c/d".to_string())]);
    }

    #[test]
    fn the_total_size_and_the_count_use_the_limit_texts() {
        let limits = UploadLimits { max_batch_bytes: 10 * 1024 * 1024 * 1024, ..Default::default() };
        let files = vec![file("a", 6 * 1024 * 1024 * 1024), file("b", 5 * 1024 * 1024 * 1024)];
        let check = check_manifest(&limits, "/", &files);
        assert_eq!(check.batch_problems, vec!["This upload has 11 GiB. The limit is 10 GiB.".to_string()]);
        assert_eq!(format_count(10_000), "10,000");
        assert_eq!(format_upload_size(482_113), "470.8 KiB");
    }

    #[test]
    fn ancestors_exclude_the_root_and_the_path() {
        assert_eq!(ancestors("/a/b/c"), vec!["/a".to_string(), "/a/b".to_string()]);
        assert!(ancestors("/a").is_empty());
    }
}
