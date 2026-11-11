//! Links to board nodes in the text of statements, facts, labels, events and assessment
//! checks.
//!
//! A model or a person can name a node by its storage id (`finding-raptor-hedges`,
//! `constat-année-parution`, the older `fact-raptor-hedges`, the legacy `f1.1`, `i2.3` or
//! `c0c5`) or by its slug (`goal-01`). `link_nodes` finds those names as whole words and
//! returns the text in parts, so the page can show each name as a link with the node title.
//! A word character is a letter or a digit of any script, `-`, `.` or `_`, and a combining
//! mark that follows such a character. The comparison ignores case. A word is a name only
//! when it holds a hyphen or a digit, so ordinary words such as `goal`, `origin` or
//! `background`, which are also legacy ids and slugs, stay text. A name inside a run of
//! letters stays text, so a name in a text without spaces, such as Chinese, links only when a
//! space or a punctuation mark is beside it.
//!
//! The parser leaves these spans as text: fenced code blocks, inline code, Markdown links,
//! URLs, and citation handles such as `[D1]` or `[W2]`.

/// A node that text can name.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct LinkNode {
    /// The storage id of the node.
    pub id: String,
    /// The slug of the node. The address selects a node by it. Empty before the label pass.
    pub slug: String,
    /// The title that a link shows. Empty before the label pass.
    pub title: String,
}

impl LinkNode {
    /// The name that the address uses to select the node.
    pub fn target(&self) -> &str {
        if self.slug.is_empty() { &self.id } else { &self.slug }
    }

    /// The text of a link: the title, else the slug, else the id.
    pub fn label(&self) -> &str {
        if self.title.is_empty() { self.target() } else { &self.title }
    }
}

/// One part of a text: plain text, or a name of the node at `node` in the node list.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TextPart {
    Text(String),
    Node { name: String, node: usize },
}

fn word_char(c: char) -> bool {
    c.is_alphanumeric() || c == '-' || c == '.' || c == '_'
}

/// A combining mark of the common ranges: Latin, Greek and Cyrillic accents, Hebrew points,
/// Arabic vowel marks, the Devanagari signs and the Japanese sound marks. The standard
/// library has no general category, and a mark outside these ranges ends a word.
fn mark(c: char) -> bool {
    matches!(c,
        '\u{0300}'..='\u{036F}' | '\u{0483}'..='\u{0489}' | '\u{0591}'..='\u{05BD}' | '\u{05BF}'
        | '\u{05C1}'..='\u{05C2}' | '\u{05C4}'..='\u{05C5}' | '\u{05C7}' | '\u{0610}'..='\u{061A}'
        | '\u{064B}'..='\u{065F}' | '\u{0670}' | '\u{06D6}'..='\u{06DC}' | '\u{06DF}'..='\u{06E4}'
        | '\u{06E7}'..='\u{06E8}' | '\u{06EA}'..='\u{06ED}' | '\u{0900}'..='\u{0903}'
        | '\u{093A}'..='\u{094F}' | '\u{0951}'..='\u{0957}' | '\u{0962}'..='\u{0963}'
        | '\u{1AB0}'..='\u{1AFF}' | '\u{1DC0}'..='\u{1DFF}' | '\u{20D0}'..='\u{20FF}'
        | '\u{3099}'..='\u{309A}' | '\u{FE20}'..='\u{FE2F}')
}

/// A character inside a word: a word character, or a mark after one.
fn in_word(c: char) -> bool {
    word_char(c) || mark(c)
}

/// The byte length of a span at `rest` that the parser leaves as text, or 0.
fn skipped(rest: &str) -> usize {
    if let Some(body) = rest.strip_prefix("```") {
        return body.find("```").map(|end| end + 6).unwrap_or(rest.len());
    }
    if let Some(body) = rest.strip_prefix('`') {
        return body.find('`').map(|end| end + 2).unwrap_or(1);
    }
    if rest.starts_with('[') {
        if let Some(close) = rest.find(']') {
            let inner = &rest[1..close];
            // A citation handle: capital letters, then digits.
            let letters = inner.chars().take_while(|c| c.is_ascii_uppercase()).count();
            if letters > 0 && letters < inner.len() && inner[letters..].chars().all(|c| c.is_ascii_digit()) {
                return close + 1;
            }
            // A Markdown link: the text and the target.
            if rest[close + 1..].starts_with('(') {
                if let Some(end) = rest[close + 1..].find(')') {
                    return close + 1 + end + 1;
                }
            }
        }
    }
    let starts = |prefix: &str| {
        rest.as_bytes().get(..prefix.len()).is_some_and(|b| b.eq_ignore_ascii_case(prefix.as_bytes()))
    };
    if starts("http://") || starts("https://") || starts("www.") {
        return rest.find(char::is_whitespace).unwrap_or(rest.len());
    }
    0
}

/// The parts of `text`, with each whole-word name of a node in `nodes` as a node part.
pub fn link_nodes(text: &str, nodes: &[LinkNode]) -> Vec<TextPart> {
    let find = |word: &str| {
        let word = word.to_lowercase();
        nodes.iter().position(|n| n.id.to_lowercase() == word || (!n.slug.is_empty() && n.slug.to_lowercase() == word))
    };
    let mut parts: Vec<TextPart> = Vec::new();
    let mut plain = String::new();
    let mut i = 0;
    let mut previous: Option<char> = None;
    while i < text.len() {
        let rest = &text[i..];
        let skip = skipped(rest);
        if skip > 0 {
            plain.push_str(&rest[..skip]);
            previous = rest[..skip].chars().last();
            i += skip;
            continue;
        }
        let c = rest.chars().next().unwrap_or(' ');
        let starts_word = word_char(c) && !previous.is_some_and(in_word);
        if starts_word {
            let run = rest.find(|ch: char| !in_word(ch)).unwrap_or(rest.len());
            let word = rest[..run].trim_end_matches(['.', '-', '_']);
            let named = (word.contains('-') || word.chars().any(|ch| ch.is_numeric()))
                .then(|| find(word))
                .flatten();
            if let Some(node) = named {
                if !plain.is_empty() {
                    parts.push(TextPart::Text(std::mem::take(&mut plain)));
                }
                parts.push(TextPart::Node { name: word.to_string(), node });
                previous = word.chars().last();
                i += word.len();
                continue;
            }
            plain.push_str(&rest[..run]);
            previous = rest[..run].chars().last();
            i += run;
            continue;
        }
        plain.push(c);
        previous = Some(c);
        i += c.len_utf8();
    }
    if !plain.is_empty() {
        parts.push(TextPart::Text(plain));
    }
    parts
}

/// `text` with each node name replaced by the label of its node, for a text that shows no
/// links, such as a node title on the graph.
pub fn name_nodes(text: &str, nodes: &[LinkNode]) -> String {
    link_nodes(text, nodes)
        .into_iter()
        .map(|part| match part {
            TextPart::Text(t) => t,
            TextPart::Node { node, .. } => nodes[node].label().to_string(),
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn nodes() -> Vec<LinkNode> {
        vec![
            LinkNode { id: "f1.1".into(), slug: "fact-raptor-hedges".into(), title: "Raptor hedges".into() },
            LinkNode { id: "goal-01".into(), slug: "goal-01".into(), title: "Who approved".into() },
            LinkNode { id: "goal".into(), slug: "goal".into(), title: "Legacy goal".into() },
            LinkNode { id: "background".into(), slug: "background".into(), title: "Background".into() },
            LinkNode { id: "c0c5".into(), slug: String::new(), title: String::new() },
        ]
    }

    fn node(name: &str, node: usize) -> TextPart {
        TextPart::Node { name: name.into(), node }
    }

    fn text(t: &str) -> TextPart {
        TextPart::Text(t.into())
    }

    #[test]
    fn legacy_ids_and_slugs_become_node_parts() {
        assert_eq!(link_nodes("Fact f1.1 answers goal-01.", &nodes()),
                   vec![text("Fact "), node("f1.1", 0), text(" answers "), node("goal-01", 1), text(".")]);
        assert_eq!(link_nodes("See fact-raptor-hedges, and c0c5", &nodes()),
                   vec![text("See "), node("fact-raptor-hedges", 0), text(", and "), node("c0c5", 4)]);
    }

    #[test]
    fn ordinary_words_that_match_a_slug_stay_text() {
        let words = "The goal and the background of the goal.";
        assert_eq!(link_nodes(words, &nodes()), vec![text(words)]);
        assert_eq!(link_nodes("goal-012 and xgoal-01 and f1.12", &nodes()),
                   vec![text("goal-012 and xgoal-01 and f1.12")]);
    }

    #[test]
    fn code_links_urls_and_handles_stay_text() {
        for literal in ["`goal-01`", "```\ngoal-01\n```", "[goal-01](https://x.org/goal-01)",
                        "https://x.org/f1.1", "www.f1.1.org", "[D1]"] {
            assert_eq!(link_nodes(literal, &nodes()), vec![text(literal)], "{literal}");
        }
        assert_eq!(link_nodes("[D12] supports f1.1", &nodes()), vec![text("[D12] supports "), node("f1.1", 0)]);
    }

    #[test]
    fn slugs_in_other_scripts_become_node_parts() {
        let nodes = vec![
            LinkNode { id: "constat-année-parution".into(), slug: "constat-année-parution".into(), title: "Année".into() },
            LinkNode { id: "constatare-anulare-alegeri".into(), slug: "constatare-anulare-alegeri".into(), title: String::new() },
            LinkNode { id: "استنتاج-تاريخ-العقد".into(), slug: "استنتاج-تاريخ-العقد".into(), title: String::new() },
            LinkNode { id: "发现-出版年份".into(), slug: "发现-出版年份".into(), title: String::new() },
            LinkNode { id: "निष्कर्ष-तारीख".into(), slug: "निष्कर्ष-तारीख".into(), title: String::new() },
        ];
        assert_eq!(link_nodes("Voir constat-année-parution.", &nodes),
                   vec![text("Voir "), node("constat-année-parution", 0), text(".")]);
        assert_eq!(link_nodes("Vezi Constatare-Anulare-Alegeri, apoi", &nodes),
                   vec![text("Vezi "), node("Constatare-Anulare-Alegeri", 1), text(", apoi")]);
        assert_eq!(link_nodes("انظر استنتاج-تاريخ-العقد هنا", &nodes),
                   vec![text("انظر "), node("استنتاج-تاريخ-العقد", 2), text(" هنا")]);
        assert_eq!(link_nodes("见 发现-出版年份。", &nodes), vec![text("见 "), node("发现-出版年份", 3), text("。")]);
        // A Devanagari vowel sign is a mark inside the word, so the whole slug is one name.
        assert_eq!(link_nodes("देखें निष्कर्ष-तारीख", &nodes), vec![text("देखें "), node("निष्कर्ष-तारीख", 4)]);
        // A longer word and a word inside a run of letters stay text.
        for literal in ["constat-année-parutions", "xconstat-année-parution", "见发现-出版年份"] {
            assert_eq!(link_nodes(literal, &nodes), vec![text(literal)], "{literal}");
        }
    }

    #[test]
    fn names_become_labels_in_a_text_without_links() {
        assert_eq!(name_nodes("Finding for goal-01 from c0c5", &nodes()), "Finding for Who approved from c0c5");
    }
}
