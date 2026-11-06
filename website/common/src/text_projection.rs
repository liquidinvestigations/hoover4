//! Map indexed text to the complete stored source without changing index bytes.

use crate::text_highlight::HighlightTextSpan;

#[derive(Clone)]
struct Unit {
    character: char,
    source: Option<std::ops::Range<usize>>,
}

fn whitespace(c: char) -> bool {
    c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')
}

fn encoded(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '+' | '/' | '=')
}

fn lines(units: &[Unit]) -> Vec<&[Unit]> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut i = 0;
    while i < units.len() {
        if matches!(units[i].character, '\n' | '\r' | '\u{b}' | '\u{c}' | '\u{1c}'..='\u{1e}' | '\u{85}' | '\u{2028}' | '\u{2029}') {
            if units[i].character == '\r' && units.get(i + 1).is_some_and(|u| u.character == '\n') {
                i += 1;
            }
            out.push(&units[start..=i]);
            start = i + 1;
        }
        i += 1;
    }
    if start < units.len() { out.push(&units[start..]); }
    out
}

fn encoded_line(line: &[Unit]) -> Option<(&[Unit], &[Unit])> {
    let end = line.iter().rposition(|u| !matches!(u.character, '\r' | '\n')).map_or(0, |i| i + 1);
    let start = line[..end].iter().position(|u| !matches!(u.character, ' ' | '\t')).unwrap_or(end);
    let body = &line[start..end];
    (body.len() >= 60 && body.iter().all(|u| encoded(u.character))).then_some((body, &line[end..]))
}

fn project(source: &str) -> Vec<Unit> {
    let all: Vec<Unit> = source.char_indices().map(|(i, character)| Unit {
        character, source: Some(i..i + character.len_utf8()),
    }).collect();
    let start = all.iter().position(|u| !whitespace(u.character)).unwrap_or(all.len());
    let end = all.iter().rposition(|u| !whitespace(u.character)).map_or(start, |i| i + 1);
    let lines = lines(&all[start..end]);
    let mut out = Vec::new();
    let mut i = 0;
    while i < lines.len() {
        if encoded_line(lines[i]).is_some() {
            let mut kept = 0;
            let mut ending = &[][..];
            while i < lines.len() {
                let Some((body, last)) = encoded_line(lines[i]) else { break };
                let take = (65usize.saturating_sub(kept)).min(body.len());
                out.extend_from_slice(&body[..take]);
                kept += take;
                ending = last;
                i += 1;
            }
            out.extend_from_slice(ending);
        } else {
            let line = lines[i];
            let mut j = 0;
            while j < line.len() {
                if encoded(line[j].character) {
                    let begin = j;
                    while j < line.len() && encoded(line[j].character) { j += 1; }
                    if j - begin >= 201 {
                        out.extend_from_slice(&line[begin..begin + 65]);
                        out.push(Unit { character: ' ', source: None });
                    } else { out.extend_from_slice(&line[begin..j]); }
                } else {
                    out.push(line[j].clone());
                    j += 1;
                }
            }
            i += 1;
        }
    }
    for unit in &mut out {
        if unit.character == '\0' { unit.character = ' '; }
    }
    out
}

/// Return the exact bytes produced by Python's clean_text and indexed_text.
pub fn indexed_text(source: &str) -> String {
    project(source).iter().map(|u| u.character).collect()
}

/// Validate all markers and text before mapping marked characters to source bytes.
pub fn highlight_spans(highlighted: &str, source: &str) -> Option<Vec<HighlightTextSpan>> {
    const OPEN: &str = "<hoover4_strong>";
    const CLOSE: &str = "</hoover4_strong>";
    let mut plain = String::new();
    let mut marks = Vec::new();
    let mut rest = highlighted;
    let mut marked = false;
    let mut ordinal = 0;
    while !rest.is_empty() {
        if rest.starts_with(OPEN) {
            if marked { return None; }
            marked = true;
            rest = &rest[OPEN.len()..];
        } else if rest.starts_with(CLOSE) {
            if !marked { return None; }
            marked = false;
            rest = &rest[CLOSE.len()..];
            if !rest.starts_with(OPEN) { ordinal += 1; }
        } else {
            let c = rest.chars().next()?;
            plain.push(c);
            marks.push(marked.then_some(ordinal));
            rest = &rest[c.len_utf8()..];
        }
    }
    if marked { return None; }
    let units = if plain == source {
        source.char_indices().map(|(i, character)| Unit { character, source: Some(i..i + character.len_utf8()) }).collect()
    } else {
        let units = project(source);
        if units.iter().map(|u| u.character).collect::<String>() != plain { return None; }
        units
    };
    let mut ranges: Vec<(std::ops::Range<usize>, u64)> = Vec::new();
    for (unit, mark) in units.iter().zip(marks) {
        if let (Some(range), Some(index)) = (&unit.source, mark) {
            match ranges.last_mut() {
                Some((previous, old)) if *old == index && previous.end == range.start => previous.end = range.end,
                _ => ranges.push((range.clone(), index)),
            }
        }
    }
    let mut spans = Vec::new();
    let mut cursor = 0;
    for (range, index) in ranges {
        if cursor < range.start { spans.push(HighlightTextSpan { text: source[cursor..range.start].into(), is_highlighted: false, index: 0 }); }
        spans.push(HighlightTextSpan { text: source[range.clone()].into(), is_highlighted: true, index });
        cursor = range.end;
    }
    if cursor < source.len() { spans.push(HighlightTextSpan { text: source[cursor..].into(), is_highlighted: false, index: 0 }); }
    Some(spans)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn producer_fixtures_match_and_map_complete_source() {
        let fixtures: Vec<serde_json::Value> = serde_json::from_str(include_str!("../tests/text_projection.json")).unwrap();
        for fixture in fixtures {
            let source = fixture["source"].as_str().unwrap();
            let indexed = fixture["indexed"].as_str().unwrap();
            assert_eq!(indexed_text(source), indexed);
            let marked = indexed.replace("quokka", "<hoover4_strong>quokka</hoover4_strong>");
            let spans = highlight_spans(&marked, source).unwrap();
            assert_eq!(spans.iter().map(|s| s.text.as_str()).collect::<String>(), source);
            assert_eq!(spans.iter().filter(|s| s.is_highlighted).count(), indexed.matches("quokka").count());
            assert!(highlight_spans(&(marked + "stale"), source).is_none());
        }
    }
}
