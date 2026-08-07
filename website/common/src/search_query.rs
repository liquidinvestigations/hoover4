//! Shared search query models and helpers.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::search_result::FacetOriginalValue;

/// `date_min`/`date_max` of a document with no confirmed historical date.
///
/// Manticore attributes are not nullable, so "unknown" needs a reserved value and
/// `i64::MIN` is the one no real date can collide with. A `BETWEEN` range can never
/// match it, so undated documents fall out of every range automatically; the UI's
/// "Unknown only" filters on equality with it. The Python indexer pins the same
/// constant in `database/manticore.py` — keep them in step.
pub const DATE_UNKNOWN: i64 = i64::MIN;

/// `file_size_bytes` of a document that exists in `file_types` but in no `vfs_files`
/// row. 0 is a legitimate size (an empty file), so it cannot double as "unknown", and
/// every size range excludes negatives.
pub const SIZE_UNKNOWN: i64 = -1;

/// A closed-open-ended numeric range over one indexed attribute.
///
/// Integers only, deliberately: these values are interpolated into Manticore SQL and an
/// `i64` has no injection surface at all. A string range would have needed quoting
/// rules, and quoting rules are where injection bugs live.
///
/// `include_unknown` is a separate flag rather than a magic bound because "documents
/// with no date" is a different question from "documents dated before X" — the sentinel
/// sorts below every real date, so a naive open-ended `max` would silently sweep every
/// undated document into "before 1900".
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct RangeFilter {
    pub min: Option<i64>,
    pub max: Option<i64>,
    /// Match documents whose value is the unknown sentinel. With no `min`/`max` this
    /// is "unknown only"; alongside a range it is "the range OR unknown".
    pub include_unknown: bool,
}

impl RangeFilter {
    /// Whether this filter would narrow anything. An all-default filter is dropped
    /// rather than turned into a tautological predicate.
    pub fn is_active(&self) -> bool {
        self.min.is_some() || self.max.is_some() || self.include_unknown
    }

    /// A range whose bounds cross is a user error the UI catches inline; if one gets
    /// through anyway it must not silently return everything.
    pub fn is_inverted(&self) -> bool {
        matches!((self.min, self.max), (Some(lo), Some(hi)) if lo > hi)
    }
}

/// What the result list is ordered by. Whitelisted as an enum rather than a column
/// name: the value ends up in an `ORDER BY` and the fan-out merge has to implement the
/// same order, so an open-ended string would be both an injection surface and a way to
/// desynchronise the two.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize, Default)]
pub enum SortKey {
    /// BM25 weight. Meaningless without a query string — enforced server-side.
    #[default]
    Relevance,
    /// `date_min` ascending / `date_max` descending: "oldest first" and "newest first"
    /// are questions about different ends of a document's date set.
    Date,
    FileSize,
    /// `primary_filename`, a string attribute (a text field would not be sortable).
    Name,
}

impl SortKey {
    pub const ALL: [SortKey; 4] = [
        SortKey::Relevance,
        SortKey::Date,
        SortKey::FileSize,
        SortKey::Name,
    ];

    /// The label the sort menu shows.
    pub fn label(&self) -> &'static str {
        match self {
            SortKey::Relevance => "Relevance",
            SortKey::Date => "Date",
            SortKey::FileSize => "File size",
            SortKey::Name => "Name",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct SortSpec {
    pub key: SortKey,
    pub desc: bool,
}

impl SortSpec {
    /// Relevance is not a valid order without something to be relevant to. Callers
    /// resolve the spec through this so the UI and the SQL builder cannot disagree.
    pub fn resolved(&self, query_string: &str) -> SortSpec {
        if self.key == SortKey::Relevance && query_string.trim().is_empty() {
            SortSpec { key: SortKey::Date, desc: true }
        } else {
            *self
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct SearchQuery {
    pub collection_datasets: Vec<String>,
    pub query_string: String,
    pub facet_filters: BTreeMap<String, BTreeSet<FacetOriginalValue>>,
    /// Numeric ranges keyed by indexed field name (`dates`, `file_size_bytes`).
    ///
    /// `#[serde(default)]`, like every field added after the first release: search URLs
    /// are bookmarkable CBOR blobs and an old one must keep decoding. ciborium writes
    /// structs as field-name maps, so a missing key takes the default rather than
    /// shifting every field after it.
    pub range_filters: BTreeMap<String, RangeFilter>,
    pub sort: SortSpec,
}

impl SearchQuery {
    /// Range filters that would actually narrow the result set, in a stable order.
    pub fn active_range_filters(&self) -> Vec<(&String, &RangeFilter)> {
        self.range_filters
            .iter()
            .filter(|(_, filter)| filter.is_active())
            .collect()
    }

    /// Whether anything at all is selected — used to decide between "no filters" and
    /// "these filters matched nothing".
    pub fn has_any_filter(&self) -> bool {
        self.facet_filters.values().any(|v| !v.is_empty())
            || !self.active_range_filters().is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn range_filter_activity_and_inversion() {
        assert!(!RangeFilter::default().is_active());
        assert!(RangeFilter { min: Some(1), ..Default::default() }.is_active());
        assert!(RangeFilter { include_unknown: true, ..Default::default() }.is_active());
        assert!(RangeFilter { min: Some(5), max: Some(1), include_unknown: false }.is_inverted());
        assert!(!RangeFilter { min: Some(1), max: Some(5), include_unknown: false }.is_inverted());
        assert!(!RangeFilter { min: Some(5), max: None, include_unknown: false }.is_inverted());
    }

    #[test]
    fn relevance_falls_back_without_a_query_string() {
        let relevance = SortSpec { key: SortKey::Relevance, desc: true };
        assert_eq!(relevance.resolved("word").key, SortKey::Relevance);
        assert_eq!(relevance.resolved("").key, SortKey::Date);
        assert_eq!(relevance.resolved("   ").key, SortKey::Date);
        // Any other key is left alone whether or not there is a query.
        let by_name = SortSpec { key: SortKey::Name, desc: false };
        assert_eq!(by_name.resolved("").key, SortKey::Name);
    }

    /// The bookmark-compatibility guarantee: a CBOR blob written by the build BEFORE
    /// `range_filters` and `sort` existed must still decode.
    ///
    /// The bytes below are `ciborium` output for the old three-field struct, captured
    /// from the pre-plan-3 shape. If this test fails, every bookmarked search URL in
    /// every user's browser has stopped working.
    #[test]
    fn a_pre_plan_3_query_still_decodes() {
        // {"collection_datasets": [], "query_string": "easychair", "facet_filters": {}}
        let old = serde_json::json!({
            "collection_datasets": [],
            "query_string": "easychair",
            "facet_filters": {},
        });
        let mut cbor = Vec::new();
        ciborium::into_writer(&old, &mut cbor).unwrap();
        let decoded: SearchQuery = ciborium::from_reader(std::io::Cursor::new(cbor)).unwrap();
        assert_eq!(decoded.query_string, "easychair");
        assert!(decoded.range_filters.is_empty());
        assert_eq!(decoded.sort, SortSpec::default());
    }

    #[test]
    fn a_current_query_round_trips() {
        let mut range_filters = BTreeMap::new();
        range_filters.insert(
            "dates".to_string(),
            RangeFilter { min: Some(-3786825600), max: Some(1370000000), include_unknown: true },
        );
        let query = SearchQuery {
            collection_datasets: vec!["testdata_testfiles".to_string()],
            query_string: "word".to_string(),
            facet_filters: BTreeMap::new(),
            range_filters,
            sort: SortSpec { key: SortKey::FileSize, desc: true },
        };
        let mut cbor = Vec::new();
        ciborium::into_writer(&query, &mut cbor).unwrap();
        let decoded: SearchQuery = ciborium::from_reader(std::io::Cursor::new(cbor)).unwrap();
        assert_eq!(decoded, query);
    }
}
