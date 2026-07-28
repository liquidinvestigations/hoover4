//! Lightweight markdown-ish rendering for assistant turns (paragraphs, bullets, numbers).

use dioxus::prelude::*;

#[component]
pub fn MarkdownishText(text: String) -> Element {
    let blocks = parse_blocks(&text);
    rsx! {
        div { style: "font-size: 15px; line-height: 1.65; color: #0F172A;",
            for (i, block) in blocks.into_iter().enumerate() {
                {
                    match block {
                        Block::Paragraph(p) => rsx! {
                            p { key: "{i}", style: "margin: 0 0 10px 0;", "{p}" }
                        },
                        Block::Bullets(items) => rsx! {
                            ul { key: "{i}", style: "margin: 0 0 10px 0; padding-left: 22px;",
                                for (j, item) in items.into_iter().enumerate() {
                                    li { key: "{j}", style: "margin-bottom: 4px;", "{item}" }
                                }
                            }
                        },
                        Block::Numbers(items) => rsx! {
                            ol { key: "{i}", style: "margin: 0 0 10px 0; padding-left: 22px;",
                                for (j, item) in items.into_iter().enumerate() {
                                    li { key: "{j}", style: "margin-bottom: 4px;", "{item}" }
                                }
                            }
                        },
                    }
                }
            }
        }
    }
}

enum Block {
    Paragraph(String),
    Bullets(Vec<String>),
    Numbers(Vec<String>),
}

fn parse_blocks(text: &str) -> Vec<Block> {
    let mut out = Vec::new();
    let mut para: Vec<String> = Vec::new();
    let mut bullets: Vec<String> = Vec::new();
    let mut numbers: Vec<String> = Vec::new();

    let flush_para = |para: &mut Vec<String>, out: &mut Vec<Block>| {
        if !para.is_empty() {
            out.push(Block::Paragraph(para.join(" ")));
            para.clear();
        }
    };
    let flush_bullets = |bullets: &mut Vec<String>, out: &mut Vec<Block>| {
        if !bullets.is_empty() {
            out.push(Block::Bullets(std::mem::take(bullets)));
        }
    };
    let flush_numbers = |numbers: &mut Vec<String>, out: &mut Vec<Block>| {
        if !numbers.is_empty() {
            out.push(Block::Numbers(std::mem::take(numbers)));
        }
    };

    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            flush_bullets(&mut bullets, &mut out);
            flush_numbers(&mut numbers, &mut out);
            flush_para(&mut para, &mut out);
            continue;
        }
        if let Some(rest) = trimmed.strip_prefix("- ").or_else(|| trimmed.strip_prefix("* ")) {
            flush_para(&mut para, &mut out);
            flush_numbers(&mut numbers, &mut out);
            bullets.push(rest.to_string());
            continue;
        }
        if let Some(rest) = numbered_item(trimmed) {
            flush_para(&mut para, &mut out);
            flush_bullets(&mut bullets, &mut out);
            numbers.push(rest);
            continue;
        }
        flush_bullets(&mut bullets, &mut out);
        flush_numbers(&mut numbers, &mut out);
        para.push(trimmed.to_string());
    }
    flush_bullets(&mut bullets, &mut out);
    flush_numbers(&mut numbers, &mut out);
    flush_para(&mut para, &mut out);
    out
}

fn numbered_item(line: &str) -> Option<String> {
    let mut chars = line.chars();
    let mut saw_digit = false;
    while let Some(c) = chars.next() {
        if c.is_ascii_digit() {
            saw_digit = true;
            continue;
        }
        if (c == '.' || c == ')') && saw_digit {
            let rest = chars.as_str().trim_start();
            if !rest.is_empty() {
                return Some(rest.to_string());
            }
        }
        break;
    }
    None
}
