//! Markdown rendering for assistant turns.
//!
//! The model writes markdown — headings, bold, tables, fenced code, links — and showing
//! that as plain text is why answers looked like source. This parses it to a block tree
//! and renders Dioxus nodes.
//!
//! **Nothing here emits raw HTML.** `dangerous_inner_html` on model output would be an
//! injection sink fed by whatever the agent scraped off the open web, so markdown maps
//! to real elements and any HTML in the source is shown as the text it is. That rules
//! out a few things a full CommonMark renderer would do (nested lists, block quotes
//! inside lists) in exchange for not having to trust the input.
//!
//! ## Type scale
//!
//! Chat headings are *labels inside a message*, not page titles: a browser-default `h1`
//! is 2em and towers over the conversation. The scale here tops out just above body
//! text (18px against 15px) and leans on weight and colour instead of size, so a reply
//! that opens with `# Summary` still reads as one message rather than a new document.

use dioxus::prelude::*;

/// Body size for assistant prose. Heading sizes are derived from it.
const BODY_PX: f32 = 15.0;

#[component]
pub fn MarkdownishText(text: String) -> Element {
    let blocks = parse_blocks(&text);
    rsx! {
        div {
            style: "font-size: {BODY_PX}px; line-height: 1.65; color: #0F172A; \
                    word-break: break-word; overflow-wrap: anywhere;",
            for (i, block) in blocks.into_iter().enumerate() {
                BlockView { key: "{i}", block }
            }
        }
    }
}

#[component]
fn BlockView(block: Block) -> Element {
    match block {
        Block::Heading { level, spans } => {
            let (size, weight, top) = heading_style(level);
            rsx! {
                div {
                    style: "font-size: {size}px; font-weight: {weight}; margin: {top}px 0 6px 0; \
                            line-height: 1.35; color: #0F172A;",
                    InlineSpans { spans }
                }
            }
        }
        Block::Paragraph(spans) => rsx! {
            p { style: "margin: 0 0 10px 0;", InlineSpans { spans } }
        },
        Block::Bullets(items) => rsx! {
            ul { style: "margin: 0 0 10px 0; padding-left: 22px;",
                for (j, item) in items.into_iter().enumerate() {
                    li { key: "{j}", style: "margin-bottom: 4px;", InlineSpans { spans: item } }
                }
            }
        },
        Block::Numbers(items) => rsx! {
            ol { style: "margin: 0 0 10px 0; padding-left: 22px;",
                for (j, item) in items.into_iter().enumerate() {
                    li { key: "{j}", style: "margin-bottom: 4px;", InlineSpans { spans: item } }
                }
            }
        },
        Block::Code { language, body } => rsx! {
            div { style: "margin: 0 0 10px 0;",
                if !language.is_empty() {
                    div {
                        style: "font-size: 11px; color: #64748B; text-transform: uppercase; \
                                letter-spacing: 0.4px; margin-bottom: 2px;",
                        "{language}"
                    }
                }
                pre {
                    style: "margin: 0; background: #F1F5F9; border: 1px solid #E2E8F0; \
                            border-radius: 8px; padding: 10px 12px; overflow-x: auto; \
                            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; \
                            font-size: 12.5px; line-height: 1.5; white-space: pre;",
                    "{body}"
                }
            }
        },
        Block::Quote(spans) => rsx! {
            blockquote {
                style: "margin: 0 0 10px 0; padding: 2px 0 2px 12px; \
                        border-left: 3px solid #CBD5E1; color: #475569;",
                InlineSpans { spans }
            }
        },
        // Wide tables scroll inside their own box; the transcript column must not gain
        // a horizontal scrollbar because one answer contained a ten-column table.
        Block::Table { header, rows } => rsx! {
            div { style: "margin: 0 0 10px 0; overflow-x: auto;",
                table {
                    style: "border-collapse: collapse; font-size: 13.5px; min-width: 100%;",
                    if !header.is_empty() {
                        thead {
                            tr {
                                for (c, cell) in header.into_iter().enumerate() {
                                    th {
                                        key: "{c}",
                                        style: "text-align: left; padding: 6px 10px; \
                                                border-bottom: 2px solid #CBD5E1; \
                                                font-weight: 600; white-space: nowrap;",
                                        InlineSpans { spans: cell }
                                    }
                                }
                            }
                        }
                    }
                    tbody {
                        for (r, row) in rows.into_iter().enumerate() {
                            tr { key: "{r}",
                                for (c, cell) in row.into_iter().enumerate() {
                                    td {
                                        key: "{c}",
                                        style: "padding: 6px 10px; border-bottom: 1px solid #E2E8F0; \
                                                vertical-align: top;",
                                        InlineSpans { spans: cell }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        Block::Rule => rsx! {
            hr { style: "border: none; border-top: 1px solid #E2E8F0; margin: 14px 0;" }
        },
    }
}

/// `(font-size px, weight, margin-top px)` for a heading level.
///
/// Levels 4-6 all land on body size and are distinguished by weight alone — the model
/// reaches for `####` freely and three more distinct sizes would be noise.
fn heading_style(level: u8) -> (f32, u16, f32) {
    match level {
        1 => (BODY_PX + 3.0, 700, 16.0),
        2 => (BODY_PX + 2.0, 700, 14.0),
        3 => (BODY_PX + 1.0, 650, 12.0),
        _ => (BODY_PX, 650, 10.0),
    }
}

#[component]
fn InlineSpans(spans: Vec<Span>) -> Element {
    rsx! {
        for (i, span) in spans.into_iter().enumerate() {
            {
                match span {
                    Span::Text(t) => rsx! { span { key: "{i}", "{t}" } },
                    Span::Bold(t) => rsx! {
                        strong { key: "{i}", style: "font-weight: 650;", "{t}" }
                    },
                    Span::Italic(t) => rsx! { em { key: "{i}", "{t}" } },
                    Span::Code(t) => rsx! {
                        code {
                            key: "{i}",
                            style: "background: #F1F5F9; border: 1px solid #E2E8F0; \
                                    border-radius: 4px; padding: 0 4px; \
                                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; \
                                    font-size: 0.88em;",
                            "{t}"
                        }
                    },
                    Span::Handle(handle) => rsx! {
                        button {
                            key: "{i}",
                            style: "
                                display: inline; border: 1px solid #C7D2FE;
                                background: #EEF2FF; color: #3730A3; border-radius: 5px;
                                padding: 0 4px; margin: 0 1px; font-size: 0.82em;
                                font-weight: 600; cursor: pointer; vertical-align: baseline;
                            ",
                            title: "Jump to the cited document",
                            onclick: {
                                let handle = handle.clone();
                                move |_| scroll_to_handle(&handle)
                            },
                            "{handle}"
                        }
                    },
                    Span::Link { text, href } => rsx! {
                        a {
                            key: "{i}",
                            href: "{href}",
                            // Model output can cite anywhere on the open web; never let
                            // a citation reach back into this tab.
                            target: "_blank",
                            rel: "noopener noreferrer nofollow",
                            style: "color: #4F46E5; text-decoration: underline;",
                            "{text}"
                        }
                    },
                }
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Span {
    Text(String),
    Bold(String),
    Italic(String),
    Code(String),
    Link { text: String, href: String },
    /// A citation handle the agent wrote into its prose, `[D3]`.
    ///
    /// Rendered as a chip that scrolls to the document's card in the Sources strip and
    /// highlights it. Recognised before the link syntax so `[D3](http://…)` is still a
    /// link — a handle is `[D` followed by digits and a `]` and nothing else.
    Handle(String),
}

#[derive(Debug, Clone, PartialEq)]
pub enum Block {
    Heading { level: u8, spans: Vec<Span> },
    Paragraph(Vec<Span>),
    Bullets(Vec<Vec<Span>>),
    Numbers(Vec<Vec<Span>>),
    Code { language: String, body: String },
    Quote(Vec<Span>),
    Table { header: Vec<Vec<Span>>, rows: Vec<Vec<Vec<Span>>> },
    Rule,
}

pub fn parse_blocks(text: &str) -> Vec<Block> {
    let lines: Vec<&str> = text.lines().collect();
    let mut out: Vec<Block> = Vec::new();
    let mut para: Vec<String> = Vec::new();
    let mut bullets: Vec<Vec<Span>> = Vec::new();
    let mut numbers: Vec<Vec<Span>> = Vec::new();
    let mut i = 0;

    macro_rules! flush {
        () => {
            if !para.is_empty() {
                out.push(Block::Paragraph(parse_inline(&para.join(" "))));
                para.clear();
            }
            if !bullets.is_empty() {
                out.push(Block::Bullets(std::mem::take(&mut bullets)));
            }
            if !numbers.is_empty() {
                out.push(Block::Numbers(std::mem::take(&mut numbers)));
            }
        };
    }

    while i < lines.len() {
        let raw = lines[i];
        let trimmed = raw.trim();

        // Fenced code. An unterminated fence runs to the end of the message rather than
        // being abandoned — a truncated answer should still show its code.
        if let Some(language) = fence_language(trimmed) {
            flush!();
            let mut body: Vec<&str> = Vec::new();
            i += 1;
            while i < lines.len() && fence_language(lines[i].trim()).is_none() {
                body.push(lines[i]);
                i += 1;
            }
            i += 1; // closing fence (or past the end)
            out.push(Block::Code {
                language,
                body: body.join("\n"),
            });
            continue;
        }

        if trimmed.is_empty() {
            flush!();
            i += 1;
            continue;
        }

        if is_rule(trimmed) {
            flush!();
            out.push(Block::Rule);
            i += 1;
            continue;
        }

        if let Some((level, rest)) = heading(trimmed) {
            flush!();
            out.push(Block::Heading {
                level,
                spans: parse_inline(rest),
            });
            i += 1;
            continue;
        }

        // A table needs its delimiter row (`|---|---|`) on the next line; without it a
        // line containing a pipe is just prose.
        if trimmed.starts_with('|') && i + 1 < lines.len() && is_delimiter_row(lines[i + 1].trim())
        {
            flush!();
            let header = split_row(trimmed);
            let mut rows = Vec::new();
            i += 2;
            while i < lines.len() && lines[i].trim().starts_with('|') {
                rows.push(split_row(lines[i].trim()));
                i += 1;
            }
            out.push(Block::Table { header, rows });
            continue;
        }

        if let Some(rest) = trimmed.strip_prefix("> ").or_else(|| trimmed.strip_prefix(">")) {
            flush!();
            out.push(Block::Quote(parse_inline(rest.trim())));
            i += 1;
            continue;
        }

        if let Some(rest) = bullet_item(trimmed) {
            if !para.is_empty() {
                out.push(Block::Paragraph(parse_inline(&para.join(" "))));
                para.clear();
            }
            if !numbers.is_empty() {
                out.push(Block::Numbers(std::mem::take(&mut numbers)));
            }
            bullets.push(parse_inline(rest));
            i += 1;
            continue;
        }

        if let Some(rest) = numbered_item(trimmed) {
            if !para.is_empty() {
                out.push(Block::Paragraph(parse_inline(&para.join(" "))));
                para.clear();
            }
            if !bullets.is_empty() {
                out.push(Block::Bullets(std::mem::take(&mut bullets)));
            }
            numbers.push(parse_inline(&rest));
            i += 1;
            continue;
        }

        if !bullets.is_empty() {
            out.push(Block::Bullets(std::mem::take(&mut bullets)));
        }
        if !numbers.is_empty() {
            out.push(Block::Numbers(std::mem::take(&mut numbers)));
        }
        para.push(trimmed.to_string());
        i += 1;
    }

    flush!();
    out
}

fn fence_language(line: &str) -> Option<String> {
    let rest = line.strip_prefix("```")?;
    Some(rest.trim().to_string())
}

fn is_rule(line: &str) -> bool {
    let n = line.len();
    n >= 3
        && (line.chars().all(|c| c == '-')
            || line.chars().all(|c| c == '*')
            || line.chars().all(|c| c == '_'))
}

fn heading(line: &str) -> Option<(u8, &str)> {
    let hashes = line.chars().take_while(|c| *c == '#').count();
    if hashes == 0 || hashes > 6 {
        return None;
    }
    let rest = line[hashes..].strip_prefix(' ')?;
    Some((hashes as u8, rest.trim()))
}

fn is_delimiter_row(line: &str) -> bool {
    if !line.starts_with('|') {
        return false;
    }
    let body: String = line.chars().filter(|c| !c.is_whitespace()).collect();
    !body.is_empty()
        && body.chars().all(|c| matches!(c, '|' | '-' | ':'))
        && body.contains('-')
}

fn split_row(line: &str) -> Vec<Vec<Span>> {
    let inner = line.trim().trim_start_matches('|').trim_end_matches('|');
    inner.split('|').map(|c| parse_inline(c.trim())).collect()
}

fn bullet_item(line: &str) -> Option<&str> {
    for p in ["- ", "* ", "+ "] {
        if let Some(rest) = line.strip_prefix(p) {
            return Some(rest.trim());
        }
    }
    None
}

fn numbered_item(line: &str) -> Option<String> {
    let digits: String = line.chars().take_while(|c| c.is_ascii_digit()).collect();
    if digits.is_empty() {
        return None;
    }
    let rest = &line[digits.len()..];
    let rest = rest.strip_prefix('.').or_else(|| rest.strip_prefix(')'))?;
    let rest = rest.trim_start();
    if rest.is_empty() {
        return None;
    }
    Some(rest.to_string())
}

/// Inline markdown: `**bold**`, `*italic*`/`_italic_`, `` `code` ``, `[text](href)`.
///
/// Code is matched first and its contents are never re-scanned, so a backtick span
/// containing asterisks survives intact.
pub fn parse_inline(text: &str) -> Vec<Span> {
    let chars: Vec<char> = text.chars().collect();
    let mut out: Vec<Span> = Vec::new();
    let mut plain = String::new();
    let mut i = 0;

    let push_plain = |plain: &mut String, out: &mut Vec<Span>| {
        if !plain.is_empty() {
            out.push(Span::Text(std::mem::take(plain)));
        }
    };

    while i < chars.len() {
        let c = chars[i];

        if c == '`' {
            if let Some(end) = find_char(&chars, i + 1, '`') {
                push_plain(&mut plain, &mut out);
                out.push(Span::Code(chars[i + 1..end].iter().collect()));
                i = end + 1;
                continue;
            }
        }

        if c == '*' && i + 1 < chars.len() && chars[i + 1] == '*' {
            if let Some(end) = find_seq(&chars, i + 2, &['*', '*']) {
                push_plain(&mut plain, &mut out);
                out.push(Span::Bold(chars[i + 2..end].iter().collect()));
                i = end + 2;
                continue;
            }
        }

        if c == '*' || c == '_' {
            // A `_` inside a word (`file_hash`, `snake_case`) is not emphasis.
            let word_internal = c == '_' && i > 0 && is_wordish(chars[i - 1]);
            if !word_internal {
                if let Some(end) = find_char(&chars, i + 1, c) {
                    let body: String = chars[i + 1..end].iter().collect();
                    if !body.is_empty() && !body.starts_with(' ') {
                        push_plain(&mut plain, &mut out);
                        out.push(Span::Italic(body));
                        i = end + 1;
                        continue;
                    }
                }
            }
        }

        if c == '[' {
            if let Some(close) = find_char(&chars, i + 1, ']')
                && chars.get(close + 1) != Some(&'(')
                && let Some(handle) = as_handle(&chars[i..=close])
            {
                push_plain(&mut plain, &mut out);
                out.push(Span::Handle(handle));
                i = close + 1;
                continue;
            }
            if let Some(close) = find_char(&chars, i + 1, ']') {
                if chars.get(close + 1) == Some(&'(') {
                    if let Some(paren) = find_char(&chars, close + 2, ')') {
                        let href: String = chars[close + 2..paren].iter().collect();
                        if is_safe_href(&href) {
                            push_plain(&mut plain, &mut out);
                            out.push(Span::Link {
                                text: chars[i + 1..close].iter().collect(),
                                href,
                            });
                            i = paren + 1;
                            continue;
                        }
                    }
                }
            }
        }

        plain.push(c);
        i += 1;
    }

    push_plain(&mut plain, &mut out);
    out
}

/// `[D12]` and nothing else. `[Dog]`, `[D]` and `[12]` are ordinary text.
fn as_handle(chars: &[char]) -> Option<String> {
    let inner: String = chars.iter().collect();
    let digits = inner.strip_prefix("[D")?.strip_suffix(']')?;
    if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }
    Some(inner)
}

/// Scroll the Sources strip's entry for one handle into view and flash it.
///
/// Done with an element id and the platform's own scrolling rather than by lifting the
/// selection into a signal: the strip and the prose are in different components with no
/// shared owner, and threading a signal between them would put chat-wide state in the
/// markdown renderer.
fn scroll_to_handle(handle: &str) {
    let id = source_anchor_id(handle);
    document::eval(&format!(
        r#"
        const el = document.getElementById("{id}");
        if (el) {{
            el.scrollIntoView({{ behavior: "smooth", block: "center" }});
            el.classList.remove("x-source-flash");
            // Reading offsetWidth forces a reflow, which is what makes removing and
            // re-adding the class restart the animation rather than do nothing.
            void el.offsetWidth;
            el.classList.add("x-source-flash");
        }}
        "#
    ));
}

/// The DOM id of a Sources-strip entry. One function, because the prose writes it and
/// the strip reads it, and two spellings would scroll to nothing.
pub fn source_anchor_id(handle: &str) -> String {
    let digits: String = handle.chars().filter(|c| c.is_ascii_digit()).collect();
    format!("x-source-{digits}")
}

fn is_wordish(c: char) -> bool {
    c.is_alphanumeric() || c == '_'
}

fn find_char(chars: &[char], from: usize, target: char) -> Option<usize> {
    (from..chars.len()).find(|&i| chars[i] == target)
}

fn find_seq(chars: &[char], from: usize, seq: &[char]) -> Option<usize> {
    (from..chars.len().saturating_sub(seq.len() - 1))
        .find(|&i| chars[i..i + seq.len()] == *seq)
}

/// Only http(s) and mailto links become anchors.
///
/// The blocked case that matters is `javascript:`; everything unrecognised is left as
/// literal text, which is the safe direction to fail in for text a model produced from
/// scraped pages.
fn is_safe_href(href: &str) -> bool {
    let lower = href.trim().to_ascii_lowercase();
    lower.starts_with("http://") || lower.starts_with("https://") || lower.starts_with("mailto:")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn text(s: &str) -> Vec<Span> {
        vec![Span::Text(s.to_string())]
    }

    #[test]
    fn headings_parse_at_every_level_and_keep_their_text() {
        let blocks = parse_blocks("# One\n\n### Three\n\n###### Six");
        assert_eq!(
            blocks,
            vec![
                Block::Heading { level: 1, spans: text("One") },
                Block::Heading { level: 3, spans: text("Three") },
                Block::Heading { level: 6, spans: text("Six") },
            ]
        );
    }

    #[test]
    fn a_hash_without_a_space_is_not_a_heading() {
        // "#1 priority" and "#hashtag" are prose, not headings.
        assert_eq!(parse_blocks("#1 priority"), vec![Block::Paragraph(text("#1 priority"))]);
    }

    #[test]
    fn heading_sizes_stay_close_to_body_text() {
        // The bug this guards: a browser-default h1 is 2em and dwarfs the conversation.
        for level in 1..=6u8 {
            let (size, _, _) = heading_style(level);
            assert!(
                size >= BODY_PX && size <= BODY_PX + 3.0,
                "level {level} is {size}px, outside the chat scale"
            );
        }
        assert!(heading_style(1).0 > heading_style(3).0, "h1 must outrank h3");
    }

    /// `[D3]` in the prose is the reader's route from a claim to the document behind it.
    /// It has to be recognised before the link syntax, and it must not swallow ordinary
    /// bracketed text.
    #[test]
    fn a_citation_handle_becomes_a_chip_and_nothing_else_does() {
        assert_eq!(
            parse_inline("see [D3] for this"),
            vec![
                Span::Text("see ".into()),
                Span::Handle("[D3]".into()),
                Span::Text(" for this".into()),
            ]
        );
        assert_eq!(parse_inline("[Dog]"), vec![Span::Text("[Dog]".into())]);
        assert_eq!(parse_inline("[D]"), vec![Span::Text("[D]".into())]);
        assert_eq!(parse_inline("[12]"), vec![Span::Text("[12]".into())]);
    }

    /// A link is still a link. The handle arm only fires when no `(` follows the `]`.
    #[test]
    fn a_bracketed_label_followed_by_a_url_is_a_link_not_a_handle() {
        assert_eq!(
            parse_inline("[D3](https://example.org)"),
            vec![Span::Link {
                text: "D3".into(),
                href: "https://example.org".into(),
            }]
        );
    }

    /// The prose writes the anchor id and the strip reads it. Two spellings would scroll
    /// to nothing, silently.
    #[test]
    fn the_anchor_id_is_derived_from_the_handles_digits() {
        assert_eq!(source_anchor_id("[D3]"), "x-source-3");
        assert_eq!(source_anchor_id("[D12]"), "x-source-12");
    }

    #[test]
    fn bold_italic_and_code_become_spans() {
        assert_eq!(
            parse_inline("a **b** c *d* `e`"),
            vec![
                Span::Text("a ".into()),
                Span::Bold("b".into()),
                Span::Text(" c ".into()),
                Span::Italic("d".into()),
                Span::Text(" ".into()),
                Span::Code("e".into()),
            ]
        );
    }

    #[test]
    fn underscores_inside_identifiers_are_not_emphasis() {
        assert_eq!(parse_inline("collection_dataset"), text("collection_dataset"));
        assert_eq!(parse_inline("file_hash and page_id"), text("file_hash and page_id"));
    }

    #[test]
    fn code_spans_are_not_rescanned_for_emphasis() {
        assert_eq!(
            parse_inline("`a * b * c`"),
            vec![Span::Code("a * b * c".into())]
        );
    }

    #[test]
    fn unmatched_markers_stay_literal() {
        assert_eq!(parse_inline("2 * 3 = 6"), text("2 * 3 = 6"));
        assert_eq!(parse_inline("a `b"), text("a `b"));
    }

    #[test]
    fn links_are_parsed_and_javascript_urls_are_refused() {
        assert_eq!(
            parse_inline("[docs](https://example.com/x)"),
            vec![Span::Link {
                text: "docs".into(),
                href: "https://example.com/x".into()
            }]
        );
        // Left as literal text rather than becoming an anchor.
        let spans = parse_inline("[click](javascript:alert(1))");
        assert!(!spans.iter().any(|s| matches!(s, Span::Link { .. })));
    }

    #[test]
    fn fenced_code_keeps_its_language_and_inner_blank_lines() {
        let blocks = parse_blocks("```rust\nfn a() {}\n\nfn b() {}\n```");
        assert_eq!(
            blocks,
            vec![Block::Code {
                language: "rust".into(),
                body: "fn a() {}\n\nfn b() {}".into()
            }]
        );
    }

    #[test]
    fn an_unterminated_fence_still_renders_its_body() {
        // A truncated answer must not lose the code it did produce.
        let blocks = parse_blocks("```\nhalf a snippet");
        assert_eq!(
            blocks,
            vec![Block::Code {
                language: String::new(),
                body: "half a snippet".into()
            }]
        );
    }

    #[test]
    fn tables_need_a_delimiter_row() {
        let blocks = parse_blocks("| a | b |\n|---|---|\n| 1 | 2 |");
        assert_eq!(
            blocks,
            vec![Block::Table {
                header: vec![text("a"), text("b")],
                rows: vec![vec![text("1"), text("2")]],
            }]
        );
        // A pipe in prose is prose.
        assert_eq!(
            parse_blocks("| not | a table |"),
            vec![Block::Paragraph(text("| not | a table |"))]
        );
    }

    #[test]
    fn bullets_and_numbers_group_and_separate() {
        let blocks = parse_blocks("- one\n- two\n\n1. first\n2. second");
        assert_eq!(
            blocks,
            vec![
                Block::Bullets(vec![text("one"), text("two")]),
                Block::Numbers(vec![text("first"), text("second")]),
            ]
        );
    }

    #[test]
    fn a_list_directly_after_a_paragraph_does_not_swallow_it() {
        let blocks = parse_blocks("Intro line\n- one");
        assert_eq!(
            blocks,
            vec![
                Block::Paragraph(text("Intro line")),
                Block::Bullets(vec![text("one")]),
            ]
        );
    }

    #[test]
    fn a_real_answer_parses_into_the_expected_block_kinds() {
        // Shape taken from live Qwen3.5 output: heading, bold, bullets, citation links.
        let answer = "### Summary\n\nThe **Danube** level is rising.\n\n\
                      *   `/docs/a.pdf` \u{2014} gauge data\n\
                      *   [source](https://example.org)\n\n\
                      | Station | Level |\n|---|---|\n| Budapest | 320 |\n";
        let blocks = parse_blocks(answer);
        assert!(matches!(blocks[0], Block::Heading { level: 3, .. }));
        assert!(matches!(blocks[1], Block::Paragraph(_)));
        assert!(matches!(blocks[2], Block::Bullets(ref b) if b.len() == 2));
        assert!(matches!(blocks[3], Block::Table { .. }));
    }

    #[test]
    fn empty_input_produces_no_blocks() {
        assert!(parse_blocks("").is_empty());
        assert!(parse_blocks("   \n\n  ").is_empty());
    }
}
