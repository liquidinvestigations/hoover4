//! Indexed word counts and checked spelling candidates.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct WordCount {
    pub word: String,
    pub folded: String,
    pub documents: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SpellingCandidate {
    pub word: String,
    pub distance: u32,
    pub documents: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct WordSuggestions {
    pub word: String,
    pub candidates: Vec<SpellingCandidate>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SuggestedQuery {
    pub query: String,
    pub count: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SearchSuggestions {
    pub word_counts: Vec<WordCount>,
    pub suggestions: Vec<WordSuggestions>,
    #[serde(default)]
    pub queries: Vec<SuggestedQuery>,
    #[serde(default)]
    pub partial: bool,
}
