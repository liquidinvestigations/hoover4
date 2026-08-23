//! The collections > datasets skeleton that sits above the per-dataset VFS trees.
//!
//! VFS node keys are dataset-scoped by construction (`vfs::make_node_key`), so there is
//! no such thing as a cross-dataset tree in the structure index. The two levels above a
//! dataset (the collection and the dataset itself) are therefore composed from the
//! registry rather than fetched from the index, and these are the types that carry them.

use serde::{Deserialize, Serialize};

/// One dataset as the storage surfaces need it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DatasetSummary {
    /// The globally unique id, and the key every VFS call is scoped by.
    pub collection_dataset: String,
    pub collectionname: String,
    pub dataset_name: String,
    pub dataset_display_name: String,
}

impl DatasetSummary {
    /// What a tree row or a card says: the display name when an admin set one, the
    /// short name otherwise. Never the composed id. That is the tooltip's job.
    pub fn label(&self) -> &str {
        if self.dataset_display_name.is_empty() {
            &self.dataset_name
        } else {
            &self.dataset_display_name
        }
    }
}

/// One collection and the datasets in it the current user may read.
///
/// A collection with no readable datasets is not in the list at all: an expandable row
/// that expands to nothing is worse than an absent one.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct CollectionNode {
    pub collectionname: String,
    pub datasets: Vec<DatasetSummary>,
}

impl CollectionNode {
    pub fn dataset_ids(&self) -> Vec<String> {
        self.datasets
            .iter()
            .map(|d| d.collection_dataset.clone())
            .collect()
    }
}

/// Materialised per-dataset numbers for the collection landing page's cards.
///
/// Every field is something the pipeline already writes and something the admin pages
/// already count; nothing here is computed for the sake of a card.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DatasetAggregates {
    pub collection_dataset: String,
    /// Distinct blobs, which is the population every processing stage reports against.
    pub document_count: u64,
    pub total_size_bytes: u64,
    /// Documents that reached the search index (`index_state`).
    pub indexed_count: u64,
    pub error_count: u64,
}

/// A collection's datasets with their aggregates, in one response.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct CollectionOverview {
    pub collectionname: String,
    pub datasets: Vec<DatasetSummary>,
    pub aggregates: Vec<DatasetAggregates>,
}

impl CollectionOverview {
    pub fn aggregates_for(&self, collection_dataset: &str) -> Option<&DatasetAggregates> {
        self.aggregates
            .iter()
            .find(|a| a.collection_dataset == collection_dataset)
    }
}

/// Bytes as a short human string. Shared by the storage cards and the file listing so
/// two places on the same page cannot round differently.
pub fn format_size(bytes: u64) -> String {
    const KB: f64 = 1024.0;
    const MB: f64 = KB * 1024.0;
    const GB: f64 = MB * 1024.0;
    let b = bytes as f64;
    if b < KB {
        format!("{bytes} B")
    } else if b < MB {
        format!("{:.0} KB", b / KB)
    } else if b < GB {
        format!("{:.1} MB", b / MB)
    } else {
        format!("{:.2} GB", b / GB)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_dataset_falls_back_to_its_short_name() {
        let mut dataset = DatasetSummary {
            collection_dataset: "testdata_shapes".to_string(),
            collectionname: "testdata".to_string(),
            dataset_name: "shapes".to_string(),
            dataset_display_name: String::new(),
        };
        assert_eq!(dataset.label(), "shapes");
        dataset.dataset_display_name = "Shapes fixture".to_string();
        assert_eq!(dataset.label(), "Shapes fixture");
    }

    #[test]
    fn sizes_round_the_way_the_listing_rounds() {
        assert_eq!(format_size(0), "0 B");
        assert_eq!(format_size(1023), "1023 B");
        assert_eq!(format_size(1024), "1 KB");
        assert_eq!(format_size(1024 * 1024), "1.0 MB");
    }
}
