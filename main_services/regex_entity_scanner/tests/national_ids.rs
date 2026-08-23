//! National identity numbers, detection only.
//!
//! The fixtures are the documented examples from `stdnum/it/codicefiscale.py`, `stdnum/es/dni.py`,
//! `stdnum/es/nie.py`, `stdnum/mx/curp.py` and `stdnum/in_/pan.py`, each module's valid number
//! and the counterpart that differs only in its check character. The subset covers what each
//! scheme claims: the codice fiscale's two-table check character, the Spanish modulo-23 letter in
//! both its resident and its foreign-national spelling, the CURP's weighted check digit and state
//! code, and the PAN's holder-type letter and the cue word it needs because its check character is
//! not a published algorithm.
//!
//! Nothing here asserts a date of birth or a sex, because nothing produces one.

mod support;

use regex_entity_scanner::model::{EntityType, Flag, Value};

fn scheme_and_country(text: &str) -> (String, String) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
    assert_eq!(entities[0].entity_type, EntityType::NationalId);
    match &entities[0].value {
        Value::Identifier {
            scheme, country, ..
        } => (
            scheme.clone(),
            country.clone().unwrap_or_else(|| "?".to_string()),
        ),
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

fn rejects(text: &str) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert!(entities.is_empty(), "{text:?} produced {entities:?}");
}

#[test]
fn accepts_a_documented_codice_fiscale() {
    assert_eq!(
        scheme_and_country("taxpayer RCCMNL83S18D969H filed late"),
        ("it_codice_fiscale".to_string(), "IT".to_string())
    );
}

#[test]
fn rejects_a_codice_fiscale_whose_check_character_disagrees() {
    rejects("taxpayer RCCMNL83S18D969A filed late");
}

#[test]
fn accepts_spanish_numbers_in_both_spellings() {
    assert_eq!(
        scheme_and_country("resident 54362315K on the register"),
        ("es_nif_nie".to_string(), "ES".to_string())
    );
    assert_eq!(
        scheme_and_country("foreign national X2482300W on the register"),
        ("es_nif_nie".to_string(), "ES".to_string())
    );
    assert_eq!(
        scheme_and_country("holder M1234567L on the register"),
        ("es_nif_nie".to_string(), "ES".to_string())
    );
}

#[test]
fn rejects_spanish_numbers_whose_check_letter_disagrees() {
    rejects("resident 54362315Z on the register");
    rejects("foreign national X2482300A on the register");
}

#[test]
fn accepts_a_documented_curp() {
    assert_eq!(
        scheme_and_country("registered as BOXW310820HNERXN09"),
        ("mx_curp".to_string(), "MX".to_string())
    );
}

#[test]
fn rejects_curps_with_a_bad_check_digit_or_an_unknown_state() {
    rejects("registered as BOXW310820HNERXN08");
    // ZZ is not a state the registry uses.
    rejects("registered as BOXW310820HZZRXN09");
}

/// The check character's algorithm has never been published, so structure plus a word nearby is
/// the whole precision story, and the flag and the confidence say exactly that.
#[test]
fn a_pan_needs_a_word_beside_it_and_reports_no_checksum() {
    let scanner = support::scanner();
    let entities = scanner.scan("PAN ACUPA7085R on the return", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert!(entities[0].flags.contains(&Flag::NoChecksum));
    assert!(entities[0].confidence < 0.95, "{entities:?}");

    rejects("code ACUPA7085R in the export");
}

#[test]
fn rejects_pans_with_an_impossible_holder_type_or_serial() {
    // X is not a holder type the department assigns.
    rejects("PAN ABMXA3211G on the return");
    // The serial runs from 0001.
    rejects("PAN ACUPA0000R on the return");
}

/// The valid numbers from `stdnum/pl/pesel.py` and from Presidio's own recogniser fixtures. The
/// subset covers both checks the rule makes: the weighted check digit, and the birth date whose
/// century is folded into the month field.
#[test]
fn accepts_documented_pesels_beside_their_label() {
    for text in [
        "PESEL 44051401359 on the form",
        "PESEL 44051401458 on the form",
        "My pesel is 02070803628.",
        "PESEL 11111111116 on the form",
    ] {
        assert_eq!(
            scheme_and_country(text),
            ("pl_pesel".to_string(), "PL".to_string()),
            "{text:?}"
        );
    }
}

/// Each of the three filters on its own. `02381307589` is the invalid-birth-date example from
/// `stdnum/pl/pesel.py`: month 38 decodes to month 18 of the 2000s, which is no month at all.
#[test]
fn rejects_eleven_digit_runs_that_are_not_pesels() {
    rejects("PESEL 44051401358 on the form");
    rejects("PESEL 02381307589 on the form");
    rejects("PESEL 11110021111 on the form");
    // No word beside it says what it is.
    rejects("claim number 44051401458 was filed");
    // Eleven digits cut out of a longer run.
    rejects("PESEL 440514014581 on the form");
}

/// The valid numbers from `stdnum/se/personnummer.py` and from Presidio's fixtures, in both
/// spellings and with both separators. The subset covers the twelve-digit form that carries its
/// own century, the ten-digit form that does not, and the coordination number.
#[test]
fn accepts_documented_personnummer_in_both_spellings() {
    for text in [
        "personnummer 880320-0016 in the register",
        "personnummer 8803200016 in the register",
        "personnummer 189004119807 in the register",
        "personnummer 19910924-2397 in the register",
        "pnr 199109242397 is mine",
        "My personal identity code is: 189110089811.",
        // The plus sign marks a holder past a hundred; it is a century marker rather than a
        // separator to refuse.
        "personnummer 880320+0016 in the register",
    ] {
        assert_eq!(
            scheme_and_country(text),
            ("se_personnummer".to_string(), "SE".to_string()),
            "{text:?}"
        );
    }
}

/// The value keeps the separator, which is the century: `880320+0016` and `880320-0016` are two
/// people born a hundred years apart, and a value that stripped the sign would merge them. The
/// canonical form is `stdnum/se/personnummer.py`'s own, which inserts the hyphen where the
/// document wrote none.
#[test]
fn a_personnummer_keeps_the_separator_that_says_which_century() {
    let scanner = support::scanner();
    for (text, compact) in [
        ("personnummer 871220-2384 filed", "871220-2384"),
        ("personnummer 8712202384 filed", "871220-2384"),
        ("personnummer 880320+0016 filed", "880320+0016"),
        ("personnummer 198712202384 filed", "19871220-2384"),
    ] {
        let entities = scanner.scan(text, 0);
        assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
        match &entities[0].value {
            Value::Identifier { compact: found, .. } => assert_eq!(found, compact, "{text:?}"),
            other => panic!("expected an identifier value, got {other:?}"),
        }
    }
}

#[test]
fn rejects_personnummer_shaped_runs_that_do_not_check_out() {
    // The checksum disagrees: `stdnum/se/personnummer.py` and Presidio's invalid fixtures.
    rejects("personnummer 880320-0018 in the register");
    rejects("personnummer 19000309-3393 in the register");
    // Month 13 and day 44 are days nobody was born on.
    rejects("personnummer 19001309-2393 in the register");
    rejects("personnummer 200504422381 in the register");
    // No word beside it says what it is.
    rejects("batch reference 189004119807 was shipped");
    // A number glued to the word in front of it is not a standalone token.
    rejects("My swedish personnummer is189004119807.");
}

/// The disjoint cue lists and the two date checks between them: an eleven-digit PESEL and a
/// twelve-digit personnummer on adjacent lines each stay in their own rule.
#[test]
fn a_pesel_and_a_personnummer_do_not_claim_each_other() {
    let scanner = support::scanner();
    let entities = scanner.scan("PESEL 44051401458\npersonnummer 189004119807", 0);
    assert_eq!(entities.len(), 2, "{entities:?}");
    assert_eq!(entities[0].rule_id, "natid.pl_pesel");
    assert_eq!(entities[1].rule_id, "natid.se_personnummer");
}
