//! Securities identifiers: ISIN, CUSIP, SEDOL.
//!
//! The fixtures are the documented examples from `stdnum/isin.py`, `stdnum/cusip.py` and
//! `stdnum/gb/sedol.py`, each module's valid number and the counterpart that differs only in the
//! check digit. The subset covers what separates the three: the ISIN's country prefix and Luhn over
//! the letter-expanded form, the CUSIP's alternating-weight variant, the SEDOL's vowel-free
//! alphabet, and the cue word both bare tokens require.

mod support;

use regex_entity_scanner::model::{EntityType, Value};

fn scheme_and_compact(text: &str) -> (String, String) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
    assert_eq!(entities[0].entity_type, EntityType::Security);
    match &entities[0].value {
        Value::Identifier {
            scheme, compact, ..
        } => (scheme.clone(), compact.clone()),
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

fn rejects(text: &str) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert!(entities.is_empty(), "{text:?} produced {entities:?}");
}

#[test]
fn accepts_a_documented_isin_and_reports_its_country() {
    let scanner = support::scanner();
    let entities = scanner.scan("holding US0378331005 at par", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].rule_id, "security.isin");
    match &entities[0].value {
        Value::Identifier {
            scheme,
            compact,
            country,
            parts,
        } => {
            assert_eq!(scheme, "isin");
            assert_eq!(compact, "US0378331005");
            assert_eq!(country.as_deref(), Some("US"));
            assert_eq!(
                parts.get("national_number").map(String::as_str),
                Some("037833100")
            );
        }
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

/// `XS` is the allocation for internationally cleared securities rather than a country, and an
/// investigative corpus full of Eurobonds would be empty without it.
#[test]
fn accepts_an_internationally_cleared_isin_without_claiming_a_country() {
    let scanner = support::scanner();
    let entities = scanner.scan("bond XS1748848295 matured", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    match &entities[0].value {
        Value::Identifier {
            compact, country, ..
        } => {
            assert_eq!(compact, "XS1748848295");
            assert_eq!(country.as_deref(), None);
        }
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

#[test]
fn rejects_isin_shaped_runs_that_do_not_check_out() {
    // The documented invalid-checksum counterpart.
    rejects("holding US0378331003 at par");
    // ZQ is not a country and not one of the allocations ISO 6166 makes.
    rejects("holding ZQ0378331005 at par");
}

/// Both bare tokens need the word beside them. Without it a nine-character part number and a
/// seven-character reference code pass their check digits often enough to ruin the facet.
#[test]
fn bare_securities_tokens_need_a_cue_word() {
    let (scheme, compact) = scheme_and_compact("CUSIP DUS0421C5 confirmed");
    assert_eq!(scheme, "cusip");
    assert_eq!(compact, "DUS0421C5");

    let (scheme, compact) = scheme_and_compact("SEDOL B15KXQ8 confirmed");
    assert_eq!(scheme, "sedol");
    assert_eq!(compact, "B15KXQ8");

    rejects("part number DUS0421C5 confirmed");
    rejects("reference B15KXQ8 confirmed");
}

#[test]
fn rejects_securities_tokens_whose_check_digit_disagrees() {
    // The documented invalid counterparts, cue word present in both.
    rejects("CUSIP DUS0421C4 confirmed");
    rejects("SEDOL B15KXQ7 confirmed");
    // A digit-led SEDOL has to be entirely numeric; this one is not.
    rejects("SEDOL 1B5KXQ8 confirmed");
}
