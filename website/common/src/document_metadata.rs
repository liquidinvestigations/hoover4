//! Shared document metadata models.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Hash, Eq, PartialOrd, Ord)]
pub struct DocumentMetadataTableInfo {
    pub table_name: String,
    pub hash_column_name: String,
    pub json_columns: Vec<String>,
}

impl DocumentMetadataTableInfo {
    pub fn new(table_name: impl Into<String>, hash_column_name: impl Into<String>) -> Self {
        Self { table_name: table_name.into(), hash_column_name: hash_column_name.into(), json_columns: vec![] }
    }
    pub fn new3(table_name: impl Into<String>, hash_column_name: impl Into<String>, json_columns: Vec<impl Into<String>>) -> Self {
        Self { table_name: table_name.into(), hash_column_name: hash_column_name.into(), json_columns: json_columns.into_iter().map(|s| s.into()).collect() }
    }
}