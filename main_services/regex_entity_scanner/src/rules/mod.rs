//! Rule definitions: one candidate pattern plus one validator each.
//!
//! A rule owns both halves of the two-stage design. [`Rule::candidate_pattern`] is deliberately
//! loose and must be expressible in a linear-time engine (no lookaround, no backreferences)
//! because it runs over raw, attacker-influenceable document text. [`Rule::validate`] then sees
//! one candidate at a time and may be as expensive as it likes: it re-imposes the guards that were
//! stripped out of the pattern, applies the checks that decide truth, and produces the canonical
//! value.
//!
//! Adding a type is therefore a pattern, a validator and a fixture, not a new pipeline.

pub mod bank;
pub mod checksum;
pub mod company;
pub mod context;
pub mod coordinates;
pub mod crypto;
pub mod date_iso;
pub mod date_machine;
pub mod device;
pub mod email;
pub mod extras;
pub mod maritime;
pub mod money;
pub mod national_id;
pub mod network;
pub mod phone;
pub mod security;

use crate::data::VendoredData;
use crate::model::{EntityType, Flag, Value};

/// Bumped whenever a pattern, a validator, or the rule inventory changes. Extraction is not
/// idempotent across rule sets (the same document yields different entities under different ones)
/// so this is what makes the scope of a reindex computable rather than guessed. It ships on every
/// scan response and on `/health` and `/rules`.
///
/// What bumps it: any change to a candidate pattern, any change to a validator's accept or reject
/// boundary or to the value it normalises to, and any rule added or removed. What does not: card
/// text, a doc comment, a catalogue entry, because none of those change what a document yields.
pub const RULE_SET_VERSION: u32 = 17;

/// Whether the three fields name a day that exists. Several schemes here admit a number whose
/// opening digits are a date of birth; an impossible date is what rules those out, and it is the
/// second independent filter on formats whose only other check is one digit of arithmetic.
///
/// Reading the date is all the validators do with it: no value carries a birth date and no rule
/// derives one, which is the difference between detecting an identifier and decoding a person.
pub fn is_real_date(year: i32, month: i32, day: i32) -> bool {
    let (Ok(year), Ok(month), Ok(day)) =
        (i16::try_from(year), i8::try_from(month), i8::try_from(day))
    else {
        return false;
    };
    jiff::civil::Date::new(year, month, day).is_ok()
}

/// A span the prefilter proposed, with the surrounding fragment available for the guard checks.
pub struct Candidate<'a> {
    /// The whole fragment, so a validator can look at what precedes and follows the span.
    pub fragment: &'a str,
    /// Byte offsets of the candidate within `fragment`.
    pub start: usize,
    pub end: usize,
    pub data: &'a VendoredData,
}

impl<'a> Candidate<'a> {
    pub fn text(&self) -> &'a str {
        &self.fragment[self.start..self.end]
    }

    /// The byte immediately before the candidate, if any. This is how a stripped `(?<!\d)` guard
    /// is re-imposed: the assertion is a statement about one neighbouring byte, and checking it
    /// here keeps the scanning pass linear.
    pub fn byte_before(&self) -> Option<u8> {
        self.fragment
            .as_bytes()
            .get(self.start.checked_sub(1)?)
            .copied()
    }

    /// The byte immediately after the candidate, if any.
    pub fn byte_after(&self) -> Option<u8> {
        self.fragment.as_bytes().get(self.end).copied()
    }
}

/// What a validator returns when it accepts a candidate.
pub struct Verdict {
    /// Offsets within the fragment. A validator may narrow the span it was given, trailing
    /// punctuation that the pattern swallowed is trimmed here, not in the pattern.
    pub start: usize,
    pub end: usize,
    pub value: Value,
    pub confidence: f32,
    pub flags: Vec<Flag>,
}

pub trait Rule: Send + Sync {
    /// Stable identifier, dotted from general to specific: `date.iso8601`, `email.basic`. It ends
    /// up in the output and in the index, so renaming one is a data migration.
    fn id(&self) -> &'static str;

    fn entity_type(&self) -> EntityType;

    /// The guard-free candidate pattern for the prefilter.
    fn candidate_pattern(&self) -> &'static str;

    /// Decides whether the candidate is real and what it means. `None` rejects it.
    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict>;

    /// Whether rejecting a candidate of this rule should resume the search past it, instead of
    /// only looking inside it.
    ///
    /// The scan loop's recovery re-runs the pattern over a rejected candidate's **interior**,
    /// which by construction cannot find a match ending past the candidate's right edge. That edge
    /// matters only for a pattern whose marker may *trail* its number. The engine is
    /// leftmost-first, so in `1 $10 dollars` the trailing-sign alternative matches `1 $` at offset
    /// 0 before the leading-sign alternative can match `$10` at offset 2; the interior of `1 $`
    /// holds nothing, and `$10` is never proposed at all.
    ///
    /// The two money rules are the only patterns in the set with a trailing-marker alternation, so
    /// they are the only ones that buy the extra linear pass. It is off by default because the
    /// pass is real work and a rule that cannot need it should not pay for it.
    fn resumes_past_rejection(&self) -> bool {
        false
    }
}

/// Every rule the scanner knows about.
pub fn all() -> Vec<Box<dyn Rule>> {
    vec![
        Box::new(email::EmailRule),
        Box::new(date_iso::Iso8601Rule),
        Box::new(date_machine::Rfc2822Rule),
        Box::new(date_machine::ClfRule),
        Box::new(date_machine::IsoWeekRule),
        Box::new(bank::IbanRule),
        Box::new(bank::BicRule),
        Box::new(bank::PaymentCardRule),
        Box::new(bank::AbaRoutingRule),
        Box::new(company::LeiRule),
        Box::new(company::VatEuRule),
        Box::new(company::VatNonEuRule),
        Box::new(company::OrganisationsnummerRule),
        Box::new(security::IsinRule),
        Box::new(security::CusipRule),
        Box::new(security::SedolRule),
        Box::new(maritime::ImoRule),
        Box::new(maritime::MmsiRule),
        Box::new(maritime::ContainerRule),
        Box::new(device::ImeiRule),
        Box::new(device::MacRule),
        Box::new(network::IpRule),
        Box::new(network::AsnRule),
        Box::new(extras::CveRule),
        Box::new(extras::DoiRule),
        Box::new(extras::OrcidRule),
        Box::new(extras::MessageIdRule),
        Box::new(coordinates::DecimalRule),
        Box::new(coordinates::DmsRule),
        Box::new(coordinates::PlusCodeRule),
        Box::new(crypto::EthereumRule),
        Box::new(crypto::BitcoinRule),
        Box::new(national_id::CodiceFiscaleRule),
        Box::new(national_id::NifNieRule),
        Box::new(national_id::CurpRule),
        Box::new(national_id::PanRule),
        Box::new(national_id::PeselRule),
        Box::new(national_id::PersonnummerRule),
        Box::new(phone::InternationalRule),
        Box::new(money::IsoCodeRule),
        Box::new(money::SymbolRule),
    ]
}
