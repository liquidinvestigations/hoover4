//! The inline excerpt of one table cell.
//!
//! The grid draws at most [`CELL_EXCERPT_LINES`] lines of a cell, each at most
//! [`CELL_LINE_COLUMNS`] display columns wide, around the first match of the find text.
//! The excerpt is presentation only. Row selection, sorting, filters and the full-cell
//! view all read the raw stored value.
//!
//! Widths are display columns, not characters. The grid renders cell text in a monospaced
//! font at `80ch`, where a CJK character takes two columns and a combining mark none. A
//! character count would let the browser wrap one engine line into two, and the five-line
//! CSS limit would then hide the lower half of the excerpt, where the match is.

use serde::{Deserialize, Serialize};
use std::ops::Range;

use crate::text_highlight::case_insensitive_ranges;

/// Most display columns on one excerpt line, omission markers included.
pub const CELL_LINE_COLUMNS: usize = 80;

/// Most lines one inline excerpt shows.
pub const CELL_EXCERPT_LINES: usize = 5;

/// Wrapped lines of the full value from which the grid offers the full-cell view.
pub const CELL_EXPAND_LINES: u32 = 3;

const OMISSION: &str = "\u{2026}";

/// The excerpt the grid draws for one cell.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct TableCellPreview {
    /// At most [`CELL_EXCERPT_LINES`] lines. Each line is its pieces, `true` for a match.
    /// The omission markers are part of the first and last line's text.
    pub lines: Vec<Vec<(String, bool)>>,
    /// Lines of the whole value after wrapping. Greater than the line count of
    /// [`Self::lines`] exactly when the excerpt omits content.
    pub line_count: u32,
}

impl TableCellPreview {
    /// Whether the grid offers the full-cell view for this value.
    pub fn offers_full_view(&self) -> bool {
        self.line_count >= CELL_EXPAND_LINES
    }
}

/// Display columns of one character in a monospaced font.
pub fn display_width(character: char) -> usize {
    let code = character as u32;
    if is_zero_width(code) {
        0
    } else if is_wide(code) {
        2
    } else {
        1
    }
}

fn is_zero_width(code: u32) -> bool {
    matches!(code,
        0x0000..=0x001F | 0x007F..=0x009F | 0x00AD
        | 0x0300..=0x036F | 0x0483..=0x0489 | 0x0591..=0x05BD | 0x05BF | 0x05C1..=0x05C2
        | 0x05C4..=0x05C5 | 0x05C7 | 0x0610..=0x061A | 0x064B..=0x065F | 0x0670
        | 0x06D6..=0x06DC | 0x06DF..=0x06E4 | 0x06E7..=0x06E8 | 0x06EA..=0x06ED
        | 0x0900..=0x0902 | 0x093A | 0x093C | 0x0941..=0x0948 | 0x094D | 0x0951..=0x0957
        | 0x0E31 | 0x0E34..=0x0E3A | 0x0E47..=0x0E4E
        | 0x1160..=0x11FF | 0x1AB0..=0x1AFF | 0x1DC0..=0x1DFF
        | 0x200B..=0x200F | 0x202A..=0x202E | 0x2060..=0x2064 | 0x20D0..=0x20FF
        | 0xFE00..=0xFE0F | 0xFE20..=0xFE2F | 0xFEFF
        | 0x1F3FB..=0x1F3FF | 0xE0000..=0xE007F | 0xE0100..=0xE01EF)
}

fn is_wide(code: u32) -> bool {
    matches!(code,
        0x1100..=0x115F | 0x231A..=0x231B | 0x2329..=0x232A | 0x23E9..=0x23EC | 0x23F0 | 0x23F3
        | 0x25FD..=0x25FE | 0x2614..=0x2615 | 0x2648..=0x2653 | 0x267F | 0x2693 | 0x26A1
        | 0x26AA..=0x26AB | 0x26BD..=0x26BE | 0x26C4..=0x26C5 | 0x26CE | 0x26D4 | 0x26EA
        | 0x26F2..=0x26F3 | 0x26F5 | 0x26FA | 0x26FD | 0x2705 | 0x270A..=0x270B | 0x2728
        | 0x274C | 0x274E | 0x2753..=0x2755 | 0x2757 | 0x2795..=0x2797 | 0x27B0 | 0x27BF
        | 0x2B1B..=0x2B1C | 0x2B50 | 0x2B55
        | 0x2E80..=0x303E | 0x3041..=0x33FF | 0x3400..=0x4DBF | 0x4E00..=0x9FFF
        | 0xA000..=0xA4CF | 0xA960..=0xA97F | 0xAC00..=0xD7A3 | 0xF900..=0xFAFF
        | 0xFE10..=0xFE19 | 0xFE30..=0xFE6F | 0xFF00..=0xFF60 | 0xFFE0..=0xFFE6
        | 0x16FE0..=0x16FE4 | 0x17000..=0x18CFF | 0x1B000..=0x1B2FF
        | 0x1F004 | 0x1F0CF | 0x1F18E | 0x1F191..=0x1F19A | 0x1F200..=0x1F251
        | 0x1F300..=0x1F320 | 0x1F32D..=0x1F335 | 0x1F337..=0x1F37C | 0x1F37E..=0x1F393
        | 0x1F3A0..=0x1F3CA | 0x1F3CF..=0x1F3D3 | 0x1F3E0..=0x1F3F0 | 0x1F3F4 | 0x1F3F8..=0x1F3FA
        | 0x1F400..=0x1F43E | 0x1F440 | 0x1F442..=0x1F4FC | 0x1F4FF..=0x1F53D
        | 0x1F54B..=0x1F54E | 0x1F550..=0x1F567 | 0x1F57A | 0x1F595..=0x1F596 | 0x1F5A4
        | 0x1F5FB..=0x1F64F | 0x1F680..=0x1F6C5 | 0x1F6CC | 0x1F6D0..=0x1F6D2
        | 0x1F6D5..=0x1F6D7 | 0x1F6DC..=0x1F6DF | 0x1F6EB..=0x1F6EC | 0x1F6F4..=0x1F6FC
        | 0x1F7E0..=0x1F7EB | 0x1F7F0 | 0x1F90C..=0x1F93A | 0x1F93C..=0x1F945
        | 0x1F947..=0x1F9FF | 0x1FA70..=0x1FAFF
        | 0x20000..=0x2FFFD | 0x30000..=0x3FFFD)
}

fn width_of(text: &str) -> usize {
    text.chars().map(display_width).sum()
}

/// Line breaks and tabs as the grid draws them. A tab would render eight columns wide in
/// `pre-wrap`, and a lone carriage return has no agreed rendering, so both are replaced
/// before any column is counted.
fn normalise(text: &str) -> String {
    text.replace("\r\n", "\n").replace(['\r'], "\n").replace('\t', " ")
}

/// Wrap `text` into byte ranges of at most [`CELL_LINE_COLUMNS`] columns.
///
/// Each explicit line break ends a line. Inside a paragraph, words wrap at spaces and the
/// space at a wrap point is dropped. A word wider than the limit splits at a character
/// boundary. A zero-width character never starts a line, so a combining mark stays with
/// the character it modifies.
fn wrap(text: &str) -> Vec<Range<usize>> {
    let mut lines = Vec::new();
    let mut paragraph_start = 0;
    for paragraph in text.split('\n') {
        let base = paragraph_start;
        paragraph_start += paragraph.len() + 1;
        let mut line_start = base;
        let mut width = 0;
        // The end of the line before the last space, and the start of the word after it.
        let mut last_break: Option<(usize, usize)> = None;
        for (offset, character) in paragraph.char_indices() {
            let at = base + offset;
            let columns = display_width(character);
            if character == ' ' {
                if width + 1 > CELL_LINE_COLUMNS {
                    lines.push(line_start..at);
                    line_start = at + 1;
                    width = 0;
                    last_break = None;
                } else {
                    width += 1;
                    last_break = Some((at, at + 1));
                }
                continue;
            }
            if width + columns > CELL_LINE_COLUMNS {
                match last_break {
                    Some((end, next)) if next > line_start => {
                        lines.push(line_start..end);
                        line_start = next;
                        width = width_of(&text[next..at]);
                        last_break = None;
                        if width + columns > CELL_LINE_COLUMNS {
                            lines.push(line_start..at);
                            line_start = at;
                            width = 0;
                        }
                    }
                    _ => {
                        lines.push(line_start..at);
                        line_start = at;
                        width = 0;
                        last_break = None;
                    }
                }
            }
            width += columns;
        }
        lines.push(line_start..base + paragraph.len());
    }
    lines
}

/// The pieces of one line, with every match range marked.
fn pieces(text: &str, line: &Range<usize>, matches: &[Range<usize>]) -> Vec<(String, bool)> {
    let mut out = Vec::new();
    let mut cursor = line.start;
    for found in matches {
        let start = found.start.max(line.start);
        let end = found.end.min(line.end);
        if start >= end {
            continue;
        }
        if start > cursor {
            out.push((text[cursor..start].to_string(), false));
        }
        out.push((text[start..end].to_string(), true));
        cursor = end;
    }
    if cursor < line.end {
        out.push((text[cursor..line.end].to_string(), false));
    }
    out
}

/// Remove `columns` display columns from the start (`from_start`) or end of a line.
fn trim_columns(line: &mut Vec<(String, bool)>, mut columns: usize, from_start: bool) {
    while columns > 0 && !line.is_empty() {
        let index = if from_start { 0 } else { line.len() - 1 };
        let piece = &mut line[index].0;
        let character = if from_start { piece.chars().next() } else { piece.chars().next_back() };
        let Some(character) = character else {
            line.remove(index);
            continue;
        };
        if from_start {
            piece.drain(..character.len_utf8());
        } else {
            piece.pop();
        }
        columns = columns.saturating_sub(display_width(character));
        if piece.is_empty() {
            line.remove(index);
        }
    }
}

fn line_width(line: &[(String, bool)]) -> usize {
    line.iter().map(|(text, _)| width_of(text)).sum()
}

/// Build the inline excerpt of `text` around the first match of `needle`.
///
/// `needle` is the find text after [`crate::document_tables::table_find_text`]. Matches
/// are found in the whole value before it is wrapped, so a phrase across a wrap point
/// stays marked on both lines.
pub fn cell_preview(text: &str, needle: &str) -> TableCellPreview {
    let text = normalise(text);
    let matches = case_insensitive_ranges(&text, needle);
    let lines = wrap(&text);
    let total = lines.len();
    let first = matches
        .first()
        .and_then(|found| lines.iter().position(|line| line.end > found.start))
        .unwrap_or(0);
    let start = if total <= CELL_EXCERPT_LINES {
        0
    } else {
        (first.max(2) - 2).min(total - CELL_EXCERPT_LINES)
    };
    let end = (start + CELL_EXCERPT_LINES).min(total);
    let mut shown: Vec<Vec<(String, bool)>> =
        lines[start..end].iter().map(|line| pieces(&text, line, &matches)).collect();
    if start > 0 {
        let first_line = &mut shown[0];
        let over = (line_width(first_line) + 1).saturating_sub(CELL_LINE_COLUMNS);
        trim_columns(first_line, over, true);
        first_line.insert(0, (OMISSION.to_string(), false));
    }
    if end < total {
        let last_line = shown.last_mut().expect("a window past its end has lines");
        let over = (line_width(last_line) + 1).saturating_sub(CELL_LINE_COLUMNS);
        trim_columns(last_line, over, false);
        last_line.push((OMISSION.to_string(), false));
    }
    TableCellPreview { lines: shown, line_count: total as u32 }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn plain(line: &[(String, bool)]) -> String {
        line.iter().map(|(text, _)| text.as_str()).collect()
    }

    fn marked(preview: &TableCellPreview) -> Vec<String> {
        preview
            .lines
            .iter()
            .flat_map(|line| line.iter().filter(|(_, m)| *m).map(|(t, _)| t.clone()))
            .collect()
    }

    fn assert_limits(preview: &TableCellPreview) {
        assert!(preview.lines.len() <= CELL_EXCERPT_LINES, "{preview:?}");
        for line in &preview.lines {
            assert!(line_width(line) <= CELL_LINE_COLUMNS, "{} columns: {:?}", line_width(line), plain(line));
        }
    }

    fn words(count: usize) -> String {
        (0..count).map(|i| format!("w{i:03}")).collect::<Vec<_>>().join(" ")
    }

    #[test]
    fn a_short_value_is_one_complete_line() {
        let preview = cell_preview("Jenalynn Weed", "");
        assert_eq!(preview.lines, vec![vec![("Jenalynn Weed".to_string(), false)]]);
        assert_eq!(preview.line_count, 1);
        assert!(!preview.offers_full_view());
    }

    #[test]
    fn a_word_ending_at_column_80_wraps_without_lost_text() {
        let first = "a".repeat(80);
        let text = format!("{first} next");
        let preview = cell_preview(&text, "");
        assert_eq!(preview.lines.iter().map(|l| plain(l)).collect::<Vec<_>>(), vec![first, "next".to_string()]);
        assert_limits(&preview);
    }

    #[test]
    fn a_word_longer_than_80_columns_splits_and_rejoins() {
        let long = "x".repeat(200);
        let preview = cell_preview(&format!("ab {long}"), "");
        let joined: String = preview.lines.iter().map(|l| plain(l)).collect();
        assert_eq!(joined, format!("ab{long}"));
        assert_eq!(preview.line_count, 4);
        assert_limits(&preview);
    }

    #[test]
    fn explicit_breaks_stay_and_carriage_returns_and_tabs_are_normalised() {
        let preview = cell_preview("one\r\ntwo\rthree\n\tfour", "");
        let lines: Vec<String> = preview.lines.iter().map(|l| plain(l)).collect();
        assert_eq!(lines, vec!["one", "two", "three", " four"]);
    }

    #[test]
    fn wide_characters_use_two_columns_and_marks_none() {
        let preview = cell_preview(&"漢".repeat(80), "");
        assert_eq!(preview.line_count, 2);
        assert_eq!(width_of(&plain(&preview.lines[0])), 80);
        let combining = "e\u{0301}".repeat(80);
        assert_eq!(cell_preview(&combining, "").line_count, 1);
    }

    #[test]
    fn a_first_match_is_marked_at_the_beginning_middle_and_end() {
        let text = words(200);
        for needle in ["w000", "w100", "w199"] {
            let preview = cell_preview(&text, needle);
            assert_eq!(marked(&preview), vec![needle.to_string()], "{needle}");
            assert_limits(&preview);
        }
    }

    #[test]
    fn the_window_centres_on_the_first_of_repeated_matches() {
        let mut parts: Vec<String> = (0..200).map(|i| format!("w{i:03}")).collect();
        parts[100] = "target".into();
        parts[150] = "target".into();
        let preview = cell_preview(&parts.join(" "), "target");
        assert_eq!(marked(&preview), vec!["target".to_string()]);
        let middle = plain(&preview.lines[2]);
        assert!(middle.contains("target"), "{middle}");
        assert!(plain(&preview.lines[0]).starts_with(OMISSION));
        assert!(plain(&preview.lines[4]).ends_with(OMISSION));
    }

    #[test]
    fn a_phrase_across_a_wrap_point_is_marked_on_both_lines() {
        let text = format!("{} alpha beta", "a".repeat(70));
        let preview = cell_preview(&text, "alpha beta");
        assert_eq!(marked(&preview), vec!["alpha".to_string(), "beta".to_string()]);
    }

    #[test]
    fn markers_never_exceed_the_column_or_line_limit() {
        let text = (0..40).map(|_| "y".repeat(80)).collect::<Vec<_>>().join("\n");
        let needle_line = 20;
        let mut lines: Vec<String> = text.split('\n').map(str::to_string).collect();
        lines[needle_line] = format!("{}needle", "y".repeat(74));
        let preview = cell_preview(&lines.join("\n"), "needle");
        assert_eq!(preview.lines.len(), CELL_EXCERPT_LINES);
        assert_eq!(preview.line_count, 40);
        assert_limits(&preview);
        assert_eq!(marked(&preview), vec!["needle".to_string()]);
    }

    #[test]
    fn a_match_longer_than_one_line_shows_its_first_part() {
        let long_match = "m".repeat(300);
        let text = format!("{} {long_match} {}", words(100), words(100));
        let preview = cell_preview(&text, &long_match);
        let shown: String = marked(&preview).concat();
        assert!(shown.len() >= 80, "{shown}");
        assert!(long_match.starts_with(&shown));
        assert_limits(&preview);
    }

    #[test]
    fn a_value_without_a_match_shows_its_first_lines() {
        let preview = cell_preview(&words(200), "absent");
        assert!(plain(&preview.lines[0]).starts_with("w000"));
        assert!(marked(&preview).is_empty());
        assert_limits(&preview);
    }

    #[test]
    fn the_full_view_starts_at_three_wrapped_lines() {
        assert!(!cell_preview("one\ntwo", "").offers_full_view());
        assert!(cell_preview("one\ntwo\nthree", "").offers_full_view());
        assert!(!cell_preview(&"z".repeat(160), "").offers_full_view());
        assert!(cell_preview(&"z".repeat(161), "").offers_full_view());
    }

    #[test]
    fn case_folding_marks_the_source_text() {
        let preview = cell_preview("İstanbul WEED", "weed");
        assert_eq!(marked(&preview), vec!["WEED".to_string()]);
    }
}
