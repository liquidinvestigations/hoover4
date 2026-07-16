//! Admin API DTOs shared between frontend and backend.

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminUserItem {
    pub username: String,
    pub fullname: String,
    pub email: String,
    pub is_admin: bool,
    pub created_at: String,
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
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminCollectionDetail {
    pub collection: AdminCollectionItem,
    pub datasets: Vec<AdminDatasetItem>,
    pub groups_with_access: Vec<String>,
    pub unassigned_datasets: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetItem {
    pub collection_dataset: String,
    pub dataset_name: String,
    pub dataset_type: String,
    pub dataset_path: String,
    pub date_created: String,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct AdminDatasetDetail {
    pub dataset: AdminDatasetItem,
    pub collectionname: Option<String>,
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
