//! Bank account and bank institution identifiers: IBAN, BIC, payment card and ABA routing number.
//!
//! The four sit at opposite ends of how much a pattern can carry on its own. An IBAN names its
//! country in its first two characters and closes with mod-97 over up to thirty-four of them, so it
//! is findable in bare text. A card number and a routing number are digit runs and nothing else,
//! and the arithmetic on them — Luhn, and a weighted mod-10 over nine digits — is a one-in-ten
//! filter that every long reference number in a document passes at that rate. Both are therefore
//! **cue-gated**: a run with a valid check digit and no word beside it saying what it is stays
//! silent, and if the cue requirement is ever dropped the rule goes with it.

use std::collections::BTreeMap;

use crate::model::{EntityType, Flag, Value};
use crate::rules::checksum::{iso7064, luhn, weighted_mod};
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{Candidate, Rule, Verdict};

// ---------------------------------------------------------------------------------------------
// IBAN
// ---------------------------------------------------------------------------------------------

pub struct IbanRule;

/// Deliberately loose: two letters, two check digits and a run that may carry the group separators
/// IBANs are written with as often as not. Length, alphabet and arithmetic are all the validator's
/// work, because they are per country and a pattern that encoded them would be ninety alternations.
///
/// The upper repetition bound is arithmetic and not policy. The longest registered IBAN is 34
/// characters, so 30 follow the four-character prefix; written in groups of four they carry up to
/// eight separators. A bound of 34 truncates a grouped candidate, the exact registry length then
/// fails, and the retry loop only ever shrinks a candidate — it can never grow one back.
const IBAN_PATTERN: &str = r"[A-Z]{2}\d{2}[A-Z0-9 -]{10,42}";

/// The separators a printed IBAN is grouped with. They are stripped from the value, because the
/// canonical form is compact: one account is one index key however the document spaced it.
const IBAN_SEPARATORS: [char; 2] = [' ', '-'];

impl Rule for IbanRule {
    fn id(&self) -> &'static str {
        "bank.iban"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::BankAccount
    }

    fn candidate_pattern(&self) -> &'static str {
        IBAN_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // Stripped `(?<![A-Z0-9])`: an IBAN growing out of a longer token is part of that token.
        // There is no matching guard on the right, and that is deliberate — the registry length is
        // exact, so a candidate whose tail is a page number is rejected on length and the scan
        // loop then finds the IBAN inside it.
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric())
        {
            return None;
        }

        // The pattern's character class contains the separators, so a match can end in one.
        let text = candidate.text().trim_end_matches(IBAN_SEPARATORS);
        let end = candidate.start + text.len();

        let compact: String = text
            .chars()
            .filter(|c| !IBAN_SEPARATORS.contains(c))
            .collect();
        let country_code = compact.get(0..2)?.to_string();
        let registry = candidate.data.iban_country(&country_code)?;

        if compact.len() != registry.length {
            return None;
        }
        if !matches_structure(compact.get(4..)?, &registry.structure) {
            return None;
        }
        // ISO 7064 mod-97-10 over the rearranged form: the country code and check digits move to
        // the end, which is what puts them inside the arithmetic.
        if !iso7064::mod_97_10(&format!("{}{}", &compact[4..], &compact[..4])) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("bban".to_string(), compact[4..].to_string());
        parts.insert("check_digits".to_string(), compact[2..4].to_string());
        if let Some([from, to]) = registry.bank {
            if let Some(bank) = compact.get(from..to) {
                parts.insert("bank_code".to_string(), bank.to_string());
            }
        }

        Some(Verdict {
            start: candidate.start,
            end,
            value: Value::Identifier {
                scheme: "iban".to_string(),
                compact,
                country: Some(country_code),
                parts,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

/// Whether a BBAN satisfies a registry structure string — a run of `<length>!<class>` groups where
/// `n` is digits, `a` letters and `c` alphanumerics.
///
/// This is the half of IBAN validation that mod-97 does not do: the checksum accepts about one
/// malformed candidate in ninety-seven, and the positional alphabet is what closes that gap.
fn matches_structure(bban: &str, structure: &str) -> bool {
    let mut rest = bban.as_bytes();
    let mut spec = structure;

    while !spec.is_empty() {
        let Some(bang) = spec.find('!') else {
            return false;
        };
        let Ok(count) = spec[..bang].parse::<usize>() else {
            return false;
        };
        let Some(class) = spec.as_bytes().get(bang + 1).copied() else {
            return false;
        };
        spec = &spec[bang + 2..];

        if rest.len() < count {
            return false;
        }
        let (group, remainder) = rest.split_at(count);
        rest = remainder;

        let ok = group.iter().all(|byte| match class {
            b'n' => byte.is_ascii_digit(),
            b'a' => byte.is_ascii_uppercase(),
            b'c' => byte.is_ascii_alphanumeric(),
            _ => false,
        });
        if !ok {
            return false;
        }
    }

    rest.is_empty()
}

// ---------------------------------------------------------------------------------------------
// BIC
// ---------------------------------------------------------------------------------------------

pub struct BicRule;

/// Four letters of institution code, two of country, two of location, and an optional three-letter
/// branch. ISO 9362 defines no check digit, so everything precise about this rule is in the
/// validator.
const BIC_PATTERN: &str = r"[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?";

/// A BIC is eight or eleven uppercase characters with no checksum, which is a shape ordinary
/// English words in a heading also have — `DOCUMENT` and `CUSTOMER` both carry a valid ISO 3166-1
/// country code in positions five and six. The label beside the code is what separates a bank
/// identifier from a capitalised word, so it is required.
const BIC_CUES: &[&str] = &[
    "bic",
    "swift",
    "swiftbic",
    "iban",
    "bank",
    "beneficiary",
    "correspondent",
];

impl Rule for BicRule {
    fn id(&self) -> &'static str {
        "bank.bic"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::BankAccount
    }

    fn candidate_pattern(&self) -> &'static str {
        BIC_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // The length is fixed at eight or eleven, so both neighbours are guards: a code cut out of
        // a longer token is not a code.
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric())
        {
            return None;
        }
        if candidate
            .byte_after()
            .is_some_and(|b| b.is_ascii_alphanumeric())
        {
            return None;
        }

        let text = candidate.text();
        if text.len() != 8 && text.len() != 11 {
            return None;
        }

        let country_code = text.get(4..6)?;
        // Membership in the country list is the structural half of the precision story: it is what
        // makes positions five and six mean something.
        if !candidate.data.is_country_code(country_code) {
            return None;
        }

        if !candidate.has_cue(BIC_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("institution".to_string(), text[0..4].to_string());
        parts.insert("location".to_string(), text[6..8].to_string());
        if text.len() == 11 {
            parts.insert("branch".to_string(), text[8..11].to_string());
        }

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "bic".to_string(),
                compact: text.to_string(),
                country: Some(country_code.to_string()),
                parts,
            },
            confidence: 0.95,
            flags: vec![Flag::NoChecksum],
        })
    }
}

// ---------------------------------------------------------------------------------------------
// Payment card
// ---------------------------------------------------------------------------------------------

pub struct PaymentCardRule;

/// Thirteen to nineteen digits carrying the group separators a printed card number is written
/// with. The interior class holds the separators as well as the digits, so the bound is on
/// characters rather than on digits: nineteen digits in groups of four carry four separators.
const PAYMENT_CARD_PATTERN: &str = r"[0-9](?:[0-9 -]{11,21})[0-9]";

/// The words that admit a card number. Presidio's own recogniser context list, narrowed to the
/// forms that survive a word-boundary test — its bare `credit` and `debit` are dropped, because a
/// credit note and a debit balance are ordinary invoice words and `card` already covers the two
/// phrases that matter.
const PAYMENT_CARD_CUES: &[&str] = &[
    "card",
    "cardholder",
    "visa",
    "mastercard",
    "amex",
    "discover",
    "jcb",
    "diners",
    "maestro",
];

/// The issuer identification ranges this rule admits, each with the lengths that issuer's cards
/// are, from ISO/IEC 7812-1's allocation of the major industry identifier.
///
/// Luhn over a long digit run is a one-in-ten filter, and long digit runs are what an invoice, an
/// order confirmation or a manifest is made of. The prefix table is what turns that filter into a
/// real one: the number has to begin inside a range an issuer was allocated **and** be as long as
/// that issuer's cards. Measured on a page of invoice-like text, the two together still leave
/// several article and tracking numbers standing, which is why the cue is required on top of them.
///
/// The airline range — major industry identifier 1 — is not here. Fifteen digits beginning with a
/// 1 is the shape of half the reference numbers in a logistics document, and a travel-agency card
/// is not what an investigative corpus is looking for.
type IssuerRange = (
    &'static str,
    &'static [(&'static str, &'static str)],
    &'static [usize],
);
const ISSUER_RANGES: &[IssuerRange] = &[
    ("Visa", &[("4", "4")], &[13, 16, 19]),
    ("Mastercard", &[("51", "55"), ("2221", "2720")], &[16]),
    ("American Express", &[("34", "34"), ("37", "37")], &[15]),
    (
        "Diners Club",
        &[("300", "305"), ("3095", "3095"), ("36", "36"), ("38", "39")],
        &[14, 16, 19],
    ),
    ("JCB", &[("3528", "3589")], &[16, 19]),
    (
        "Discover",
        &[
            ("6011", "6011"),
            ("644", "649"),
            ("65", "65"),
            ("622126", "622925"),
        ],
        &[16, 19],
    ),
    ("UnionPay", &[("62", "62")], &[16, 17, 18, 19]),
    (
        "Maestro",
        &[
            ("5018", "5018"),
            ("5020", "5020"),
            ("5038", "5038"),
            ("5893", "5893"),
            ("6304", "6304"),
            ("6759", "6759"),
            ("6761", "6763"),
        ],
        &[12, 13, 14, 15, 16, 17, 18, 19],
    ),
    ("Dankort", &[("5019", "5019")], &[16]),
    ("InterPayment", &[("636", "636")], &[16, 17, 18, 19]),
    ("InstaPayment", &[("637", "639")], &[16]),
];

impl Rule for PaymentCardRule {
    fn id(&self) -> &'static str {
        "bank.payment_card"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::BankAccount
    }

    fn candidate_pattern(&self) -> &'static str {
        PAYMENT_CARD_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // Both neighbours guard, and a hyphen guards with them. The scan loop shrinks a rejected
        // candidate from the right, so a longer digit run offers up every shorter prefix of
        // itself, and one shorter prefix in ten passes Luhn: a fifteen-digit IMEI hands over a
        // Luhn-valid thirteen-digit head. Refusing to end beside a digit is what turns that back
        // into silence.
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'-')
            || candidate
                .byte_after()
                .is_some_and(|b| b.is_ascii_alphanumeric() || b == b'-')
        {
            return None;
        }

        let text = candidate.text();
        // One separator character throughout or none at all. A run that mixes them is a reference
        // number that happens to hold digits, not a card written in groups.
        let separators: Vec<char> = text.chars().filter(|c| !c.is_ascii_digit()).collect();
        if separators.windows(2).any(|pair| pair[0] != pair[1]) {
            return None;
        }

        let compact: String = text.chars().filter(char::is_ascii_digit).collect();
        if !luhn(&compact) {
            return None;
        }
        let issuer = issuer_of(&compact)?;

        if !candidate.has_cue(PAYMENT_CARD_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("issuer".to_string(), issuer.to_string());
        parts.insert("iin".to_string(), compact.get(0..6)?.to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "payment_card".to_string(),
                compact,
                country: None,
                parts,
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

/// The issuer whose allocated range the number begins in and whose card length it has, or `None`.
fn issuer_of(compact: &str) -> Option<&'static str> {
    ISSUER_RANGES
        .iter()
        .find_map(|(issuer, prefixes, lengths)| {
            let in_range = prefixes.iter().any(|(low, high)| {
                compact
                    .get(0..low.len())
                    .is_some_and(|head| head >= *low && head <= *high)
            });
            (in_range && lengths.contains(&compact.len())).then_some(*issuer)
        })
}

// ---------------------------------------------------------------------------------------------
// ABA routing number
// ---------------------------------------------------------------------------------------------

pub struct AbaRoutingRule;

/// Nine digits, compact. The hyphenated spelling some forms print is deliberately not matched:
/// nine digits behind a one-in-ten checksum do not buy separator tolerance, which is the same
/// arithmetic the IBAN rule passes and this one does not.
const ABA_ROUTING_PATTERN: &str = r"[0-9]{9}";

/// The words that admit a bare nine-digit run, from the American Bankers Association's own names
/// for the number and from Presidio's recogniser context list.
const ABA_ROUTING_CUES: &[&str] = &[
    "routing",
    "aba",
    "abarouting",
    "bankrouting",
    "rtn",
    "transit",
];

/// The leading two digits a routing number may carry, as inclusive ranges.
///
/// The first two digits are the Federal Reserve routing symbol, and only four blocks of them were
/// ever allocated: 00–12 for the twelve districts and the government, 21–32 for the thrift
/// institutions that mirror them, 61–72 for electronic-only transactions, and 80 for traveller's
/// cheques. Everything else is not a routing number whatever its checksum says, which is a second
/// filter over the same nine digits and independent of the first.
const ROUTING_SYMBOL_RANGES: [(u32, u32); 4] = [(0, 12), (21, 32), (61, 72), (80, 80)];

impl Rule for AbaRoutingRule {
    fn id(&self) -> &'static str {
        "bank.aba_routing"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::BankAccount
    }

    fn candidate_pattern(&self) -> &'static str {
        ABA_ROUTING_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // The length is exactly nine, so both neighbours guard: nine digits cut out of a longer
        // run are not a routing number.
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
        let district: u32 = text.get(0..2)?.parse().ok()?;
        if !ROUTING_SYMBOL_RANGES
            .iter()
            .any(|(low, high)| district >= *low && district <= *high)
        {
            return None;
        }

        let digits: Vec<u32> = text.chars().filter_map(|c| c.to_digit(10)).collect();
        if weighted_mod(&digits, &[3, 7, 1], 10) != 0 {
            return None;
        }

        if !candidate.has_cue(ABA_ROUTING_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("routing_symbol".to_string(), text[0..4].to_string());
        parts.insert("institution".to_string(), text[4..8].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "aba_routing".to_string(),
                compact: text.to_string(),
                country: Some("US".to_string()),
                parts,
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The structure strings from the registry entries for Romania, Germany and the United Kingdom,
    /// which between them exercise all three character classes.
    #[test]
    fn structures_are_checked_positionally() {
        assert!(matches_structure("AAAA1B31007593840000", "4!a16!c"));
        assert!(!matches_structure("1AAA1B31007593840000", "4!a16!c"));
        assert!(matches_structure("370400440532013000", "8!n10!n"));
        assert!(!matches_structure("37040044053201300A", "8!n10!n"));
        assert!(matches_structure("WEST12345698765432", "4!a6!n8!n"));
        // Too short and too long both fail, which is what makes the length check positional rather
        // than a prefix test.
        assert!(!matches_structure("WEST1234569876543", "4!a6!n8!n"));
        assert!(!matches_structure("WEST123456987654321", "4!a6!n8!n"));
    }
}
