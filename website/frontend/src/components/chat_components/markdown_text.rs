//! Markdown rendering for assistant turns.
//!
//! The model writes markdown (headings, bold, tables, fenced code, links), and showing
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
use common::chat_pages::ChatPageRef;
use common::chat_types::ChatDocRef;
use super::transcript::DocumentCitationCards;
use super::web_page::WebPageCard;

/// Body size for assistant prose. Heading sizes are derived from it.
const BODY_PX: f32 = 15.0;

/// The text of a handle that no citation of the conversation gave.
const UNCITED_LABEL: &str = "not cited";

/// The text of a handle that citations of the conversation gave to more than one document.
const CONFLICTING_LABEL: &str = "names more than one document";

#[component]
pub fn MarkdownishText(
    text: String,
    /// The handles that the `cite_documents` results of the conversation gave. `None`
    /// renders every handle as a chip. With a list, a handle that is not in it renders
    /// as plain text marked "not cited", because no document stands behind it.
    #[props(default)]
    cited_handles: Option<Vec<String>>,
    /// Handles that citations of the conversation gave to more than one document. Each
    /// renders as plain text with no link, because no one document stands behind it.
    #[props(default)]
    conflicting_handles: Vec<String>,
    #[props(default)]
    sources: Vec<ChatDocRef>,
    #[props(default)]
    pages: Vec<ChatPageRef>,
    #[props(default = true)]
    citation_links: bool,
    #[props(default)]
    card_handles: Option<Vec<String>>,
) -> Element {
    let blocks = if !citation_links {
        parse_blocks(&text).into_iter().map(|block| map_spans(block, &|span| match span {
            Span::Handle(handle) => Span::Text(handle), other => other,
        })).collect()
    } else { match &cited_handles {
        Some(issued) => mark_handles(parse_blocks(&text), issued, &conflicting_handles),
        None => mark_handles(parse_blocks(&text), &[], &conflicting_handles)
            .into_iter()
            .map(unmark_uncited)
            .collect(),
    }};
    let blocks = unique_card_blocks(blocks, card_handles.as_deref());
    rsx! {
        div {
            style: "font-size: {BODY_PX}px; line-height: 1.65; color: var(--x-ink-strong); \
                    word-break: break-word; overflow-wrap: anywhere;",
            for (i, block) in blocks.into_iter().enumerate() {
                CitationBlock { key: "{i}", block, sources: sources.clone(), pages: pages.clone(), conflicting: conflicting_handles.clone() }
            }
        }
    }
}

#[component]
fn CitationBlock(block: Block, sources: Vec<ChatDocRef>, pages: Vec<ChatPageRef>, conflicting: Vec<String>) -> Element {
    if let Block::Paragraph(spans) = &block {
        let parts = citation_parts(spans);
        if parts.len() > 1 {
            return rsx! {
                for (index, spans) in parts.into_iter().enumerate() {
                    CitationBlock { key: "part-{index}", block: Block::Paragraph(spans), sources: sources.clone(), pages: pages.clone(), conflicting: conflicting.clone() }
                }
            };
        }
    }
    let list = match &block {
        Block::Bullets(items) => Some((false, items.clone())),
        Block::Numbers(items) => Some((true, items.clone())),
        _ => None,
    };
    if let Some((ordered, items)) = list {
        let children = rsx! {
            for (index, spans) in items.into_iter().enumerate() {
                li { key: "{index}", style: "margin-bottom: 4px;",
                    CitationBlock { block: Block::Paragraph(spans), sources: sources.clone(), pages: pages.clone(), conflicting: conflicting.clone() }
                }
            }
        };
        return if ordered { rsx! { ol { style: "padding-left: 22px;", {children} } } }
            else { rsx! { ul { style: "padding-left: 22px;", {children} } } };
    }
    let handles = if matches!(&block, Block::Table { .. }) { Vec::new() } else { block_handles(&block) };
    rsx! {
        BlockView { block, sources: sources.clone(), pages: pages.clone(), conflicting: conflicting.clone() }
        CitationSources { handles, sources, pages, conflicting }
    }
}

#[component]
fn CitationSources(handles: Vec<String>, sources: Vec<ChatDocRef>, pages: Vec<ChatPageRef>, conflicting: Vec<String>) -> Element {
    rsx! {
        for handle in handles {
            if let Some(doc) = sources.iter().find(|source| source.handle == handle).cloned() {
                DocumentCitationCards { sources: sources.iter().filter(|source| source.file_hash == doc.file_hash).cloned().collect::<Vec<_>>(), conflicting: conflicting.clone() }
            }
            if let Some(page) = pages.iter().rev().find(|source| source.handle == handle).cloned() {
                div { "data-citation-handle": "{handle}",
                    "data-citation-aliases": serde_json::to_string(&pages.iter().filter(|source| source.url == page.url).map(|source| source.handle.clone()).collect::<Vec<_>>()).unwrap_or_default(),
                    WebPageCard { page: page.clone(), passages: pages.iter().filter(|source| source.url == page.url).cloned().collect::<Vec<_>>() }
                }
            }
        }
    }
}

fn citation_parts(spans: &[Span]) -> Vec<Vec<Span>> {
    let mut parts = Vec::new();
    let mut current = Vec::new();
    let mut cited = false;
    for span in spans {
        if cited && !matches!(span, Span::Handle(_)) {
            if let Span::Text(text) = span {
                let boundary = text.char_indices().find(|(_, ch)| !ch.is_whitespace() && !ch.is_ascii_punctuation())
                    .map(|(index, _)| index).unwrap_or(text.len());
                if boundary > 0 { current.push(Span::Text(text[..boundary].to_string())); }
                if boundary == text.len() { continue; }
                parts.push(std::mem::take(&mut current));
                current.push(Span::Text(text[boundary..].to_string()));
                cited = false;
                continue;
            }
            parts.push(std::mem::take(&mut current));
            cited = false;
        }
        current.push(span.clone());
        cited |= span_has_handle(span);
    }
    if !current.is_empty() { parts.push(current); }
    parts
}

fn span_has_handle(span: &Span) -> bool {
    match span {
        Span::Handle(_) => true,
        Span::Styled { spans, .. } => spans.iter().any(span_has_handle),
        _ => false,
    }
}

fn block_handles(block: &Block) -> Vec<String> {
    let handles = std::cell::RefCell::new(Vec::new());
    map_spans(block.clone(), &|span| {
        if let Span::Handle(handle) = &span {
            if !handles.borrow().contains(handle) { handles.borrow_mut().push(handle.clone()); }
        }
        span
    });
    handles.into_inner()
}

#[component]
fn BlockView(
    block: Block,
    #[props(default)] sources: Vec<ChatDocRef>,
    #[props(default)] pages: Vec<ChatPageRef>,
    #[props(default)] conflicting: Vec<String>,
) -> Element {
    match block {
        Block::Heading { level, spans } => {
            let (size, weight, top) = heading_style(level);
            rsx! {
                div {
                    style: "font-size: {size}px; font-weight: {weight}; margin: {top}px 0 6px 0; \
                            line-height: 1.35; color: var(--x-ink-strong);",
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
                        style: "font-size: var(--x-text-xs); color: var(--x-ink-muted); text-transform: uppercase; \
                                letter-spacing: 0.4px; margin-bottom: 2px;",
                        "{language}"
                    }
                }
                pre {
                    style: "margin: 0; background: #F1F5F9; border: 1px solid; border-color: var(--x-border); \
                            border-radius: 8px; padding: 10px 12px; overflow-x: auto; \
                            font-family: ui-monospace, SFMono-Regular, Menlo, monospace; \
                            font-size: var(--x-text-sm); line-height: 1.5; white-space: pre;",
                    "{body}"
                }
            }
        },
        Block::Quote(spans) => rsx! {
            blockquote {
                style: "margin: 0 0 10px 0; padding: 2px 0 2px 12px; \
                        border-left: 3px solid #CBD5E1; color: var(--x-ink);",
                InlineSpans { spans }
            }
        },
        // Wide tables scroll inside their own box; the transcript column must not gain
        // a horizontal scrollbar because one answer contained a ten-column table.
        Block::Table { header, rows } => {
            let columns = header.len().max(rows.iter().map(Vec::len).max().unwrap_or(1)).max(1);
            let header_handles = table_row_handles(&header);
            rsx! {
            div { style: "margin: 0 0 10px 0; overflow-x: auto;",
                table {
                    style: "border-collapse: collapse; font-size: var(--x-text-sm); min-width: 100%;",
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
                        if !header_handles.is_empty() {
                            tr { "data-citation-table-row": "header",
                                td { colspan: "{columns}",
                                    CitationSources { handles: header_handles, sources: sources.clone(), pages: pages.clone(), conflicting: conflicting.clone() }
                                }
                            }
                        }
                        for (r, row) in rows.into_iter().enumerate() {
                            {let handles = table_row_handles(&row); rsx! {
                            tr { key: "{r}",
                                for (c, cell) in row.into_iter().enumerate() {
                                    td {
                                        key: "{c}",
                                        style: "padding: 6px 10px; border-bottom: 1px solid; border-bottom-color: var(--x-border); \
                                                vertical-align: top;",
                                        InlineSpans { spans: cell }
                                    }
                                }
                            }
                            if !handles.is_empty() {
                                tr { key: "sources-{r}", "data-citation-table-row": "{r}",
                                    td { colspan: "{columns}",
                                        CitationSources { handles, sources: sources.clone(), pages: pages.clone(), conflicting: conflicting.clone() }
                                    }
                                }
                            }
                            }}
                        }
                    }
                }
            }
        }},
        Block::Rule => rsx! {
            hr { style: "border: none; border-top: 1px solid; border-top-color: var(--x-border); margin: 14px 0;" }
        },
    }
}

fn table_row_handles(row: &[Vec<Span>]) -> Vec<String> {
    block_handles(&Block::Paragraph(row.iter().flatten().cloned().collect()))
}

/// `(font-size px, weight, margin-top px)` for a heading level.
///
/// Levels 4-6 all land on body size and are distinguished by weight alone, the model
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
                    Span::Styled { bold, spans } => if bold {
                        rsx! { strong { key: "{i}", style: "font-weight: 650;", InlineSpans { spans } } }
                    } else {
                        rsx! { em { key: "{i}", InlineSpans { spans } } }
                    },
                    Span::Code(t) => rsx! {
                        code {
                            key: "{i}",
                            style: "background: #F1F5F9; border: 1px solid; border-color: var(--x-border); \
                                    border-radius: 4px; padding: 0 4px; \
                                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace; \
                                    font-size: 0.88em;",
                            "{t}"
                        }
                    },
                    Span::Handle(handle) | Span::Reference(handle) => rsx! {
                        button {
                            key: "{i}",
                            style: "
                                display: inline; border: 1px solid; border-color: var(--x-border);
                                background: #F8FAFC; color: var(--x-ink); border-radius: 5px;
                                padding: 0 4px; margin: 0 1px; font-size: 0.82em;
                                font-weight: 400; cursor: pointer; vertical-align: baseline;
                            ",
                            title: "Show the cited source",
                            onclick: {
                                let handle = handle.clone();
                                move |_| scroll_to_handle(&handle)
                            },
                            "{handle}"
                        }
                    },
                    Span::UncitedHandle(handle) => rsx! {
                        span {
                            key: "{i}",
                            style: "color: var(--x-ink-muted);",
                            title: "No citation of this conversation gave this handle, so \
                                    no document stands behind it.",
                            "{handle} ({UNCITED_LABEL})"
                        }
                    },
                    Span::ConflictingHandle(handle) => rsx! {
                        span {
                            key: "{i}",
                            "data-conflicting-handle": "{handle}",
                            style: "color: var(--x-warning);",
                            title: "Citations of this conversation gave this handle to more \
                                    than one document, so it links to none of them.",
                            "{handle} ({CONFLICTING_LABEL})"
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
                            style: "color: var(--x-link); text-decoration: underline;",
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
    /// Preserve emphasis around citation controls and their validation state.
    Styled { bold: bool, spans: Vec<Span> },
    Code(String),
    Link { text: String, href: String },
    /// A document or web citation handle in assistant prose.
    /// Its control opens the next matching source card in the same answer.
    Handle(String),
    /// A later citation marker selects the existing source card.
    Reference(String),
    /// A handle that no `cite_documents` result of the conversation gave. Rendered as
    /// plain text marked "not cited", with no chip.
    UncitedHandle(String),
    /// A handle that citations of the conversation gave to more than one document, in
    /// records from before durable handles. Rendered as plain text with no chip.
    ConflictingHandle(String),
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

/// A block with each `Span::UncitedHandle` back as a `Span::Handle`, for a text that
/// is rendered with no list of issued handles.
fn unmark_uncited(block: Block) -> Block {
    map_spans(block, &|span| match span {
        Span::UncitedHandle(h) => Span::Handle(h),
        other => other,
    })
}

/// Turn each `Span::Handle` in `conflicting` into a `Span::ConflictingHandle`, and each
/// other handle that is not in `issued` into a `Span::UncitedHandle`.
pub fn mark_handles(blocks: Vec<Block>, issued: &[String], conflicting: &[String]) -> Vec<Block> {
    blocks
        .into_iter()
        .map(|block| {
            map_spans(block, &|span| match span {
                Span::Handle(h) if conflicting.contains(&h) => Span::ConflictingHandle(h),
                Span::Handle(h) if !issued.contains(&h) => Span::UncitedHandle(h),
                other => other,
            })
        })
        .collect()
}

/// `block` with `f` applied to each of its spans.
fn map_spans(block: Block, f: &dyn Fn(Span) -> Span) -> Block {
    fn inline(spans: Vec<Span>, f: &dyn Fn(Span) -> Span) -> Vec<Span> {
        spans.into_iter().map(|span| f(match span {
            Span::Styled { bold, spans } => Span::Styled { bold, spans: inline(spans, f) },
            other => other,
        })).collect()
    }
    let mark = |spans| inline(spans, f);
    let mark_all = |lists: Vec<Vec<Span>>| -> Vec<Vec<Span>> { lists.into_iter().map(mark).collect() };
    match block {
        Block::Heading { level, spans } => Block::Heading { level, spans: mark(spans) },
        Block::Paragraph(spans) => Block::Paragraph(mark(spans)),
        Block::Bullets(items) => Block::Bullets(mark_all(items)),
        Block::Numbers(items) => Block::Numbers(mark_all(items)),
        Block::Quote(spans) => Block::Quote(mark(spans)),
        Block::Table { header, rows } => Block::Table {
            header: mark_all(header),
            rows: rows.into_iter().map(mark_all).collect(),
        },
        other => other,
    }
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
        // being abandoned. A truncated answer should still show its code.
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
    parse_inline_depth(text, 0)
}

fn emphasis_span(body: String, bold: bool, depth: usize) -> Span {
    if depth < 8 && body.contains('[') {
        let spans = parse_inline_depth(&body, depth + 1);
        if spans.iter().any(span_has_handle) {
            return Span::Styled { bold, spans };
        }
    }
    if bold { Span::Bold(body) } else { Span::Italic(body) }
}

fn parse_inline_depth(text: &str, depth: usize) -> Vec<Span> {
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
                let body: String = chars[i + 2..end].iter().collect();
                out.push(emphasis_span(body, true, depth));
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
                        out.push(emphasis_span(body, false, depth));
                        i = end + 1;
                        continue;
                    }
                }
            }
        }

        if c == '[' {
            if let Some(close) = find_char(&chars, i + 1, ']')
                && chars.get(close + 1) != Some(&'(')
                && let Some(handles) = as_handles(&chars[i..=close])
            {
                push_plain(&mut plain, &mut out);
                for (index, handle) in handles.into_iter().enumerate() {
                    if index > 0 { out.push(Span::Text(", ".into())); }
                    out.push(Span::Handle(handle));
                }
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

/// Read document and web citation handles. Other bracketed words remain ordinary text.
fn as_handles(chars: &[char]) -> Option<Vec<String>> {
    let inner: String = chars.iter().collect();
    inner.strip_prefix('[')?.strip_suffix(']')?.split(',').map(|value| {
        let value = value.trim();
        let digits = value.strip_prefix('D').or_else(|| value.strip_prefix('W'))?;
        if digits.is_empty() || !digits.chars().all(|c| c.is_ascii_digit()) { return None; }
        Some(format!("[{value}]"))
    }).collect()
}

/// Scroll to and select the conversation's single source card.
fn scroll_to_handle(handle: &str) {
    let handle = serde_json::to_string(handle).unwrap_or_default();
    document::eval(&format!(r#"
        const el = [...document.querySelectorAll('#x-chat-transcript [data-citation-handle]')]
            .find(el => el.dataset.citationHandle === {handle} || JSON.parse(el.dataset.citationAliases || "[]").includes({handle}));
        if (el) {{
            el.querySelector('[data-citation-select]')?.click();
            el.scrollIntoView({{ behavior: "smooth", block: "center" }});
            el.classList.remove("x-source-flash");
            void el.offsetWidth;
            el.classList.add("x-source-flash");
        }}
    "#));
}

/// Return citation markers in their visible Markdown order.
pub(super) fn referenced_handles(text: &str) -> Vec<String> {
    parse_blocks(text).iter().flat_map(block_handles).collect()
}

fn unique_card_blocks(blocks: Vec<Block>, allowed: Option<&[String]>) -> Vec<Block> {
    let seen = std::cell::RefCell::new(Vec::new());
    blocks.into_iter().map(|block| map_spans(block, &|span| match span {
        Span::Handle(handle) => {
            if allowed.is_some_and(|handles| !handles.contains(&handle)) || seen.borrow().contains(&handle) {
                Span::Reference(handle)
            } else {
                seen.borrow_mut().push(handle.clone());
                Span::Handle(handle)
            }
        },
        other => other,
    })).collect()
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
    fn repeated_styled_and_table_references_render_one_card() {
        let blocks = unique_card_blocks(parse_blocks("First **[D1]**. Again [D1].\n\n| Source |\n| --- |\n| [D1] |\n| [D2] |"), Some(&["[D1]".into()]));
        assert_eq!(blocks.iter().flat_map(block_handles).collect::<Vec<_>>(), vec!["[D1]"]);
        assert_eq!(referenced_handles("**[D1]** then *[D2]*"), vec!["[D1]", "[D2]"]);
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

    /// A handle that no citation gave renders as plain text, and a given one stays a chip,
    /// in every block kind that holds spans.
    #[test]
    fn a_handle_that_no_citation_gave_is_marked_not_cited() {
        let blocks = parse_blocks("see [D1] and [D2]\n\n- item [D2]\n\n| a |\n|---|\n| [D2] |");
        let marked = mark_handles(blocks, &["[D1]".to_string()], &[]);
        assert_eq!(
            marked[0],
            Block::Paragraph(vec![
                Span::Text("see ".into()),
                Span::Handle("[D1]".into()),
                Span::Text(" and ".into()),
                Span::UncitedHandle("[D2]".into()),
            ])
        );
        assert_eq!(
            marked[1],
            Block::Bullets(vec![vec![
                Span::Text("item ".into()),
                Span::UncitedHandle("[D2]".into()),
            ]])
        );
        let Block::Table { rows, .. } = &marked[2] else {
            panic!("a table: {:?}", marked[2]);
        };
        assert_eq!(rows[0][0], vec![Span::UncitedHandle("[D2]".into())]);
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

    #[test]
    fn citation_parts_keep_punctuation_and_source_order() {
        let parts = citation_parts(&parse_inline("First [D2]. Next **claim** [W1][D1]. Last."));
        assert_eq!(parts.len(), 3);
        assert_eq!(block_handles(&Block::Paragraph(parts[0].clone())), vec!["[D2]"]);
        assert_eq!(block_handles(&Block::Paragraph(parts[1].clone())), vec!["[W1]", "[D1]"]);
        assert_eq!(parts[0].last(), Some(&Span::Text(". ".into())));
        assert_eq!(parts[2], vec![Span::Text("Last.".into())]);
    }

    #[test]
    fn table_row_citations_keep_cell_order_and_remove_repeats() {
        let row = vec![parse_inline("First [W2][D1]"), parse_inline("Again [W2], then [W1]")];
        assert_eq!(table_row_handles(&row), vec!["[W2]", "[D1]", "[W1]"]);
        assert!(table_row_handles(&[parse_inline("No citation")]).is_empty());
    }

    #[test]
    fn emphasized_citations_keep_source_order_and_validation() {
        let parts = citation_parts(&parse_inline("First **[W1, W2]**. Next *[D8]*."));
        assert_eq!(parts.len(), 2);
        assert_eq!(block_handles(&Block::Paragraph(parts[0].clone())), vec!["[W1]", "[W2]"]);
        assert_eq!(block_handles(&Block::Paragraph(parts[1].clone())), vec!["[D8]"]);
        let marked = mark_handles(vec![Block::Paragraph(parts[1].clone())], &[], &[]);
        assert_eq!(marked, vec![Block::Paragraph(vec![Span::Text("Next ".into()),
            Span::Styled { bold: false, spans: vec![Span::UncitedHandle("[D8]".into())] },
            Span::Text(".".into())])]);
        assert!(block_handles(&parse_blocks("**`[W1]`**")[0]).is_empty());
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
