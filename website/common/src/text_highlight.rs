//! Utilities for highlighting text spans in search results.

use serde::{Deserialize, Serialize};


#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct HighlightTextSpan {
    pub text: String,
    pub is_highlighted: bool,
    pub index: u64,
}