//! Explainer cards: the client posts an entity back unchanged and gets something a reader can use.

mod support;

use regex_entity_scanner::explain::{self, catalog, ExplainRequest};

/// The contract that makes the endpoint usable at all: whatever `/scan` produced can be posted back
/// verbatim, with no field stripped, reordered or renamed.
fn round_trip(fragment: &str, index: usize) -> ExplainRequest {
    let scanner = support::scanner();
    let entities = scanner.scan(fragment, 0);
    let entity = entities
        .get(index)
        .unwrap_or_else(|| panic!("{fragment:?} produced {entities:?}"));
    let json = serde_json::to_string(entity).expect("an entity serialises");
    serde_json::from_str(&json).expect("and deserialises back into an explain request")
}

#[test]
fn every_compiled_rule_is_documented() {
    let scanner = support::scanner();
    for rule_id in scanner.rule_ids() {
        assert!(
            catalog::lookup(rule_id).is_some(),
            "{rule_id} is compiled into the scanner but has no catalogue entry, so a reader who \
             clicks one of its matches gets nothing"
        );
    }
}

#[test]
fn a_date_card_names_the_weekday_and_the_zone() {
    let scanner = support::scanner();
    let request = round_trip("filed 2021-03-04T09:12:00+0200 in Bucharest", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for date.iso8601");

    assert_eq!(card.title, "ISO 8601 timestamp");
    // 4 March 2021 was a Thursday, and the offset is not dropped on the way to the reader.
    assert!(
        card.subtitle.contains("Thursday, 4 March 2021"),
        "{}",
        card.subtitle
    );
    assert!(card.subtitle.contains("UTC+02:00"), "{}", card.subtitle);

    let weekday = card
        .facts
        .iter()
        .find(|fact| fact.label == "Day of the week")
        .expect("a weekday fact");
    assert_eq!(weekday.value, "Thursday");

    // The body explains the normalisation, because the surface form and the canonical value differ.
    assert!(card.body.contains("2021-03-04T09:12:00+02:00"));
    assert!(card.body.contains("rfc-editor.org/rfc/rfc3339"));
}

#[test]
fn a_zoneless_date_card_says_the_moment_is_not_pinned() {
    let scanner = support::scanner();
    let request = round_trip("filed 2021-03-04 in Bucharest", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for date.iso8601");

    assert_eq!(card.title, "ISO 8601 date");
    assert!(
        card.subtitle.contains("no time zone stated"),
        "{}",
        card.subtitle
    );
    assert!(card.body.contains("the date is certain, the moment is not"));
}

/// The country behind a country-code top-level domain is the most useful thing on an email card,
/// and `.uk` is the case that a straight ISO 3166 lookup gets wrong.
#[test]
fn an_email_card_resolves_the_country_code_domain() {
    let scanner = support::scanner();
    let request = round_trip("write to Anna.Popescu@Example.CO.UK today", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for email.basic");

    assert_eq!(card.title, "Email address");
    assert_eq!(card.subtitle, "example.co.uk · United Kingdom");

    let country = card
        .facts
        .iter()
        .find(|fact| fact.label == "Country")
        .expect("a country fact");
    assert_eq!(country.value, "United Kingdom");

    // The register entry for this specific domain leads the reference list.
    assert_eq!(
        card.references[0].url,
        "https://www.iana.org/domains/root/db/uk.html"
    );
    assert!(card
        .body
        .contains("country-code top-level domain for United Kingdom"));
    // What acceptance does not prove matters as much as what it does.
    assert!(card.body.contains("no lookup of any kind is made"));
}

#[test]
fn a_vat_card_resolves_the_prefix_the_administration_writes() {
    let scanner = support::scanner();
    let request = round_trip("counterparty EL094259216 in Athens", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for company.vat_eu");

    assert_eq!(card.subtitle, "EL094259216 · Greece");
    let country = card
        .facts
        .iter()
        .find(|fact| fact.label == "Country")
        .expect("a country fact");
    assert_eq!(country.value, "Greece");
    // The prefix as written and the country in the value are different two letters here.
    assert!(card.body.contains("The prefix is written `EL`"));
}

#[test]
fn a_phone_card_names_the_country_and_the_line_type() {
    let scanner = support::scanner();
    let request = round_trip("Call +40 21 555 0100 for details.", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for phone.international");

    assert_eq!(card.title, "Telephone number, international form");
    assert_eq!(card.subtitle, "+40215550100 · Romania");

    let line_type = card
        .facts
        .iter()
        .find(|fact| fact.label == "Line type")
        .expect("a line type fact");
    assert_eq!(line_type.value, "fixed line");
    assert!(card.body.contains("The calling code belongs to Romania"));
    // What acceptance does not prove matters as much as what it does.
    assert!(card
        .body
        .contains("nothing here says the line is in service"));
}

#[test]
fn a_generic_domain_card_does_not_invent_a_country() {
    let scanner = support::scanner();
    let request = round_trip("hello@my-agency.consulting is the contact", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for email.basic");

    assert_eq!(
        card.subtitle,
        "my-agency.consulting · generic top-level domain"
    );
    assert!(card.facts.iter().all(|fact| fact.label != "Country"));
}

/// An entity kept by a client from an older rule set still explains itself: only `rule_id` is
/// required, and an unrecognised value shape thins the card instead of failing it.
#[test]
fn a_sparse_entity_still_produces_a_card() {
    let scanner = support::scanner();
    let request: ExplainRequest =
        serde_json::from_str(r#"{"rule_id": "email.basic", "unknown_field": 7}"#)
            .expect("a sparse entity deserialises");
    let card = explain::explain(&request, scanner.data()).expect("a card from the catalogue alone");

    assert_eq!(card.title, "Email address");
    assert!(card.subtitle.is_empty());
    assert!(card.body.contains("IANA's list of delegated domains"));
}

#[test]
fn an_unknown_rule_has_no_card() {
    let scanner = support::scanner();
    let request: ExplainRequest = serde_json::from_str(r#"{"rule_id": "phone.zw.mobile"}"#)
        .expect("the request deserialises");
    assert!(explain::explain(&request, scanner.data()).is_none());
}

/// The four identifiers that carry a country in their own characters all resolve it the same way,
/// through the same territory table, and all put it where a reader looks first.
#[test]
fn an_encoded_country_reaches_the_subtitle_and_the_facts() {
    let scanner = support::scanner();
    let cases = [
        (
            "transfer to GB82 WEST 1234 5698 7654 32 today",
            "United Kingdom",
            "Country",
        ),
        (
            "swift bic DEUTDEFF for the beneficiary bank",
            "Germany",
            "Country",
        ),
        (
            "the ISIN US0378331005 is quoted in New York",
            "United States",
            "Country",
        ),
        (
            "MMSI 232003453 was heard on channel 16",
            "United Kingdom",
            "Flag state",
        ),
    ];

    for (fragment, country, label) in cases {
        let request = round_trip(fragment, 0);
        let card = explain::explain(&request, scanner.data())
            .unwrap_or_else(|| panic!("a card for {fragment:?}"));
        assert!(
            card.subtitle.contains(country),
            "{}: {}",
            request.rule_id,
            card.subtitle
        );
        let fact = card
            .facts
            .iter()
            .find(|fact| fact.label == label)
            .unwrap_or_else(|| panic!("{} has no {label} fact", request.rule_id));
        assert_eq!(fact.value, country);
    }
}

/// An ISIN whose prefix belongs to a substitute numbering agency names no country, and the card
/// says so rather than inventing one.
#[test]
fn a_substitute_agency_isin_names_no_country() {
    let scanner = support::scanner();
    let request = round_trip("the ISIN XS1088885550 was issued in London", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for security.isin");

    assert!(card.facts.iter().all(|fact| fact.label != "Country"));
    assert!(card.body.contains("substitute agencies"), "{}", card.body);
}

/// The confidence note is one sentence for the whole rule set: it appears on every card that
/// carries a number, and nowhere on one that does not.
#[test]
fn the_confidence_note_is_the_same_on_every_card() {
    let scanner = support::scanner();
    for fragment in [
        "filed 2021-03-04 in Bucharest",
        "write to anna@example.co.uk today",
        "the ISIN US0378331005 is quoted in New York",
    ] {
        let request = round_trip(fragment, 0);
        let card = explain::explain(&request, scanner.data())
            .unwrap_or_else(|| panic!("a card for {fragment:?}"));
        assert!(
            card.body.contains(catalog::CONFIDENCE_NOTE),
            "{} carries a confidence but does not explain it",
            request.rule_id
        );
    }

    let request: ExplainRequest = serde_json::from_str(r#"{"rule_id": "email.basic"}"#)
        .expect("an entity with no confidence deserialises");
    let card = explain::explain(&request, scanner.data()).expect("a card from the catalogue alone");
    assert!(!card.body.contains(catalog::CONFIDENCE_NOTE));
}

/// A money card puts the decimal point back: the scaled integer is the right thing to index and
/// the wrong thing to show, and the currency's own exponent is where the point goes.
#[test]
fn a_money_card_writes_the_amount_out_and_names_the_currency() {
    let scanner = support::scanner();
    let request = round_trip("the invoice total is EUR 1.234,56 net", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for money.iso_code");

    assert!(card.subtitle.contains("1234.56 EUR"), "{}", card.subtitle);
    assert!(card.subtitle.contains("Euro"), "{}", card.subtitle);
    let amount = card
        .facts
        .iter()
        .find(|fact| fact.label == "Amount")
        .expect("an amount fact");
    assert_eq!(amount.value, "1234.56");

    let request = round_trip("a handling fee of JPY 1200 was applied", 0);
    let card = explain::explain(&request, scanner.data()).expect("a card for money.iso_code");
    // The yen has no minor unit, so there is no point to put back.
    assert!(card.subtitle.contains("1200 JPY"), "{}", card.subtitle);
}
