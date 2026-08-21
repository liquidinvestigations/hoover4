//! Securities identifiers: ISIN, CUSIP, SEDOL.
//!
//! The three sit at different points on the same trade-off. An ISIN carries a country prefix and a
//! fixed twelve-character length, so its checksum is enough. A CUSIP and a SEDOL are bare
//! alphanumeric tokens of nine and seven characters, which is the shape of every part number and
//! internal reference code in existence — their check digit is a one-in-ten filter and the word
//! beside them is what makes acceptance defensible.

use std::collections::BTreeMap;

use crate::model::{EntityType, Value};
use crate::rules::checksum::{luhn, weighted_mod};
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{Candidate, Rule, Verdict};

/// The words that admit a bare securities token. They appear verbatim in the catalogue entries for
/// `security.cusip` and `security.sedol`, because "this was accepted because the word SEDOL was
/// nearby" is what a reader needs in order to weigh the match.
const SECURITY_CUES: &[&str] = &["CUSIP", "SEDOL", "ISIN", "ticker", "security", "CIK"];

/// Whether the neighbouring bytes make this a token in its own right rather than a slice of a
/// longer one. Every format here is fixed-length, so both sides are guards.
fn is_standalone(candidate: &Candidate<'_>) -> bool {
    !candidate
        .byte_before()
        .is_some_and(|b| b.is_ascii_alphanumeric())
        && !candidate
            .byte_after()
            .is_some_and(|b| b.is_ascii_alphanumeric())
}

// ---------------------------------------------------------------------------------------------
// ISIN
// ---------------------------------------------------------------------------------------------

pub struct IsinRule;

/// Two letters of country, nine of national identifier, one check digit.
const ISIN_PATTERN: &str = r"[A-Z]{2}[A-Z0-9]{9}\d";

/// Prefixes ISO 6166 allows that are not countries: the substitute-agency ranges, the codes
/// exchanges use internally, and `XS` for internationally cleared securities. Without these the
/// rule silently drops every Eurobond.
const ISIN_NON_COUNTRY_PREFIXES: [&str; 9] = ["EU", "QS", "QT", "XA", "XB", "XC", "XD", "XF", "XS"];

impl Rule for IsinRule {
    fn id(&self) -> &'static str {
        "security.isin"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Security
    }

    fn candidate_pattern(&self) -> &'static str {
        ISIN_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let prefix = text.get(0..2)?;
        if !candidate.data.is_country_code(prefix) && !ISIN_NON_COUNTRY_PREFIXES.contains(&prefix) {
            return None;
        }

        // Luhn over the letter-expanded form: each letter becomes its two-digit base-36 value, and
        // the resulting digit string, check digit included, has to satisfy the ordinary algorithm.
        if !luhn(&expand_letters(text)?) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("national_number".to_string(), text[2..11].to_string());
        parts.insert("check_digit".to_string(), text[11..12].to_string());

        // The substitute-agency prefixes are not countries, so the country is reported only where
        // one was actually encoded.
        let country = candidate
            .data
            .is_country_code(prefix)
            .then(|| prefix.to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "isin".to_string(),
                compact: text.to_string(),
                country,
                parts,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

/// Rewrites letters as their base-36 value in decimal, which is what turns an alphanumeric code
/// into something the Luhn algorithm can run over. `None` for a character outside `0-9A-Z`.
fn expand_letters(text: &str) -> Option<String> {
    let mut expanded = String::with_capacity(text.len() * 2);
    for character in text.chars() {
        let value = character.to_digit(36)?;
        if value < 10 {
            expanded.push(character);
        } else {
            expanded.push_str(&value.to_string());
        }
    }
    Some(expanded)
}

// ---------------------------------------------------------------------------------------------
// CUSIP
// ---------------------------------------------------------------------------------------------

pub struct CusipRule;

/// Six characters of issuer, two of issue, one check digit.
const CUSIP_PATTERN: &str = r"[A-Z0-9]{8}\d";

impl Rule for CusipRule {
    fn id(&self) -> &'static str {
        "security.cusip"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Security
    }

    fn candidate_pattern(&self) -> &'static str {
        CUSIP_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }
        if !candidate.has_cue(SECURITY_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        if cusip_check_digit(text.get(0..8)?)? != text.as_bytes()[8] - b'0' {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("issuer".to_string(), text[0..6].to_string());
        parts.insert("issue".to_string(), text[6..8].to_string());
        parts.insert("check_digit".to_string(), text[8..9].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "cusip".to_string(),
                compact: text.to_string(),
                country: None,
                parts,
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

/// The CUSIP check digit: alternating weights of one and two, and the **digits of each product**
/// summed rather than the product itself, which is what makes it a Luhn variant rather than a plain
/// weighted sum.
fn cusip_check_digit(body: &str) -> Option<u8> {
    let mut sum = 0u32;
    for (index, character) in body.chars().enumerate() {
        let value = character.to_digit(36)?;
        let product = value * if index % 2 == 0 { 1 } else { 2 };
        sum += product / 10 + product % 10;
    }
    Some(((10 - sum % 10) % 10) as u8)
}

// ---------------------------------------------------------------------------------------------
// SEDOL
// ---------------------------------------------------------------------------------------------

pub struct SedolRule;

/// Six characters and a check digit. The alphabet has no vowels, which is the one piece of
/// self-identification the format offers and is written into the pattern.
const SEDOL_PATTERN: &str = r"[0-9BCDFGHJKLMNPQRSTVWXYZ]{6}\d";

impl Rule for SedolRule {
    fn id(&self) -> &'static str {
        "security.sedol"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Security
    }

    fn candidate_pattern(&self) -> &'static str {
        SEDOL_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }
        if !candidate.has_cue(SECURITY_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        // Numbers issued since 2004 start with a letter; the older ones are entirely numeric. A
        // digit followed by letters is neither.
        let first_is_digit = text.as_bytes()[0].is_ascii_digit();
        if first_is_digit && !text.bytes().all(|b| b.is_ascii_digit()) {
            return None;
        }

        let values: Vec<u32> = text
            .get(0..6)?
            .chars()
            .map(|character| character.to_digit(36))
            .collect::<Option<_>>()?;
        let check = (10 - weighted_mod(&values, &[1, 3, 1, 7, 3, 9], 10)) % 10;
        if check != u32::from(text.as_bytes()[6] - b'0') {
            return None;
        }

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "sedol".to_string(),
                compact: text.to_string(),
                country: None,
                parts: BTreeMap::new(),
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The documented pair from `stdnum/cusip.py`: the same body with the right check digit and a
    /// wrong one.
    #[test]
    fn the_cusip_check_digit_matches_the_reference() {
        assert_eq!(cusip_check_digit("DUS0421C"), Some(5));
        assert_eq!(cusip_check_digit("91324PAE"), Some(2));
        assert_eq!(cusip_check_digit("DUS0421-"), None);
    }

    /// A letter becomes its base-36 value written out, which is what an ISIN's country prefix
    /// contributes to the Luhn sum.
    #[test]
    fn letters_expand_to_their_base_36_value() {
        assert_eq!(
            expand_letters("US0378331005").as_deref(),
            Some("30280378331005")
        );
        // `to_digit(36)` folds case, so the guard that matters is a character outside the alphabet.
        assert_eq!(expand_letters("US03783310-5"), None);
    }
}
