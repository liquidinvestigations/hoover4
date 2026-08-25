//! Email addresses.
//!
//! The strictness question is settled deliberately: full RFC 5322 (quoted local parts, comments,
//! folding whitespace) accepts a great deal nobody writes and costs a famously large pattern to
//! express. What works on real corpora is a pragmatic shape plus a TLD membership test,
//! which is where nearly all of the precision comes from.

use crate::model::{EntityType, Value};
use crate::rules::{Candidate, Rule, Verdict};

pub struct EmailRule;

/// Local part characters we accept unquoted, then a domain of dot-separated LDH labels.
const PATTERN: &str = r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+";

/// RFC 5321 §4.5.3.1 limits, which double as length limits against runaway matches.
const MAX_LOCAL: usize = 64;
const MAX_DOMAIN: usize = 255;

impl Rule for EmailRule {
    fn id(&self) -> &'static str {
        "email.basic"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Email
    }

    fn candidate_pattern(&self) -> &'static str {
        PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // The pattern carries no boundary guards, so a match cut out of a longer token is
        // possible; an address is only an address when nothing addressable runs into it from
        // either side. The right-hand guard is what keeps a shortened re-scan of `icons@2x.png`
        // from landing on `icons@2x.pn` and finding a real country-code domain at the end of it.
        if let Some(before) = candidate.byte_before() {
            if before.is_ascii_alphanumeric() || b"._%+-@".contains(&before) {
                return None;
            }
        }
        if let Some(after) = candidate.byte_after() {
            if after.is_ascii_alphanumeric() || b"-_%+@".contains(&after) {
                return None;
            }
        }

        let mut text = candidate.text();
        let mut end = candidate.end;

        // A trailing dot belongs to the sentence, not the address. The pattern cannot know that,
        // and trimming here keeps the pattern readable.
        while text.ends_with('.') {
            end -= 1;
            text = &candidate.fragment[candidate.start..end];
        }

        let (local, domain) = text.rsplit_once('@')?;
        if local.is_empty() || local.len() > MAX_LOCAL || domain.len() > MAX_DOMAIN {
            return None;
        }
        // Consecutive dots and a leading or trailing dot are invalid unquoted.
        if local.starts_with('.') || local.ends_with('.') || local.contains("..") {
            return None;
        }

        let tld = domain.rsplit('.').next()?;
        if !candidate.data.is_known_tld(tld) {
            return None;
        }

        Some(Verdict {
            start: candidate.start,
            end,
            value: Value::Email {
                address: format!("{}@{}", local, domain.to_lowercase()),
                local: local.to_string(),
                domain: domain.to_lowercase(),
            },
            confidence: 0.95,
            flags: Vec::new(),
        })
    }
}
