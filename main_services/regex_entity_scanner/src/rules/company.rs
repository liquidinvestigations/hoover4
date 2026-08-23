//! Identifiers that name a legal entity rather than an account or an instrument.

use std::collections::BTreeMap;

use crate::model::{EntityType, Flag, Value};
use crate::rules::checksum::{iso7064, luhn, weighted_mod};
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{is_real_date, Candidate, Rule, Verdict};

pub struct LeiRule;

/// Twenty characters: four of issuing LOU, two usually zero, thirteen identifying the organisation
/// and two check digits. Fixed length, fixed alphabet, and the last two positions are digits, a
/// shape common enough to need the checksum, and rare enough that the checksum settles it.
const LEI_PATTERN: &str = r"[A-Z0-9]{18}\d{2}";

impl Rule for LeiRule {
    fn id(&self) -> &'static str {
        "company.lei"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::CompanyId
    }

    fn candidate_pattern(&self) -> &'static str {
        LEI_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // The length is exactly twenty, so both neighbours are guards: twenty characters cut out
        // of a hash or a base32 blob are not an LEI.
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
        // ISO 7064 mod-97-10 over the whole code, letters counting as their base-36 value.
        if !iso7064::mod_97_10(text) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("lou".to_string(), text[0..4].to_string());
        parts.insert("entity".to_string(), text[6..18].to_string());
        parts.insert("check_digits".to_string(), text[18..20].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "lei".to_string(),
                compact: text.to_string(),
                country: None,
                parts,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

// ---------------------------------------------------------------------------------------------
// European Union VAT identification numbers
// ---------------------------------------------------------------------------------------------

pub struct VatEuRule;

/// One alternation per member state, because a generic "two letters and a digit run" pattern
/// proposes a candidate for every capitalised abbreviation in a document. The prefix is the
/// literal marker that makes the format self-identifying, and the body's length and alphabet are
/// the state's own, four to thirteen characters, digits except where the state allows letters
/// (Austria's `U`, Cyprus's check letter, Spain's entity letter, France's two-character key,
/// Ireland's check letters and the Netherlands' `B`).
///
/// Longer alternatives for a prefix come first: the engine takes the first alternative that
/// matches at a position, so `RO` with thirteen digits has to be offered before `RO` with ten.
const VAT_EU_PATTERN: &str = concat!(
    r"ATU\d{8}",
    r"|BE\d{9,10}",
    r"|BG\d{9,10}",
    r"|CY\d{8}[A-Z]",
    r"|CZ\d{8,10}",
    r"|DE\d{9}",
    r"|DK\d{8}",
    r"|EE\d{9}",
    r"|EL\d{8,9}",
    r"|ES[0-9A-Z]\d{7}[0-9A-Z]",
    r"|FI\d{8}",
    r"|FR[0-9A-Z]{2}\d{9}",
    r"|HR\d{11}",
    r"|HU\d{8}",
    r"|IE\d[0-9A-Z+*]\d{5}[A-Z]{1,2}",
    r"|IT\d{11}",
    r"|LT\d{12}|LT\d{9}",
    r"|LU\d{8}",
    r"|LV\d{11}",
    r"|MT\d{8}",
    r"|NL\d{9}B\d{2}",
    r"|PL\d{10}",
    r"|PT\d{9}",
    r"|RO\d{13}|RO\d{4,10}",
    r"|SE\d{12}",
    r"|SI\d{8}",
    r"|SK\d{10}",
);

impl Rule for VatEuRule {
    fn id(&self) -> &'static str {
        "company.vat_eu"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::CompanyId
    }

    fn candidate_pattern(&self) -> &'static str {
        VAT_EU_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // Both neighbours are guards. Several bodies are variable length, so without the
        // right-hand one a longer digit run donates a prefix of itself to the facet.
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
        let prefix = text.get(0..2)?;
        let body = text.get(2..)?;

        // Two states write shorter historical forms that their registers zero-fill.
        let national = match prefix {
            "BE" => zero_fill(body, 10),
            "EL" => zero_fill(body, 9),
            _ => body.to_string(),
        };

        if !member_state_check(prefix, &national) {
            return None;
        }

        // Greece writes EL where ISO 3166-1 writes GR, and the value carries the country rather
        // than the tax prefix so that it joins with every other country-bearing identifier.
        let country = if prefix == "EL" { "GR" } else { prefix };

        let mut parts = BTreeMap::new();
        parts.insert("prefix".to_string(), prefix.to_string());
        parts.insert("number".to_string(), national.clone());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "vat".to_string(),
                compact: format!("{prefix}{national}"),
                country: Some(country.to_string()),
                parts,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

/// The member-state table: a prefix selects the arithmetic its own tax administration publishes.
/// Every branch is a port of the corresponding `python-stdnum` module, following the delegation
/// where a state's VAT module is an alias for its company-register or personal-number module.
fn member_state_check(prefix: &str, national: &str) -> bool {
    match prefix {
        "AT" => at_uid(national),
        "BE" => be_ondernemingsnummer(national),
        "BG" => bg_ddn(national),
        "CY" => cy_tic(national),
        "CZ" => cz_dic(national),
        "DE" => de_ustid(national),
        "DK" => dk_cvr(national),
        "EE" => ee_kmkr(national),
        "EL" => el_afm(national),
        "ES" => es_nif(national),
        "FI" => fi_alv(national),
        "FR" => fr_tva(national),
        "HR" => hr_oib(national),
        "HU" => hu_anum(national),
        "IE" => ie_vat(national),
        "IT" => it_iva(national),
        "LT" => lt_pvm(national),
        "LU" => lu_tva(national),
        "LV" => lv_pvn(national),
        "MT" => mt_vat(national),
        "NL" => nl_btw(national),
        "PL" => pl_nip(national),
        "PT" => pt_nif(national),
        "RO" => ro_cf(national),
        "SE" => se_momsnr(national),
        "SI" => si_ddv(national),
        "SK" => sk_dph(national),
        _ => false,
    }
}

/// Left-pad with zeros to `width`, leaving anything already that long alone.
fn zero_fill(body: &str, width: usize) -> String {
    if body.len() >= width {
        return body.to_string();
    }
    let mut filled = "0".repeat(width - body.len());
    filled.push_str(body);
    filled
}

/// The decimal digits of `text`, or `None` if any character is not one.
fn digits(text: &str) -> Option<Vec<u32>> {
    text.chars().map(|c| c.to_digit(10)).collect()
}

/// A positional weighted sum, without the modulus `weighted_mod` applies as it goes. Several of
/// these schemes need the raw sum before reducing it.
fn weighted_sum(values: &[u32], weights: &[u32]) -> u32 {
    values
        .iter()
        .zip(weights)
        .map(|(value, weight)| value * weight)
        .sum()
}

/// The digits read as one integer. Every caller here bounds the length well inside `u64`.
fn as_integer(values: &[u32]) -> u64 {
    values.iter().fold(0u64, |acc, d| acc * 10 + u64::from(*d))
}

/// The Luhn sum itself rather than a verdict: Austria and Spain both derive a check digit from it
/// instead of comparing it to zero.
fn luhn_sum(values: &[u32]) -> u32 {
    values
        .iter()
        .rev()
        .enumerate()
        .map(|(index, digit)| {
            if index % 2 == 1 {
                let doubled = digit * 2;
                doubled / 10 + doubled % 10
            } else {
                *digit
            }
        })
        .sum::<u32>()
        % 10
}

/// The digit that makes `values` pass Luhn.
fn luhn_check_digit(values: &[u32]) -> u32 {
    let mut extended = values.to_vec();
    extended.push(0);
    (10 - luhn_sum(&extended)) % 10
}

/// Austria, UID. `U` and eight digits, the last a Luhn-derived check digit.
fn at_uid(national: &str) -> bool {
    let Some(rest) = national.strip_prefix('U') else {
        return false;
    };
    let Some(d) = digits(rest) else {
        return false;
    };
    if d.len() != 8 {
        return false;
    }
    (16 - luhn_sum(&d[..7])) % 10 == d[7]
}

/// Belgium, ondernemingsnummer. Ten digits opening with 0 or 1, where the last two are the
/// remainder of the first eight modulo 97.
fn be_ondernemingsnummer(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 10 || d[0] > 1 {
        return false;
    }
    (as_integer(&d[..8]) + as_integer(&d[8..])) % 97 == 0
}

/// Bulgaria, ДДС. Nine digits for a legal entity; ten for a person, which is then an EGN, a
/// foreigner's number or the residual scheme.
fn bg_ddn(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    match d.len() {
        9 => {
            let mut check = weighted_sum(&d[..8], &[1, 2, 3, 4, 5, 6, 7, 8]) % 11;
            if check == 10 {
                check = weighted_sum(&d[..8], &[3, 4, 5, 6, 7, 8, 9, 10]) % 11;
            }
            check % 10 == d[8]
        }
        10 => bg_egn(&d) || bg_pnf(&d) || bg_other(&d),
        _ => false,
    }
}

/// Bulgaria, EGN, the personal number, which opens with a date of birth whose month field is
/// offset by twenty or forty to name the century.
fn bg_egn(d: &[u32]) -> bool {
    let mut year = 1900 + (d[0] * 10 + d[1]) as i32;
    let mut month = (d[2] * 10 + d[3]) as i32;
    if month > 40 {
        year += 100;
        month -= 40;
    } else if month > 20 {
        year -= 100;
        month -= 20;
    }
    if !is_real_date(year, month, (d[4] * 10 + d[5]) as i32) {
        return false;
    }
    weighted_sum(&d[..9], &[2, 4, 8, 5, 10, 9, 7, 3, 6]) % 11 % 10 == d[9]
}

/// Bulgaria, PNF, the number issued to a foreign resident.
fn bg_pnf(d: &[u32]) -> bool {
    weighted_sum(&d[..9], &[21, 19, 17, 13, 11, 9, 7, 3, 1]) % 10 == d[9]
}

/// Bulgaria, the residual ten-digit scheme.
fn bg_other(d: &[u32]) -> bool {
    let sum = weighted_sum(&d[..9], &[4, 3, 2, 7, 6, 5, 4, 3, 2]) % 11;
    (11 - sum) % 11 == d[9]
}

/// Cyprus, ΦΠΑ. Eight digits and a check letter, where the even positions are read through a
/// substitution table before the sum selects a letter modulo twenty-six.
fn cy_tic(national: &str) -> bool {
    /// The value of each digit when it sits in an even position.
    const EVEN_POSITION: [u32; 10] = [1, 0, 5, 7, 9, 13, 15, 17, 19, 21];

    if national.len() != 9 || national.starts_with("12") {
        return false;
    }
    let Some(d) = digits(&national[..8]) else {
        return false;
    };
    let sum: u32 = d
        .iter()
        .enumerate()
        .map(|(index, digit)| {
            if index % 2 == 0 {
                EVEN_POSITION[*digit as usize]
            } else {
                *digit
            }
        })
        .sum();
    b'A' + (sum % 26) as u8 == national.as_bytes()[8]
}

/// Czechia, DIČ. Eight digits for a legal entity, nine opening with 6 for a person without a
/// birth number, and otherwise the birth number itself.
fn cz_dic(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    match d.len() {
        8 => {
            if d[0] == 9 {
                return false;
            }
            let sum = weighted_sum(&d[..7], &[8, 7, 6, 5, 4, 3, 2]) % 11;
            let check = (11 - sum) % 11;
            (if check == 0 { 1 } else { check }) % 10 == d[7]
        }
        9 if d[0] == 6 => {
            let sum = weighted_sum(&d[1..8], &[8, 7, 6, 5, 4, 3, 2]) % 11;
            let check = (8 - (10 - sum as i32).rem_euclid(11)).rem_euclid(10);
            check as u32 == d[8]
        }
        9 | 10 => cz_rodne_cislo(&d),
        _ => false,
    }
}

/// Czechia and Slovakia, rodné číslo, the birth number, identical in both. Nine digits were
/// issued until 1954 and ten since; the month field carries fifty for a woman and twenty for a
/// serial that overflowed.
fn cz_rodne_cislo(d: &[u32]) -> bool {
    let mut year = 1900 + (d[0] * 10 + d[1]) as i32;
    let month = ((d[2] * 10 + d[3]) % 50 % 20) as i32;
    let day = (d[4] * 10 + d[5]) as i32;
    if d.len() == 9 {
        if year >= 1980 {
            year -= 100;
        }
        if year > 1953 {
            return false;
        }
    } else if year < 1954 {
        year += 100;
    }
    if !is_real_date(year, month, day) {
        return false;
    }
    d.len() == 9 || as_integer(&d[..9]) % 11 % 10 == u64::from(d[9])
}

/// Germany, USt-IdNr. Nine digits under ISO 7064 mod-11-10.
fn de_ustid(national: &str) -> bool {
    national.len() == 9
        && !national.starts_with('0')
        && digits(national).is_some()
        && iso7064::mod_11_10(national)
}

/// Denmark, CVR. Eight digits under a weighted sum modulo eleven.
fn dk_cvr(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    d.len() == 8 && d[0] != 0 && weighted_mod(&d, &[2, 7, 6, 5, 4, 3, 2, 1], 11) == 0
}

/// Estonia, KMKR. Nine digits under a repeating 3/7/1 weighting modulo ten.
fn ee_kmkr(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    d.len() == 9 && weighted_mod(&d, &[3, 7, 1], 10) == 0
}

/// Greece, ΑΦΜ. Nine digits whose checksum is a running doubling rather than fixed weights.
fn el_afm(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 9 {
        return false;
    }
    let sum = d[..8].iter().fold(0u32, |acc, digit| acc * 2 + digit);
    sum * 2 % 11 % 10 == d[8]
}

/// Spain, NIF. Nine characters that are a DNI, an NIE or a CIF depending on the first, so the
/// module delegates to whichever of the three the opening character selects.
fn es_nif(national: &str) -> bool {
    /// The DNI check alphabet, in the order the modulus selects it.
    const CHECK_LETTERS: &[u8] = b"TRWAGMYFPDXBNJZSQVHLCKE";
    /// The entity-type letters a CIF may open with.
    const ENTITY_TYPES: &[u8] = b"ABCDEFGHJNPQRSUVW";
    /// The letter form of a CIF check digit.
    const CIF_CHECK_LETTERS: &[u8] = b"JABCDEFGHI";

    if national.len() != 9 {
        return false;
    }
    let bytes = national.as_bytes();
    let Some(middle) = digits(&national[1..8]) else {
        return false;
    };
    let middle_value = as_integer(&middle) as u32;
    let check = bytes[8];

    match bytes[0] {
        // K, L and M carry the older algorithm, run over the digits alone.
        b'K' | b'L' | b'M' => CHECK_LETTERS[(middle_value % 23) as usize] == check,
        // A foreign natural person, whose leading letter stands for 0, 1 or 2.
        b'X' | b'Y' | b'Z' => {
            let value = u32::from(bytes[0] - b'X') * 10_000_000 + middle_value;
            CHECK_LETTERS[(value % 23) as usize] == check
        }
        first if first.is_ascii_digit() => {
            let value = u32::from(first - b'0') * 10_000_000 + middle_value;
            CHECK_LETTERS[(value % 23) as usize] == check
        }
        // A legal entity. The sources conflict over which entity types take the digit form of the
        // check and which take the letter form, so both are accepted.
        first if ENTITY_TYPES.contains(&first) => {
            let digit = luhn_check_digit(&middle);
            check == b'0' + digit as u8 || check == CIF_CHECK_LETTERS[digit as usize]
        }
        _ => false,
    }
}

/// Finland, ALV nro, the Y-tunnus without its hyphen. Eight digits modulo eleven.
fn fi_alv(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    d.len() == 8 && weighted_mod(&d, &[7, 9, 10, 5, 8, 4, 2, 1], 11) == 0
}

/// France, n° TVA. A two-character key and the nine-digit SIREN. The key is numeric in the old
/// style and has at least one letter in the new, and the two styles check differently.
fn fr_tva(national: &str) -> bool {
    /// The key alphabet, which omits I and O so that they cannot be read as 1 and 0.
    const KEY_ALPHABET: &[u8] = b"0123456789ABCDEFGHJKLMNPQRSTUVWXYZ";

    if national.len() != 11 {
        return false;
    }
    let bytes = national.as_bytes();
    let (Some(first), Some(second)) = (
        KEY_ALPHABET.iter().position(|c| *c == bytes[0]),
        KEY_ALPHABET.iter().position(|c| *c == bytes[1]),
    ) else {
        return false;
    };
    let Some(siren) = digits(&national[2..]) else {
        return false;
    };
    // Numbers issued in Monaco are valid here but are not SIREN numbers.
    if &national[2..5] != "000" && !luhn(&national[2..]) {
        return false;
    }
    let siren_value = as_integer(&siren);

    if bytes[0].is_ascii_digit() && bytes[1].is_ascii_digit() {
        let key = as_integer(&digits(&national[..2]).unwrap_or_default());
        return key == (siren_value * 100 + 12) % 97;
    }
    let key = if bytes[0].is_ascii_digit() {
        first as u64 * 24 + second as u64 - 10
    } else {
        first as u64 * 34 + second as u64 - 100
    };
    (siren_value + 1 + key / 11) % 11 == key % 11
}

/// Croatia, OIB. Eleven digits under ISO 7064 mod-11-10.
fn hr_oib(national: &str) -> bool {
    national.len() == 11 && digits(national).is_some() && iso7064::mod_11_10(national)
}

/// Hungary, közösségi adószám. Eight digits under a repeating 9/7/3/1 weighting modulo ten.
fn hu_anum(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    d.len() == 8 && weighted_mod(&d, &[9, 7, 3, 1], 10) == 0
}

/// Ireland, VAT. Seven digits and one or two check letters in the current form, or the older
/// form whose second character is a letter, `+` or `*` and which is checked after being rotated
/// into the current shape.
fn ie_vat(national: &str) -> bool {
    let bytes = national.as_bytes();
    if bytes.len() != 8 && bytes.len() != 9 {
        return false;
    }
    if !bytes[0].is_ascii_digit() || !bytes[2..7].iter().all(u8::is_ascii_digit) {
        return false;
    }
    if !bytes[7..].iter().all(|c| IE_ALPHABET.contains(c)) {
        return false;
    }

    if bytes[..7].iter().all(u8::is_ascii_digit) {
        let extra = if bytes.len() == 9 {
            Some(bytes[8])
        } else {
            None
        };
        ie_check_letter(&bytes[..7], extra) == bytes[7]
    } else if bytes[1].is_ascii_uppercase() || bytes[1] == b'+' || bytes[1] == b'*' {
        // The old form's leading digit belongs at the end, and the position it vacates is zero.
        let mut rotated = vec![b'0'];
        rotated.extend_from_slice(&bytes[2..7]);
        rotated.push(bytes[0]);
        ie_check_letter(&rotated, None) == bytes[7]
    } else {
        false
    }
}

/// Ireland's check alphabet, in the order the modulus selects it. It has no W in a value position
/// because W marks a married woman's number, which counts as zero.
const IE_ALPHABET: &[u8] = b"WABCDEFGHIJKLMNOPQRSTUV";

/// The Irish check letter over seven digits, with the optional second letter weighted by nine.
fn ie_check_letter(head: &[u8], extra: Option<u8>) -> u8 {
    let mut sum: u32 = head
        .iter()
        .enumerate()
        .map(|(index, byte)| (8 - index as u32) * u32::from(byte - b'0'))
        .sum();
    if let Some(extra) = extra {
        sum += 9 * IE_ALPHABET.iter().position(|c| *c == extra).unwrap_or(0) as u32;
    }
    IE_ALPHABET[(sum % 23) as usize]
}

/// Italy, partita IVA. Eleven digits under Luhn, with three of them naming a province.
fn it_iva(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 11 || d[..7].iter().all(|digit| *digit == 0) {
        return false;
    }
    let province = &national[7..10];
    let known =
        ("001"..="100").contains(&province) || matches!(province, "120" | "121" | "888" | "999");
    known && luhn(national)
}

/// Lithuania, PVM. Nine digits for a legal entity or twelve for a temporary registration, with a
/// fixed 1 in the position before the check digit.
fn lt_pvm(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    match d.len() {
        9 if d[7] == 1 => {}
        12 if d[10] == 1 => {}
        _ => return false,
    }
    let head = &d[..d.len() - 1];
    let weights: Vec<u32> = (0..head.len()).map(|index| 1 + index as u32 % 9).collect();
    let mut check = weighted_sum(head, &weights) % 11;
    if check == 10 {
        // The second pass shifts the weights by two rather than reducing the first sum again.
        let shifted: Vec<u32> = (0..head.len())
            .map(|index| 1 + (index as u32 + 2) % 9)
            .collect();
        check = weighted_sum(head, &shifted);
    }
    check % 11 % 10 == d[d.len() - 1]
}

/// Luxembourg, TVA. Eight digits whose last two are the first six modulo eighty-nine.
fn lu_tva(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 8 {
        return false;
    }
    let check = as_integer(&d[..6]) % 89;
    check == as_integer(&d[6..])
}

/// Latvia, PVN. Eleven digits: a legal entity when the first is above three, otherwise a personal
/// code, which since 2017 opens with 32 and before that with a date of birth.
fn lv_pvn(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 11 {
        return false;
    }
    if d[0] > 3 {
        return weighted_mod(&d, &[9, 1, 4, 8, 3, 10, 2, 5, 7, 6, 1], 11) == 3;
    }
    if !(d[0] == 3 && d[1] == 2) {
        let year = 1800 + (d[6] * 100) as i32 + (d[4] * 10 + d[5]) as i32;
        if !is_real_date(year, (d[2] * 10 + d[3]) as i32, (d[0] * 10 + d[1]) as i32) {
            return false;
        }
    }
    let sum = weighted_mod(&d[..10], &[10, 5, 8, 4, 2, 1, 6, 3, 7, 9], 11);
    (1 + sum) % 11 % 10 == d[10]
}

/// Malta, VAT. Eight digits under a weighted sum modulo thirty-seven.
fn mt_vat(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    d.len() == 8 && d[0] != 0 && weighted_mod(&d, &[3, 4, 6, 7, 8, 9, 10, 1], 37) == 0
}

/// The Netherlands, btw-nummer. Nine digits, a literal B, and a two-digit sequence. The older
/// form's leading digits are a BSN; the current one checks under ISO 7064 mod-97-10 over the whole
/// number with its NL prefix.
fn nl_btw(national: &str) -> bool {
    if national.len() != 12 || national.as_bytes()[9] != b'B' {
        return false;
    }
    let (Some(head), Some(tail)) = (digits(&national[..9]), digits(&national[10..])) else {
        return false;
    };
    if as_integer(&head) == 0 || as_integer(&tail) == 0 {
        return false;
    }
    nl_bsn(&head) || iso7064::mod_97_10(&format!("NL{national}"))
}

/// The Netherlands, BSN, the personal number the older btw-nummer is built on.
fn nl_bsn(d: &[u32]) -> bool {
    let sum = weighted_sum(&d[..8], &[9, 8, 7, 6, 5, 4, 3, 2]) as i64 - i64::from(d[8]);
    sum.rem_euclid(11) == 0
}

/// Poland, NIP. Ten digits under a weighted sum modulo eleven, the check digit weighted by minus
/// one, which is ten in the same modulus.
fn pl_nip(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    d.len() == 10 && weighted_mod(&d, &[6, 5, 7, 2, 3, 4, 5, 6, 7, 10], 11) == 0
}

/// Portugal, NIF. Nine digits under a descending weighting modulo eleven.
fn pt_nif(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 9 || d[0] == 0 {
        return false;
    }
    let sum = weighted_sum(&d[..8], &[9, 8, 7, 6, 5, 4, 3, 2]) % 11;
    (11 - sum) % 11 % 10 == d[8]
}

/// Romania, CF. Four to ten digits for a company (the CUI), or thirteen for a personal number.
///
/// The register itself allocates CUIs from two digits up, and this is the one member state whose
/// body can be that short. `RO` and two digits is a token ordinary text produces (a route, a
/// revision, a room), and one check digit over one information digit accepts nine of the ninety
/// possible values, so the floor here is four rather than the register's two. The catalogue entry
/// says so.
fn ro_cf(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() == 13 {
        return ro_cnp(&d);
    }
    if !(4..=10).contains(&d.len()) || d[0] == 0 {
        return false;
    }
    // The weights are right-aligned against nine positions, so a shorter number is padded.
    let head = &d[..d.len() - 1];
    let mut padded = [0u32; 9];
    padded[9 - head.len()..].copy_from_slice(head);
    let sum = weighted_sum(&padded, &[7, 5, 3, 2, 1, 7, 5, 3, 2]);
    10 * sum % 11 % 10 == d[d.len() - 1]
}

/// Romania, CNP, the personal number: a century marker, a date of birth, a county and a check
/// digit.
fn ro_cnp(d: &[u32]) -> bool {
    if d[0] == 0 {
        return false;
    }
    let century = match d[0] {
        1 | 2 => 1900,
        3 | 4 => 1800,
        5 | 6 => 2000,
        _ => 1900,
    };
    let year = century + (d[1] * 10 + d[2]) as i32;
    if !is_real_date(year, (d[3] * 10 + d[4]) as i32, (d[5] * 10 + d[6]) as i32) {
        return false;
    }
    // The county codes the register assigns, including the sectors of Bucharest and the codes
    // reserved for a birth outside the country.
    let county = d[7] * 10 + d[8];
    if !((1..=48).contains(&county) || matches!(county, 51 | 52 | 70 | 80..=83)) {
        return false;
    }
    let check = weighted_sum(&d[..12], &[2, 7, 9, 1, 4, 6, 3, 5, 8, 2, 7, 9]) % 11;
    (if check == 10 { 1 } else { check }) == d[12]
}

/// Sweden, momsregistreringsnummer. The ten-digit organisationsnummer under Luhn, followed by a
/// literal 01.
fn se_momsnr(national: &str) -> bool {
    national.len() == 12
        && digits(national).is_some()
        && &national[10..] == "01"
        && luhn(&national[..10])
}

/// Slovenia, ID za DDV. Eight digits under a descending weighting modulo eleven.
fn si_ddv(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 8 || d[0] == 0 {
        return false;
    }
    let check = 11 - weighted_sum(&d[..7], &[8, 7, 6, 5, 4, 3, 2]) % 11;
    match check {
        // Eleven would need two characters, so it names no valid number.
        11 => false,
        10 => d[7] == 0,
        _ => check == d[7],
    }
}

/// Slovakia, IČ DPH. Ten digits divisible by eleven, with a constrained third digit, or a birth
/// number, which the register also accepts.
fn sk_dph(national: &str) -> bool {
    let Some(d) = digits(national) else {
        return false;
    };
    if d.len() != 10 {
        return false;
    }
    if cz_rodne_cislo(&d) {
        return true;
    }
    d[0] != 0 && matches!(d[2], 2 | 3 | 4 | 7 | 8 | 9) && as_integer(&d) % 11 == 0
}

// ---------------------------------------------------------------------------------------------
// VAT identification numbers outside the European Union
// ---------------------------------------------------------------------------------------------

pub struct VatNonEuRule;

/// The VATIN form outside the Union: an ISO 3166-1 alpha-2 country code followed by that
/// country's own tax number. Only the countries whose check digit is implemented here are
/// offered, because a prefix without arithmetic behind it is a two-letter string in front of a
/// digit run. Exactly the bare-digit-run problem the prefix is supposed to solve.
///
/// Longer alternatives for a prefix come first: the engine takes the first alternative that
/// matches at a position, so the twelve-digit British and Russian bodies have to be offered
/// before the nine- and ten-digit ones, and the eleven-character government form before the
/// five-character one.
const VAT_NON_EU_PATTERN: &str = concat!(
    r"CHE\d{9}MWST|CHE\d{9}TVA|CHE\d{9}IVA|CHE\d{9}TPV",
    r"|GBGD8888\d{5}|GBHA8888\d{5}|GBGD\d{3}|GBHA\d{3}|GB\d{12}|GB\d{9}",
    r"|ME\d{8}",
    r"|MK\d{13}",
    r"|NO\d{9}MVA",
    r"|RS\d{9}",
    r"|RU\d{12}|RU\d{10}",
    r"|TR\d{10}",
);

impl Rule for VatNonEuRule {
    fn id(&self) -> &'static str {
        "company.vat_non_eu"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::CompanyId
    }

    fn candidate_pattern(&self) -> &'static str {
        VAT_NON_EU_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // Both neighbours are guards. Three of these bodies are variable length, so without the
        // right-hand one a longer digit run donates a prefix of itself to the facet.
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
        let prefix = text.get(0..2)?;
        let body = text.get(2..)?;

        let flags = non_eu_country_check(prefix, body)?;

        let mut parts = BTreeMap::new();
        parts.insert("prefix".to_string(), prefix.to_string());
        parts.insert("number".to_string(), body.to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "vat".to_string(),
                compact: text.to_string(),
                country: Some(prefix.to_string()),
                parts,
            },
            confidence: 0.99,
            flags,
        })
    }
}

// ---------------------------------------------------------------------------------------------
// Sweden, organisationsnummer
// ---------------------------------------------------------------------------------------------

pub struct OrganisationsnummerRule;

/// Ten digits with an optional hyphen in front of the last four, or the twelve-digit form that
/// prefixes the century marker `16`. The twelve-digit alternative comes first so that a full
/// number is preferred over its own last ten digits.
const ORGANISATIONSNUMMER_PATTERN: &str = r"16\d{6}-?\d{4}|\d{6}-?\d{4}";

/// The words that admit a bare ten-digit run, from Bolagsverket's own name for the number and
/// from Presidio's recogniser context list.
const ORGANISATIONSNUMMER_CUES: &[&str] = &[
    "organisationsnummer",
    "orgnummer",
    "orgnr",
    "org nr",
    "org.nr",
    "företagsnummer",
    "company identity",
    "company registration",
];

/// The leading digit, which says what kind of body holds the number: 1 an estate, 2 a public
/// authority, 3 a foreign company, 5 a limited company, 6 a simple partnership, 7 a cooperative,
/// 8 a non-profit association or foundation, 9 a trading or limited partnership. 0 and 4 were
/// never allocated.
const LEGAL_FORM_DIGITS: [u32; 8] = [1, 2, 3, 5, 6, 7, 8, 9];

impl Rule for OrganisationsnummerRule {
    fn id(&self) -> &'static str {
        "company.se_organisationsnummer"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::CompanyId
    }

    fn candidate_pattern(&self) -> &'static str {
        ORGANISATIONSNUMMER_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // The length is fixed, so both neighbours guard: ten digits cut out of a longer run are
        // not a company number.
        if candidate
            .byte_before()
            .is_some_and(|b| b.is_ascii_alphanumeric())
            || candidate
                .byte_after()
                .is_some_and(|b| b.is_ascii_alphanumeric())
        {
            return None;
        }
        if !candidate.has_cue(ORGANISATIONSNUMMER_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let text = candidate.text();
        let all_digits: String = text.chars().filter(char::is_ascii_digit).collect();
        // The century marker is not part of the number and takes no part in the arithmetic.
        let compact = match all_digits.len() {
            10 => all_digits.clone(),
            12 => all_digits.strip_prefix("16")?.to_string(),
            _ => return None,
        };

        let digits: Vec<u32> = compact.chars().filter_map(|c| c.to_digit(10)).collect();
        if !LEGAL_FORM_DIGITS.contains(&digits[0]) {
            return None;
        }
        // The third digit is what separates this from a personnummer written the same way: it is
        // the tens of the month field there, so it never reaches two.
        if digits[2] < 2 {
            return None;
        }
        // `stdnum/se/orgnr.py` checks the length and Luhn and nothing else; the two structural
        // digits above are what a ten-digit Luhn-valid run needs before it can be a company.
        if !luhn(&compact) {
            return None;
        }

        let mut parts = BTreeMap::new();
        parts.insert("legal_form".to_string(), digits[0].to_string());

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Identifier {
                scheme: "se_organisationsnummer".to_string(),
                compact,
                country: Some("SE".to_string()),
                parts,
            },
            confidence: 0.97,
            flags: Vec::new(),
        })
    }
}

/// The country table, on the same principle as the member-state one: a prefix selects the
/// arithmetic its own tax administration publishes, ported from the corresponding `python-stdnum`
/// module and following the delegation where a country's VAT module is an alias for its
/// company-register module. `Some(flags)` accepts the number.
fn non_eu_country_check(prefix: &str, body: &str) -> Option<Vec<Flag>> {
    match prefix {
        "CH" => ch_mwst(body),
        "GB" => gb_vat(body),
        "ME" => me_pib(body),
        "MK" => mk_edb(body),
        "NO" => no_mva(body),
        "RS" => rs_pib(body),
        "RU" => ru_inn(body),
        "TR" => tr_vkn(body),
        _ => None,
    }
}

/// Switzerland, Mehrwertsteuernummer. The UID, whose own `CHE` prefix doubles as the country
/// code, followed by the tax abbreviation in one of the four national languages. Nine digits
/// under a weighted sum, the last of them the check digit.
fn ch_mwst(body: &str) -> Option<Vec<Flag>> {
    let uid = body.strip_prefix('E')?;
    let number = ["MWST", "TVA", "IVA", "TPV"]
        .iter()
        .find_map(|suffix| uid.strip_suffix(suffix))?;
    let d = digits(number)?;
    if d.len() != 9 {
        return None;
    }
    let check = (11 - weighted_sum(&d[..8], &[5, 4, 3, 2, 7, 6, 5, 4]) % 11) % 11;
    // Ten would need two characters, so it names no valid number.
    (check < 10 && check == d[8]).then(Vec::new)
}

/// United Kingdom (and the Isle of Man) VAT registration number. Three shapes: the nine-digit
/// standard number, optionally carrying a three-digit branch identifier; the five-character
/// government-department and health-authority form; and the eleven-character form those bodies
/// use when they are themselves branch-registered.
fn gb_vat(body: &str) -> Option<Vec<Flag>> {
    // A government department's serial runs below 500 and a health authority's from 500 up,
    // which is the only thing that distinguishes the two prefixes.
    let departmental = |kind: &str, serial: u64| match kind {
        "GD" => serial < 500,
        "HA" => serial >= 500,
        _ => false,
    };

    if body.len() == 5 {
        let serial = as_integer(&digits(body.get(2..)?)?);
        if !departmental(body.get(0..2)?, serial) {
            return None;
        }
        // This form carries no check digit at all: the literal GD or HA marker and the serial
        // range are the whole of what identifies it, and the flag says so.
        return Some(vec![Flag::NoChecksum]);
    }

    if body.len() == 11 {
        let head = body.get(0..6)?;
        if head != "GD8888" && head != "HA8888" {
            return None;
        }
        let d = digits(body.get(6..)?)?;
        let serial = as_integer(&d[..3]);
        if !departmental(head.get(0..2)?, serial) {
            return None;
        }
        return (serial % 97 == as_integer(&d[3..])).then(Vec::new);
    }

    if body.len() != 9 && body.len() != 12 {
        return None;
    }
    let d = digits(body)?;
    let remainder = weighted_sum(&d[..9], &[8, 7, 6, 5, 4, 3, 2, 10, 1]) % 97;
    // The series was restarted at 100, and the numbers issued since then satisfy the weighted sum
    // at any of three remainders rather than only at zero. A branch identifier takes no part.
    let accepted: &[u32] = if as_integer(&d[..3]) >= 100 {
        &[0, 42, 55]
    } else {
        &[0]
    };
    accepted.contains(&remainder).then(Vec::new)
}

/// Montenegro, PIB. Eight digits under a descending weighting modulo eleven.
fn me_pib(body: &str) -> Option<Vec<Flag>> {
    let d = digits(body)?;
    if d.len() != 8 {
        return None;
    }
    let check = (11 - weighted_sum(&d[..7], &[8, 7, 6, 5, 4, 3, 2]) % 11) % 11 % 10;
    (check == d[7]).then(Vec::new)
}

/// North Macedonia, ЕДБ. Thirteen digits under two runs of descending weights.
fn mk_edb(body: &str) -> Option<Vec<Flag>> {
    let d = digits(body)?;
    if d.len() != 13 {
        return None;
    }
    let sum = weighted_sum(&d[..12], &[7, 6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2]);
    ((11 - sum % 11) % 11 % 10 == d[12]).then(Vec::new)
}

/// Norway, MVA. The nine-digit organisasjonsnummer with the tax suffix after it.
fn no_mva(body: &str) -> Option<Vec<Flag>> {
    let d = digits(body.strip_suffix("MVA")?)?;
    if d.len() != 9 {
        return None;
    }
    (weighted_sum(&d, &[3, 2, 7, 6, 5, 4, 3, 2, 1]) % 11 == 0).then(Vec::new)
}

/// Serbia, PIB. Nine digits under ISO 7064 mod 11, 10.
fn rs_pib(body: &str) -> Option<Vec<Flag>> {
    (body.len() == 9 && digits(body).is_some() && iso7064::mod_11_10(body)).then(Vec::new)
}

/// Russia, ИНН. Ten digits for an organisation, twelve for a person, each with its own weights.
fn ru_inn(body: &str) -> Option<Vec<Flag>> {
    let d = digits(body)?;
    match d.len() {
        10 => {
            (weighted_sum(&d[..9], &[2, 4, 10, 3, 5, 9, 4, 6, 8]) % 11 % 10 == d[9]).then(Vec::new)
        }
        12 => {
            let first = weighted_sum(&d[..10], &[7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) % 11 % 10;
            if first != d[10] {
                return None;
            }
            // The second check digit is computed over the first ten digits and the first check
            // digit, so it depends on the one before it.
            let mut head = d[..10].to_vec();
            head.push(first);
            let second = weighted_sum(&head, &[3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) % 11 % 10;
            (second == d[11]).then(Vec::new)
        }
        _ => None,
    }
}

/// Türkiye, VKN. Ten digits, where each of the first nine contributes a value that depends on
/// its position through a doubling ladder rather than a fixed weight.
fn tr_vkn(body: &str) -> Option<Vec<Flag>> {
    let d = digits(body)?;
    if d.len() != 10 {
        return None;
    }
    let mut sum = 0u32;
    for (index, digit) in d[..9].iter().rev().enumerate() {
        let position = index as u32 + 1;
        let shifted = (digit + position) % 10;
        if shifted != 0 {
            let contribution = (shifted << position) % 9;
            sum += if contribution == 0 { 9 } else { contribution };
        }
    }
    ((10 - sum % 10) % 10 == d[9]).then(Vec::new)
}
