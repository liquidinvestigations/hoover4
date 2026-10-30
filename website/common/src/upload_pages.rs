//! The types and the rules of the upload pages: the batch list, the batch detail and the
//! "Continue upload" selection.
//!
//! The backend fills these types in `backend::api::uploads_api`, and the pages in
//! `frontend::pages::uploads` show them. The file states of the detail page follow the
//! success rule of `classify_outcome` in `main_services/processing/database/uploads.py`,
//! so the detail page shows the same counts while a batch runs that the worker writes at
//! its end.

use serde::{Deserialize, Serialize};

/// Rows in one page of the batch list and of the file table of the batch detail.
pub const PAGE_ROWS: usize = 200;

/// The label of a stored batch state, in the order of the `state` column comment of
/// `upload_batches`.
pub fn batch_state_label(state: &str) -> &'static str {
    match state {
        "uploading" => "Uploading",
        "committing" => "Placing",
        "queued" => "Queued",
        "ingesting" => "Ingesting",
        "processing" => "Processing",
        "completed" => "Indexed",
        "completed_with_errors" => "Indexed with errors",
        "failed" => "Failed",
        "cancelled" => "Cancelled",
        _ => "Unknown",
    }
}

/// True for a batch state that never changes again.
pub fn batch_state_is_terminal(state: &str) -> bool {
    matches!(state, "completed" | "completed_with_errors" | "failed" | "cancelled")
}

/// One row of the batch list, and the head of the batch detail.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UploadBatchRow {
    pub collection: String,
    pub batch_id: String,
    pub upload_dataset: String,
    pub folder: String,
    pub username: String,
    pub state: String,
    pub file_count: u32,
    pub byte_count: u64,
    /// Time of `begin`, in milliseconds since 1970.
    pub created_ms: i64,
}

/// The position after the last row of a batch list page. The list is ordered by creation
/// time and batch id, newest first.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UploadBatchCursor {
    pub created_ms: i64,
    pub batch_id: String,
}

/// One page of the batch list.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct UploadBatchPage {
    pub rows: Vec<UploadBatchRow>,
    /// The cursor of the next page, or `None` after the last row.
    pub next: Option<UploadBatchCursor>,
    /// The collections whose batch history the user may read, for the filter.
    pub collections: Vec<String>,
}

/// The state of one file on the detail page.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum UploadFileState {
    /// Declared, or complete in the upload space and not yet in the dataset folder.
    Waiting,
    /// In the dataset folder. Ingestion has not read it yet.
    Placed,
    /// Ingested, with no processing plan yet.
    Ingested,
    /// Ingested, with an unfinished plan or a path that is not published yet.
    Processing,
    /// Processed and published without a current error.
    Indexed,
    /// The file or a member below it has a current processing error.
    Errors,
    Rejected,
    NotSent,
}

impl UploadFileState {
    pub fn label(self) -> &'static str {
        match self {
            UploadFileState::Waiting => "Waiting",
            UploadFileState::Placed => "Placed",
            UploadFileState::Ingested => "Ingested",
            UploadFileState::Processing => "Processing",
            UploadFileState::Indexed => "Indexed",
            UploadFileState::Errors => "Errors",
            UploadFileState::Rejected => "Rejected",
            UploadFileState::NotSent => "Not sent",
        }
    }

    /// True for the states that the file table shows first.
    pub fn is_problem(self) -> bool {
        matches!(self, UploadFileState::Errors | UploadFileState::Rejected | UploadFileState::NotSent)
    }
}

/// The stored facts of one ingested file that decide its state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct IngestedEvidence {
    /// The path has a live top-level `vfs_files` row with the file hash and a `vfs_nodes`
    /// row.
    pub published: bool,
    /// The number of plans that list the file hash.
    pub planned: u64,
    /// A plan of the file hash or of a member below it has not finished.
    pub unfinished: bool,
    /// The file hash or a member below it has a current processing error.
    pub failing: bool,
}

/// The state of one file from its `upload_files.state` and, for an ingested file, its
/// evidence. The success rule is the rule of `classify_outcome`: published, planned, every
/// plan finished, and no current error.
pub fn file_state(stored: &str, evidence: Option<IngestedEvidence>) -> UploadFileState {
    match stored {
        "not_sent" => UploadFileState::NotSent,
        "rejected" => UploadFileState::Rejected,
        "placed" => UploadFileState::Placed,
        "ingested" => {
            let e = evidence.unwrap_or_default();
            if e.failing {
                UploadFileState::Errors
            } else if e.planned == 0 {
                UploadFileState::Ingested
            } else if e.unfinished || !e.published {
                UploadFileState::Processing
            } else {
                UploadFileState::Indexed
            }
        }
        _ => UploadFileState::Waiting,
    }
}

/// The counters of the detail page. Each counts manifest entries.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub struct UploadCounts {
    pub files: u64,
    pub ingested: u64,
    pub indexed: u64,
    pub with_errors: u64,
    pub rejected: u64,
    pub not_sent: u64,
}

impl UploadCounts {
    /// Add one file. `ingested` counts every file that ingestion accepted, so it also
    /// counts the files that are indexed or have errors.
    pub fn add(&mut self, state: UploadFileState) {
        self.files += 1;
        match state {
            UploadFileState::Ingested | UploadFileState::Processing => self.ingested += 1,
            UploadFileState::Indexed => {
                self.ingested += 1;
                self.indexed += 1;
            }
            UploadFileState::Errors => {
                self.ingested += 1;
                self.with_errors += 1;
            }
            UploadFileState::Rejected => self.rejected += 1,
            UploadFileState::NotSent => self.not_sent += 1,
            UploadFileState::Waiting | UploadFileState::Placed => {}
        }
    }
}

/// One row of the file table of the detail page.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UploadFileRow {
    pub file_no: u32,
    /// The destination path in the dataset.
    pub path: String,
    pub size_bytes: u64,
    pub state: UploadFileState,
    /// The rejection reason, or the first current processing error. Empty for none.
    pub error: String,
    /// The blob hash of an ingested file, empty before ingestion.
    pub file_hash: String,
}

/// Sort file rows for the table: files with a problem first, then manifest order.
pub fn sort_file_rows(rows: &mut [UploadFileRow]) {
    rows.sort_by_key(|row| (!row.state.is_problem(), row.file_no));
}

/// The batch detail page.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UploadBatchDetail {
    pub batch: UploadBatchRow,
    /// The `ingest_upload` operation of the batch. Only administrators receive it.
    pub op_id: Option<String>,
    /// The batch error text, empty for none.
    pub error: String,
    /// True when the reader owns the batch.
    pub is_owner: bool,
    pub counts: UploadCounts,
    /// One page of the file table, in the order of [`sort_file_rows`].
    pub files: Vec<UploadFileRow>,
    pub page: u32,
    pub page_count: u32,
}

/// One manifest file of an `uploading` batch, for "Continue upload".
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ResumeFile {
    pub file_no: u32,
    /// The path relative to the batch folder, as the page sent it in `begin`.
    pub relative_path: String,
    pub size: u64,
    /// The declared modification time in whole seconds, as `upload_files.client_mtime`
    /// stores it.
    pub mtime_s: i64,
    /// The stored `upload_files.state`.
    pub state: String,
}

/// The relative path of a destination path beneath the batch folder: `/press/2026/a.pdf`
/// in `/press` gives `2026/a.pdf`.
pub fn relative_to_folder(folder: &str, destination: &str) -> String {
    let rest = if folder == "/" || folder.is_empty() {
        destination.strip_prefix('/')
    } else {
        destination.strip_prefix(folder).and_then(|r| r.strip_prefix('/'))
    };
    rest.unwrap_or(destination).to_string()
}

/// One file of a "Continue upload" selection.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SelectedFile {
    /// The id of the browser `File` in the upload script.
    pub id: u64,
    pub path: String,
    pub size: u64,
    pub last_modified_ms: Option<i64>,
}

/// The result of [`match_resume_selection`].
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct ResumeMatch {
    /// `(selected file id, manifest file number)` of each file to send.
    pub matched: Vec<(u64, u32)>,
    /// The selected files that match no file of the batch.
    pub unmatched: usize,
    /// The selected files that match a file of the batch that has all its bytes.
    pub complete: usize,
    /// The relative paths of the `pending` files of the batch that the selection does
    /// not name, in manifest order.
    pub not_selected: Vec<String>,
}

impl ResumeMatch {
    /// True when the selection names a file of the batch. Only then does the page resume.
    pub fn names_the_batch(&self) -> bool {
        !self.matched.is_empty() || self.complete > 0
    }

    /// True when the selection names every `pending` file of the batch. Only then may
    /// the run commit after its last file, because no file of the batch then waits for
    /// bytes. A file whose prefix differs keeps the run from committing too.
    pub fn sends_every_pending_file(&self) -> bool {
        self.not_selected.is_empty()
    }
}

/// Match a reselection against the `pending` files of a batch by relative path, size and
/// modification second. A file that matches a file that has all its bytes is neither sent
/// nor counted as unmatched. The `pending` files that no selected file matches are
/// listed in `not_selected`.
pub fn match_resume_selection(batch: &[ResumeFile], selected: &[SelectedFile]) -> ResumeMatch {
    let mut result = ResumeMatch::default();
    let mut taken = std::collections::BTreeSet::new();
    for file in selected {
        let entry = batch.iter().find(|b| {
            b.relative_path == file.path
                && b.size == file.size
                && file.last_modified_ms.map(|ms| ms.div_euclid(1000)) == Some(b.mtime_s)
        });
        match entry {
            Some(entry) if entry.state == "pending" => {
                if taken.insert(entry.file_no) {
                    result.matched.push((file.id, entry.file_no));
                }
            }
            Some(_) => result.complete += 1,
            None => result.unmatched += 1,
        }
    }
    result.not_selected = batch
        .iter()
        .filter(|b| b.state == "pending" && !taken.contains(&b.file_no))
        .map(|b| b.relative_path.clone())
        .collect();
    result
}

/// The `pending` files of a batch, by relative path, in manifest order.
pub fn pending_paths(batch: &[ResumeFile]) -> Vec<String> {
    batch.iter().filter(|b| b.state == "pending").map(|b| b.relative_path.clone()).collect()
}

/// A `begin` that the page sent without a decision of the server: the request id, and
/// the body without the id, so the page can send the same request again.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnconfirmedBegin {
    pub request_id: String,
    /// The JSON of the request with an empty request id.
    pub request_key: String,
}

/// The request id of a `begin`. The id of an unconfirmed `begin` of the same selection
/// and destination is sent again, so the server returns the batch that it recorded for
/// the lost answer. Any other request gets `fresh()`.
pub fn begin_request_id(
    unconfirmed: Option<&UnconfirmedBegin>,
    request_key: &str,
    fresh: impl FnOnce() -> String,
) -> String {
    match unconfirmed {
        Some(previous) if previous.request_key == request_key => previous.request_id.clone(),
        _ => fresh(),
    }
}

/// True when a `begin` answer leaves its result unknown: no answer (status 0), a lock
/// that another request held (423), or a server failure. The page then keeps the request
/// id for the next click. Any other answer is a decision of the server.
pub fn begin_result_unknown(status: u16) -> bool {
    status == 0 || status == 423 || status >= 500
}

/// A size for the page, as the storage pages show sizes.
pub fn size_label(bytes: u64) -> String {
    crate::uploads::format_upload_size(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn evidence(published: bool, planned: u64, unfinished: bool, failing: bool) -> Option<IngestedEvidence> {
        Some(IngestedEvidence { published, planned, unfinished, failing })
    }

    #[test]
    fn every_stored_state_has_a_label_in_the_column_order() {
        let states = [
            "uploading", "committing", "queued", "ingesting", "processing", "completed",
            "completed_with_errors", "failed", "cancelled",
        ];
        let labels: Vec<&str> = states.iter().map(|s| batch_state_label(s)).collect();
        assert_eq!(
            labels,
            vec![
                "Uploading", "Placing", "Queued", "Ingesting", "Processing", "Indexed",
                "Indexed with errors", "Failed", "Cancelled",
            ]
        );
        assert!(batch_state_is_terminal("cancelled"));
        assert!(!batch_state_is_terminal("processing"));
    }

    #[test]
    fn an_ingested_file_is_indexed_only_when_published_planned_finished_and_without_error() {
        assert_eq!(file_state("ingested", evidence(true, 1, false, false)), UploadFileState::Indexed);
        assert_eq!(file_state("ingested", evidence(true, 1, false, true)), UploadFileState::Errors);
        assert_eq!(file_state("ingested", evidence(true, 2, true, false)), UploadFileState::Processing);
        assert_eq!(file_state("ingested", evidence(false, 1, false, false)), UploadFileState::Processing);
        assert_eq!(file_state("ingested", evidence(true, 0, false, false)), UploadFileState::Ingested);
        assert_eq!(file_state("ingested", None), UploadFileState::Ingested);
        // A current error of a member wins over an unfinished plan.
        assert_eq!(file_state("ingested", evidence(false, 1, true, true)), UploadFileState::Errors);
        assert_eq!(file_state("pending", None), UploadFileState::Waiting);
        assert_eq!(file_state("staged", None), UploadFileState::Waiting);
        assert_eq!(file_state("placed", None), UploadFileState::Placed);
        assert_eq!(file_state("rejected", None), UploadFileState::Rejected);
        assert_eq!(file_state("not_sent", None), UploadFileState::NotSent);
    }

    #[test]
    fn counters_count_manifest_entries() {
        let mut counts = UploadCounts::default();
        for state in [
            UploadFileState::Indexed,
            UploadFileState::Indexed,
            UploadFileState::Errors,
            UploadFileState::Processing,
            UploadFileState::Rejected,
            UploadFileState::NotSent,
            UploadFileState::Waiting,
        ] {
            counts.add(state);
        }
        assert_eq!(
            counts,
            UploadCounts { files: 7, ingested: 4, indexed: 2, with_errors: 1, rejected: 1, not_sent: 1 }
        );
    }

    #[test]
    fn problem_rows_come_first_and_keep_manifest_order() {
        let row = |file_no, state| UploadFileRow {
            file_no,
            path: format!("/{file_no}"),
            size_bytes: 1,
            state,
            error: String::new(),
            file_hash: String::new(),
        };
        let mut rows = vec![
            row(0, UploadFileState::Indexed),
            row(1, UploadFileState::NotSent),
            row(2, UploadFileState::Indexed),
            row(3, UploadFileState::Errors),
        ];
        sort_file_rows(&mut rows);
        assert_eq!(rows.iter().map(|r| r.file_no).collect::<Vec<_>>(), vec![1, 3, 0, 2]);
    }

    #[test]
    fn a_destination_path_loses_its_folder() {
        assert_eq!(relative_to_folder("/press", "/press/2026/a.pdf"), "2026/a.pdf");
        assert_eq!(relative_to_folder("/", "/a b.txt"), "a b.txt");
        assert_eq!(relative_to_folder("/pre", "/press/a"), "/press/a");
    }

    #[test]
    fn a_reselection_matches_path_size_and_second() {
        let batch = vec![
            ResumeFile { file_no: 0, relative_path: "d/a.txt".into(), size: 10, mtime_s: 1_792_500_000, state: "placed".into() },
            ResumeFile { file_no: 1, relative_path: "d/b.txt".into(), size: 20, mtime_s: 1_792_500_000, state: "pending".into() },
            ResumeFile { file_no: 2, relative_path: "d/c.txt".into(), size: 30, mtime_s: 1_792_500_000, state: "pending".into() },
        ];
        let pick = |id, path: &str, size, ms| SelectedFile { id, path: path.into(), size, last_modified_ms: Some(ms) };
        let selected = vec![
            pick(1, "d/a.txt", 10, 1_792_500_000_123),
            pick(2, "d/b.txt", 20, 1_792_500_000_999),
            pick(3, "d/c.txt", 31, 1_792_500_000_000),
            pick(4, "d/new.txt", 1, 1_792_500_000_000),
            pick(5, "d/b.txt", 20, 1_792_500_000_000),
        ];
        let result = match_resume_selection(&batch, &selected);
        assert_eq!(result.matched, vec![(2, 1)]);
        assert_eq!((result.unmatched, result.complete), (2, 1));
        assert!(result.names_the_batch());
        let none = match_resume_selection(&batch, &[pick(6, "other.txt", 1, 1_792_500_000_000)]);
        assert!(!none.names_the_batch());
        // d/c.txt did not match (size), so it is not selected and the run may not commit.
        assert_eq!(result.not_selected, vec!["d/c.txt".to_string()]);
        assert!(!result.sends_every_pending_file());
    }

    fn resume_batch() -> Vec<ResumeFile> {
        let file = |file_no, path: &str, state: &str| ResumeFile {
            file_no,
            relative_path: path.into(),
            size: 10,
            mtime_s: 1_792_500_000,
            state: state.into(),
        };
        vec![file(0, "d1/a", "pending"), file(1, "d1/b", "pending"), file(2, "d2/c", "pending"), file(3, "d2/e", "placed")]
    }

    fn select(id: u64, path: &str) -> SelectedFile {
        SelectedFile { id, path: path.into(), size: 10, last_modified_ms: Some(1_792_500_000_000) }
    }

    #[test]
    fn a_partial_reselection_names_the_files_that_stay_pending_and_does_not_commit() {
        let batch = resume_batch();
        let partial = match_resume_selection(&batch, &[select(1, "d1/a"), select(2, "d1/b")]);
        assert_eq!(partial.matched, vec![(1, 0), (2, 1)]);
        assert_eq!(partial.not_selected, vec!["d2/c".to_string()]);
        assert!(partial.names_the_batch() && !partial.sends_every_pending_file());
        // A selection of a complete file only names the batch, and it sends nothing.
        let complete = match_resume_selection(&batch, &[select(5, "d2/e")]);
        assert!(complete.names_the_batch() && complete.matched.is_empty());
        assert_eq!(complete.not_selected.len(), 3);
        assert!(!complete.sends_every_pending_file());
        let all = match_resume_selection(&batch, &[select(1, "d1/a"), select(2, "d1/b"), select(3, "d2/c")]);
        assert!(all.sends_every_pending_file());
        assert_eq!(pending_paths(&batch), vec!["d1/a", "d1/b", "d2/c"]);
    }

    #[test]
    fn an_unconfirmed_begin_of_the_same_request_keeps_its_id() {
        let unconfirmed = UnconfirmedBegin { request_id: "first".into(), request_key: "{same}".into() };
        assert_eq!(begin_request_id(Some(&unconfirmed), "{same}", || "fresh".into()), "first");
        assert_eq!(begin_request_id(Some(&unconfirmed), "{changed}", || "fresh".into()), "fresh");
        assert_eq!(begin_request_id(None, "{same}", || "fresh".into()), "fresh");
        assert!(begin_result_unknown(0) && begin_result_unknown(423) && begin_result_unknown(502));
        assert!(!begin_result_unknown(409) && !begin_result_unknown(400) && !begin_result_unknown(201));
    }
}
