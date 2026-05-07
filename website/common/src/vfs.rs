//! Shared types for browsing the virtual file system.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VfsDirectoryEntry {
    pub name: String,
    pub path: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VfsFileEntry {
    pub name: String,
    pub path: String,
    pub hash: String,
    pub file_size_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct VfsListing {
    pub collection_dataset: String,
    pub path: String,
    pub directories: Vec<VfsDirectoryEntry>,
    pub files: Vec<VfsFileEntry>,
}
