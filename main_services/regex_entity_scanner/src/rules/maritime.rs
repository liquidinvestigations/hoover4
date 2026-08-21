//! Ship and container identifiers: IMO numbers, MMSIs, ISO 6346 container numbers.
//!
//! The three sit at different points of the same trade-off. A container number carries a fixed
//! four-letter owner code whose last letter is drawn from a four-character alphabet, which makes it
//! self-identifying, and it is checksummed. An IMO number is a bare seven-digit run with a check
//! digit, so the literal `IMO` marker or a word beside it is what makes acceptance defensible. An
//! MMSI has **no check digit at all** — a valid Maritime Identification Digit triple plus a cue
//! word is the whole precision story, and the flag state falls out of the same lookup.

use std::collections::BTreeMap;

use crate::model::{EntityType, Flag, Value};
use crate::rules::checksum::weighted_mod;
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{Candidate, Rule, Verdict};

/// The words that admit a bare seven-digit hull number. They appear verbatim in the catalogue
/// entry, because "this was accepted because the word tanker was nearby" is what a reader needs in
/// order to weigh the match.
const IMO_CUES: &[&str] = &["IMO", "vessel", "ship", "tanker", "hull", "flag"];

/// The words that admit an MMSI. Nine digits with no checksum is the weakest surface form here.
const MMSI_CUES: &[&str] = &["MMSI", "AIS", "call sign", "callsign", "vessel", "ship"];

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
// IMO ship identification number
// ---------------------------------------------------------------------------------------------

pub struct ImoRule;

/// The literal marker is optional in the pattern and mandatory in the validator unless a cue word
/// stands in for it — the separator is only allowed when the marker is present, so a bare digit run
/// can never acquire a leading space.
const IMO_PATTERN: &str = r"(?:IMO[ :]{0,3})?\d{7}";

impl Rule for ImoRule {
    fn id(&self) -> &'static str {
        "vessel.imo"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Vessel
    }

    fn candidate_pattern(&self) -> &'static str {
        IMO_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let marked = text.starts_with("IMO");
        let digits = text.get(text.len() - 7..)?;

        // A bare seven-digit run is an order number, an invoice line and a postcode as often as it
        // is a hull, so it is admitted only when something nearby says what it is.
        if !marked && !candidate.has_cue(IMO_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let values: Vec<u32> = digits
            .chars()
            .map(|character| character.to_digit(10))
            .collect::<Option<_>>()?;
        if weighted_mod(&values[..6], &[7, 6, 5, 4, 3, 2], 10) != values[6] {
            return None;
        }

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "imo".to_string(),
                compact: digits.to_string(),
                country: None,
                parts: BTreeMap::new(),
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

// ---------------------------------------------------------------------------------------------
// MMSI
// ---------------------------------------------------------------------------------------------

pub struct MmsiRule;

const MMSI_PATTERN: &str = r"\d{9}";

impl Rule for MmsiRule {
    fn id(&self) -> &'static str {
        "vessel.mmsi"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Vessel
    }

    fn candidate_pattern(&self) -> &'static str {
        MMSI_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }
        if !candidate.has_cue(MMSI_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        // The flag state lives in the first three digits for a ship station. Coast stations,
        // group calls and craft associated with a parent ship shift the triple to another
        // position; those forms are not matched, because reading the wrong three digits as a MID
        // is worse than not reading them.
        let country = candidate.data.maritime_id_country(text.get(0..3)?)?;

        let mut parts = BTreeMap::new();
        parts.insert("mid".to_string(), text[0..3].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "mmsi".to_string(),
                compact: text.to_string(),
                country: Some(country.to_string()),
                parts,
            },
            confidence: 0.90,
            flags: vec![Flag::NoChecksum],
        })
    }
}

// ---------------------------------------------------------------------------------------------
// ISO 6346 container number
// ---------------------------------------------------------------------------------------------

pub struct ContainerRule;

/// Three letters of owner code, a category letter from a four-character alphabet, six digits of
/// serial and a check digit. Written forms group the number, so single spaces are matched and
/// stripped.
const CONTAINER_PATTERN: &str = r"[A-Z]{3}[UJZR][ ]?\d{6}[ ]?\d";

impl Rule for ContainerRule {
    fn id(&self) -> &'static str {
        "container.iso6346"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::CargoContainer
    }

    fn candidate_pattern(&self) -> &'static str {
        CONTAINER_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let compact: String = text.chars().filter(|c| !c.is_whitespace()).collect();
        if compact.len() != 11 {
            return None;
        }
        if iso6346_check_digit(compact.get(0..10)?)? != compact.as_bytes()[10] - b'0' {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("owner".to_string(), compact[0..3].to_string());
        parts.insert("category".to_string(), compact[3..4].to_string());
        parts.insert("serial".to_string(), compact[4..10].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "iso6346".to_string(),
                compact,
                country: None,
                parts,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

/// The ISO 6346 check digit: each character's value times a power of two, summed, modulo eleven and
/// then modulo ten. The letter values skip every multiple of eleven, which is why the alphabet is
/// written out rather than computed from the letter's position.
fn iso6346_check_digit(body: &str) -> Option<u8> {
    /// `0-9` then the letters, with a gap wherever the value would be a multiple of eleven.
    const ALPHABET: &str = "0123456789A BCDEFGHIJK LMNOPQRSTU VWXYZ";

    let mut sum = 0u64;
    for (index, character) in body.chars().enumerate() {
        let value = ALPHABET.find(character).filter(|_| character != ' ')? as u64;
        sum += value * 2u64.pow(index as u32);
    }
    Some((sum % 11 % 10) as u8)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The documented pair from `stdnum/iso6346.py`: the same body with the right check digit and
    /// the wrong one.
    #[test]
    fn the_container_check_digit_matches_the_reference() {
        assert_eq!(iso6346_check_digit("CSQU305438"), Some(3));
        assert_eq!(iso6346_check_digit("TASU117000"), Some(0));
        // A space is in the alphabet string only as padding; it is not a container character.
        assert_eq!(iso6346_check_digit("CSQU30543 "), None);
    }
}
