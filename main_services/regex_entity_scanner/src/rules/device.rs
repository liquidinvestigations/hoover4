//! Equipment identifiers: IMEI and MAC address.
//!
//! The two are opposites in what makes them findable. An IMEI is a bare fifteen-digit run with a
//! Luhn check digit — the arithmetic is a one-in-ten filter and the word beside it is what makes
//! acceptance defensible. A MAC address has no checksum at all, but its separators make it
//! self-identifying; the bare twelve-hex form is deliberately **not** matched, because it is
//! indistinguishable from half a hash.

use std::collections::BTreeMap;

use crate::model::{EntityType, Flag, Value};
use crate::rules::checksum::luhn;
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{Candidate, Rule, Verdict};

/// The words that admit a bare fifteen-digit run. They appear verbatim in the catalogue entry.
const IMEI_CUES: &[&str] = &["IMEI", "handset", "device"];

// ---------------------------------------------------------------------------------------------
// IMEI
// ---------------------------------------------------------------------------------------------

pub struct ImeiRule;

/// Eight digits of type allocation code, six of serial and a check digit. The grouped written form
/// separates them with hyphens or spaces, so those are matched and stripped.
const IMEI_PATTERN: &str = r"\d{2}[- ]?\d{6}[- ]?\d{6}[- ]?\d";

impl Rule for ImeiRule {
    fn id(&self) -> &'static str {
        "device.imei"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Device
    }

    fn candidate_pattern(&self) -> &'static str {
        IMEI_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // Both sides guard, and the separator characters guard too: a fifteen-digit slice of a
        // longer run is not an IMEI, and neither is one taken out of a longer hyphenated code.
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'-')
            || candidate
                .byte_after()
                .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'-')
        {
            return None;
        }
        if !candidate.has_cue(IMEI_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        let compact: String = text.chars().filter(char::is_ascii_digit).collect();
        if compact.len() != 15 || !luhn(&compact) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("tac".to_string(), compact[0..8].to_string());
        parts.insert("serial".to_string(), compact[8..14].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "imei".to_string(),
                compact,
                country: None,
                parts,
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

// ---------------------------------------------------------------------------------------------
// MAC address
// ---------------------------------------------------------------------------------------------

pub struct MacRule;

/// Six colon- or hyphen-separated octets, or the three dotted quads Cisco equipment prints. The
/// twelve bare hex characters that some tools emit are not here on purpose.
const MAC_PATTERN: &str =
    r"[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}|[0-9A-Fa-f]{4}(?:[.][0-9A-Fa-f]{4}){2}";

impl Rule for MacRule {
    fn id(&self) -> &'static str {
        "device.mac"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Device
    }

    fn candidate_pattern(&self) -> &'static str {
        MAC_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        let text = candidate.text();

        // A certificate fingerprint is twenty colon-separated octets, and any six consecutive ones
        // of it look exactly like this. Refusing to start or end beside a separator is what keeps
        // the fingerprint out, and it costs nothing a real address needs.
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b':' || b == b'-' || b == b'.')
        {
            return None;
        }
        if !ends_the_address(candidate) {
            return None;
        }

        let separators: Vec<char> = text.chars().filter(|c| !c.is_ascii_hexdigit()).collect();
        // Mixed separators are a coincidence of two adjacent fields, not an address.
        if separators.windows(2).any(|pair| pair[0] != pair[1]) {
            return None;
        }

        let hex: String = text.chars().filter(char::is_ascii_hexdigit).collect();
        if hex.len() != 12 {
            return None;
        }
        let lowered = hex.to_ascii_lowercase();
        let compact = lowered
            .as_bytes()
            .chunks(2)
            .map(|pair| std::str::from_utf8(pair).unwrap_or_default().to_string())
            .collect::<Vec<_>>()
            .join(":");

        let mut parts = BTreeMap::new();
        // The first three octets are the IEEE-assigned organisationally unique identifier. The
        // registry that resolves one to a manufacturer is not vendored, so the bytes are reported
        // and not resolved.
        parts.insert("oui".to_string(), lowered[0..6].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "mac".to_string(),
                compact,
                country: None,
                parts,
            },
            confidence: 0.95,
            flags: vec![Flag::NoChecksum],
        })
    }
}

/// Whether nothing continues the address past its right-hand edge. A trailing full stop is a
/// sentence ending unless a hex digit follows it, in which case the match is a slice of a longer
/// dotted run.
fn ends_the_address(candidate: &Candidate<'_>) -> bool {
    match candidate.byte_after() {
        None => true,
        Some(b'.') => !candidate
            .fragment
            .as_bytes()
            .get(candidate.end + 1)
            .is_some_and(u8::is_ascii_hexdigit),
        Some(byte) => !(byte.is_ascii_alphanumeric() || byte == b':' || byte == b'-'),
    }
}
