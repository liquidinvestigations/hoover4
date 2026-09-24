//! The investigative lexicon: the shipped files load, and the signal corpus scores.
//!
//! `tests/golden/signals.jsonl` holds two kinds of case. A positive case lists `[category, text]`
//! pairs that must be reported, `text` being the surface form in the source. A `silent` case is text
//! that must raise no unflagged `H` or `M` signal: disclaimers, compliance training, IT prose,
//! quoted replies, ordinary mail in every language the lexicon holds. `L` terms and flagged hits are
//! allowed there, because that is what the tiers and flags are for. A silent case may list `noise`:
//! known false positives that are tolerated so the test passes, and counted against precision so
//! the number stays honest.

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::Instant;

use regex_entity_scanner::lexicon::{Lexicon, Signal, Tier};

fn lexicon() -> &'static Lexicon {
    static LEXICON: OnceLock<Lexicon> = OnceLock::new();
    LEXICON.get_or_init(|| {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("lexicon");
        Lexicon::load(&root).expect("loading the lexicon")
    })
}

#[test]
fn every_language_holds_every_category() {
    let lexicon = lexicon();
    assert!(lexicon.languages().len() >= 4, "{:?}", lexicon.languages());
    for category in lexicon.categories() {
        for lang in lexicon.languages() {
            assert!(
                category.terms.get(lang).copied().unwrap_or(0) > 0,
                "{lang}/{} has no term",
                category.doc.id
            );
        }
        assert!(
            !category.doc.does_not_prove.is_empty(),
            "{}",
            category.doc.id
        );
    }
    assert!(lexicon.empty_categories().is_empty());
}

#[derive(serde::Deserialize)]
struct Case {
    note: String,
    text: String,
    #[serde(default)]
    expect: Vec<(String, String)>,
    #[serde(default)]
    silent: bool,
    #[serde(default)]
    noise: Vec<(String, String)>,
}

fn same_text(signal: &Signal, category: &str, text: &str) -> bool {
    signal.category == category && signal.text.to_lowercase() == text.to_lowercase()
}

/// Strong enough to count on its own: what a silent case must not produce.
fn counts_alone(signal: &Signal) -> bool {
    signal.tier != Tier::L && signal.flags.is_empty()
}

#[test]
fn signal_corpus_precision_and_recall() {
    let lexicon = lexicon();
    let corpus = std::fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden/signals.jsonl"),
    )
    .expect("reading the signal corpus");

    // Per category: (true positives, false positives, false negatives).
    let mut score: BTreeMap<String, (u32, u32, u32)> = BTreeMap::new();
    let mut failures = Vec::new();
    for (line, raw) in corpus.lines().enumerate() {
        let case: Case = serde_json::from_str(raw)
            .unwrap_or_else(|err| panic!("signals.jsonl:{}: {err}", line + 1));
        let signals = lexicon.scan(&case.text, 0);

        for signal in &signals {
            assert_eq!(
                &case.text[signal.start..signal.end],
                signal.text,
                "a signal's offsets must cover exactly its text"
            );
        }

        for (category, text) in &case.expect {
            let entry = score.entry(category.clone()).or_default();
            if signals.iter().any(|s| same_text(s, category, text)) {
                entry.0 += 1;
            } else {
                entry.2 += 1;
                failures.push(format!(
                    "line {}: missed [{category}, {text:?}] ({})",
                    line + 1,
                    case.note
                ));
            }
        }

        if case.silent {
            for signal in signals.iter().filter(|s| counts_alone(s)) {
                score.entry(signal.category.clone()).or_default().1 += 1;
                let tolerated = case
                    .noise
                    .iter()
                    .any(|(category, text)| same_text(signal, category, text));
                if !tolerated {
                    failures.push(format!(
                        "line {}: spurious [{}, {:?}] tier {:?} ({})",
                        line + 1,
                        signal.category,
                        signal.text,
                        signal.tier,
                        case.note
                    ));
                }
            }
        }
    }

    let (mut tp, mut fp, mut fn_) = (0, 0, 0);
    println!("{:<24} {:>5} {:>5} {:>5}", "category", "tp", "fp", "fn");
    for (category, (t, f, n)) in &score {
        println!("{category:<24} {t:>5} {f:>5} {n:>5}");
        tp += t;
        fp += f;
        fn_ += n;
    }
    let precision = f64::from(tp) / f64::from((tp + fp).max(1));
    let recall = f64::from(tp) / f64::from((tp + fn_).max(1));
    println!("signals: precision {precision:.3}, recall {recall:.3} ({tp} tp, {fp} fp, {fn_} fn)");

    assert!(failures.is_empty(), "{}", failures.join("\n"));
}

/// A fragment that repeats one term is the input that turns a per-hit comparison with every
/// earlier hit into a quadratic. The check stage is linear by construction; this holds it there.
#[test]
fn a_fragment_of_one_repeated_term_scans_in_linear_time() {
    let lexicon = lexicon();
    let fragment = "secret, keep this between us > ".repeat(8_000);
    let started = Instant::now();
    let signals = lexicon.scan(&fragment, 0);
    let elapsed = started.elapsed();
    assert!(signals.len() >= 16_000, "{}", signals.len());
    assert!(
        elapsed.as_secs_f64() < 5.0,
        "{} bytes took {elapsed:?}",
        fragment.len()
    );
}

/// Throughput on a mixed-language megabyte, in MB/s, printed rather than asserted: the number
/// depends on the machine and on the build profile. Run it with
/// `cargo test --release --test lexicon -- --ignored --nocapture`.
#[test]
#[ignore]
fn throughput() {
    let lexicon = lexicon();
    let corpus = std::fs::read_to_string(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden/signals.jsonl"),
    )
    .expect("reading the signal corpus");
    let prose = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("README.md");
    let prose = std::fs::read_to_string(prose).expect("reading the README");
    let mut text = String::new();
    while text.len() < 1_000_000 {
        text.push_str(&prose);
        text.push_str(&corpus);
    }
    let started = Instant::now();
    let rounds = 5;
    let mut hits = 0;
    for _ in 0..rounds {
        hits += lexicon.scan(&text, 0).len();
    }
    let seconds = started.elapsed().as_secs_f64() / f64::from(rounds);
    println!(
        "lexicon: {} terms, {:.1} MB in {:.1} ms, {:.0} MB/s, {} signals",
        lexicon.term_count(),
        text.len() as f64 / 1e6,
        seconds * 1e3,
        text.len() as f64 / 1e6 / seconds,
        hits / rounds as usize
    );
}
