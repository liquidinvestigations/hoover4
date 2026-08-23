//! Bank identifiers: IBAN, BIC, payment card and ABA routing number.
//!
//! The fixtures are the documented examples from the `python-stdnum` modules this arithmetic is
//! ported from: `stdnum/iban.py` and the per-country `stdnum/*/iban.py` docstrings for the valid
//! numbers and their invalid-check-digit counterparts, `stdnum/bic.py` for the codes,
//! `stdnum/us/rtn.py` for the routing numbers, and Presidio's recogniser fixtures for the cards.
//! The IBAN subset is chosen to cover the three BBAN character classes, the shortest and longest
//! registry lengths, and the four ways an IBAN candidate can fail: unknown country, wrong length,
//! wrong alphabet, wrong checksum. The card subset covers one number per issuer range and every
//! length the issuer table admits, because the length is half of what that table checks.

mod support;

use regex_entity_scanner::model::{EntityType, Flag, Value};

fn identifier(text: &str) -> (String, String, Option<String>) {
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
fn accepts_the_documented_ibans_in_both_spellings() {
    for (text, compact) in [
        (
            "IBAN GR16 0110 1050 0000 1054 7023 795",
            "GR1601101050000010547023795",
        ),
        ("IBAN BE31435411161155", "BE31435411161155"),
        ("IBAN NO93 8601 1117 947", "NO9386011117947"),
        ("IBAN ME25510000000006234133", "ME25510000000006234133"),
        ("IBAN GB82 WEST 1234 5698 7654 32", "GB82WEST12345698765432"),
        (
            "IBAN RO49 AAAA 1B31 0075 9384 0000",
            "RO49AAAA1B31007593840000",
        ),
        // The longest registered length, 34 characters, in the grouped spelling a statement
        // prints: eight separators past the four-character prefix.
        (
            "IBAN LC55 HEMM 0001 0001 0012 0012 0002 3015",
            "LC55HEMM000100010012001200023015",
        ),
        ("IBAN GB82-WEST-1234-5698-7654-32", "GB82WEST12345698765432"),
    ] {
        let (scheme, found, country) = identifier(text);
        assert_eq!(scheme, "iban");
        assert_eq!(found, compact);
        assert_eq!(country.as_deref(), Some(&compact[0..2]));
    }
}

/// The country in the value comes from the number itself, and the parts are sliced where the
/// registry says the bank identifier sits.
#[test]
fn an_iban_carries_its_country_and_its_bank_code() {
    let scanner = support::scanner();
    let entities = scanner.scan("settle to IBAN GB82 WEST 1234 5698 7654 32 please", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    let entity = &entities[0];
    assert_eq!(entity.entity_type, EntityType::BankAccount);
    assert_eq!(entity.rule_id, "bank.iban");
    assert_eq!(entity.text, "GB82 WEST 1234 5698 7654 32");
    match &entity.value {
        Value::Identifier { parts, .. } => {
            assert_eq!(parts.get("bank_code").map(String::as_str), Some("WEST"));
            assert_eq!(parts.get("check_digits").map(String::as_str), Some("82"));
            assert_eq!(
                parts.get("bban").map(String::as_str),
                Some("WEST12345698765432")
            );
        }
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

/// The four ways a candidate fails: a country that issues no IBANs, a length the registry does not
/// give, an alphabet the structure does not allow, and arithmetic that does not agree.
#[test]
fn rejects_iban_shaped_runs_that_do_not_check_out() {
    // Invalid check digits, from the `no/iban.py` and `es/iban.py` docstrings.
    rejects("IBAN NO92 8601 1117 947");
    rejects("IBAN ES12 1234 1234 1612 3456 7890");
    // The right number of characters for nobody: GB is 22.
    rejects("IBAN GB82WEST1234569876543");
    // XX is not a country that issues IBANs.
    rejects("IBAN XX82WEST12345698765432");
    // GB's structure is four letters then fourteen digits; this has digits where letters belong.
    rejects("IBAN GB8212ST12345698765432");
}

/// A rejected candidate is not the end of the story: an IBAN followed immediately by a digit run
/// over-matches into something that fails on length, and the account number inside it survives.
#[test]
fn an_iban_survives_a_digit_run_glued_to_its_end() {
    let scanner = support::scanner();
    let entities = scanner.scan("IBAN GB82WEST123456987654321234 booked", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].text, "GB82WEST12345698765432");
}

#[test]
fn accepts_bics_beside_a_label() {
    for (text, compact) in [
        ("SWIFT AGRIFRPP882", "AGRIFRPP882"),
        ("BIC: AGRIFRPP", "AGRIFRPP"),
        ("beneficiary bank DEUTDEFF500", "DEUTDEFF500"),
    ] {
        let (scheme, found, country) = identifier(text);
        assert_eq!(scheme, "bic");
        assert_eq!(found, compact);
        assert_eq!(country.as_deref(), Some(&compact[4..6]));
    }
}

#[test]
fn a_bic_reports_that_it_has_no_checksum() {
    let scanner = support::scanner();
    let entities = scanner.scan("BIC AGRIFRPP", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert!(entities[0].flags.contains(&Flag::NoChecksum));
    assert!((entities[0].confidence - 0.95).abs() < f32::EPSILON);
}

/// ISO 9362 has no check digit, so the guards are the length, the country code and the label. An
/// ordinary capitalised word carries a country code often enough that the label is what makes the
/// rule usable: DOCUMENT has ME in positions five and six, CUSTOMER has OM.
#[test]
fn rejects_code_shaped_words_and_malformed_codes() {
    rejects("SECTION 4: DOCUMENT CUSTOMER RETAINED");
    // A cue is present, but nine characters is not a length ISO 9362 defines.
    rejects("BIC AGRIFRPP8");
    // A cue is present, but ZZ is not a country.
    rejects("BIC AGRIZZPP");
    // No cue anywhere near it.
    rejects("the header read AGRIFRPP and nothing else");
}

/// Presidio's `test_credit_card_recognizer.py` fixtures, one per issuer range, plus the three
/// spellings its first row writes in one fragment. The subset covers every length the table
/// admits. Diners at fourteen, Amex at fifteen, the rest at sixteen, because the length is half
/// of what the issuer table checks.
#[test]
fn accepts_a_card_number_from_each_issuer_range() {
    for (text, compact) in [
        ("card number 4012 8888 8888 1881", "4012888888881881"),
        ("card number 4012-8888-8888-1881", "4012888888881881"),
        ("card number 4012888888881881", "4012888888881881"),
        ("cardholder 371449635398431", "371449635398431"),
        ("visa 4111111111111111", "4111111111111111"),
        ("mastercard 5555555555554444", "5555555555554444"),
        ("diners 30569309025904", "30569309025904"),
        ("discover 6011000400000000", "6011000400000000"),
        ("jcb 3528000700000000", "3528000700000000"),
        ("maestro 6759649826438453", "6759649826438453"),
        ("card 5019717010103742", "5019717010103742"),
    ] {
        let (scheme, found, country) = identifier(text);
        assert_eq!(scheme, "payment_card", "{text:?}");
        assert_eq!(found, compact);
        assert_eq!(country, None, "a card number names no country");
    }
}

/// The issuer and the six digits that identify it travel with the value: an investigator reading a
/// card number wants to know which institution issued it, and that is the only thing about the
/// number a validator can say for itself.
#[test]
fn a_card_carries_its_issuer_and_issuer_identification_number() {
    let scanner = support::scanner();
    let entities = scanner.scan("card number 4012 8888 8888 1881 on file", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].rule_id, "bank.payment_card");
    assert_eq!(entities[0].text, "4012 8888 8888 1881");
    match &entities[0].value {
        Value::Identifier { parts, .. } => {
            assert_eq!(parts.get("issuer").map(String::as_str), Some("Visa"));
            assert_eq!(parts.get("iin").map(String::as_str), Some("401288"));
        }
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

/// Every filter the card rule has, one fragment each. The no-cue case is the one that decides precision. A
/// page of invoice-like text puts several Luhn-valid runs inside allocated issuer ranges, and the
/// word beside the number is the only thing that separates a card from an article number.
#[test]
fn rejects_card_shaped_runs_that_do_not_check_out() {
    // The check digit disagrees. Presidio's own invalid fixture.
    rejects("card number 4012-8888-8888-1882");
    rejects("credit card 36168002586008");
    // Luhn agrees and nothing says card.
    rejects("order reference 4012888888881881 shipped");
    rejects("article 5555 5555 5555 4444 in stock");
    // Luhn agrees, the cue is there, and the prefix belongs to no issuer.
    rejects("card number 9999999999999995");
    // Luhn agrees on fifteen digits beginning with 1, which is the airline range this rule does
    // not claim.
    rejects("card number 122000000000003");
    // The separators are not one character used throughout.
    rejects("card 4012-8888 8888-1881");
    // A card number cut out of a longer digit run is not a card number.
    rejects("card 40128888888818817 charged");
}

/// The scan loop shrinks a rejected candidate from the right, so a longer digit run offers up
/// every shorter head of itself and one head in ten passes Luhn. A fifteen-digit IMEI beside a
/// card reader is the shape that finds it.
#[test]
fn a_longer_digit_run_does_not_yield_a_card_from_its_head() {
    let scanner = support::scanner();
    let entities = scanner.scan("the card reader logged IMEI 490154203237518", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].rule_id, "device.imei");
}

/// The valid numbers from Presidio's `test_aba_routing_recognizer.py` and from `stdnum/us/rtn.py`,
/// with the cue words each source's own recogniser lists.
#[test]
fn accepts_routing_numbers_beside_their_label() {
    for text in [
        "routing number 121000358",
        "ABA 121042882",
        "RTN 111000025",
        "transit number 121000358",
    ] {
        let (scheme, found, country) = identifier(text);
        assert_eq!(scheme, "aba_routing", "{text:?}");
        assert_eq!(found.len(), 9);
        assert_eq!(country.as_deref(), Some("US"));
    }
}

#[test]
fn a_routing_number_carries_its_routing_symbol_and_institution() {
    let scanner = support::scanner();
    let entities = scanner.scan("routing number 121000358 for the wire", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].rule_id, "bank.aba_routing");
    match &entities[0].value {
        Value::Identifier { parts, .. } => {
            assert_eq!(
                parts.get("routing_symbol").map(String::as_str),
                Some("1210")
            );
            assert_eq!(parts.get("institution").map(String::as_str), Some("0035"));
        }
        other => panic!("expected an identifier value, got {other:?}"),
    }
}

/// Two independent filters over nine digits and a cue on top of them, one fragment each.
#[test]
fn rejects_routing_shaped_runs_that_do_not_check_out() {
    // The 3-7-1 sum disagrees, from `stdnum/us/rtn.py` and from Presidio's invalid fixtures.
    rejects("routing number 112000025");
    rejects("ABA 421042111");
    // The sum agrees and the leading two digits are in no Federal Reserve block.
    rejects("routing number 130000006");
    rejects("routing number 990000000");
    // Nothing beside it says what it is.
    rejects("case file 121000358 was closed");
    // The hyphenated spelling on a cheque is not matched at all.
    rejects("routing number 3222-7162-7");
    // Nine digits cut out of a longer run are not a routing number.
    rejects("routing number 1210003589");
}
