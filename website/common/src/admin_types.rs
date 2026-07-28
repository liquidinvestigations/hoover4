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
    /// The owning collection. Fixed when the dataset is created (decision D1) — it can
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
