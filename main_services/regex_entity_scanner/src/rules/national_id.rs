//! National identity numbers, detection only.
//!
//! Two constraints shape this module and neither is negotiable.
//!
//! The first is scope: a bare digit run with one check digit is still a bare digit run, and a
//! facet built out of those is a facet of invoice numbers. A scheme ships here on one of two
//! grounds. Either the **surface form identifies itself** — a fixed letter-and-digit pattern, a
//! restricted check alphabet, a holder-type position — which is the codice fiscale, the NIF/NIE,
//! the CURP and the PAN. Or the number carries **two independent checks and a mandatory cue**: the
//! PESEL and the personnummer are nothing but digits, and what admits them is a check digit *and*
//! an embedded date that has to be a real day *and* the word beside them. If the cue requirement
//! is ever dropped from those two, the rules go with it.
//!
//! The second is what "detection" means. The codice fiscale, the CURP, the PESEL and the
//! personnummer all encode their holder's date of birth, and two of them encode sex. **No value
//! here carries either.** The date-bearing validators read those positions for exactly one
//! purpose, to reject a number whose date could never have existed, and the catalogue entry says
//! so — the identifier encodes personal data that this service does not derive, and that is a
//! decision to state rather than to leave implicit in what the code happens not to do.

use std::collections::BTreeMap;

use crate::model::{EntityType, Flag, Value};
use crate::rules::checksum::{luhn, weighted_mod};
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{is_real_date, Candidate, Rule, Verdict};

/// Whether the neighbouring bytes make this a token in its own right. Every format here is fixed
/// length, so both sides are guards.
fn is_standalone(candidate: &Candidate<'_>) -> bool {
    !candidate
        .byte_before()
        .is_some_and(|b| b.is_ascii_alphanumeric())
        && !candidate
            .byte_after()
            .is_some_and(|b| b.is_ascii_alphanumeric())
}

fn national_id(
    candidate: &Candidate<'_>,
    scheme: &str,
    country: &str,
    confidence: f32,
    flags: Vec<Flag>,
) -> Verdict {
    let mut parts = BTreeMap::new();
    parts.insert("scheme".to_string(), scheme.to_string());

    Verdict {
        start: candidate.start,
        end: candidate.end,
        value: Value::Identifier {
            scheme: scheme.to_string(),
            compact: candidate.text().to_string(),
            country: Some(country.to_string()),
            parts,
        },
        confidence,
        flags,
    }
}

// ---------------------------------------------------------------------------------------------
// Italy — codice fiscale
// ---------------------------------------------------------------------------------------------

pub struct CodiceFiscaleRule;

/// Six name letters, then the positions that hold the birth date, then the place code and the
/// check character. The digit positions accept the letters the *omocodia* substitution puts there
/// when two people would otherwise collide, which is why they are not plain digit classes.
const CODICE_FISCALE_PATTERN: &str =
    r"[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z]";

impl Rule for CodiceFiscaleRule {
    fn id(&self) -> &'static str {
        "natid.it_codice_fiscale"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::NationalId
    }

    fn candidate_pattern(&self) -> &'static str {
        CODICE_FISCALE_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        if cin_check_character(text.get(0..15)?)? != text.as_bytes()[15] {
            return None;
        }

        Some(national_id(
            candidate,
            "it_codice_fiscale",
            "IT",
            0.99,
            Vec::new(),
        ))
    }
}

/// The CIN check character: characters in odd positions are weighted through one table and those
/// in even positions through another, and the sum modulo twenty-six selects a letter.
fn cin_check_character(body: &str) -> Option<u8> {
    /// The odd-position value of each character, indexed by its position in `0-9A-Z`.
    const ODD: [u32; 26] = [
        1, 0, 5, 7, 9, 13, 15, 17, 19, 21, 2, 4, 18, 20, 11, 3, 6, 8, 12, 14, 16, 10, 22, 25, 24,
        23,
    ];

    let mut sum = 0u32;
    for (index, character) in body.chars().enumerate() {
        let ordinal = match character {
            '0'..='9' => character as u32 - '0' as u32,
            'A'..='Z' => character as u32 - 'A' as u32,
            _ => return None,
        };
        sum += if index % 2 == 0 {
            ODD[ordinal as usize]
        } else {
            ordinal
        };
    }
    Some(b'A' + (sum % 26) as u8)
}

// ---------------------------------------------------------------------------------------------
// Spain — NIF and NIE
// ---------------------------------------------------------------------------------------------

pub struct NifNieRule;

/// Eight digits and a check letter for a resident, or one of `XYZ` — a foreign national — or
/// `KLM` — the residual categories — followed by seven digits and the same check letter. The check
/// alphabet is in the pattern because it excludes the letters that would otherwise be confused
/// with digits, and that exclusion is most of what makes the shape recognisable.
const NIF_NIE_PATTERN: &str =
    r"\d{8}[TRWAGMYFPDXBNJZSQVHLCKE]|[XYZKLM]\d{7}[TRWAGMYFPDXBNJZSQVHLCKE]";

/// The check letters, in the order the modulus selects them.
const NIF_CHECK_LETTERS: &[u8] = b"TRWAGMYFPDXBNJZSQVHLCKE";

impl Rule for NifNieRule {
    fn id(&self) -> &'static str {
        "natid.es_nif_nie"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::NationalId
    }

    fn candidate_pattern(&self) -> &'static str {
        NIF_NIE_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        let body = text.get(0..text.len() - 1)?;
        let number: u32 = match body.as_bytes()[0] {
            b'X' => format!("0{}", &body[1..]).parse().ok()?,
            b'Y' => format!("1{}", &body[1..]).parse().ok()?,
            b'Z' => format!("2{}", &body[1..]).parse().ok()?,
            // K, L and M carry the older algorithm, run over the digits alone.
            b'K' | b'L' | b'M' => body[1..].parse().ok()?,
            _ => body.parse().ok()?,
        };
        if NIF_CHECK_LETTERS[(number % 23) as usize] != text.as_bytes()[text.len() - 1] {
            return None;
        }

        Some(national_id(candidate, "es_nif_nie", "ES", 0.99, Vec::new()))
    }
}

// ---------------------------------------------------------------------------------------------
// Mexico — CURP
// ---------------------------------------------------------------------------------------------

pub struct CurpRule;

/// Four name letters, six positions of birth date, six more letters, and two check positions.
const CURP_PATTERN: &str = r"[A-Z]{4}\d{6}[A-Z]{6}[0-9A-Z]\d";

/// The state codes the registry uses, including `NE` for a birth abroad. A code outside this set
/// is not a CURP, and this is a check about geography rather than about a person.
const CURP_STATES: [&str; 33] = [
    "AS", "BC", "BS", "CC", "CH", "CL", "CM", "CS", "DF", "DG", "GR", "GT", "HG", "JC", "MC", "MN",
    "MS", "NE", "NL", "NT", "OC", "PL", "QR", "QT", "SL", "SP", "SR", "TC", "TL", "TS", "VZ", "YN",
    "ZS",
];

/// The CURP alphabet, in value order. `&` is in it because the registry allows it inside the name
/// positions of a legacy record.
const CURP_ALPHABET: &str = "0123456789ABCDEFGHIJKLMN&OPQRSTUVWXYZ";

impl Rule for CurpRule {
    fn id(&self) -> &'static str {
        "natid.mx_curp"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::NationalId
    }

    fn candidate_pattern(&self) -> &'static str {
        CURP_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }

        let text = candidate.text();
        if !CURP_STATES.contains(&text.get(11..13)?) {
            return None;
        }
        if curp_check_digit(text.get(0..17)?)? != text.as_bytes()[17] - b'0' {
            return None;
        }

        Some(national_id(candidate, "mx_curp", "MX", 0.99, Vec::new()))
    }
}

/// The CURP check digit: each character's value in the registry's alphabet, weighted by its
/// distance from the end, summed and complemented modulo ten.
fn curp_check_digit(body: &str) -> Option<u8> {
    let mut sum = 0u32;
    for (index, character) in body.chars().enumerate() {
        let value = CURP_ALPHABET.find(character)? as u32;
        sum += value * (18 - index as u32);
    }
    Some(((10 - sum % 10) % 10) as u8)
}

// ---------------------------------------------------------------------------------------------
// India — PAN
// ---------------------------------------------------------------------------------------------

pub struct PanRule;

/// Five letters, four digits and a final letter. The fourth letter says what kind of holder it is,
/// which is the only structural constraint the format offers.
const PAN_PATTERN: &str = r"[A-Z]{5}\d{4}[A-Z]";

/// The holder-type letters the income tax department assigns. Everything else in the fourth
/// position is not a PAN.
const PAN_HOLDER_TYPES: &[u8] = b"ABCFGHJKLPT";

/// The words that admit a PAN. The check character's algorithm is not published, so structure plus
/// context is the whole precision story and the confidence says so.
const PAN_CUES: &[&str] = &["PAN", "income tax", "Aadhaar", "ITR", "assessee"];

impl Rule for PanRule {
    fn id(&self) -> &'static str {
        "natid.in_pan"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::NationalId
    }

    fn candidate_pattern(&self) -> &'static str {
        PAN_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }
        if !candidate.has_cue(PAN_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        if !PAN_HOLDER_TYPES.contains(&text.as_bytes()[3]) {
            return None;
        }
        // The serial runs from 0001, so an all-zero block is a placeholder rather than a number.
        if text.get(5..9)? == "0000" {
            return None;
        }

        Some(national_id(
            candidate,
            "in_pan",
            "IN",
            0.90,
            vec![Flag::NoChecksum],
        ))
    }
}

// ---------------------------------------------------------------------------------------------
// Poland — PESEL
// ---------------------------------------------------------------------------------------------

pub struct PeselRule;

/// Eleven digits and nothing else, which is why this rule is admitted only behind a cue: the
/// surface form identifies nothing on its own.
const PESEL_PATTERN: &str = r"\d{11}";

/// The one word that admits an eleven-digit run, which is also the whole of Presidio's own
/// context list for the scheme.
const PESEL_CUES: &[&str] = &["PESEL"];

/// The check-digit weights, cycling over the first ten digits.
const PESEL_WEIGHTS: [u32; 4] = [1, 3, 7, 9];

impl Rule for PeselRule {
    fn id(&self) -> &'static str {
        "natid.pl_pesel"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::NationalId
    }

    fn candidate_pattern(&self) -> &'static str {
        PESEL_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }
        if !candidate.has_cue(PESEL_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        let digits: Vec<u32> = text.chars().filter_map(|c| c.to_digit(10)).collect();
        let check = (10 - weighted_mod(digits.get(..10)?, &PESEL_WEIGHTS, 10)) % 10;
        if check != *digits.get(10)? {
            return None;
        }
        if !pesel_date_exists(&digits) {
            return None;
        }

        Some(national_id(candidate, "pl_pesel", "PL", 0.97, Vec::new()))
    }
}

/// Whether the six leading digits name a day that exists.
///
/// The century is folded into the month field — twenty is added to it once per century from the
/// nineteenth on — so a month of 38 is February 2002 rather than a malformed month. The date is
/// read here and only here: it decides whether the number can exist, and neither the value nor the
/// card carries a birth date out of it.
fn pesel_date_exists(digits: &[u32]) -> bool {
    let month_field = digits[2] * 10 + digits[3];
    let Some(century) = [1900, 2000, 2100, 2200, 1800].get((month_field / 20) as usize) else {
        return false;
    };
    let year = century + (digits[0] * 10 + digits[1]) as i32;
    let month = (month_field % 20) as i32;
    let day = (digits[4] * 10 + digits[5]) as i32;
    is_real_date(year, month, day)
}

// ---------------------------------------------------------------------------------------------
// Sweden — personnummer
// ---------------------------------------------------------------------------------------------

pub struct PersonnummerRule;

/// The twelve-digit form first, so that a full number is preferred over its own last ten digits,
/// then the ten-digit one. Both admit the separator standing in front of the last four digits.
const PERSONNUMMER_PATTERN: &str = r"\d{8}[-+]?\d{4}|\d{6}[-+]?\d{4}";

/// The words that admit a bare digit run of this shape.
const PERSONNUMMER_CUES: &[&str] = &[
    "personnummer",
    "samordningsnummer",
    "personal identity",
    "person number",
    "pnr",
];

impl Rule for PersonnummerRule {
    fn id(&self) -> &'static str {
        "natid.se_personnummer"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::NationalId
    }

    fn candidate_pattern(&self) -> &'static str {
        PERSONNUMMER_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if !is_standalone(candidate) {
            return None;
        }
        if !candidate.has_cue(PERSONNUMMER_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        let digits: Vec<u32> = text.chars().filter_map(|c| c.to_digit(10)).collect();
        if !personnummer_date_exists(&digits) {
            return None;
        }

        // Luhn runs over the last ten digits, which is the number without its century: the two
        // spellings of one person have to agree, and only the ten-digit form is inside the
        // arithmetic.
        let all_digits: String = text.chars().filter(char::is_ascii_digit).collect();
        if !luhn(all_digits.get(all_digits.len() - 10..)?) {
            return None;
        }

        // The canonical form keeps the separator instead of stripping it, which is the one place
        // this rule departs from compact-form normalisation and it is not a preference: the sign
        // is the century. Two people born a hundred years apart write the same ten digits and
        // differ only in the `+`, so a value that dropped it would merge them under one index key.
        let separator = if text.contains('+') { '+' } else { '-' };
        let split = all_digits.len() - 4;

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "se_personnummer".to_string(),
                compact: format!(
                    "{}{separator}{}",
                    &all_digits[..split],
                    &all_digits[split..]
                ),
                country: Some("SE".to_string()),
                parts: BTreeMap::from([("scheme".to_string(), "se_personnummer".to_string())]),
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

/// Whether the leading digits name a day that could exist.
///
/// The twelve-digit form carries its century and gets a full calendar check. The ten-digit form
/// does not, and the separator that would say which century — a `+` once the holder turns 100 —
/// only resolves against the date the document was written, which this service does not hold. So
/// the ten-digit form is checked for a real month and a day in range and no further: inventing a
/// century in order to run a leap-day test would make the same number valid or invalid depending
/// on when the scan ran.
///
/// A day sixty past the month is a samordningsnummer, the number issued to somebody who has no
/// personnummer, and it is the same identifier space.
fn personnummer_date_exists(digits: &[u32]) -> bool {
    let coordination = |day: u32| if day >= 61 { day - 60 } else { day };
    match digits.len() {
        12 => {
            let year = (digits[0] * 1000 + digits[1] * 100 + digits[2] * 10 + digits[3]) as i32;
            let month = (digits[4] * 10 + digits[5]) as i32;
            let day = coordination(digits[6] * 10 + digits[7]) as i32;
            is_real_date(year, month, day)
        }
        10 => {
            let month = digits[2] * 10 + digits[3];
            let day = coordination(digits[4] * 10 + digits[5]);
            (1..=12).contains(&month) && (1..=31).contains(&day)
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The documented example from `stdnum/it/codicefiscale.py`.
    #[test]
    fn the_cin_check_character_matches_the_reference() {
        assert_eq!(cin_check_character("RCCMNL83S18D969"), Some(b'H'));
        assert_eq!(cin_check_character("RCCMNL83S18D96-"), None);
    }

    /// The documented example from `stdnum/mx/curp.py`.
    #[test]
    fn the_curp_check_digit_matches_the_reference() {
        assert_eq!(curp_check_digit("BOXW310820HNERXN0"), Some(9));
        assert_eq!(curp_check_digit("BOXW310820HNERXN-"), None);
    }
}
