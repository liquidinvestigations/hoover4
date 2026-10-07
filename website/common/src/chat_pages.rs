//! References to captured web page text in chat tool results.

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ChatPageRef {
    pub handle: String,
    pub url: String,
    pub final_url: String,
    pub title: String,
    pub artifact_id: String,
    pub version: String,
    #[serde(default)]
    pub terms: Vec<String>,
    #[serde(default)]
    pub quotes: Vec<String>,
    pub quote_verified: bool,
}

#[derive(Debug, Clone, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct CapturedWebPage {
    pub url: String,
    pub final_url: String,
    pub title: String,
    pub version: String,
    pub markdown: String,
}

/// Split source text at exact term matches without changing Unicode byte boundaries.
pub fn exact_quote_parts(text: &str, terms: &[String]) -> Vec<(String, bool)> {
    let mut ranges = terms.iter().filter(|term| !term.is_empty())
        .flat_map(|term| text.match_indices(term).map(move |(start, found)| (start, start + found.len())))
        .collect::<Vec<_>>();
    ranges.sort_unstable();
    let mut merged: Vec<(usize, usize)> = Vec::new();
    for (start, end) in ranges {
        if let Some(last) = merged.last_mut().filter(|last| start <= last.1) {
            last.1 = last.1.max(end);
        } else { merged.push((start, end)); }
    }
    let mut parts = Vec::new();
    let mut offset = 0;
    for (start, end) in merged {
        if start > offset { parts.push((text[offset..start].to_string(), false)); }
        parts.push((text[start..end].to_string(), true));
        offset = end;
    }
    if offset < text.len() { parts.push((text[offset..].to_string(), false)); }
    parts
}

/// Read citation objects through the stored tool-result wrappers.
pub fn extract_page_refs(output: &str) -> Vec<ChatPageRef> {
    fn collect(value: &serde_json::Value, depth: usize, out: &mut Vec<ChatPageRef>) {
        if depth > 8 { return; }
        match value {
            serde_json::Value::String(text) => {
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(text) {
                    collect(&parsed, depth + 1, out);
                }
            }
            serde_json::Value::Array(items) => {
                for item in items { collect(item, depth + 1, out); }
            }
            serde_json::Value::Object(object) => {
                if object.contains_key("handle") {
                    if let Ok(page) = serde_json::from_value::<ChatPageRef>(value.clone()) {
                        let number = page.handle.strip_prefix("[W")
                            .and_then(|s| s.strip_suffix(']'))
                            .and_then(|s| s.parse::<u16>().ok());
                        if page.quote_verified && number.is_some_and(|n| (1..=200).contains(&n))
                            && !page.artifact_id.is_empty() && !page.version.is_empty()
                        {
                            out.push(page);
                        }
                    }
                }
                for key in ["output", "content", "text", "citations", "items", "structuredContent"] {
                    if let Some(child) = object.get(key) { collect(child, depth + 1, out); }
                }
            }
            _ => {}
        }
    }
    let mut out = Vec::new();
    if let Ok(value) = serde_json::from_str(output) { collect(&value, 0, &mut out); }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn overlapping_unicode_terms_keep_the_complete_source_text() {
        let source = "α Exact text. exact text.";
        let parts = exact_quote_parts(source, &["α Exact".into(), "Exact text".into()]);
        assert_eq!(parts.iter().map(|(text, _)| text.as_str()).collect::<String>(), source);
        assert_eq!(parts.iter().filter(|(_, marked)| *marked).collect::<Vec<_>>(), vec![&(String::from("α Exact text"), true)]);
    }

    #[test]
    fn nested_tool_text_keeps_verified_page_identity() {
        let reference = serde_json::json!({"handle":"[W1]", "url":"https://example.org/",
            "final_url":"https://example.org/", "title":"Example", "artifact_id":"source-id",
            "version":"text-version", "terms":["Exact text"], "quotes":["Exact text."],
            "quote_verified":true});
        let output = serde_json::json!({"output":{"content":serde_json::json!({"citations":[reference]}).to_string()}});
        let refs = extract_page_refs(&output.to_string());
        assert_eq!(refs.len(), 1);
        assert_eq!(refs[0].terms, vec!["Exact text"]);
        assert_eq!(refs[0].artifact_id, "source-id");
    }

    #[test]
    fn failed_or_incomplete_citations_do_not_create_cards() {
        assert!(extract_page_refs(r#"{"citations":[{"handle":"[W1]","error":"Unread page"}]}"#).is_empty());
    }
}
