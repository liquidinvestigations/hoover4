//! The output contract.
//!
//! Offsets are byte offsets into the source document, not into the fragment that was scanned, and
//! not character indices. Fragments carry the offset of their first byte and the scanner adds it,
//! so a caller that splits a document into overlapping windows gets spans it can use directly
//! against the original bytes.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

/// The category a rule produces. The wire form is the string a consumer indexes on.
///
/// Types are per domain rather than per shape: they are the facets somebody would actually build,
/// and each one maps onto a FollowTheMoney property. Several types share one [`Value`] shape, which
/// is why the value carries its own discriminant.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EntityType {
    Date,
    Email,
    Phone,
    Money,
    BankAccount,
    CompanyId,
    Security,
    Vessel,
    CargoContainer,
    Device,
    Network,
    Publication,
    Vulnerability,
    CryptoWallet,
    Coordinates,
    NationalId,
    MessageId,
}

impl EntityType {
    /// Decides which type wins when two accepted spans overlap. A higher number wins.
    ///
    /// Precedence is by structural strength, not by usefulness: a type whose acceptance depended on
    /// a checksum or a calendar check is far less likely to be the accidental reading of the two,
    /// so it outranks a type that only had to look right. The bands are shared. Types that had the
    /// same evidence available to them get the same number, and length then position break the tie.
    ///
    /// `date` sitting below every identifier is deliberate: an eight-digit run inside a longer
    /// reference is the overlap this ordering exists to settle, and the identifier is the less
    /// accidental reading.
    pub fn precedence(self) -> u8 {
        match self {
            // Check digit plus a self-identifying prefix or fixed alphabet.
            EntityType::BankAccount
            | EntityType::CompanyId
            | EntityType::Security
            | EntityType::CargoContainer
            | EntityType::NationalId => 95,
            // Check digit on a bare token, admitted on a cue word.
            EntityType::Vessel | EntityType::Device => 85,
            // A self-identifying literal prefix, no check digit.
            EntityType::Vulnerability
            | EntityType::Publication
            | EntityType::MessageId
            | EntityType::CryptoWallet => 75,
            // Structure plus membership of an authoritative list.
            EntityType::Email | EntityType::Phone | EntityType::Network => 65,
            // Structure plus separator inference.
            EntityType::Money => 45,
            // Calendar validity plus a plausibility window.
            EntityType::Date => 35,
            // A range check and nothing else.
            EntityType::Coordinates => 25,
        }
    }
}

/// A machine-readable caveat attached to an otherwise accepted match.
///
/// Flags are the alternative to guessing silently. An ambiguity that a document cannot resolve is
/// reported as an ambiguity; it is never resolved by coin flip and presented as certainty.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Flag {
    /// The day and month could be either way round and nothing in reach decides it.
    AmbiguousOrder,
    /// The value carries no time zone, so the instant is only defined up to the reader's guess.
    NoTimezone,
    /// The format carries no check digit, so acceptance rests on structure, list membership and
    /// context alone. The number is well-formed; nothing arithmetic corroborates it.
    NoChecksum,
    /// The symbol maps to more than one ISO 4217 code and nothing in reach decides which.
    AmbiguousCurrency,
    /// The decimal and grouping separators were inferred rather than unambiguous, so the magnitude
    /// rests on a convention the document did not state.
    SeparatorInferred,
}

/// The canonical value a match normalises to, which is the entire point of the second stage.
///
/// Internally tagged on `kind`, so an entity deserialises back into this type by construction and
/// a consumer can dispatch on the shape without knowing the rule set. The tag is the shape of the
/// fields, not the facet: many identifier rules across several [`EntityType`]s all produce
/// [`Value::Identifier`].
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum Value {
    Date {
        /// The instant or civil time in RFC 3339 form, truncated to `precision`.
        rfc3339: String,
        precision: DatePrecision,
        /// False when the offset was absent and had to be left unstated.
        tz_known: bool,
    },
    Email {
        /// Local part unchanged, domain lowercased, the RFC-correct normalisation.
        address: String,
        local: String,
        domain: String,
    },
    Phone {
        /// E.164 form, `+` then country calling code then the national number.
        e164: String,
        /// ISO 3166-1 alpha-2 region the number belongs to, or `001` for the global services
        /// (freephone, satellite) that the ITU allocates to no country.
        country: String,
        /// The national significant number, without the country calling code.
        national: String,
        /// `mobile`, `fixed_line`, `toll_free` and the like, or `unknown` when the metadata does
        /// not narrow it.
        number_type: String,
    },
    Money {
        /// ISO 4217 alphabetic code.
        currency: String,
        /// Minor units as a string-encoded integer. A JSON number is a double in most consumers,
        /// and a sum of money is not a float.
        amount_minor: String,
        /// ISO 4217 minor-unit count, so the major-unit value is `amount_minor / 10^exponent`
        /// computed in integers by whoever needs it.
        exponent: u8,
    },
    Identifier {
        /// Which scheme this is: `iban`, `lei`, `isin`. It is what makes two identifiers with the
        /// same digits distinguishable.
        scheme: String,
        /// Separators and case normalised away, which is the form to join on.
        compact: String,
        /// ISO 3166-1 alpha-2, where the identifier itself encodes one. Promoted out of `parts`
        /// because it is cross-scheme and maps to a FollowTheMoney property of its own.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        country: Option<String>,
        /// Scheme-specific components sliced out of the identifier: bank code, check digits,
        /// issuer. A named field per scheme across two dozen schemes would force a model change
        /// for every new one.
        #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
        parts: BTreeMap<String, String>,
    },
    NetworkAddress {
        /// `ipv4` or `ipv6`.
        family: String,
        /// Canonical textual form: lowercase and compressed for IPv6.
        address: String,
        /// Present when the surface form carried a CIDR prefix.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        prefix_length: Option<u8>,
    },
    GeoPoint {
        latitude: f64,
        longitude: f64,
        /// The reference frame the pair is in, `wgs84` unless the text names another.
        datum: String,
    },
}

/// How far down a date was actually specified. A date field indexed at the wrong precision reads
/// as spurious accuracy, so the precision travels with the value.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DatePrecision {
    Day,
    Minute,
    Second,
}

/// One accepted match.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Entity {
    #[serde(rename = "type")]
    pub entity_type: EntityType,
    /// Byte offset of the first byte of the match in the source document.
    pub start: usize,
    /// Byte offset one past the last byte of the match.
    pub end: usize,
    /// The surface form exactly as it appears, for highlighting and for showing a user why.
    pub text: String,
    pub value: Value,
    pub confidence: f32,
    /// Which rule produced this. Without it, tracking down a bad facet over a real corpus means
    /// guessing, so it is part of the contract rather than a debug aid.
    pub rule_id: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub flags: Vec<Flag>,
}

impl Value {
    /// The single normalised string a facet is keyed on.
    ///
    /// One string per value, chosen so that two surface forms of the same fact collapse: a phone
    /// number written three ways is one `+44…`, an IBAN with and without spaces is one compact
    /// form. Money keeps its full precision here. The magnitude bucketing a facet needs is a
    /// consumer's decision, and a value that arrives already bucketed cannot be un-bucketed.
    pub fn facet_key(&self) -> String {
        match self {
            Value::Date { rfc3339, .. } => rfc3339.clone(),
            Value::Email { address, .. } => address.clone(),
            Value::Phone { e164, .. } => e164.clone(),
            Value::Money {
                currency,
                amount_minor,
                exponent,
            } => format!("{currency} {}", major_units(amount_minor, *exponent)),
            Value::Identifier { compact, .. } => compact.clone(),
            Value::NetworkAddress {
                address,
                prefix_length,
                ..
            } => match prefix_length {
                Some(bits) => format!("{address}/{bits}"),
                None => address.clone(),
            },
            Value::GeoPoint {
                latitude,
                longitude,
                ..
            } => format!("{latitude},{longitude}"),
        }
    }
}

/// Minor units rendered as a major-unit decimal, in integer arithmetic.
///
/// A sum of money that round-trips through a float has already lost the property that makes it a
/// sum of money, so the decimal point is inserted into the digit string rather than computed.
fn major_units(amount_minor: &str, exponent: u8) -> String {
    let exponent = exponent as usize;
    if exponent == 0 {
        return amount_minor.to_string();
    }
    let (sign, digits) = match amount_minor.strip_prefix('-') {
        Some(rest) => ("-", rest),
        None => ("", amount_minor),
    };
    let padded = if digits.len() <= exponent {
        format!("{}{digits}", "0".repeat(exponent + 1 - digits.len()))
    } else {
        digits.to_string()
    };
    let split = padded.len() - exponent;
    format!("{sign}{}.{}", &padded[..split], &padded[split..])
}

#[cfg(test)]
mod facet_key_tests {
    use super::*;

    #[test]
    fn money_renders_minor_units_without_a_float() {
        let value = Value::Money {
            currency: "USD".into(),
            amount_minor: "2500000".into(),
            exponent: 2,
        };
        assert_eq!(value.facet_key(), "USD 25000.00");
    }

    #[test]
    fn money_pads_an_amount_shorter_than_its_exponent() {
        let value = Value::Money {
            currency: "EUR".into(),
            amount_minor: "7".into(),
            exponent: 2,
        };
        assert_eq!(value.facet_key(), "EUR 0.07");
    }

    #[test]
    fn a_zero_exponent_currency_keeps_its_digits() {
        let value = Value::Money {
            currency: "JPY".into(),
            amount_minor: "1200".into(),
            exponent: 0,
        };
        assert_eq!(value.facet_key(), "JPY 1200");
    }
}
