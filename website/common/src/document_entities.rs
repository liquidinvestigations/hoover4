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
    /// Which NER models found this value, sorted and deduplicated.
    ///
    /// The pipeline runs more than one NER provider and more than one text variant per
    /// document, so the same name is found several times. The rows are aggregated by
    /// value rather than listed, because a panel that shows "Voronkov" four times reads as
    /// a bug — but *which* provider found it is real provenance and the reason this is a
    /// list rather than a count.
    #[serde(default)]
    pub providers: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DocumentEntitiesResponse {
    pub items: Vec<DocumentEntityItem>,
}
