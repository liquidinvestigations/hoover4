//! Shared search query models and helpers.

use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use crate::search_result::FacetOriginalValue;


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
#[serde(default)]
pub struct SearchQuery {
    pub collection_datasets: Vec<String>,
    pub query_string: String,
    pub facet_filters: BTreeMap<String, BTreeSet<FacetOriginalValue>>,
}