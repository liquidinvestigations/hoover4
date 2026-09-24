//! From automaton matches to signals: nesting, and the flags that mark a weak hit.
//!
//! Every check here runs per hit or once per fragment, never per byte of the text again. Hits are
//! sparse, so this stage costs little next to the fold and the match. It is the lexicon's version of
//! the entity pipeline's validator: the place where anything that needs context happens, because the
//! match itself is a literal search.
//!
//! The flags annotate rather than drop. Compliance training that says "never keep funds off the
//! books" is exactly the text the `negated` flag catches, and it can still be what an investigator
//! wants to read.

use super::fold::Folded;
use super::SignalFlag;

/// Negation words, in every language the lexicon holds, folded. A term preceded by one of them
/// within [`NEGATION_WINDOW`] words is flagged. A term that contains its own negation (`do not
/// volunteer information`) is unaffected, because only the words before the term are read.
const NEGATIONS: &[&str] = &[
    // en
    "not",
    "never",
    "no",
    "dont",
    "doesnt",
    "didnt",
    "wont",
    "cannot",
    "cant",
    "shouldnt",
    "mustnt",
    "avoid",
    "without",
    "prohibited",
    "forbidden", // de
    "nicht",
    "nie",
    "niemals",
    "kein",
    "keine",
    "keinen",
    "keinesfalls",
    "ohne",
    "verboten",
    // fr
    "ne",
    "pas",
    "jamais",
    "aucun",
    "aucune",
    "sans",
    "interdit", // ru
    "не",
    "нет",
    "никогда",
    "без",
    "нельзя",
    "запрещено",
];

/// Words after a negation that turn it into something else: `not only`, `no doubt`.
const PSEUDO_NEGATION_FOLLOWERS: &[&str] = &[
    "only",
    "just",
    "doubt",
    "nur",
    "zweifel",
    "seulement",
    "doute",
    "только",
    "сомнения",
];

/// How many words before a term a negation reaches. The clinical negation literature settled on
/// five; a longer window starts negating the next clause.
const NEGATION_WINDOW: usize = 5;

/// Disclaimer openers, folded. A hit in the paragraph one of these opens is flagged
/// `boilerplate`: without it, `confidential` fires on every corporate email in a collection.
const DISCLAIMER_OPENERS: &[&str] = &[
    "this email and any attachments",
    "this e mail and any attachments",
    "this message and any attachments",
    "this email is confidential",
    "this message is confidential",
    "if you are not the intended recipient",
    "the information contained in this",
    "diese e mail enthalt vertrauliche",
    "diese nachricht enthalt vertrauliche",
    "wenn sie nicht der richtige adressat",
    "sollten sie nicht der vorgesehene empfanger",
    "ce message et toutes les pieces jointes",
    "ce courriel et toutes les pieces jointes",
    "si vous netes pas le destinataire",
    "si vous n etes pas le destinataire",
    "это сообщение и любые приложения",
    "данное сообщение содержит конфиденциальную",
    "если вы не являетесь адресатом",
    "если вы получили это сообщение по ошибке",
];

/// Lines that start a quoted or forwarded message, lowercased and trimmed. Everything below the
/// first one repeats earlier mail.
const REPLY_HEADERS: &[&str] = &[
    "-----original message-----",
    "-----ursprüngliche nachricht-----",
    "-----message d'origine-----",
    "-----исходное сообщение-----",
    "---------- forwarded message",
    "-------- weitergeleitete nachricht",
    "-------- message transféré",
    "-------- пересылаемое сообщение",
];

/// The endings of an attribution line: `On Monday, Anna wrote:`.
const ATTRIBUTION_ENDINGS: &[&str] = &[
    "wrote:",
    "schrieb:",
    "a écrit :",
    "a écrit:",
    "написал:",
    "написала:",
    "написал(а):",
];

pub struct Hit {
    pub term: usize,
    pub category: usize,
    /// Folded byte span of the term, without the padding spaces.
    pub start: usize,
    pub end: usize,
}

/// Within one category, a hit inside a longer hit is the same evidence counted twice: `cover up`
/// inside `cover up the losses`. Two terms of one category that compile to the same span (a word
/// spelled alike in two languages) are one piece of evidence too. Across categories both stay,
/// because the two readings are both true.
///
/// One pass after a sort. Sorted by start and then by descending end, a hit is contained in an
/// earlier one exactly when some earlier hit of its category ends at or after it, so a running
/// maximum decides it. Comparing each hit with every earlier one would be quadratic in a fragment
/// that repeats one word, which is the input an adversary would send.
pub fn drop_nested(hits: &mut Vec<Hit>) {
    hits.sort_by(|a, b| {
        (a.category, a.start, std::cmp::Reverse(a.end), a.term).cmp(&(
            b.category,
            b.start,
            std::cmp::Reverse(b.end),
            b.term,
        ))
    });
    let mut kept: Vec<Hit> = Vec::with_capacity(hits.len());
    let mut category = usize::MAX;
    let mut furthest_end = 0;
    for hit in hits.drain(..) {
        if hit.category != category {
            category = hit.category;
            furthest_end = 0;
        }
        if hit.end <= furthest_end {
            continue;
        }
        furthest_end = hit.end;
        kept.push(hit);
    }
    *hits = kept;
}

/// Sorted, merged byte ranges with a logarithmic membership test.
struct Ranges(Vec<(usize, usize)>);

impl Ranges {
    fn new(mut ranges: Vec<(usize, usize)>) -> Self {
        ranges.sort_unstable();
        let mut merged: Vec<(usize, usize)> = Vec::with_capacity(ranges.len());
        for (start, end) in ranges {
            match merged.last_mut() {
                Some(last) if start <= last.1 => last.1 = last.1.max(end),
                _ => merged.push((start, end)),
            }
        }
        Self(merged)
    }

    fn contains(&self, at: usize) -> bool {
        let index = self.0.partition_point(|(start, _)| *start <= at);
        index > 0 && at < self.0[index - 1].1
    }
}

/// How many disclaimer paragraphs one fragment is searched for. Each costs a search for its
/// paragraph's edges, and a fragment made of nothing but disclaimers must not buy unbounded work.
const MAX_DISCLAIMERS: usize = 64;

/// What the flags need to know about one fragment, computed once.
pub struct Context<'a> {
    source: &'a str,
    folded: &'a Folded,
    /// Source offset where quoted or forwarded text begins, if it does.
    quoted_from: Option<usize>,
    /// Source byte ranges of lines that begin with `>`.
    quote_lines: Ranges,
    /// Source byte ranges of paragraphs that open like a disclaimer.
    boilerplate: Ranges,
}

impl<'a> Context<'a> {
    pub fn new(source: &'a str, folded: &'a Folded) -> Self {
        let mut quoted_from = None;
        let mut quote_lines = Vec::new();
        let mut offset = 0;
        // A header block at the very top is the message's own header, not a quoted one, so a
        // separator only counts once the message has said something.
        let mut seen_content = false;
        let lines: Vec<&str> = source.split_inclusive('\n').collect();
        for (index, line) in lines.iter().enumerate() {
            let trimmed = line.trim();
            let lower = trimmed.to_lowercase();
            if quoted_from.is_none()
                && seen_content
                && starts_quoted_text(&lower, &lines[index + 1..])
            {
                quoted_from = Some(offset);
            }
            if !trimmed.is_empty() && !starts_quoted_text(&lower, &lines[index + 1..]) {
                seen_content = true;
            }
            if trimmed.starts_with('>') {
                quote_lines.push((offset, offset + line.len()));
            }
            offset += line.len();
        }

        let mut boilerplate = Vec::new();
        'openers: for opener in DISCLAIMER_OPENERS {
            let needle = format!(" {opener} ");
            let mut from = 0;
            while let Some(found) = folded.text[from..].find(&needle) {
                if boilerplate.len() == MAX_DISCLAIMERS {
                    break 'openers;
                }
                let at = folded.source_start(from + found + 1);
                boilerplate.push(paragraph_around(source, at));
                from += found + 1;
            }
        }

        Self {
            source,
            folded,
            quoted_from,
            quote_lines: Ranges::new(quote_lines),
            boilerplate: Ranges::new(boilerplate),
        }
    }

    /// The flags for a hit at folded offset `folded_start` and source offset `source_start`.
    pub fn flags(&self, folded_start: usize, source_start: usize) -> Vec<SignalFlag> {
        let mut flags = Vec::new();
        if self.negated(folded_start, self.source, source_start) {
            flags.push(SignalFlag::Negated);
        }
        if self.quote_lines.contains(source_start)
            || self.quoted_from.is_some_and(|from| source_start >= from)
        {
            flags.push(SignalFlag::Quoted);
        }
        if self.boilerplate.contains(source_start) {
            flags.push(SignalFlag::Boilerplate);
        }
        flags
    }

    /// Reads only the few words before the hit, walking backwards, so the cost does not grow with
    /// the hit's position in the fragment. The window also stops at the start of the hit's clause:
    /// in "I'm not comfortable with this, I want no part of this" the `not` belongs to the first
    /// clause and says nothing about the second.
    fn negated(&self, folded_start: usize, source: &str, source_start: usize) -> bool {
        let clause_start = source[..source_start]
            .rfind(['.', ',', ';', ':', '!', '?', '\n'])
            .map_or(0, |at| at + 1);
        let text = self.folded.text.as_str();
        let mut window: Vec<&str> = Vec::with_capacity(NEGATION_WINDOW);
        // `text[folded_start - 1]` is the space before the term.
        let mut end = folded_start.saturating_sub(1);
        while window.len() < NEGATION_WINDOW && end > 0 {
            let start = text[..end].rfind(' ').map_or(0, |at| at + 1);
            if start >= end || self.folded.source_start(start) < clause_start {
                break;
            }
            window.push(&text[start..end]);
            end = start.saturating_sub(1);
        }
        window.reverse();
        window.iter().enumerate().any(|(index, word)| {
            NEGATIONS.contains(word)
                && !window
                    .get(index + 1)
                    .is_some_and(|next| PSEUDO_NEGATION_FOLLOWERS.contains(next))
        })
    }
}

/// Whether a line starts the quoted part of a message: a reply or forward separator, an attribution
/// line, or an Outlook-style header block (`From:` followed within three lines by `Sent:`).
fn starts_quoted_text(lower: &str, following: &[&str]) -> bool {
    if REPLY_HEADERS.iter().any(|header| lower.starts_with(header)) {
        return true;
    }
    if ATTRIBUTION_ENDINGS
        .iter()
        .any(|ending| lower.ends_with(ending))
        && lower.len() < 200
    {
        return true;
    }
    const FROM: &[&str] = &["from:", "von:", "de :", "de:", "от:"];
    const SENT: &[&str] = &["sent:", "gesendet:", "envoyé :", "envoyé:", "отправлено:"];
    FROM.iter().any(|label| lower.starts_with(label))
        && following.iter().take(3).any(|line| {
            let next = line.trim().to_lowercase();
            SENT.iter().any(|label| next.starts_with(label))
        })
}

/// The source range of the paragraph around `at`: from the blank line before it to the blank line
/// after it, or the fragment's ends.
fn paragraph_around(source: &str, at: usize) -> (usize, usize) {
    let start = source[..at]
        .rfind("\n\n")
        .or_else(|| source[..at].rfind("\n\r\n"))
        .map_or(0, |found| found + 1);
    let end = source[at..]
        .find("\n\n")
        .or_else(|| source[at..].find("\r\n\r\n"))
        .map_or(source.len(), |found| at + found);
    (start, end)
}

/// The folded forms above must already be folded, or they never match. Checked in a test rather
/// than folded at startup, so the lists stay readable as the strings they match.
#[cfg(test)]
mod tests {
    use super::{Context, SignalFlag, DISCLAIMER_OPENERS, NEGATIONS};
    use crate::lexicon::fold::fold;

    #[test]
    fn the_built_in_lists_are_already_folded() {
        for word in NEGATIONS.iter().chain(DISCLAIMER_OPENERS) {
            assert_eq!(
                fold(word).text.trim(),
                *word,
                "{word:?} is not in folded form"
            );
        }
    }

    fn flags_at(source: &str, word: &str) -> Vec<SignalFlag> {
        let folded = fold(source);
        let context = Context::new(source, &folded);
        let folded_start = folded.text.find(word).expect("the word is in the text");
        context.flags(folded_start, folded.source_start(folded_start))
    }

    #[test]
    fn negation_reaches_five_words_back_and_no_further() {
        assert_eq!(
            flags_at(
                "We must never keep anything off the books.",
                "off the books"
            ),
            vec![SignalFlag::Negated]
        );
        assert!(flags_at(
            "Never mind that, the plan is to keep it all off the books.",
            "off the books"
        )
        .is_empty());
        assert!(flags_at("It was not only off the books.", "off the books").is_empty());
    }

    #[test]
    fn quoted_replies_and_disclaimers_are_flagged() {
        let mail = "Fine by me.\n\nOn Monday, Anna wrote:\n> keep it off the books\n";
        assert_eq!(flags_at(mail, "off the books"), vec![SignalFlag::Quoted]);
        let footer = "See you.\n\nThis email and any attachments are confidential and may be \
                      privileged.\n";
        assert_eq!(
            flags_at(footer, "confidential"),
            vec![SignalFlag::Boilerplate]
        );
    }
}
