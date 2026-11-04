//! Admin API DTOs shared between frontend and backend.

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminUserItem {
    pub username: String,
    pub fullname: String,
    pub email: String,
    pub is_admin: bool,
    pub created_at: String,
    pub last_login: Option<String>,
    pub group_count: u32,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminUserDetail {
    pub user: AdminUserItem,
    pub memberships: Vec<AdminMembershipItem>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminMembershipItem {
    pub groupname: String,
    pub is_group_admin: bool,
    /// The uploader flag of the membership.
    pub is_uploader: bool,
    pub origin: String,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminGroupItem {
    pub groupname: String,
    pub fullname: String,
    pub member_count: u32,
    pub collection_count: u32,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminGroupDetail {
    pub group: AdminGroupItem,
    pub members: Vec<AdminGroupMemberItem>,
    pub collections: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminGroupMemberItem {
    pub username: String,
    pub is_group_admin: bool,
    /// The uploader flag of the membership.
    pub is_uploader: bool,
    pub origin: String,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminCollectionItem {
    pub collectionname: String,
    pub fullname: String,
    pub dataset_count: u32,
    pub group_count: u32,
    /// False while `Hoover4_Collection_<collectionname>` is still being provisioned by the
    /// `EnsureCollectionDatabase` workflow that collection creation starts.
    pub db_ready: bool,
    /// True when the collection is readable by every authenticated user without a group
    /// grant. False = restricted to the groups listed in `collection_group_permissions`.
    pub is_public: bool,
    /// The summed cached statistics of the collection's datasets.
    #[serde(default)]
    pub stats: crate::storage_tree::CollectionAggregates,
    /// True when a live dataset of the collection has `uploads_enabled`.
    #[serde(default)]
    pub accepts_uploads: bool,
}

/// One row of the administration Datasets list, which covers every collection.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetListItem {
    pub collectionname: String,
    pub collection_dataset: String,
    pub dataset_name: String,
    pub dataset_display_name: String,
    pub date_created: String,
    /// `None` until the pipeline writes the dataset's first statistics row.
    pub stats: Option<crate::storage_tree::DatasetAggregates>,
    /// True when the dataset has `uploads_enabled`.
    #[serde(default)]
    pub accepts_uploads: bool,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminCollectionDetail {
    pub collection: AdminCollectionItem,
    pub datasets: Vec<AdminDatasetItem>,
    pub groups_with_access: Vec<String>,
    /// The newest `ensure_collection` operation of the collection: its state and error.
    /// Empty when none exists.
    #[serde(default)]
    pub provisioning_state: String,
    #[serde(default)]
    pub provisioning_error: String,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetItem {
    pub collection_dataset: String,
    pub dataset_name: String,
    pub dataset_display_name: String,
    pub dataset_type: String,
    pub dataset_path: String,
    pub date_created: String,
    /// The cached statistics, `None` until the pipeline writes the first row.
    #[serde(default)]
    pub stats: Option<crate::storage_tree::DatasetAggregates>,
    /// True when the dataset has `uploads_enabled`.
    #[serde(default)]
    pub accepts_uploads: bool,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetDetail {
    pub dataset: AdminDatasetItem,
    /// The owning collection. Fixed when the dataset is created. It can
    /// never be changed, so it is not optional: a dataset without a collection cannot
    /// exist any more.
    pub collectionname: String,
    pub stats: AdminDatasetStats,
    /// The cached statistics, `None` until the pipeline writes the first row.
    #[serde(default)]
    pub aggregates: Option<crate::storage_tree::DatasetAggregates>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetStats {
    pub blob_count: u64,
    pub vfs_file_count: u64,
    pub plans_total: u64,
    pub plans_finished: u64,
    pub error_count: u64,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ServerSettingItem {
    pub key: String,
    pub value: String,
}

// ---------------------------------------------------------------------------
// Per-dataset OCR settings, the apply operation, and dataset creation
// ---------------------------------------------------------------------------

/// The newest operation touching one dataset, as the dataset page's strip renders it.
///
/// A projection of the `operations` row, which is the one place a long run is recorded:
/// the strip and the admin operations log show the same run rather than two mechanisms
/// that can disagree. The strip exists because a form that disables itself while a run is
/// in flight locks forever if that run becomes invisible. `stale_seconds` is how long the
/// row has gone without an update: a running operation that has stopped advancing is the
/// failure that has no error message, so it needs a number of its own rather than an
/// absence of one.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetOperationStatus {
    pub op_id: String,
    pub kind: String,
    /// `pending | queued | running | finished | errored | cancelled`.
    pub state: String,
    /// JSON written by the workflow: `{"stage": …, "added": […], "removed": […]}`.
    pub detail: String,
    pub error: String,
    pub started_at: String,
    pub finished_at: String,
    pub stale_seconds: u64,
    #[serde(default)]
    pub progress_done: u64,
    #[serde(default)]
    pub progress_total: u64,
}

impl DatasetOperationStatus {
    /// `pending` and `queued` count as running: the row exists, it holds the lock, and
    /// the work is on its way to a worker. Treating it as idle is what would let a second
    /// dispatch through before the workflow starts its work.
    pub fn is_running(&self) -> bool {
        matches!(self.state.as_str(), "pending" | "queued" | "running")
    }
}

/// One `extracted_by` variant that currently exists in the dataset, with its size.
///
/// Shown next to the language form so an admin can see what removing a language would
/// actually delete before pressing Apply.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetTextVariant {
    pub extracted_by: String,
    pub page_count: u64,
}

/// One derived searchable-PDF variant, keyed exactly like its `pdf_ocr_results` row.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetPdfVariant {
    pub engine: String,
    pub languages: String,
    pub pdf_count: u64,
    pub total_bytes: u64,
}

/// The OCR languages of the dataset create form: the collection defaults that the form
/// starts with, and the languages that each service reports.
#[derive(Debug, Clone, PartialEq, Default, serde::Serialize, serde::Deserialize)]
pub struct CollectionOcrDefaults {
    /// `+`-joined, in the stored order.
    pub tesseract_languages: String,
    /// `+`-joined. Empty turns EasyOCR off.
    pub easyocr_languages: String,
    /// From the Tesseract `/health`. Empty when the service did not answer.
    pub tesseract_available: Vec<String>,
    /// From the EasyOCR `/health`. Empty when the service did not report them.
    pub easyocr_supported: Vec<String>,
    /// The EasyOCR languages whose models the image preloads.
    pub easyocr_preloaded: Vec<String>,
    /// Whether an EasyOCR endpoint is configured.
    pub easyocr_configured: bool,
}

/// Everything the dataset OCR panel renders, in one round trip.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetOcrPanel {
    pub collection_dataset: String,
    pub collectionname: String,
    /// `+`-joined, exactly as stored. Order is significant to Tesseract, so it is never
    /// normalised on the way through.
    pub tesseract_languages: String,
    pub easyocr_languages: String,
    /// Where each value comes from: `dataset`, `collection` or `installation`.
    #[serde(default)]
    pub tesseract_source: String,
    #[serde(default)]
    pub easyocr_source: String,
    /// The value that the dataset gets without its own row, and its source.
    #[serde(default)]
    pub inherited_tesseract: String,
    #[serde(default)]
    pub inherited_tesseract_source: String,
    #[serde(default)]
    pub inherited_easyocr: String,
    #[serde(default)]
    pub inherited_easyocr_source: String,
    /// The EasyOCR languages that the installed package supports, from the service.
    #[serde(default)]
    pub easyocr_supported: Vec<String>,
    /// The EasyOCR languages whose models the image preloads. Others download on first use.
    #[serde(default)]
    pub easyocr_preloaded: Vec<String>,
    /// First-use model downloads that failed, as `languages: error`.
    #[serde(default)]
    pub easyocr_failed_downloads: Vec<String>,
    /// What the Tesseract image can actually serve, read from its `/health` rather than
    /// from configuration. Empty when the tier did not answer. The form then says so
    /// instead of offering a list it cannot stand behind.
    pub tesseract_available: Vec<String>,
    /// Whether an EasyOCR endpoint is configured at all. False renders that half of the
    /// form disabled with the reason, rather than hiding it.
    pub easyocr_configured: bool,
    /// Whether searchable PDFs are produced at all (`ocr_pdf_enabled`).
    pub ocr_pdf_configured: bool,
    pub text_variants: Vec<DatasetTextVariant>,
    pub pdf_variants: Vec<DatasetPdfVariant>,
    pub operation: Option<DatasetOperationStatus>,
}

/// One configured dataset mount, for the creation form.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetMountOption {
    /// The section name of `[dataset_mount.<name>]`, or `testdata` for the inferred mount.
    pub name: String,
    /// The container path.
    pub path: String,
    /// True when the website may create folders in the mount. Always false for the
    /// inferred mount, which the website mounts read-only.
    pub writable: bool,
}

/// One candidate folder directly beneath a dataset mount, for the creation form.
///
/// The form offers names from this list and nothing else: a free-text path in a browser
/// form is a way to point the ingest walker at any directory the container can see.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetFolderOption {
    pub name: String,
    pub entry_count: u64,
    /// True when a dataset already exists for this folder in the chosen collection.
    pub already_used: bool,
}

/// The upload setting of one dataset, for the dataset page.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetUploadsSetting {
    /// True when the dataset is a disk dataset whose folder resolves beneath a writable
    /// mount of the running website. The page shows "Accept uploads" then, and while
    /// `enabled` is true.
    pub writable_mount: bool,
    /// The stored value of `uploads_enabled`.
    pub enabled: bool,
}
