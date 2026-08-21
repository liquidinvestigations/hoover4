//! Telephone numbers.
//!
//! The subset is chosen for the two things this rule claims: that a number in international form
//! reaches the same E.164 value however it is punctuated, and that the shapes libphonenumber's own
//! text matcher refuses — page ranges, timestamps, plus-addressed mailboxes, digit runs that
//! continue past the match — are refused here too. Numbers in national form are not in the subset
//! as positives, because the rule deliberately cannot read them.

mod support;

use regex_entity_scanner::model::{EntityType, Flag, Value};

fn only_phone(text: &str) -> (String, String, String, f32) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
    assert_eq!(entities[0].entity_type, EntityType::Phone);
    match &entities[0].value {
        Value::Phone {
            e164,
            country,
            number_type,
            ..
        } => (
            e164.clone(),
            country.clone(),
            number_type.clone(),
            entities[0].confidence,
        ),
        other => panic!("expected a phone value, got {other:?}"),
    }
}

fn no_phone(text: &str) {
    let scanner = support::scanner();
    let phones: Vec<_> = scanner
        .scan(text, 0)
        .into_iter()
        .filter(|entity| entity.entity_type == EntityType::Phone)
        .collect();
    assert!(phones.is_empty(), "{text:?} produced {phones:?}");
}

#[test]
fn accepts_international_numbers_from_several_countries() {
    assert_eq!(
        only_phone("Call +40 21 555 0100 for details."),
        (
            "+40215550100".to_string(),
            "RO".to_string(),
            "fixed_line".to_string(),
            0.95
        )
    );
    assert_eq!(
        only_phone("Reach us on +1 202-555-0143 during office hours."),
        (
            "+12025550143".to_string(),
            "US".to_string(),
            "fixed_line_or_mobile".to_string(),
            0.95
        )
    );
    assert_eq!(
        only_phone("Mobil: +49 (0) 30 901820 in Berlin"),
        (
            "+4930901820".to_string(),
            "DE".to_string(),
            "fixed_line".to_string(),
            0.95
        )
    );
    assert_eq!(
        only_phone("+55 11 91234-5678 Sao Paulo"),
        (
            "+5511912345678".to_string(),
            "BR".to_string(),
            "mobile".to_string(),
            0.95
        )
    );
}

#[test]
fn a_global_service_number_belongs_to_no_country() {
    assert_eq!(
        only_phone("freephone +800 1234 5678 worldwide"),
        (
            "+80012345678".to_string(),
            "001".to_string(),
            "toll_free".to_string(),
            0.95
        )
    );
}

#[test]
fn punctuation_does_not_change_the_number() {
    let plain = only_phone("Tel. +44 20 7123 4567").0;
    assert_eq!(only_phone("+44-20-7123-4567").0, plain);
    assert_eq!(only_phone("+44.20.7123.4567").0, plain);
    assert_eq!(only_phone("+44 (20) 7123 4567").0, plain);
    assert_eq!(only_phone("tel:+442071234567").0, plain);
}

#[test]
fn the_dialling_prefix_stands_for_the_plus_sign() {
    assert_eq!(
        only_phone("dial 0044 20 7123 4567 from abroad").0,
        "+442071234567"
    );
    // Written as one run it is any thirteen-digit identifier with two zeros in front of it.
    no_phone("invoice 0012345678901 paid");
    no_phone("00442071234567 solid");
}

#[test]
fn national_format_is_not_read_without_a_region() {
    no_phone("Ring 020 7123 4567 and ask for Ana.");
    no_phone("Telefon 0722 123 456 disponibil");
    no_phone("(202) 555-0143 is the desk number");
}

#[test]
fn the_national_number_drops_the_country_calling_code() {
    let scanner = support::scanner();
    let entities = scanner.scan("Tel: +33 1 42 68 53 00", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    match &entities[0].value {
        Value::Phone { national, e164, .. } => {
            assert_eq!(national, "142685300");
            assert_eq!(e164, "+33142685300");
        }
        other => panic!("expected a phone value, got {other:?}"),
    }
}

#[test]
fn a_number_the_metadata_only_half_recognises_is_reported_lower() {
    let scanner = support::scanner();
    // The region's own pattern accepts these digits; no line type claims them.
    let entities = scanner.scan("Fax +40 200 001 132 in Bucharest", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].confidence, 0.85);
    assert_eq!(entities[0].flags, vec![Flag::NoChecksum]);
    // Digits no country issues at all are not a number at any confidence.
    no_phone("Fax +40 999 999 999 in Bucharest");
    no_phone("+99 12 345 6789 nowhere");
}

#[test]
fn refuses_the_shapes_libphonenumber_refuses() {
    // A citation's page range and year.
    no_phone("Chen Li. VLDB J. 12(3): 211-227 (2003).");
    // A timestamp whose minutes follow the span.
    no_phone("logged at +41 2012-01-02 08:30 today");
    // A release number with a build tag.
    no_phone("release 2.10.3+40712345678 build");
    no_phone("version +1.2.3.4 tag");
    // A plus-addressed mailbox, which is an address and not a number.
    no_phone("user+40712345678@example.com wrote");
    // A sum of money.
    no_phone("the adjustment was +12.50 EUR");
}

#[test]
fn a_run_that_continues_past_the_match_is_not_a_number() {
    // Hyphen-joined digits are one token, so no reading of it is a number.
    no_phone("ticket +40-21-555-0100-999 raised");
    // Separated by a space they are two things, and the number is recovered from the longer
    // candidate that failed.
    assert_eq!(only_phone("call +40 21 555 0100 3 times").0, "+40215550100");
}

/// An extension is not part of the E.164 number. The card promises it is dropped, so the marker
/// that introduces one may touch the match, and the span ends in front of it.
#[test]
fn an_attached_extension_is_dropped_rather_than_refused() {
    let scanner = support::scanner();
    for (text, expected) in [
        ("call +44 2034567890x456 for support", "+442034567890"),
        ("call +44 2034567890 ext. 456 for support", "+442034567890"),
        ("call +44 2034567890#456 for support", "+442034567890"),
    ] {
        let entities = scanner.scan(text, 0);
        assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
        assert_eq!(only_phone(text).0, expected, "{text:?}");
        assert_eq!(entities[0].text, "+44 2034567890", "{text:?}");
    }
    // A letter that is not an extension marker still means the run continues.
    no_phone("code +442034567890abc here");
}
