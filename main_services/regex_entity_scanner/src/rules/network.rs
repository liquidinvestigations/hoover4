//! Network addresses and autonomous system numbers.
//!
//! `network.ip` does no pattern arithmetic: the candidate is handed to `std::net`, whose parsers
//! are the definition of the two address formats and already enforce octet ranges, group counts
//! and the single `::` elision. What is left for the validator is everything the parser cannot
//! know — that a dotted quad in a document is not always an address, and that four numbers
//! separated by dots is also how software versions are written.

use std::collections::BTreeMap;
use std::net::{Ipv4Addr, Ipv6Addr};

use crate::model::{EntityType, Flag, Value};
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{Candidate, Rule, Verdict};

/// Words that make a dotted quad a release number rather than an address. This is a negative
/// context test: the presence of one of these rejects, where a cue word would admit.
const VERSION_CUES: &[&str] = &[
    "version", "versions", "release", "build", "firmware", "revision", "semver",
];

// ---------------------------------------------------------------------------------------------
// IP addresses
// ---------------------------------------------------------------------------------------------

pub struct IpRule;

/// A dotted quad or a run of colon-separated hex groups, either optionally followed by a prefix
/// length. Both halves over-match wildly — `09:12:00` matches the second — because `std::net` is
/// the validator and rejecting there is cheaper than encoding the grammar twice.
///
/// The IPv6 form that ends in a dotted quad — `::ffff:192.0.2.1`, RFC 4291's IPv4-mapped and
/// IPv4-compatible addresses — is its own alternative and stands first, because alternation is
/// leftmost-first: without it the hex run stops at `::ffff:192` and the quad behind it is then a
/// slice of a longer dotted run, so the whole address yields nothing.
const IP_PATTERN: &str = r"(?:[0-9A-Fa-f]{0,4}:){2,7}\d{1,3}[.]\d{1,3}[.]\d{1,3}[.]\d{1,3}(?:/\d{1,3})?|\d{1,3}[.]\d{1,3}[.]\d{1,3}[.]\d{1,3}(?:/\d{1,2})?|[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?:/\d{1,3})?";

impl Rule for IpRule {
    fn id(&self) -> &'static str {
        "network.ip"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Network
    }

    fn candidate_pattern(&self) -> &'static str {
        IP_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'.' || b == b':' || b == b'-')
        {
            return None;
        }
        if !ends_the_address(candidate) {
            return None;
        }

        let text = candidate.text();
        let (address, prefix) = match text.split_once('/') {
            Some((address, prefix)) => (address, Some(prefix.parse::<u8>().ok()?)),
            None => (text, None),
        };

        let (family, canonical, max_prefix) = if let Ok(parsed) = address.parse::<Ipv4Addr>() {
            // A four-component dotted number is also how a release is written, and no arithmetic
            // separates the two — only the words around them do.
            if candidate.has_cue(VERSION_CUES, DEFAULT_CUE_WINDOW) {
                return None;
            }
            ("ipv4", parsed.to_string(), 32)
        } else if let Ok(parsed) = address.parse::<Ipv6Addr>() {
            ("ipv6", parsed.to_string(), 128)
        } else {
            return None;
        };

        if prefix.is_some_and(|length| length > max_prefix) {
            return None;
        }

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::NetworkAddress {
                family: family.to_string(),
                address: canonical,
                prefix_length: prefix,
            },
            confidence: 0.95,
            flags: vec![Flag::NoChecksum],
        })
    }
}

/// Whether nothing continues the address past its right-hand edge. A trailing full stop ends a
/// sentence unless a digit follows it, in which case the match is a slice of a longer dotted run.
fn ends_the_address(candidate: &Candidate<'_>) -> bool {
    match candidate.byte_after() {
        None => true,
        Some(b'.') => !candidate
            .fragment
            .as_bytes()
            .get(candidate.end + 1)
            .is_some_and(u8::is_ascii_digit),
        Some(byte) => !(byte.is_ascii_alphanumeric() || byte == b':' || byte == b'/'),
    }
}

// ---------------------------------------------------------------------------------------------
// Autonomous system numbers
// ---------------------------------------------------------------------------------------------

pub struct AsnRule;

/// The literal prefix is mandatory, and a space is allowed only after the three-letter spelling —
/// `AS` followed by a space is the English word far more often than it is a network.
const ASN_PATTERN: &str = r"AS\d{1,10}|ASN[ ]?\d{1,10}";

impl Rule for AsnRule {
    fn id(&self) -> &'static str {
        "network.asn"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Network
    }

    fn candidate_pattern(&self) -> &'static str {
        ASN_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric())
            || candidate
                .byte_after()
                .is_some_and(|b| b.is_ascii_alphanumeric())
        {
            return None;
        }

        let text = candidate.text();
        let digits = text.trim_start_matches(['A', 'S', 'N', ' ']);
        let number: u32 = digits.parse().ok()?;
        // Zero is reserved and never assigned; the space itself is the whole 32-bit range.
        if number == 0 {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("number".to_string(), number.to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "asn".to_string(),
                compact: format!("AS{number}"),
                country: None,
                parts,
            },
            confidence: 0.90,
            flags: vec![Flag::NoChecksum],
        })
    }
}
