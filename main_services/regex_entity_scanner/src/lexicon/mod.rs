//! The investigative lexicon: term lists matched as whole words, reported as signals.
//!
//! This runs beside the entity pipeline, not inside it. An entity is a validated, normalised value;
//! a signal is a place a reader may want to look, and nothing about a word being present makes it
//! true. The two never meet in `resolve`, because a lexicon hit on `claim` must not delete an
//! insurance-policy number it happens to overlap.
//!
//! ```text
//! fragment ─► fold ─► match ─► check ─► signals ─► summarise (per category, for storage)
//! ```
//!
//! - **fold** normalises the fragment once (`fold.rs`). Arabic and Hebrew terms also compile with
//!   the proclitics those scripts join to a word (`clitics.rs`).
//! - **match** is one Aho-Corasick pass over the folded text with every term of every language.
//!   A regex alternation of the same terms was measured at under 0.2 MB/s at ten thousand terms,
//!   an order of magnitude slower than the whole entity scan; the automaton stays above 100 MB/s at
//!   two hundred thousand.
//! - **check** turns matches into signals: word boundaries, nesting inside one category, and the
//!   flags that say why a hit is weak (`check.rs`).

mod check;
mod clitics;
pub mod fold;
mod load;

use std::collections::{BTreeMap, HashMap};
use std::path::Path;

use aho_corasick::{AhoCorasick, AhoCorasickKind, MatchKind};
use anyhow::{Context, Result};
use serde::Serialize;

/// How much one hit is worth in a category score, by tier.
const WEIGHT_H: f32 = 1.0;
const WEIGHT_M: f32 = 0.4;
const WEIGHT_L: f32 = 0.1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize)]
pub enum Tier {
    H,
    M,
    L,
}

/// Who usually writes a term. The people involved in something write euphemisms; the people
/// accusing them write the direct word. A hit on `fraud` is mostly evidence that someone is
/// complaining, which is worth finding for a different reason.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Speaker {
    Actor,
    Insider,
    Accuser,
    Neutral,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum Review {
    Original,
    MtEdited,
    Native,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Boundary {
    /// Whole words on both sides.
    Word,
    /// A whole-word start; the last word may continue (`bestech*`).
    Prefix,
}

/// Why a hit counts for less than its tier says. A flagged hit is still reported, so a reader can
/// see it and see why it was discounted.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SignalFlag {
    /// A negation stands within five words before the term: `we must never backdate`.
    Negated,
    /// The hit is in a quoted reply or below a forwarded-message header, so it repeats text the
    /// thread already holds.
    Quoted,
    /// The hit is in a paragraph that opens like an email disclaimer.
    Boilerplate,
}

#[derive(Debug, Clone, Serialize)]
pub struct CategoryDoc {
    pub id: String,
    pub title: String,
    pub catches: String,
    pub does_not_prove: String,
}

/// One row of a term file.
#[derive(Debug, Clone)]
pub struct Term {
    pub term: String,
    pub folded: String,
    pub boundary: Boundary,
    pub category: usize,
    pub lang: String,
    pub tier: Tier,
    pub speaker: Speaker,
    pub concept: String,
    pub source: String,
    pub review: Review,
    pub note: String,
    /// The line in its file, for load errors.
    pub line: usize,
}

/// One match, with byte offsets into the source document like an entity's.
#[derive(Debug, Clone, Serialize)]
pub struct Signal {
    pub category: String,
    /// The term as the lexicon writes it, with its trailing `*` if it is a stem.
    pub term: String,
    /// The English term this row expresses; the same concept in another language shares it.
    pub concept: String,
    pub lang: String,
    pub tier: Tier,
    pub speaker: Speaker,
    pub start: usize,
    pub end: usize,
    /// Exactly `source[start..end]`.
    pub text: String,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub flags: Vec<SignalFlag>,
}

/// One category's signals in one text, deduplicated per term.
#[derive(Debug, Serialize)]
pub struct CategorySummary {
    /// `1 − ∏(1 − wᵢ)` over the distinct terms, after the flags and the rule that an `L` term only
    /// counts beside a stronger signal. It saturates towards one and repeating a term does not
    /// raise it. A sort key, not a probability.
    pub score: f32,
    /// Distinct terms that counted toward the score, by tier. The thresholds a caller sets are on
    /// these counts: rule-based detectors that work require several distinct terms, never one.
    pub counted: BTreeMap<Tier, u32>,
    pub terms: Vec<TermSummary>,
}

#[derive(Debug, Serialize)]
pub struct TermSummary {
    pub term: String,
    pub concept: String,
    pub lang: String,
    pub tier: Tier,
    pub speaker: Speaker,
    pub count: u32,
    /// The surface form of the first occurrence.
    pub text: String,
    /// The flags carried by every occurrence. A term negated once and asserted once carries none.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub flags: Vec<SignalFlag>,
}

/// The public view of one category, for `/signals`.
#[derive(Debug, Serialize)]
pub struct CategoryInfo<'a> {
    #[serde(flatten)]
    pub doc: &'a CategoryDoc,
    /// Terms per language.
    pub terms: &'a BTreeMap<String, usize>,
}

pub struct Lexicon {
    categories: Vec<CategoryDoc>,
    languages: Vec<String>,
    terms: Vec<Term>,
    /// For each automaton pattern, the terms that compile to it. Two languages can spell a term the
    /// same way (`attentat*` in German and French), and both must answer.
    pattern_terms: Vec<Vec<u32>>,
    automaton: AhoCorasick,
    counts: Vec<BTreeMap<String, usize>>,
    version: String,
}

impl Lexicon {
    /// Reads `RES_LEXICON_DIR`, defaulting to `./lexicon`.
    pub fn load_from_env() -> Result<Self> {
        let root = std::env::var("RES_LEXICON_DIR").unwrap_or_else(|_| "lexicon".to_string());
        Self::load(Path::new(&root))
    }

    pub fn load(root: &Path) -> Result<Self> {
        let loaded = load::load(root)?;
        let mut patterns: Vec<String> = Vec::new();
        let mut pattern_terms: Vec<Vec<u32>> = Vec::new();
        let mut index: HashMap<String, usize> = HashMap::new();
        // The folded text has exactly one space at every word boundary and at both ends, so a
        // whole word is a literal search for the term between two spaces.
        let pattern_of = |folded: &str, boundary: Boundary| match boundary {
            Boundary::Word => format!(" {folded} "),
            Boundary::Prefix => format!(" {folded}"),
        };
        for (term_index, term) in loaded.terms.iter().enumerate() {
            let pattern = pattern_of(&term.folded, term.boundary);
            let slot = *index.entry(pattern.clone()).or_insert_with(|| {
                patterns.push(pattern);
                pattern_terms.push(Vec::new());
                patterns.len() - 1
            });
            pattern_terms[slot].push(term_index as u32);
        }
        // A proclitic variant that some row spells out is that row's, never a second reading.
        let written = patterns.len();
        for (term_index, term) in loaded.terms.iter().enumerate() {
            for variant in clitics::variants(&term.folded) {
                let pattern = pattern_of(&variant, term.boundary);
                let slot = *index.entry(pattern.clone()).or_insert_with(|| {
                    patterns.push(pattern);
                    pattern_terms.push(Vec::new());
                    patterns.len() - 1
                });
                if slot >= written && !pattern_terms[slot].contains(&(term_index as u32)) {
                    pattern_terms[slot].push(term_index as u32);
                }
            }
        }
        // Contiguous NFA, pinned: a DFA is faster on a few thousand patterns but needed over a
        // gigabyte at ninety thousand and was slower there, because its tables fall out of cache.
        // Standard semantics with overlapping search lets two adjacent terms share the space
        // between them.
        let automaton = AhoCorasick::builder()
            .kind(Some(AhoCorasickKind::ContiguousNFA))
            .match_kind(MatchKind::Standard)
            .build(&patterns)
            .context("compiling the lexicon automaton")?;
        let counts = load::counts(&loaded.terms, loaded.categories.len());
        Ok(Self {
            categories: loaded.categories,
            languages: loaded.languages,
            terms: loaded.terms,
            pattern_terms,
            automaton,
            counts,
            version: loaded.version,
        })
    }

    /// A content hash of every file the lexicon was loaded from. It changes when any term changes,
    /// so a consumer that stores signals knows which texts a lexicon edit has made stale, without
    /// touching the entity index and its `rule_set_version`.
    pub fn version(&self) -> &str {
        &self.version
    }

    pub fn term_count(&self) -> usize {
        self.terms.len()
    }

    pub fn languages(&self) -> &[String] {
        &self.languages
    }

    pub fn categories(&self) -> Vec<CategoryInfo<'_>> {
        self.categories
            .iter()
            .zip(&self.counts)
            .map(|(doc, terms)| CategoryInfo { doc, terms })
            .collect()
    }

    /// The categories with no term in some language. Loading refuses a missing file, but an empty
    /// one is a category that silently matches nothing in that language.
    pub fn empty_categories(&self) -> Vec<String> {
        let mut out = Vec::new();
        for (doc, counts) in self.categories.iter().zip(&self.counts) {
            for lang in &self.languages {
                if counts.get(lang).copied().unwrap_or(0) == 0 {
                    out.push(format!("{lang}/{}", doc.id));
                }
            }
        }
        out
    }

    /// Every signal in `fragment`, with offsets shifted by `base_offset` like entities.
    pub fn scan(&self, fragment: &str, base_offset: usize) -> Vec<Signal> {
        let folded = fold::fold(fragment);
        let context = check::Context::new(fragment, &folded);
        let mut hits: Vec<check::Hit> = Vec::new();
        for found in self.automaton.find_overlapping_iter(folded.text.as_str()) {
            let (start, mut end) = (found.start() + 1, found.end());
            let first = self.pattern_terms[found.pattern().as_usize()][0] as usize;
            match self.terms[first].boundary {
                Boundary::Word => end -= 1,
                // A stem's span runs to the end of the word it starts.
                Boundary::Prefix => {
                    end += folded.text[end..].find(' ').unwrap_or(0);
                }
            }
            for &term in &self.pattern_terms[found.pattern().as_usize()] {
                hits.push(check::Hit {
                    term: term as usize,
                    category: self.terms[term as usize].category,
                    start,
                    end,
                });
            }
        }
        check::drop_nested(&mut hits);
        hits.into_iter()
            .map(|hit| {
                let term = &self.terms[hit.term];
                let source_start = folded.source_start(hit.start);
                let source_end = folded.source_end(fragment, hit.end - 1);
                Signal {
                    category: self.categories[term.category].id.clone(),
                    term: term.term.clone(),
                    concept: term.concept.clone(),
                    lang: term.lang.clone(),
                    tier: term.tier,
                    speaker: term.speaker,
                    start: source_start + base_offset,
                    end: source_end + base_offset,
                    text: fragment[source_start..source_end].to_string(),
                    flags: context.flags(hit.start, source_start),
                }
            })
            .collect()
    }

    /// Collapses one text's signals into per-category summaries, the shape a storage consumer keeps.
    pub fn summarise(&self, signals: &[Signal]) -> BTreeMap<String, CategorySummary> {
        // An `L` term is a common word. It counts only when something stronger, unflagged, is in
        // the same text; alone it is noise by construction.
        let corroborated = signals
            .iter()
            .any(|signal| signal.tier != Tier::L && signal.flags.is_empty());

        let mut by_category: BTreeMap<String, BTreeMap<(String, String), TermSummary>> =
            BTreeMap::new();
        for signal in signals {
            let terms = by_category.entry(signal.category.clone()).or_default();
            let key = (signal.lang.clone(), signal.term.clone());
            match terms.get_mut(&key) {
                Some(summary) => {
                    summary.count += 1;
                    summary.flags.retain(|flag| signal.flags.contains(flag));
                }
                None => {
                    terms.insert(
                        key,
                        TermSummary {
                            term: signal.term.clone(),
                            concept: signal.concept.clone(),
                            lang: signal.lang.clone(),
                            tier: signal.tier,
                            speaker: signal.speaker,
                            count: 1,
                            text: signal.text.clone(),
                            flags: signal.flags.clone(),
                        },
                    );
                }
            }
        }

        by_category
            .into_iter()
            .map(|(category, terms)| {
                let mut remaining = 1.0f32;
                let mut counted: BTreeMap<Tier, u32> = BTreeMap::new();
                for summary in terms.values() {
                    let weight = weight(summary, corroborated);
                    if weight > 0.0 {
                        remaining *= 1.0 - weight;
                        *counted.entry(summary.tier).or_insert(0) += 1;
                    }
                }
                let score = ((1.0 - remaining) * 1000.0).round() / 1000.0;
                (
                    category,
                    CategorySummary {
                        score,
                        counted,
                        terms: terms.into_values().collect(),
                    },
                )
            })
            .collect()
    }
}

fn weight(summary: &TermSummary, corroborated: bool) -> f32 {
    if summary
        .flags
        .iter()
        .any(|flag| matches!(flag, SignalFlag::Quoted | SignalFlag::Boilerplate))
    {
        return 0.0;
    }
    let base = match summary.tier {
        Tier::H => WEIGHT_H,
        Tier::M => WEIGHT_M,
        Tier::L if corroborated => WEIGHT_L,
        Tier::L => 0.0,
    };
    if summary.flags.contains(&SignalFlag::Negated) {
        base * 0.5
    } else {
        base
    }
}
