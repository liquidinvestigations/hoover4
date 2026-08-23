//! The golden corpus: labelled fragments, scored as precision and recall.
//!
//! This is the test that decides whether a rule change was an improvement. Unit tests pin
//! individual behaviours; only a labelled corpus answers "did this pattern start swallowing
//! version numbers", which is the way this kind of system actually fails.
//!
//! Fixtures name the surface form and the canonical value rather than byte offsets. Offsets
//! counted by hand are wrong often enough to make a corpus not worth extending. The harness checks
//! separately that every reported span really does cover the text it claims.
//!
//! Negative cases matter as much as positive ones: roughly half the corpus is fragments where the
//! right answer is nothing at all.

mod support;

use std::collections::HashMap;

use regex_entity_scanner::model::{Entity, Value};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct Case {
    name: String,
    text: String,
    #[serde(default)]
    expect: Vec<Expected>,
}

#[derive(Debug, Deserialize, PartialEq, Eq, Hash, Clone)]
struct Expected {
    #[serde(rename = "type")]
    entity_type: String,
    text: String,
    value: String,
}

/// The comparable form of an actual match: type, surface form, canonical value.
fn observed(entity: &Entity) -> Expected {
    let value = match &entity.value {
        Value::Date { rfc3339, .. } => rfc3339.clone(),
        Value::Email { address, .. } => address.clone(),
        Value::Phone { e164, .. } => e164.clone(),
        Value::Money {
            currency,
            amount_minor,
            ..
        } => format!("{currency} {amount_minor}"),
        Value::Identifier { compact, .. } => compact.clone(),
        Value::NetworkAddress { address, .. } => address.clone(),
        Value::GeoPoint {
            latitude,
            longitude,
            ..
        } => format!("{latitude},{longitude}"),
    };
    Expected {
        entity_type: serde_json::to_value(entity.entity_type)
            .expect("entity type serialises")
            .as_str()
            .expect("as a string")
            .to_string(),
        text: entity.text.clone(),
        value,
    }
}

#[test]
fn corpus_precision_and_recall() {
    let scanner = support::scanner();
    let corpus = std::fs::read_to_string(
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/golden/corpus.jsonl"),
    )
    .expect("reading the golden corpus");

    let mut true_positives = 0usize;
    let mut false_positives: Vec<(String, Expected)> = Vec::new();
    let mut false_negatives: Vec<(String, Expected)> = Vec::new();

    for line in corpus.lines().filter(|line| !line.trim().is_empty()) {
        let case: Case = serde_json::from_str(line).expect("a well-formed corpus line");
        let entities = scanner.scan(&case.text, 0);

        for entity in &entities {
            assert_eq!(
                &case.text[entity.start..entity.end],
                entity.text,
                "in {:?} the span {}..{} does not cover the reported text",
                case.name,
                entity.start,
                entity.end
            );
        }

        // Multiset comparison: a fragment may legitimately contain the same address twice.
        let mut wanted: HashMap<Expected, isize> = HashMap::new();
        for expected in &case.expect {
            *wanted.entry(expected.clone()).or_default() += 1;
        }
        for entity in &entities {
            let seen = observed(entity);
            match wanted.get_mut(&seen) {
                Some(count) if *count > 0 => {
                    *count -= 1;
                    true_positives += 1;
                }
                _ => false_positives.push((case.name.clone(), seen)),
            }
        }
        for (expected, count) in wanted {
            for _ in 0..count.max(0) {
                false_negatives.push((case.name.clone(), expected.clone()));
            }
        }
    }

    let precision = ratio(true_positives, false_positives.len());
    let recall = ratio(true_positives, false_negatives.len());
    println!(
        "golden corpus: precision {precision:.3} recall {recall:.3} \
         ({true_positives} correct, {} spurious, {} missed)",
        false_positives.len(),
        false_negatives.len()
    );

    assert!(
        false_positives.is_empty() && false_negatives.is_empty(),
        "spurious: {false_positives:#?}\nmissed: {false_negatives:#?}"
    );
}

fn ratio(correct: usize, wrong: usize) -> f64 {
    if correct + wrong == 0 {
        1.0
    } else {
        correct as f64 / (correct + wrong) as f64
    }
}
