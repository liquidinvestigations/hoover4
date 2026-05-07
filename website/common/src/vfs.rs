//! Shared types for browsing the virtual file system.

use serde::{Deserialize, Serialize};

/// Identifies a folder or file location inside the VFS.
///
/// `path` is an absolute path within the logical VFS (root is `"/"`).
/// `container_hash` identifies the archive/email container that owns the
/// path (empty string means top-level VFS, no container).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct PathDescriptor {
    pub container_hash: String,
    pub path: String,
}

impl PathDescriptor {
    pub fn root() -> Self {
        Self {
            container_hash: String::new(),
            path: "/".to_string(),
        }
    }

    /// Returns a descriptor for the parent folder, keeping the container.
    /// The root folder's parent is itself.
    pub fn parent(&self) -> Self {
        let trimmed = self.path.trim_end_matches('/');
        let parent_path = if trimmed.is_empty() {
            "/".to_string()
        } else {
            match trimmed.rfind('/') {
                Some(0) | None => "/".to_string(),
                Some(idx) => trimmed[..idx].to_string(),
            }
        };
        Self {
            container_hash: self.container_hash.clone(),
            path: parent_path,
        }
    }
}

impl Default for PathDescriptor {
    fn default() -> Self {
        Self::root()
    }
}

impl std::fmt::Display for PathDescriptor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if self.container_hash.is_empty() {
            write!(f, "{}", self.path)
        } else {
            write!(f, "[{}]{}", self.container_hash, self.path)
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VfsDirectoryEntry {
    pub name: String,
    pub path: PathDescriptor,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VfsFileEntry {
    pub name: String,
    pub path: PathDescriptor,
    pub hash: String,
    pub file_size_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct VfsListing {
    pub collection_dataset: String,
    pub path: PathDescriptor,
    pub directories: Vec<VfsDirectoryEntry>,
    pub files: Vec<VfsFileEntry>,
}
