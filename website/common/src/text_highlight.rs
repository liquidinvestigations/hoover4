//! Utilities for highlighting text spans in search results.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, PartialOrd)]
pub struct HighlightTextSpan {
    pub text: String,
    pub is_highlighted: bool,
    pub index: u64,
}

/// Byte ranges of the literal, case-insensitive matches of `needle` in `text`.
///
/// The ranges index `text` itself, never the folded copy: folding can change a
/// character's UTF-8 length, so a folded offset used on the source cuts the wrong bytes.
pub fn case_insensitive_ranges(text: &str, needle: &str) -> Vec<std::ops::Range<usize>> {
    if needle.is_empty() {
        return Vec::new();
    }
    let mut folded = String::new();
    let mut original = Vec::new();
    for (start, character) in text.char_indices() {
        let lower: String = character.to_lowercase().collect();
        original.extend(std::iter::repeat_n((start, start + character.len_utf8()), lower.len()));
        folded.push_str(&lower);
    }
    let needle = needle.to_lowercase();
    let mut ranges = Vec::new();
    let mut cursor = 0;
    for (offset, _) in folded.match_indices(&needle) {
        let start = original[offset].0;
        let end = original[offset + needle.len() - 1].1;
        if start < cursor {
            continue;
        }
        ranges.push(start..end);
        cursor = end;
    }
    ranges
}

/// Match literal text without using folded UTF-8 offsets to slice the source.
pub fn case_insensitive_parts(text: &str, needle: &str) -> Vec<(String, bool)> {
    if needle.is_empty() {
        return vec![(text.to_string(), false)];
    }
    let mut parts = Vec::new();
    let mut cursor = 0;
    for range in case_insensitive_ranges(text, needle) {
        if range.start > cursor {
            parts.push((text[cursor..range.start].to_string(), false));
        }
        parts.push((text[range.clone()].to_string(), true));
        cursor = range.end;
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
