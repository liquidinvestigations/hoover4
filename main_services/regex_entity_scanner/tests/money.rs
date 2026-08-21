//! Sums of money: the code, the symbol, and the separators between the digits.
//!
//! The separator fixtures are the documented examples from `vendored/reference/price-parser/`,
//! whose `parse_number` docstring is where this arithmetic comes from. The subset covers the four
//! shapes that actually occur — grouped-and-fractioned in both conventions, space grouping, a bare
//! integer, and the single-separator case where both readings survive — plus the near-misses that
//! reach a money pattern and must not become money: version strings, page ranges and rates.

mod support;

use regex_entity_scanner::model::{Flag, Value};

/// The currency, the scaled integer and the exponent of the single entity in `text`.
fn money(text: &str) -> (String, String, u8, Vec<Flag>) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
    match &entities[0].value {
        Value::Money {
            currency,
            amount_minor,
            exponent,
        } => (
            currency.clone(),
            amount_minor.clone(),
            *exponent,
            entities[0].flags.clone(),
        ),
        other => panic!("expected a money value, got {other:?}"),
    }
}

fn rejects(text: &str) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert!(entities.is_empty(), "{text:?} produced {entities:?}");
}

#[test]
fn accepts_a_code_in_front_of_and_behind_its_amount() {
    for (text, expected) in [
        ("the invoice is EUR 1.234,56 net", "123456"),
        ("the invoice is 1,234.56 USD net", "123456"),
        ("the invoice is USD 1 234,56 net", "123456"),
        ("the invoice is EUR 1200 net", "120000"),
    ] {
        let (_, minor, exponent, flags) = money(text);
        assert_eq!(minor, expected, "{text:?}");
        assert_eq!(exponent, 2);
        assert!(flags.is_empty(), "{text:?} flagged {flags:?}");
    }
}

/// The exponent is the currency's own, and it is the only thing that decides what the digits mean.
/// The yen has no minor unit and the dinar has three, so the same digits scale differently.
#[test]
fn the_scale_comes_from_the_currency_not_from_the_digits() {
    assert_eq!(money("a fee of JPY 1200 was charged").1, "1200");
    assert_eq!(money("a fee of JPY 1200 was charged").2, 0);
    assert_eq!(money("a fee of BHD 1,234.567 was charged").1, "1234567");
    assert_eq!(money("a fee of BHD 1,234.567 was charged").2, 3);
}

/// The one shape both conventions claim. It is read as a thousands group, and the flag says the
/// reading was a choice rather than a fact.
#[test]
fn a_single_separator_before_three_digits_is_reported_as_inferred() {
    let (code, minor, _, flags) = money("the total was EUR 1.234 exactly");
    assert_eq!(code, "EUR");
    assert_eq!(minor, "123400");
    assert!(flags.contains(&Flag::SeparatorInferred), "{flags:?}");
}

#[test]
fn a_symbol_that_names_one_currency_is_not_flagged() {
    let (code, minor, _, flags) = money("the price is €1.234,56 today");
    assert_eq!(code, "EUR");
    assert_eq!(minor, "123456");
    assert!(flags.is_empty(), "{flags:?}");
}

/// A dollar sign is written for twenty-nine currencies. The rule names the most widely used one and
/// says, in the contract's own vocabulary, that it could not tell.
#[test]
fn a_shared_symbol_names_the_common_currency_and_flags_it() {
    let (code, minor, _, flags) = money("the price is $1,200.00 today");
    assert_eq!(code, "USD");
    assert_eq!(minor, "120000");
    assert!(flags.contains(&Flag::AmbiguousCurrency), "{flags:?}");
}

/// The capitals that distinguish one dollar from another are part of the symbol where somebody
/// writes them that way, and part of the previous word where they are not.
#[test]
fn capitals_in_front_of_a_sign_are_part_of_the_symbol_only_when_they_are_one() {
    let scanner = support::scanner();

    let (code, minor, _, _) = money("the price is R$49,90 today");
    assert_eq!(code, "BRL");
    assert_eq!(minor, "4990");

    let entities = scanner.scan("the price is US$40 today", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].text, "$40", "{entities:?}");
}

/// A bare number to the left of a sign — a list item, a table row, a quantity column — makes the
/// trailing-sign reading the leftmost one, and the engine proposes leftmost first. Rejecting it has
/// to leave the price behind it reachable, which the interior of a rejected candidate never is.
#[test]
fn a_price_is_found_past_a_bare_number_on_its_left() {
    for (text, code, minor, surface) in [
        ("1 $10 dollars bill", "USD", "1000", "$10"),
        ("Item 3 $45.00 each", "USD", "4500", "$45.00"),
        ("Lot 12 £250 reserve", "GBP", "25000", "£250"),
        ("row 7 $1,200 total", "USD", "120000", "$1,200"),
    ] {
        let scanner = support::scanner();
        let entities = scanner.scan(text, 0);
        assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
        assert_eq!(entities[0].text, surface, "{text:?}");
        let (found_code, found_minor, _, _) = money(text);
        assert_eq!((found_code.as_str(), found_minor.as_str()), (code, minor));
    }
}

/// A marker binds to the number that follows it. The same bare number to the left also makes the
/// trailing-marker reading available, and that reading is not merely the worse one: `qty 2 EUR 30`
/// is a thirty-euro line, and two euro is a wrong number in an index rather than a missing one.
#[test]
fn a_marker_binds_to_the_number_that_follows_it() {
    for (text, code, minor, surface) in [
        ("qty 2 EUR 30 per unit", "EUR", "3000", "EUR 30"),
        ("see note 4 USD 500 due", "USD", "50000", "USD 500"),
    ] {
        let scanner = support::scanner();
        let entities = scanner.scan(text, 0);
        assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
        assert_eq!(entities[0].text, surface, "{text:?}");
        let (found_code, found_minor, _, _) = money(text);
        assert_eq!((found_code.as_str(), found_minor.as_str()), (code, minor));
    }
    // The guard is a digit following the marker, not a bare number in front of it: a price at the
    // end of a clause is still a price.
    let (code, minor, _, _) = money("the total was 45 EUR, paid in full");
    assert_eq!((code.as_str(), minor.as_str()), ("EUR", "4500"));
}

/// The negatives are the point. Every one of these reaches a money pattern and none of them is a
/// sum of money.
#[test]
fn rejects_the_shapes_that_are_not_money() {
    for text in [
        // A version string: the groups are not thousands groups.
        "upgraded to USD 1.2.3 yesterday",
        // A page range: a separator on the boundary means the number continues.
        "see USD 120-134 for the schedule",
        // A rate with more decimals than the currency has minor units.
        "converted at USD 1.2345 per unit",
        // Three capitals that are not a currency at all.
        "the ISO 9001 audit is booked",
        // A code that is also a word, with nothing about money nearby.
        "TOP 40 singles of the year",
        // The amount runs into another token.
        "part number EUR 1200X is out of stock",
    ] {
        rejects(text);
    }
}

/// A word-like code is admitted when the sentence is about money, which is the whole difference
/// between the Tongan paʻanga and a chart position.
#[test]
fn a_word_like_code_needs_a_word_about_money() {
    let (code, minor, _, _) = money("the price paid was TOP 1200 for the lot");
    assert_eq!(code, "TOP");
    assert_eq!(minor, "120000");
}

/// A price is written at the end of a sentence and in a list far more often than it is written in
/// the middle of a longer number, so the separator that follows one is punctuation unless digits
/// follow it.
#[test]
fn a_sum_of_money_may_end_a_sentence_or_a_list_item() {
    assert_eq!(
        money("I would like to buy this item for USD 200.").1,
        "20000"
    );
    assert_eq!(
        money("The first price is $ 100,000,000, is it enough?").1,
        "10000000000"
    );

    let scanner = support::scanner();
    let entities = scanner.scan("Banknotes: 5 €, 10 €, 20 €.", 0);
    let amounts: Vec<&str> = entities.iter().map(|entity| entity.text.as_str()).collect();
    assert_eq!(amounts, ["5 €", "10 €", "20 €"], "{entities:?}");

    // The digits after the code belong to the sentence, not to the amount in front of it.
    assert_eq!(
        money("The cost is 500 USD,100 times more than expected.").1,
        "50000"
    );
}

/// Switzerland groups thousands with an apostrophe, and a shelf label writes a fraction with no
/// integer part at all.
#[test]
fn the_swiss_group_separator_and_a_bare_fraction_are_amounts() {
    assert_eq!(money("the price is CHF 1'049,95 today").1, "104995");
    assert_eq!(money("the price is €1'049,95 today").1, "104995");
    assert_eq!(money("marked down to $.75 each").1, "75");
    assert_eq!(money("marked down to .75 € each").1, "75");
}

/// A separator with a space after it and digits after that is one number written oddly. Neither
/// reading is provable from the text, and a wrong amount in an index is worse than a missing one,
/// so the span is refused rather than truncated at the separator.
#[test]
fn digits_across_a_separator_and_a_space_are_not_two_amounts() {
    for text in [
        "the bill came to $ 8. 94 in total",
        "the bill came to 1.837, 32 € in total",
    ] {
        rejects(text);
    }
}

/// A sign that names twenty-nine currencies stops being ambiguous the moment the writer puts the
/// code beside it. Reporting `NZD $100.70` as United States dollars is a wrong value in an indexed
/// field, which is worse than reporting nothing.
#[test]
fn an_iso_code_beside_a_sign_settles_which_currency_it_is() {
    let scanner = support::scanner();

    let (code, minor, _, flags) = money("the price is NZD $100.70 today");
    assert_eq!(code, "NZD");
    assert_eq!(minor, "10070");
    assert!(flags.is_empty(), "{flags:?}");

    let entities = scanner.scan("the price is SGD$4.90 today", 0);
    assert_eq!(entities.len(), 1, "{entities:?}");
    assert_eq!(entities[0].text, "SGD$4.90", "{entities:?}");

    // The code has to be one the sign itself can stand for, and it has to stand on its own: a
    // three-letter word beside a price is not a currency, and neither is the tail of a longer one.
    let (code, _, _, _) = money("the price is EUR $40 today");
    assert_eq!(code, "USD");
    let entities = scanner.scan("the total in XSGD$4.90 today", 0);
    assert!(entities.is_empty(), "{entities:?}");
}
