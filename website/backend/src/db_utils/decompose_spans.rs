//! Helpers for decomposing highlight spans.

use common::text_highlight::HighlightTextSpan;

const START_TAG: &str = "<hoover4_strong>";
const END_TAG: &str = "</hoover4_strong>";

pub fn decompose_text_into_spans(text: String) -> Vec<HighlightTextSpan> {
    let mut v = _do_decompose_text_into_spans(text);
    let mut index = 0;
    for item in v.iter_mut() {
        if item.is_highlighted {
            item.index = index;
            index += 1;
        }
    }
    v
}

fn _do_decompose_text_into_spans(text: String) -> Vec<HighlightTextSpan> {
    let text = text.replace("���", "�");
    let text = text.replace("��", "�");
    // let text = text.replace("\n", " ");
    let text = text.replace("  ", " ");
    let text = text.trim().to_string();
    if text.is_empty() {
        return vec![];
    }
    // Fast-path: if there is no opening <strong>, we don't attempt to parse.
    // Return a single non-highlighted span with the original text (preserving any stray closers).
    if !text.contains(START_TAG) {
        return vec![HighlightTextSpan {
            text,
            is_highlighted: false,
            index: 0,
        }];
    }

    let input = text;
    let mut spans: Vec<HighlightTextSpan> = Vec::new();
    let mut buffer = String::new(); // accumulates plain text between tags
    let mut strong_depth: usize = 0; // supports nested <strong> safely
    let mut i: usize = 0;
    let s = input.as_str();

    // Helper to flush the current buffer into a span, merging with the previous span
    // if it shares the same highlight state to avoid tiny adjacent spans.
    let flush_buffer =
        |spans: &mut Vec<HighlightTextSpan>, buffer: &mut String, highlighted: bool| {
            if buffer.is_empty() {
                return;
            }
            if let Some(last) = spans.last_mut()
                && last.is_highlighted == highlighted
            {
                last.text.push_str(buffer);
                buffer.clear();
                return;
            }
            spans.push(HighlightTextSpan {
                text: std::mem::take(buffer),
                is_highlighted: highlighted,
                index: 0,
            });
        };

    // Scan for the next tag, always consuming the nearest of START_TAG or END_TAG
    while i < s.len() {
        let next_open = s[i..].find(START_TAG).map(|p| p + i);
        let next_close = s[i..].find(END_TAG).map(|p| p + i);

        let next = match (next_open, next_close) {
            (None, None) => break, // no more tags
            (Some(op), None) => (START_TAG, op),
            (None, Some(cp)) => (END_TAG, cp),
            (Some(op), Some(cp)) => {
                if op < cp {
                    (START_TAG, op)
                } else {
                    (END_TAG, cp)
                }
            }
        };

        let (tag, pos) = next;

        // Add the text before the tag to the buffer
        buffer.push_str(&s[i..pos]);
        // Emit a span for the accumulated text under the current highlight state
        flush_buffer(&mut spans, &mut buffer, strong_depth > 0);

        // Consume the tag and update state
        if tag == START_TAG {
            // Opening tag: enter (or deepen) highlighted section
            strong_depth = strong_depth.saturating_add(1);
            i = pos + START_TAG.len();
        } else {
            // Closing tag:
            if strong_depth > 0 {
                // Valid close: step out of highlighted section
                strong_depth -= 1;
                i = pos + END_TAG.len();
            } else {
                // Edge case: stray closing tag with no matching open.
                // Treat it as literal text to preserve original content fidelity.
                buffer.push_str(END_TAG);
                i = pos + END_TAG.len();
            }
        }
    }

    // Append any trailing text after the last tag
    if i < s.len() {
        buffer.push_str(&s[i..]);
    }
    // If there were unmatched opening tags (depth > 0), remaining text is highlighted.
    // If depth == 0, it's non-highlighted.
    flush_buffer(&mut spans, &mut buffer, strong_depth > 0);

    spans
}

#[cfg(test)]
mod tests {
    use super::*;

    fn spans_of(text: &str) -> Vec<(String, bool, u64)> {
        decompose_text_into_spans(text.to_string())
            .into_iter()
            .map(|s| (s.text, s.is_highlighted, s.index))
            .collect()
    }

    #[test]
    fn empty_input_yields_no_spans() {
        assert_eq!(spans_of(""), vec![]);
        assert_eq!(spans_of("   "), vec![]);
    }

    #[test]
    fn plain_text_without_tags_is_single_plain_span() {
        assert_eq!(
            spans_of("hello world"),
            vec![("hello world".to_string(), false, 0)]
        );
    }

    #[test]
    fn stray_closing_tag_is_preserved_as_literal_text() {
        assert_eq!(
            spans_of("a </hoover4_strong> b"),
            vec![("a </hoover4_strong> b".to_string(), false, 0)]
        );
    }

    #[test]
    fn single_highlight_splits_into_three_spans() {
        assert_eq!(
            spans_of("before <hoover4_strong>hit</hoover4_strong> after"),
            vec![
                ("before ".to_string(), false, 0),
                ("hit".to_string(), true, 0),
                (" after".to_string(), false, 0),
            ]
        );
    }

    #[test]
    fn highlight_indices_increment_across_spans() {
        let spans = decompose_text_into_spans(
            "<hoover4_strong>one</hoover4_strong> mid <hoover4_strong>two</hoover4_strong>"
                .to_string(),
        );
        let highlighted: Vec<u64> = spans
            .iter()
            .filter(|s| s.is_highlighted)
            .map(|s| s.index)
            .collect();
        assert_eq!(highlighted, vec![0, 1]);
    }

    #[test]
    fn nested_open_tags_keep_text_highlighted_until_all_closed() {
        assert_eq!(
            spans_of(
                "<hoover4_strong>a <hoover4_strong>b</hoover4_strong> c</hoover4_strong> d"
            ),
            vec![
                ("a b c".to_string(), true, 0),
                (" d".to_string(), false, 0),
            ]
        );
    }

    #[test]
    fn unmatched_open_tag_highlights_trailing_text() {
        assert_eq!(
            spans_of("x <hoover4_strong>rest"),
            vec![
                ("x ".to_string(), false, 0),
                ("rest".to_string(), true, 0),
            ]
        );
    }

    #[test]
    fn adjacent_spans_with_same_state_are_merged() {
        // A close immediately followed by an open must not split the highlight run.
        assert_eq!(
            spans_of(
                "<hoover4_strong>a</hoover4_strong><hoover4_strong>b</hoover4_strong>"
            ),
            vec![("ab".to_string(), true, 0)]
        );
    }
}
