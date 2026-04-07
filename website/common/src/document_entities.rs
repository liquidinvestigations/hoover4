//! Shared per-document entity models (for document viewer).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Hash, PartialOrd, Ord)]
pub enum DocumentEntityType {
    Per,
    Org,
    Loc,
    Misc,
    Unknown,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Hash, PartialOrd, Ord)]
pub struct DocumentEntityItem {
    pub entity_type: DocumentEntityType,
    pub value: String,
    pub hit_count: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocumentEntitiesResponse {
    pub items: Vec<DocumentEntityItem>,
}

