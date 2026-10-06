//! Shared language names and stored signal evidence.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::OnceLock;

pub fn language_names() -> &'static BTreeMap<String, String> {
    static NAMES: OnceLock<BTreeMap<String, String>> = OnceLock::new();
    NAMES.get_or_init(|| {
        serde_json::from_str(include_str!("language_names.json")).expect("language names")
    })
}

pub fn language_name(code: &str) -> String {
    language_names()
        .get(code)
        .cloned()
        .unwrap_or_else(|| code.to_string())
}

pub fn language_code(value: &str) -> Option<String> {
    language_names()
        .iter()
        .find(|(code, name)| {
            code.eq_ignore_ascii_case(value.trim()) || name.eq_ignore_ascii_case(value.trim())
        })
        .map(|(code, _)| code.clone())
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SignalCategory {
    pub id: String,
    pub title: String,
    pub catches: String,
    pub does_not_prove: String,
    pub points: BTreeMap<String, f64>,
    pub threshold: f64,
    pub min_concepts: u64,
    pub l_cap: f64,
    pub low_recall: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SignalTerm {
    pub category: String,
    pub term: String,
    pub concept: String,
    pub lang: String,
    pub tier: String,
    pub speaker: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SignalCatalog {
    pub signal_set_version: String,
    pub categories: Vec<SignalCategory>,
    pub terms: Vec<SignalTerm>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SignalCluster {
    pub category: String,
    pub extracted_by: String,
    pub page_id: u32,
    pub points: f64,
    pub excerpt: String,
    pub hit_starts: Vec<u32>,
    pub hit_ends: Vec<u32>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct OtherSignalHit {
    pub category: String,
    pub extracted_by: String,
    pub page_id: u32,
    pub text: String,
    pub flags: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocumentSignals {
    pub clusters: Vec<SignalCluster>,
    pub other_hits: Vec<OtherSignalHit>,
}
