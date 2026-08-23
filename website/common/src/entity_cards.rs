//! The explainer card behind `View Details`, and the term hits behind a facet search box.
//!
//! Two shapes that travel together because both exist for the same reason: a facet value
//! is a normalised identifier, and a normalised identifier says almost nothing about
//! itself. `GB82WEST12345698765432` is a bank account in the United Kingdom at a named
//! institution, and none of that is legible in the string.
//!
//! The card is produced by the scanner rather than here. It is the only thing that knows
//! which rule accepted a value and what that rule's validator actually checked, and, as
//! usefully, what acceptance does NOT prove. Restating that in the website would be a
//! second copy of the rule catalogue with no way to notice when it drifted.

use serde::{Deserialize, Serialize};

/// One labelled piece of sub-metadata on a card: `Country`, `United Kingdom`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct EntityFact {
    pub label: String,
    pub value: String,
}

/// A reference the reader can follow: the standard, the register, the authority.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct EntityLink {
    pub title: String,
    pub url: String,
    /// Why the link is worth following, in a few words.
    pub note: String,
}

/// The card for one matched value.
///
/// Every field is optional on the wire and defaults to empty: the scanner accepts an
/// entity from a rule set older than its own and degrades to a thinner card rather than
/// failing, and this side must not turn that thinner card into a deserialisation error.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct EntityExplanation {
    #[serde(default)]
    pub rule_id: String,
    #[serde(default)]
    pub entity_type: String,
    /// What was matched, in words: "ISO 8601 timestamp", never `date.iso8601`.
    #[serde(default)]
    pub title: String,
    /// One line about this particular match: country, authority, precision, register.
    #[serde(default)]
    pub subtitle: String,
    /// The long text, in Markdown, with links inline.
    #[serde(default)]
    pub body: String,
    #[serde(default)]
    pub facts: Vec<EntityFact>,
    #[serde(default)]
    pub references: Vec<EntityLink>,
}

/// One term the facet search box found, with the reason it matched.
///
/// `term_id` is what a facet filter is written in: the search columns hold
/// `hash_string_to_uint63` ids and never the text, so a typed needle has to be resolved
/// to ids before it can narrow anything.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct EntityTermHit {
    pub term_id: u64,
    pub term_display: String,
    /// Which facet the term belongs to (`regex_email`, `ner`, `email_address`, …). One
    /// value can be a term in two fields (an address is both an envelope sender and
    /// something a body mentions), and ticking them applies different filters.
    pub term_field: String,
    /// The matched fragment, split into marked and unmarked runs, as the search box's
    /// match reason. Empty when the highlighter had nothing to add.
    ///
    /// Already decomposed on the server, like every other highlight on the site: the
    /// marker tags are a Manticore detail, and a renderer that had to parse them would be
    /// a second parser for the same wire format.
    #[serde(default)]
    pub highlight: Vec<crate::text_highlight::HighlightTextSpan>,
}

/// What a facet search box got back.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
pub struct EntityTermHits {
    pub hits: Vec<EntityTermHit>,
    /// The result set hit its cap, so the list is a sample of the matches rather than
    /// all of them. A truncated list that renders as a complete one is how a user
    /// concludes a value is absent from the corpus.
    #[serde(default)]
    pub truncated: bool,
}

impl EntityTermHits {
    /// The ids, in the order the hits came back, for restricting a facet query.
    pub fn term_ids(&self) -> Vec<u64> {
        self.hits.iter().map(|hit| hit.term_id).collect()
    }

    pub fn is_empty(&self) -> bool {
        self.hits.is_empty()
    }
}

/// The magnitude ladder, upper bound exclusive, applied to the major-unit amount.
///
/// **This is the second of two implementations, and that is deliberate.** The pipeline's
/// copy (`tasks/regex_entities.py`) decides what is stored, and this one decides what a
/// document's own amounts are labelled with in the viewer. Neither runtime may depend on
/// the other being reachable, exactly as the `extracted_by` formatter is written twice.
/// The boundaries have a test on both sides; changing one without the other makes a
/// viewer label disagree with the facet it filters into.
///
/// Bucket ids are canonical ASCII. A label spelling change (an en-dash instead of a
/// hyphen) is a render-time concern and must never be a reindex.
const MONEY_LADDER: &[(f64, &str)] = &[
    (1.0, "under 1"),
    (10.0, "1-10"),
    (100.0, "10-100"),
    (1_000.0, "100-1k"),
    (10_000.0, "1k-10k"),
    (100_000.0, "10k-100k"),
    (1_000_000.0, "100k-1M"),
    (10_000_000.0, "1M-10M"),
    (100_000_000.0, "10M-100M"),
];

const MONEY_TOP: &str = "over 100M";

/// The facet id for one amount: `USD 10k-100k`.
pub fn money_bucket(currency: &str, amount_major: f64) -> String {
    let magnitude = amount_major.abs();
    for (upper, label) in MONEY_LADDER {
        if magnitude < *upper {
            return format!("{currency} {label}");
        }
    }
    format!("{currency} {MONEY_TOP}")
}

/// The bucket for a stored scanner value, or `None` when the value is not money.
///
/// The amount arrives as minor units in a **string**, because a sum of money that
/// round-trips through a JSON number is a double and is no longer a sum of money. The
/// division into major units happens here and only for the comparison the ladder makes.
pub fn money_bucket_from_value_json(value_json: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(value_json).ok()?;
    if value.get("kind")?.as_str()? != "money" {
        return None;
    }
    let currency = value.get("currency")?.as_str()?;
    let minor: f64 = match value.get("amount_minor")? {
        serde_json::Value::String(text) => text.parse().ok()?,
        serde_json::Value::Number(number) => number.as_f64()?,
        _ => return None,
    };
    let exponent = value.get("exponent").and_then(|e| e.as_i64()).unwrap_or(0);
    Some(money_bucket(currency, minor / 10_f64.powi(exponent as i32)))
}

#[cfg(test)]
mod money_tests {
    use super::*;

    /// Every boundary, on the exclusive side and the inclusive side. These are the same
    /// cases the pipeline's copy of the ladder is tested against; the two lists agreeing
    /// is the only thing that keeps a viewer label and its facet in step.
    #[test]
    fn the_ladder_boundaries_are_exclusive_above_and_inclusive_below() {
        for (amount, expected) in [
            (0.0, "USD under 1"),
            (0.99, "USD under 1"),
            (1.0, "USD 1-10"),
            (9.99, "USD 1-10"),
            (10.0, "USD 10-100"),
            (100.0, "USD 100-1k"),
            (1_000.0, "USD 1k-10k"),
            (10_000.0, "USD 10k-100k"),
            (100_000.0, "USD 100k-1M"),
            (1_000_000.0, "USD 1M-10M"),
            (10_000_000.0, "USD 10M-100M"),
            (100_000_000.0, "USD over 100M"),
            (999_999_999.0, "USD over 100M"),
        ] {
            assert_eq!(money_bucket("USD", amount), expected, "for {amount}");
        }
    }

    /// A refund is the same magnitude as the payment it reverses, and a facet that files
    /// them apart splits every credit note away from its invoice.
    #[test]
    fn a_negative_amount_lands_in_the_bucket_of_its_magnitude() {
        assert_eq!(money_bucket("EUR", -25_000.0), "EUR 10k-100k");
    }

    #[test]
    fn minor_units_arrive_as_a_string_and_are_scaled_by_the_exponent() {
        let json = r#"{"kind":"money","currency":"USD","amount_minor":"2500000","exponent":2}"#;
        assert_eq!(money_bucket_from_value_json(json).unwrap(), "USD 10k-100k");
    }

    #[test]
    fn a_zero_exponent_currency_is_not_divided() {
        // JPY has no minor unit, so 25 000 minor units is 25 000 yen.
        let json = r#"{"kind":"money","currency":"JPY","amount_minor":"25000","exponent":0}"#;
        assert_eq!(money_bucket_from_value_json(json).unwrap(), "JPY 10k-100k");
    }

    #[test]
    fn a_value_that_is_not_money_has_no_bucket() {
        assert!(money_bucket_from_value_json(r#"{"kind":"identifier"}"#).is_none());
        assert!(money_bucket_from_value_json("not json").is_none());
        assert!(money_bucket_from_value_json("null").is_none());
    }
}
