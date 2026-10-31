//! The collections > datasets skeleton that sits above the per-dataset VFS trees.
//!
//! VFS node keys are dataset-scoped by construction (`vfs::make_node_key`), so there is
//! no such thing as a cross-dataset tree in the structure index. The two levels above a
//! dataset (the collection and the dataset itself) are therefore composed from the
//! registry rather than fetched from the index, and these are the types that carry them.

use serde::{Deserialize, Serialize};

/// The dataset id the pipeline composes: `<collectionname>_<dataset_name>`.
///
/// Mirrors `compose_collection_dataset` in `tasks/P0_scan_disk/submit_job.py`. Never split
/// it to recover the collection. A dataset name may contain `_`, so resolve the collection
/// through the `dataset` table instead.
pub fn compose_collection_dataset(collectionname: &str, dataset_name: &str) -> String {
    format!("{collectionname}_{dataset_name}")
}

/// The identifier that a collection or dataset name field saves.
///
/// It trims the text, lowercases it, and changes each `-`, space and `.` to `_`. The
/// backend derives a dataset name from a folder name with the same rule. Different
/// inputs can give one identifier (`a-b`, `a.b` and `a b` give `a_b`), so a form shows
/// the result and refuses an identifier that already exists. The result can still be
/// invalid, for example with other punctuation, and the server refuses it.
pub fn normalize_identifier(raw: &str) -> String {
    raw.trim()
        .to_lowercase()
        .chars()
        .map(|c| if matches!(c, '-' | ' ' | '.') { '_' } else { c })
        .collect()
}

/// One dataset as the storage surfaces need it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DatasetSummary {
    /// The globally unique id, and the key every VFS call is scoped by.
    pub collection_dataset: String,
    pub collectionname: String,
    pub dataset_name: String,
    pub dataset_display_name: String,
    /// Whether the dataset root has a directory or a container child in the structure index.
    /// The storage tree uses this to reserve no disclosure control for a leaf dataset.
    #[serde(default)]
    pub has_folder_children: bool,
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

/// The cached statistics of one dataset, read from the `dataset_stats` table.
///
/// The pipeline writes that table when an operation starts and ends, and while a
/// collection is processing. A dataset with no row has no `DatasetAggregates` at all, so
/// a reader shows it as not counted yet rather than as zero.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DatasetAggregates {
    pub collection_dataset: String,
    /// Distinct blobs, which is the population every processing stage reports against.
    /// Files extracted from emails and archives count as documents.
    pub document_count: u64,
    /// One size for each distinct blob, summed.
    pub total_size_bytes: u64,
    /// Documents of `document_count` that reached the search index (`index_state`).
    pub indexed_count: u64,
    /// Distinct document and task pairs with a processing error.
    pub error_count: u64,
    /// Documents of `document_count` with at least one processing error. Errors of the
    /// whole dataset, which name no document, are not in it.
    #[serde(default)]
    pub error_document_count: u64,
    /// False for a row that the pipeline counted before it counted error documents. The
    /// card then shows no error share until the next count.
    #[serde(default)]
    pub error_documents_counted: bool,
    /// The date of the count, `YYYY-MM-DD` in UTC. It says when the pipeline counted the
    /// numbers, not when files changed. Empty when the row has no count date.
    #[serde(default)]
    pub updated_on: String,
    /// True while a live operation holds the dataset. A finished, failed or cancelled
    /// operation does not, so permanently failed work reads as done.
    #[serde(default)]
    pub processing: bool,
}

/// The summed statistics of one collection's readable datasets.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct CollectionAggregates {
    pub collectionname: String,
    /// Readable datasets in the collection.
    pub dataset_count: u64,
    /// Readable datasets that have a statistics row. The sums cover only these.
    pub counted_dataset_count: u64,
    pub document_count: u64,
    pub total_size_bytes: u64,
    pub indexed_count: u64,
    pub error_count: u64,
    #[serde(default)]
    pub error_document_count: u64,
    /// True when every counted dataset has an error document count.
    #[serde(default)]
    pub error_documents_counted: bool,
    /// The latest count date of the counted datasets, `YYYY-MM-DD`.
    #[serde(default)]
    pub updated_on: String,
    /// True when one of the counted datasets is processing.
    pub processing: bool,
}

impl CollectionAggregates {
    /// Sum the statistics of `datasets`, which are the readable datasets of one collection.
    pub fn sum(collectionname: &str, dataset_count: u64, datasets: &[&DatasetAggregates]) -> Self {
        let mut total = CollectionAggregates {
            collectionname: collectionname.to_string(),
            dataset_count,
            error_documents_counted: true,
            ..Default::default()
        };
        for dataset in datasets {
            total.counted_dataset_count += 1;
            total.document_count += dataset.document_count;
            total.total_size_bytes += dataset.total_size_bytes;
            total.indexed_count += dataset.indexed_count;
            total.error_count += dataset.error_count;
            total.error_document_count += dataset.error_document_count;
            total.error_documents_counted &= dataset.error_documents_counted;
            if dataset.updated_on > total.updated_on {
                total.updated_on = dataset.updated_on.clone();
            }
            total.processing |= dataset.processing;
        }
        total
    }

    /// The summed numbers in the shape of one dataset row, for a storage card.
    pub fn as_dataset_aggregates(&self) -> DatasetAggregates {
        DatasetAggregates {
            collection_dataset: String::new(),
            document_count: self.document_count,
            total_size_bytes: self.total_size_bytes,
            indexed_count: self.indexed_count,
            error_count: self.error_count,
            error_document_count: self.error_document_count,
            error_documents_counted: self.error_documents_counted,
            updated_on: self.updated_on.clone(),
            processing: self.processing,
        }
    }

    /// Whether every dataset is counted.
    pub fn is_complete(&self) -> bool {
        self.counted_dataset_count == self.dataset_count
    }
}

/// The processing state as the interface shows it.
pub fn state_label(processing: bool) -> &'static str {
    if processing { "Processing" } else { "Done" }
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

/// `part` as a percentage of `documents`, with one decimal, for a storage card.
///
/// A collection passes summed counts, so a large dataset weighs more than a small one.
/// Zero documents give `0%`. A part above the whole gives `100%`. The pipeline counts
/// both numbers over one document population, so that case means a count that ran while
/// documents changed. Indexed documents can also have errors, so two shares of one card
/// can add up to more than 100%.
pub fn percent_of(part: u64, documents: u64) -> String {
    if documents == 0 {
        return "0%".to_string();
    }
    let share = (part.min(documents) as f64) * 100.0 / documents as f64;
    let text = format!("{share:.1}");
    format!("{}%", text.strip_suffix(".0").unwrap_or(&text))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn percentages_round_to_one_decimal_and_stop_at_the_whole() {
        assert_eq!(percent_of(0, 0), "0%");
        assert_eq!(percent_of(5, 0), "0%");
        assert_eq!(percent_of(0, 7), "0%");
        assert_eq!(percent_of(7, 7), "100%");
        assert_eq!(percent_of(1, 3), "33.3%");
        assert_eq!(percent_of(2, 3), "66.7%");
        assert_eq!(percent_of(1, 2), "50%");
        assert_eq!(percent_of(9, 7), "100%");
        assert_eq!(percent_of(1, 1000), "0.1%");
        assert_eq!(percent_of(1, 100_000), "0%");
    }

    #[test]
    fn a_collection_share_uses_summed_counts() {
        let small = DatasetAggregates {
            collection_dataset: "c_small".into(),
            document_count: 10,
            error_document_count: 10,
            error_documents_counted: true,
            updated_on: "2026-10-30".into(),
            ..Default::default()
        };
        let large = DatasetAggregates {
            collection_dataset: "c_large".into(),
            document_count: 990,
            error_document_count: 0,
            error_documents_counted: true,
            updated_on: "2026-10-31".into(),
            ..Default::default()
        };
        let total = CollectionAggregates::sum("c", 2, &[&small, &large]);
        // The average of the two dataset shares would be 50%.
        assert_eq!(percent_of(total.error_document_count, total.document_count), "1%");
        assert_eq!(total.updated_on, "2026-10-31");
        assert!(total.error_documents_counted);
        let old = DatasetAggregates { collection_dataset: "c_old".into(), ..Default::default() };
        assert!(!CollectionAggregates::sum("c", 3, &[&small, &large, &old]).error_documents_counted);
    }

    #[test]
    fn identifiers_change_separators_to_underscores() {
        assert_eq!(normalize_identifier(" P73-Test.Col "), "p73_test_col");
        assert_eq!(normalize_identifier("a b"), "a_b");
        assert_eq!(normalize_identifier("a-b"), normalize_identifier("a.b"));
        assert_eq!(normalize_identifier("under_score"), "under_score");
    }

    #[test]
    fn a_dataset_falls_back_to_its_short_name() {
        let mut dataset = DatasetSummary {
            collection_dataset: "testdata_shapes".to_string(),
            collectionname: "testdata".to_string(),
            dataset_name: "shapes".to_string(),
            dataset_display_name: String::new(),
            has_folder_children: false,
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
