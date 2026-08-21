//! Ship and container identifiers.
//!
//! The fixtures are the documented examples from `stdnum/imo.py` and `stdnum/iso6346.py`, plus
//! MMSIs whose Maritime Identification Digits are in the vendored ITU list. The subset covers what
//! separates the three: the IMO number's weighted check digit and its dependence on a marker or a
//! cue word, the MMSI's total absence of a checksum, and the container number's category letter
//! and grouped written form.

mod support;

use regex_entity_scanner::model::{EntityType, Flag, Value};

fn only_match(text: &str) -> (String, String, Option<String>) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
    match &entities[0].value {
        Value::Identifier {
            scheme,
            compact,
            country,
            ..
        } => (scheme.clone(), compact.clone(), country.clone()),
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

fn rejects(text: &str) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert!(entities.is_empty(), "{text:?} produced {entities:?}");
}

#[test]
fn accepts_documented_imo_numbers_behind_their_marker() {
    for text in [
        "IMO 9319466 arrived",
        "IMO 8814275 detained",
        "hull IMO 9074729 sold",
    ] {
        let (scheme, _, _) = only_match(text);
        assert_eq!(scheme, "imo");
    }
    assert_eq!(only_match("IMO 9319466 arrived").1, "9319466");
}

/// The marker is not always written; the cue word is what stands in for it, and without either a
/// seven-digit run stays an invoice line.
#[test]
fn a_bare_hull_number_needs_a_word_beside_it() {
    let (scheme, compact, _) = only_match("the vessel, 9319466, was detained");
    assert_eq!((scheme.as_str(), compact.as_str()), ("imo", "9319466"));
    rejects("order 9319466 shipped");
}

#[test]
fn rejects_imo_numbers_whose_check_digit_disagrees() {
    rejects("IMO 8814274 detained");
    rejects("the vessel, 9319467, was detained");
}

#[test]
fn accepts_mmsis_with_an_allocated_mid_and_reports_the_flag_state() {
    let scanner = support::scanner();
    let entities = scanner.scan("MMSI 244660000 broadcasting", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].rule_id, "vessel.mmsi");
    assert_eq!(entities[0].entity_type, EntityType::Vessel);
    assert!(entities[0].flags.contains(&Flag::NoChecksum));
    match &entities[0].value {
        Value::Identifier {
            compact,
            country,
            parts,
            ..
        } => {
            assert_eq!(compact, "244660000");
            assert_eq!(country.as_deref(), Some("NL"));
            assert_eq!(parts.get("mid").map(String::as_str), Some("244"));
        }
        other => panic!("expected an identifier value, got {other:?}"),
    }

    assert_eq!(
        only_match("AIS shows 235009802 inbound").2.as_deref(),
        Some("GB")
    );
    assert_eq!(
        only_match("call sign and MMSI 636092932").2.as_deref(),
        Some("LR")
    );
}

/// An MMSI has no check digit at all, so the two guards are the MID and the word beside it.
#[test]
fn rejects_nine_digit_runs_that_are_not_mmsis() {
    rejects("MMSI 999123456 broadcasting");
    rejects("reference 244660000 in the ledger");
}

#[test]
fn accepts_container_numbers_compact_and_grouped() {
    let scanner = support::scanner();
    let entities = scanner.scan("container CSQU3054383 sealed", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].entity_type, EntityType::CargoContainer);
    match &entities[0].value {
        Value::Identifier { compact, parts, .. } => {
            assert_eq!(compact, "CSQU3054383");
            assert_eq!(parts.get("owner").map(String::as_str), Some("CSQ"));
            assert_eq!(parts.get("category").map(String::as_str), Some("U"));
        }
        other => panic!("expected an identifier value, got {other:?}"),
    }

    let (_, compact, _) = only_match("box TASU 117000 0 on the manifest");
    assert_eq!(compact, "TASU1170000");
}

#[test]
fn rejects_container_numbers_whose_check_digit_disagrees() {
    rejects("container CSQU3054384 sealed");
    // The category letter is the format's self-identification; a fourth letter outside U, J, Z, R
    // is not a container number.
    rejects("container CSQA3054383 sealed");
}
