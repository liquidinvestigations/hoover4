//! State definitions for the document viewer.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct DocViewerState {
    pub find_query: String,
    pub selected_text_extracted_by: Option<String>,
    pub selected_text_page: u32,
}

impl DocViewerState {
    pub fn from_find_query(find_query: String) -> Self {
        Self {
            find_query,
            selected_text_extracted_by: None,
            selected_text_page: 0,
        }
    }
}