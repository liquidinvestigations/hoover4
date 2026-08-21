//! Identifiers whose surface form announces what they are: CVE ids, DOIs, ORCIDs, message ids.
//!
//! These are the cheapest precise rules in the set, and they are cheap for one reason: a literal
//! prefix or a fixed delimiter does the work that a check digit does elsewhere. `CVE-`, `10.` and
//! a pair of angle brackets are not things that occur by accident around the right number of
//! characters, so the validator's job is mostly to confirm the shape and normalise it.

use std::collections::BTreeMap;

use crate::model::{EntityType, Flag, Value};
use crate::rules::checksum::iso7064;
use crate::rules::{Candidate, Rule, Verdict};

/// The header names that make an angle-bracketed addr-spec a message id. Without one it is an
/// author or a recipient — `From: Anna Popescu <anna@example.co.uk>` has exactly the same shape —
/// and reading that as a message id both invents an entity and hides the address.
const MESSAGE_ID_HEADERS: &[&str] = &[
    "Message-ID",
    "In-Reply-To",
    "References",
    "Resent-Message-ID",
];

/// Whether the neighbouring bytes make this a token in its own right rather than a slice of a
/// longer one.
fn is_standalone(candidate: &Candidate<'_>) -> bool {
    !candidate
        .byte_before()
        .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'-')
        && !candidate
            .byte_after()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'-')
}

// ---------------------------------------------------------------------------------------------
// CVE
// ---------------------------------------------------------------------------------------------

pub struct CveRule;

const CVE_PATTERN: &str = r"CVE-\d{4}-\d{4,7}";

/// The scheme started in 1999, and a year far in the future is a digit run that happens to sit
/// behind the prefix rather than an identifier.
const CVE_YEARS: std::ops::RangeInclusive<u32> = 1999..=2100;

impl Rule for CveRule {
    fn id(&self) -> &'static str {
        "vulnerability.cve"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Vulnerability
    }

    fn candidate_pattern(&self) -> &'static str {
        CVE_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let mut fields = text.split('-');
        fields.next()?;
        let year: u32 = fields.next()?.parse().ok()?;
        let sequence = fields.next()?;
        if !CVE_YEARS.contains(&year) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("year".to_string(), year.to_string());
        parts.insert("sequence".to_string(), sequence.to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "cve".to_string(),
                compact: text.to_string(),
                country: None,
                parts,
            },
            confidence: 0.99,
            // The prefix is decisive, and there is no arithmetic behind it — both facts are worth
            // reporting, so the confidence is high and the flag says why it is not a checksum.
            flags: vec![Flag::NoChecksum],
        })
    }
}

// ---------------------------------------------------------------------------------------------
// DOI
// ---------------------------------------------------------------------------------------------

pub struct DoiRule;

/// The `10.` directory code, a registrant code, a slash and the registrant's own suffix. The
/// suffix is opaque and may hold almost anything, so the class is generous and the trailing
/// punctuation is trimmed in the validator instead.
const DOI_PATTERN: &str = r"10[.]\d{4,9}/[A-Za-z0-9()._;:+/-]{1,160}";

impl Rule for DoiRule {
    fn id(&self) -> &'static str {
        "publication.doi"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Publication
    }

    fn candidate_pattern(&self) -> &'static str {
        DOI_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'.')
        {
            return None;
        }

        // A DOI written in prose collects the sentence's punctuation. Trimming it here rather than
        // excluding it from the pattern is what lets a suffix legitimately end in a bracket.
        let text = candidate.text().trim_end_matches(['.', ',', ';', ':', ')']);
        let (prefix, suffix) = text.split_once('/')?;
        if suffix.is_empty() {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("registrant".to_string(), prefix.to_string());
        parts.insert("suffix".to_string(), suffix.to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.start + text.len(),
            value: Value::Identifier {
                // DOIs are case-insensitive, so one spelling is one index key.
                scheme: "doi".to_string(),
                compact: text.to_ascii_lowercase(),
                country: None,
                parts,
            },
            confidence: 0.95,
            flags: vec![Flag::NoChecksum],
        })
    }
}

// ---------------------------------------------------------------------------------------------
// ORCID
// ---------------------------------------------------------------------------------------------

pub struct OrcidRule;

/// Sixteen digits in four hyphenated groups, the last character possibly `X` for a check value of
/// ten.
const ORCID_PATTERN: &str = r"\d{4}-\d{4}-\d{4}-\d{3}[0-9X]";

impl Rule for OrcidRule {
    fn id(&self) -> &'static str {
        "publication.orcid"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Publication
    }

    fn candidate_pattern(&self) -> &'static str {
        ORCID_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let digits: String = text.chars().filter(|c| *c != '-').collect();
        if !iso7064::mod_11_2(&digits) {
            return None;
        }

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "orcid".to_string(),
                compact: text.to_string(),
                country: None,
                parts: BTreeMap::new(),
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

// ---------------------------------------------------------------------------------------------
// Message-ID
// ---------------------------------------------------------------------------------------------

pub struct MessageIdRule;

/// An addr-spec inside angle brackets. The brackets are what make it a message id rather than an
/// address, so they are in the pattern and in the span, and not in the value.
///
/// The right side is not required to be a domain. RFC 5322 §3.6.4's `id-right` admits a bare
/// `dot-atom-text`, and a real internal mail system emits exactly that — `<…@thyme>`,
/// `<foo@localhost>`. A registered top-level domain is a plausible-looking guard here but it is the
/// wrong one: it turns away well-formed identifiers, and the header label is what carries the
/// precision.
const MESSAGE_ID_PATTERN: &str =
    r"<[A-Za-z0-9!#%&'*+/=?_{}|~.-]{1,120}@[A-Za-z0-9][A-Za-z0-9.-]{0,80}>";

/// Whether one of the header names labels this candidate.
///
/// Proximity is not a label. A header name to the right of a value, or one with prose between it
/// and the value, says nothing about it — `Please quote the Message-ID when you reply to
/// <legal@example.com>` names an address. So the walk left from the candidate crosses only what a
/// header value may legitimately contain before its first token: whitespace, the folding line
/// break, list punctuation, and complete angle-bracketed groups, which is the `References:` list
/// form. What remains has to end in the header name and its colon.
fn labelled_by_header(candidate: &Candidate<'_>) -> bool {
    let before = &candidate.fragment[..candidate.start];
    let bytes = before.as_bytes();
    let mut at = before.len();
    loop {
        while at > 0 && matches!(bytes[at - 1], b' ' | b'\t' | b'\r' | b'\n' | b',' | b';') {
            at -= 1;
        }
        if at > 0 && bytes[at - 1] == b'>' {
            let Some(open) = before[..at - 1].rfind('<') else {
                return false;
            };
            at = open;
            continue;
        }
        break;
    }
    if at == 0 || bytes[at - 1] != b':' {
        return false;
    }
    let label = before[..at - 1].trim_end();
    MESSAGE_ID_HEADERS.iter().any(|header| {
        label.len().checked_sub(header.len()).is_some_and(|from| {
            label[from..].eq_ignore_ascii_case(header)
                && !label[..from]
                    .bytes()
                    .next_back()
                    .is_some_and(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        })
    })
}

impl Rule for MessageIdRule {
    fn id(&self) -> &'static str {
        "message.rfc5322"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::MessageId
    }

    fn candidate_pattern(&self) -> &'static str {
        MESSAGE_ID_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !labelled_by_header(candidate) {
            return None;
        }

        let text = candidate.text();
        let inner = text.get(1..text.len() - 1)?;
        let (local, domain) = inner.rsplit_once('@')?;
        if local.is_empty() || domain.ends_with('.') {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("local".to_string(), local.to_string());
        parts.insert("domain".to_string(), domain.to_ascii_lowercase());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "message-id".to_string(),
                compact: inner.to_string(),
                country: None,
                parts,
            },
            confidence: 0.90,
            flags: vec![Flag::NoChecksum],
        })
    }
}
