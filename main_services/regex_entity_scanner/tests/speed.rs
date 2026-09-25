//! How fast the scan runs, and how its cost and its output behave as a fragment grows.
//!
//! The timed tests assert floors and ratios far from the measured numbers, because they run in a
//! debug build on whatever machine runs the battery. What they catch is a change of kind: the
//! combined candidate set falling back from its lazy DFA to the NFA simulation, which is a factor of
//! twenty, or a retry path whose cost grows with the square of the fragment.

mod support;

use std::collections::BTreeSet;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use regex_entity_scanner::rules;
use regex_entity_scanner::scan::prefilter::Prefilter;

/// The text of every golden case, in corpus order: prose, mail headers, identifiers, money, and
/// the near misses that must stay silent.
fn golden_texts() -> Vec<String> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden/corpus.jsonl");
    let corpus = std::fs::read_to_string(path).expect("reading the golden corpus");
    corpus
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(|line| {
            let case: serde_json::Value = serde_json::from_str(line).expect("a golden case");
            case["text"].as_str().expect("a case text").to_string()
        })
        .collect()
}

/// Mail-shaped text of at least `len` bytes: the README's prose and tables, and the golden cases.
fn mail_like(len: usize) -> String {
    let readme = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("README.md");
    let prose = std::fs::read_to_string(readme).expect("reading the README");
    let cases = golden_texts().join("\n");
    let mut text = String::new();
    while text.len() < len {
        text.push_str(&prose);
        text.push('\n');
        text.push_str(&cases);
        text.push('\n');
    }
    text
}

/// A spreadsheet export of at least `len` bytes: every row carries a decimal amount, a date and a
/// reference number, which is the densest candidate load a real collection produces.
fn csv_like(len: usize) -> String {
    let mut text = String::from("id,name,city,amount,when,note,flag,ref\n");
    let mut row = 1usize;
    while text.len() < len {
        text.push_str(&format!(
            "{row},name{row},city{row},{}.{:02},20{:02}-{:02}-{:02},note text number {row},{},REF-{row:08}\n",
            row * 7,
            row % 100,
            row % 30,
            row % 12 + 1,
            row % 28 + 1,
            row % 2,
        ));
        row += 1;
    }
    text
}

fn megabytes_per_second(bytes: usize, elapsed: Duration) -> f64 {
    bytes as f64 / 1e6 / elapsed.as_secs_f64()
}

/// The combined set is one automaton over every candidate pattern, and its lazy DFA gives up and
/// falls back to the NFA simulation when the states the text drives it through outgrow its cache.
/// A pattern that multiplies those states is enough to do it, and nothing fails: the scan is only
/// twenty times slower. Mail text is what drives the most states.
#[test]
fn the_candidate_set_keeps_its_lazy_dfa() {
    let prefilter = Prefilter::compile(&rules::all()).expect("compiling the rule set");
    let text = mail_like(256 * 1024);
    prefilter.candidates(&text);
    let started = Instant::now();
    let found = prefilter.candidates(&text).len();
    let rate = megabytes_per_second(text.len(), started.elapsed());
    println!(
        "candidate set: {rate:.1} MB/s over {} bytes, {found} candidates",
        text.len()
    );
    assert!(rate > 0.5, "the candidate set ran at {rate:.2} MB/s");
}

/// Runs of candidates the validators reject, each the shape one retry path exists for: money whose
/// marker trails (the resume), addresses that shrink to a shorter reading, digit groups and codes
/// the checks refuse (the interior retry). Eight times the text must cost well under the
/// sixty-four times a quadratic would.
#[test]
fn rejected_runs_scan_in_linear_time() {
    let scanner = support::scanner();
    for unit in [
        "qty 2 EUR 30 ",
        "a@b.co.jp@A ",
        "1234567890123 4567-8901 ",
        "USD1A 1 $x ",
    ] {
        let small = unit.repeat(64 * 1024 / unit.len());
        let large = unit.repeat(512 * 1024 / unit.len());
        scanner.scan(&small, 0);
        let started = Instant::now();
        scanner.scan(&small, 0);
        let small_time = started.elapsed();
        let started = Instant::now();
        scanner.scan(&large, 0);
        let large_time = started.elapsed();
        println!("{unit:?}: 64 KB {small_time:?}, 512 KB {large_time:?}");
        assert!(
            large_time < small_time * 24 + Duration::from_millis(100),
            "{unit:?}: 64 KB took {small_time:?} and 512 KB took {large_time:?}"
        );
    }
}

/// The span of text that has retry budgets of its own in `Scanner::scan`.
const BUDGET_WINDOW: usize = 64 * 1024;

/// A long fragment finds what the same text finds sent as its 64 KB windows. The retry budgets
/// belong to each window, so a caller that sends a document whole gets the matches one that
/// windows it gets. The golden cases are the text, because they are mostly near misses and every
/// near miss spends budget: repeated past five windows, they spend far more than one window's
/// budget would cover for the whole fragment. Newlines pad each window so that no case crosses
/// into the next one and no entity is cut by the comparison itself.
#[test]
fn a_long_fragment_finds_what_its_windows_find() {
    let scanner = support::scanner();
    let cases = golden_texts();
    let mut whole = String::new();
    while whole.len() < 5 * BUDGET_WINDOW + BUDGET_WINDOW / 2 {
        for case in &cases {
            let room = BUDGET_WINDOW - whole.len() % BUDGET_WINDOW;
            if case.len() + 2 > room {
                whole.push_str(&"\n".repeat(room));
            }
            whole.push_str(case);
            whole.push_str("\n\n");
        }
    }
    let key =
        |entity: &regex_entity_scanner::Entity| (entity.start, entity.end, entity.rule_id.clone());
    let from_windows: BTreeSet<_> = (0..whole.len())
        .step_by(BUDGET_WINDOW)
        .flat_map(|at| scanner.scan(&whole[at..(at + BUDGET_WINDOW).min(whole.len())], at))
        .map(|entity| key(&entity))
        .collect();
    let from_whole: BTreeSet<_> = scanner.scan(&whole, 0).iter().map(key).collect();
    let missing: Vec<_> = from_windows.difference(&from_whole).take(10).collect();
    let extra: Vec<_> = from_whole.difference(&from_windows).take(10).collect();
    println!(
        "{} bytes: {} entities from the windows, {} whole",
        whole.len(),
        from_windows.len(),
        from_whole.len()
    );
    assert!(
        missing.is_empty() && extra.is_empty(),
        "only in the windows: {missing:?}\nonly in the whole: {extra:?}"
    );
}

/// Throughput in MB/s, printed rather than asserted: the number depends on the machine and on the
/// build profile. Run it with `cargo test --release --test speed -- --ignored --nocapture`.
///
/// Every sample is scanned once before it is timed. The lazy DFAs build their states from the text
/// they meet, so a cold scanner is several times slower on its first megabyte, and a server runs
/// warm.
#[test]
#[ignore]
fn throughput() {
    let scanner = support::scanner();
    let cases = golden_texts();
    let mail = mail_like(1_000_000);
    let csv = csv_like(1_000_000);
    let mut messages = Vec::new();
    let mut at = 0;
    while at < mail.len() {
        let end = mail[at..]
            .char_indices()
            .skip(4096)
            .find(|&(_, c)| c == '\n')
            .map_or(mail.len(), |(offset, _)| at + offset + 1);
        messages.push(&mail[at..end]);
        at = end;
    }
    for (name, texts) in [
        (
            "golden cases, one per call",
            cases.iter().map(String::as_str).collect(),
        ),
        ("mail-like, 4 KB per call", messages),
        ("mail-like, one 1 MB fragment", vec![mail.as_str()]),
        ("csv-like, one 1 MB fragment", vec![csv.as_str()]),
    ] {
        let bytes: usize = texts.iter().map(|text| text.len()).sum();
        let rounds = 5;
        let mut entities = 0;
        for text in &texts {
            scanner.scan(text, 0);
        }
        let started = Instant::now();
        for _ in 0..rounds {
            for text in &texts {
                entities += scanner.scan(text, 0).len();
            }
        }
        let rate = megabytes_per_second(bytes * rounds, started.elapsed());
        println!("{name}: {rate:.1} MB/s, {} entities", entities / rounds);
    }
}
