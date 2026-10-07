//! Utilities for highlighting text spans in search results.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct HighlightTextSpan {
    pub text: String,
    pub is_highlighted: bool,
    pub index: u64,
}

/// Match literal text without using folded UTF-8 offsets to slice the source.
pub fn case_insensitive_parts(text: &str, needle: &str) -> Vec<(String, bool)> {
    if needle.is_empty() {
        return vec![(text.to_string(), false)];
    }
    let mut folded = String::new();
    let mut original = Vec::new();
    for (start, character) in text.char_indices() {
        let lower: String = character.to_lowercase().collect();
        original.extend(std::iter::repeat_n((start, start + character.len_utf8()), lower.len()));
        folded.push_str(&lower);
    }
    let needle = needle.to_lowercase();
    let mut parts = Vec::new();
    let mut cursor = 0;
    for (offset, _) in folded.match_indices(&needle) {
        let start = original[offset].0;
        let end = original[offset + needle.len() - 1].1;
        if start < cursor {
            continue;
        }
        if start > cursor {
            parts.push((text[cursor..start].to_string(), false));
        }
        parts.push((text[start..end].to_string(), true));
        cursor = end;
    }
    if cursor < text.len() {
        parts.push((text[cursor..].to_string(), false));
    }
    parts
}

#[cfg(test)]
mod tests {
    use super::case_insensitive_parts;

    #[test]
    fn unicode_case_expansion_keeps_source_offsets() {
        assert_eq!(case_insensitive_parts("İstanbul Weed", "weed"),
                   vec![("İstanbul ".into(), false), ("Weed".into(), true)]);
        assert_eq!(case_insensitive_parts("Été été", "été"),
                   vec![("Été".into(), true), (" ".into(), false), ("été".into(), true)]);
        assert_eq!(case_insensitive_parts("İ", "i"), vec![("İ".into(), true)]);
    }
}
