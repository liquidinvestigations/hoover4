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
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminCollectionDetail {
    pub collection: AdminCollectionItem,
    pub datasets: Vec<AdminDatasetItem>,
    pub groups_with_access: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetItem {
    pub collection_dataset: String,
    pub dataset_name: String,
    pub dataset_display_name: String,
    pub dataset_type: String,
    pub dataset_path: String,
    pub date_created: String,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetDetail {
    pub dataset: AdminDatasetItem,
    /// The owning collection. Fixed when the dataset is created — it can
    /// never be changed, so it is not optional: a dataset without a collection cannot
    /// exist any more.
    pub collectionname: String,
    pub stats: AdminDatasetStats,
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
// Per-dataset OCR settings, the apply job, and dataset creation
// ---------------------------------------------------------------------------

/// One long-running admin job, as the dataset page's status strip renders it.
///
/// The strip exists because a form that disables itself while a job runs locks forever if
/// the job becomes invisible. `stale_seconds` is how long the row has gone without an
/// update: a `running` job that has stopped advancing is the failure that has no error
/// message, so it needs a number of its own rather than an absence of one.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetJobStatus {
    pub job_id: String,
    pub kind: String,
    /// `running | done | failed`.
    pub state: String,
    /// JSON written by the workflow: `{"stage": …, "added": […], "removed": […]}`.
    pub detail: String,
    pub error: String,
    pub started_at: String,
    pub finished_at: String,
    pub stale_seconds: u64,
}

impl DatasetJobStatus {
    pub fn is_running(&self) -> bool {
        self.state == "running"
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

/// Everything the dataset OCR panel renders, in one round trip.
#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct DatasetOcrPanel {
    pub collection_dataset: String,
    pub collectionname: String,
    /// `+`-joined, exactly as stored. Order is significant to Tesseract, so it is never
    /// normalised on the way through.
    pub tesseract_languages: String,
    pub easyocr_languages: String,
    /// What the Tesseract image can actually serve, read from its `/health` rather than
    /// from configuration. Empty when the tier did not answer — the form then says so
    /// instead of offering a list it cannot stand behind.
    pub tesseract_available: Vec<String>,
    /// Whether an EasyOCR endpoint is configured at all. False renders that half of the
    /// form disabled with the reason, rather than hiding it.
    pub easyocr_configured: bool,
    /// Whether searchable PDFs are produced at all (`ocr_pdf_enabled`).
    pub ocr_pdf_configured: bool,
    pub text_variants: Vec<DatasetTextVariant>,
    pub pdf_variants: Vec<DatasetPdfVariant>,
    pub job: Option<DatasetJobStatus>,
}

/// One candidate folder under `datasets_mount_path`, for the creation form.
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
