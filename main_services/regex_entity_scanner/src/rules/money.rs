//! Sums of money: an amount plus the currency it is denominated in.
//!
//! Two properties decide the shape of this module.
//!
//! **The value is an integer.** A sum of money is a scaled integer, an ISO 4217 code and the
//! exponent that code divides into, never a float, at any point, including intermediates. Binary
//! floating point cannot represent a tenth, so a pipeline that touches one has already lost the
//! cent it was asked to preserve, and it loses it silently.
//!
//! **The separators are a convention, not a grammar.** `1.234` is a thousand in Bucharest and
//! one-and-a-bit in London, and no amount of looking at the digits settles it. What the digits do
//! settle is which readings are impossible: a group of exactly three digits after the only
//! separator is the case where both readings survive, and that is what the separator-inferred flag
//! is for. Every other shape is decided by arithmetic, a group that is not three digits long
//! cannot be a thousands group, and a separator followed by one or two digits cannot be anything
//! but a decimal mark.

use crate::model::{EntityType, Flag, Value};
use crate::rules::context::DEFAULT_CUE_WINDOW;
use crate::rules::{Candidate, Rule, Verdict};

/// Codes that are also ordinary English words in the register where they appear in capitals: ALL
/// items, TOP 40, the CUP final. Membership of ISO 4217 is not enough for these, because the
/// sentences they turn up in are far more common than the currencies are.
const WORD_LIKE_CODES: &[&str] = &[
    "ALL", "BOB", "COP", "CUP", "GEL", "MAD", "MOP", "PEN", "SOS", "TOP", "TRY",
];

/// What a sum of money is being talked about when the code is one of the word-like ones.
const MONEY_CUES: &[&str] = &[
    "price", "cost", "costs", "amount", "total", "paid", "pay", "invoice", "fee", "fees", "salary",
    "budget", "balance", "sum", "worth", "value", "revenue", "turnover", "currency",
];

/// The amount half of both candidate patterns: digits, optionally split into three-digit groups by
/// a space or by the apostrophe Switzerland writes, optionally carrying a decimal part. Which
/// separator means what is the validator's problem, so this is deliberately looser than any real
/// number format and the shapes that mean nothing at all are rejected there.
macro_rules! amount {
    () => {
        r"[0-9]+(?:[\x20\x{a0}\x{202f}'\x{2019}][0-9]{3})*(?:[.,][0-9]+)*"
    };
}

// ---------------------------------------------------------------------------------------------
// ISO 4217 code
// ---------------------------------------------------------------------------------------------

pub struct IsoCodeRule;

/// `EUR 1.234,56` or `1,234.56 USD`. The code may lead or trail, because both are written and
/// neither is more correct.
const ISO_CODE_PATTERN: &str = concat!(
    r"[A-Z]{3}[\x20\x{a0}]?",
    amount!(),
    r"|",
    amount!(),
    r"[\x20\x{a0}]?[A-Z]{3}"
);

impl Rule for IsoCodeRule {
    fn id(&self) -> &'static str {
        "money.iso_code"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Money
    }

    fn candidate_pattern(&self) -> &'static str {
        ISO_CODE_PATTERN
    }

    fn resumes_past_rejection(&self) -> bool {
        true
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if continues_left(candidate) || continues_right(candidate) {
            return None;
        }

        let text = candidate.text();
        let leading = text.as_bytes().first()?.is_ascii_uppercase();
        let (code, amount) = if leading {
            (&text[..3], text[3..].trim_start())
        } else {
            (&text[text.len() - 3..], text[..text.len() - 3].trim_end())
        };

        let currency = candidate.data.currency(code)?;
        if WORD_LIKE_CODES.contains(&code) && !candidate.has_cue(MONEY_CUES, DEFAULT_CUE_WINDOW) {
            return None;
        }

        let (amount_minor, inferred) = to_minor_units(amount, currency.exponent)?;

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Money {
                currency: code.to_string(),
                amount_minor,
                exponent: currency.exponent,
            },
            // There is no check digit here to earn a higher number: what the validator has is the
            // amount's structure and the code's membership of the ISO 4217 list in current use,
            // which is the ladder's own description of 0.95.
            confidence: 0.95,
            flags: if inferred {
                vec![Flag::SeparatorInferred]
            } else {
                Vec::new()
            },
        })
    }
}

// ---------------------------------------------------------------------------------------------
// Currency symbol
// ---------------------------------------------------------------------------------------------

pub struct SymbolRule;

/// A Unicode currency sign, optionally carrying the one or two capitals that distinguish the
/// dollars and yuan from each other: `A$`, `CN¥`, `R$`. `\p{Sc}` is the property the signs are
/// defined by, which is why the pattern does not enumerate them. Beside a sign, an amount may
/// also be a fraction with no integer part: `$.75` is a price a shelf label carries.
const SYMBOL_PATTERN: &str = concat!(
    r"[A-Z]{0,2}\p{Sc}[\x20\x{a0}]?",
    r"(?:",
    amount!(),
    r"|[.,][0-9]+)",
    r"|",
    r"(?:",
    amount!(),
    r"|[.,][0-9]+)",
    r"[\x20\x{a0}]?[A-Z]{0,2}\p{Sc}"
);

impl Rule for SymbolRule {
    fn id(&self) -> &'static str {
        "money.symbol"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Money
    }

    fn candidate_pattern(&self) -> &'static str {
        SYMBOL_PATTERN
    }

    fn resumes_past_rejection(&self) -> bool {
        true
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        if continues_right(candidate) {
            return None;
        }

        let text = candidate.text();
        let leading = !text.starts_with(|c: char| c.is_ascii_digit() || c == '.' || c == ',');
        let (symbol, amount) = if leading {
            let digit = text.find(|c: char| c.is_ascii_digit())?;
            // An amount with no integer part starts at its decimal mark, not at its first digit:
            // splitting on the digit would turn `$.75` into seventy-five dollars.
            let split = match text.as_bytes().get(digit.wrapping_sub(1)) {
                Some(b'.' | b',') if digit > 0 => digit - 1,
                _ => digit,
            };
            (text[..split].trim_end(), text[split..].trim_start())
        } else {
            let split = text.rfind(|c: char| c.is_ascii_digit())? + 1;
            (text[split..].trim_start(), text[..split].trim_end())
        };

        // An explicit ISO 4217 code beside the sign settles which of the sign's currencies this
        // is. `NZD $100.70` and `SGD$4.90` are not United States dollars, and reporting them as
        // such is a wrong value rather than a miss, which is the worse of the two failures. This is asked
        // before the left-hand guard, because in `SGD$4.90` the pattern's leftmost match starts
        // inside the code and the letters the guard sees are the code itself.
        if leading {
            if let Some((code, code_at)) = code_beside_sign(candidate, symbol) {
                return minted(candidate, code, code_at, amount, Vec::new(), 0.95);
            }
        }

        if continues_left(candidate) {
            return None;
        }

        // A capital or two in front of the sign is part of the symbol only when the pair is one
        // somebody actually writes. Otherwise they belong to the word before it, and the span
        // narrows to the sign: `US$40` and `paid US $40` both mean forty dollars, and neither
        // means the letters are currency.
        let (symbol, start) = match candidate.data.currency_symbol(symbol) {
            Some(_) => (symbol, candidate.start),
            None => {
                let letters = symbol.len()
                    - symbol
                        .trim_start_matches(|c: char| c.is_ascii_uppercase())
                        .len();
                if letters == 0 || !leading {
                    return None;
                }
                let before = candidate.fragment.as_bytes()[..candidate.start].last();
                if before.is_some_and(|byte| byte.is_ascii_alphanumeric()) {
                    return None;
                }
                (&symbol[letters..], candidate.start + letters)
            }
        };

        let codes = candidate.data.currency_symbol(symbol)?;
        let code = codes.first()?;
        // A symbol shared by twenty-nine currencies names the most widely used of them and says so
        // with a flag; it has not established which one this is.
        let ambiguous = codes.len() > 1;
        let flags = if ambiguous {
            vec![Flag::AmbiguousCurrency]
        } else {
            Vec::new()
        };
        minted(
            candidate,
            code,
            start,
            amount,
            flags,
            if ambiguous { 0.80 } else { 0.95 },
        )
    }
}

/// The ISO 4217 code written immediately in front of a currency sign, and where it starts.
///
/// The code has to be one the sign itself can denote: that intersection is what separates
/// `SGD$4.90` from an ordinary three-letter word standing next to a price.
fn code_beside_sign<'a>(candidate: &Candidate<'a>, symbol: &str) -> Option<(&'a str, usize)> {
    let letters = symbol.len()
        - symbol
            .trim_start_matches(|c: char| c.is_ascii_uppercase())
            .len();
    let sign = symbol.get(letters..)?;
    let sign_at = candidate.start + letters;

    let head = candidate.fragment.get(..sign_at)?;
    let head = head.strip_suffix([' ', '\u{a0}']).unwrap_or(head);
    let code_at = head.len().checked_sub(3)?;
    let code = head.get(code_at..)?;
    if !code.bytes().all(|byte| byte.is_ascii_uppercase()) {
        return None;
    }
    // The code has to stand on its own. A letter or digit in front of it makes it the tail of a
    // longer word, and a sign or a separator makes the whole span the tail of a longer number,
    // and this rule reports an unsigned amount, so a dropped minus would report the wrong money.
    if head.as_bytes()[..code_at]
        .last()
        .is_some_and(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b','))
    {
        return None;
    }

    let codes = candidate.data.currency_symbol(sign)?;
    codes
        .iter()
        .any(|candidate_code| candidate_code == code)
        .then_some((code, code_at))
}

/// The verdict a resolved currency and amount make, or nothing when the amount is not a number any
/// separator convention produces.
fn minted(
    candidate: &Candidate<'_>,
    code: &str,
    start: usize,
    amount: &str,
    mut flags: Vec<Flag>,
    confidence: f32,
) -> Option<Verdict> {
    let currency = candidate.data.currency(code)?;
    let (amount_minor, inferred) = to_minor_units(amount, currency.exponent)?;
    if inferred {
        flags.push(Flag::SeparatorInferred);
    }
    Some(Verdict {
        start,
        end: candidate.end,
        value: Value::Money {
            currency: code.to_string(),
            amount_minor,
            exponent: currency.exponent,
        },
        confidence,
        flags,
    })
}

// ---------------------------------------------------------------------------------------------
// Separator inference and scaling
// ---------------------------------------------------------------------------------------------

/// A dot, a comma or a hyphen touching the span is either the number continuing or the sentence
/// ending, and one character further out is what tells them apart.
fn is_separator(byte: u8) -> bool {
    matches!(byte, b'.' | b',' | b'-')
}

/// Whether what precedes the span makes it the tail of a longer number. A letter or a digit always
/// does. A minus sign does too: this rule reports an unsigned amount, so a match that drops a
/// leading sign would report the wrong money rather than none. A dot or a comma does only when
/// digits precede it, with or without the space some documents put after it, which is what makes
/// `1.837, 32 €` one price written oddly rather than thirty-two euro.
fn continues_left(candidate: &Candidate<'_>) -> bool {
    let before = &candidate.fragment.as_bytes()[..candidate.start];
    let Some((&last, head)) = before.split_last() else {
        return false;
    };
    if last.is_ascii_alphanumeric() || last == b'-' {
        return true;
    }
    let (separator, head) = if last == b' ' {
        match head.split_last() {
            Some((&byte, head)) => (byte, head),
            None => return false,
        }
    } else {
        (last, head)
    };
    is_separator(separator) && head.last().is_some_and(u8::is_ascii_digit)
}

/// Whether what follows the span refutes this reading of it.
///
/// A span that ends in a digit is the head of a longer number when digits carry on past it. The
/// separator that ends a sentence and the separator that groups the next three digits are the same
/// character, so the test is what comes after it: a digit, or a digit one space away. Anything else
/// is punctuation, and refusing it would put the commonest way a price appears in prose (at the
/// end of a sentence, or in a list) out of reach.
///
/// A span that ends in a **marker** (a trailing ISO 4217 code or currency sign) is refuted by a
/// digit instead, because **a marker binds to the number that follows it**. In `qty 2 EUR 30 per
/// unit` the trailing-code reading `2 EUR` is a candidate, and it is not merely a worse reading than
/// `EUR 30`: it is a wrong one, and it reports two euro for a thirty-euro line. The same principle
/// already decides that a code standing immediately in front of a sign names the currency. Refusing
/// the span turns the wrong value into silence, which is the trade this project takes.
fn continues_right(candidate: &Candidate<'_>) -> bool {
    let rest = &candidate.fragment.as_bytes()[candidate.end..];
    let Some((&next, tail)) = rest.split_first() else {
        return false;
    };
    if next.is_ascii_alphanumeric() {
        return true;
    }
    let after_a_space = match tail.split_first() {
        Some((&byte, _)) if next == b' ' => Some(byte),
        _ => None,
    };
    if !candidate
        .text()
        .as_bytes()
        .last()
        .is_some_and(u8::is_ascii_digit)
    {
        return after_a_space.is_some_and(|byte| byte.is_ascii_digit());
    }
    if !is_separator(next) {
        return false;
    }
    let tail = match tail.split_first() {
        Some((b' ', rest)) => rest,
        _ => tail,
    };
    tail.first().is_some_and(u8::is_ascii_digit)
}

/// The amount as an integer number of minor units, and whether the separators had to be guessed.
///
/// Ported from `vendored/reference/price-parser/`, whose rule is the last separator's group: one or
/// two digits, or four and more, can only be a fraction; exactly three digits is a thousands group
/// unless something else in the number says otherwise. Everything is `u128` arithmetic on digit
/// strings, so no intermediate is ever a float.
fn to_minor_units(amount: &str, exponent: u8) -> Option<(String, bool)> {
    // Space grouping carries no ambiguity at all, so it is settled before anything else looks at
    // the number.
    let amount: String = amount
        .chars()
        .filter(|c| !matches!(c, ' ' | '\u{a0}' | '\u{202f}' | '\'' | '\u{2019}'))
        .collect();
    // A fraction with no integer part is a price, so the amount may open with its decimal mark,
    // but only with digits behind it, never with a bare separator.
    let opens_well = match amount.as_bytes() {
        [first, ..] if first.is_ascii_digit() => true,
        [b'.' | b',', second, ..] => second.is_ascii_digit(),
        _ => false,
    };
    if !opens_well {
        return None;
    }

    let separators: Vec<usize> = amount
        .char_indices()
        .filter(|(_, c)| *c == '.' || *c == ',')
        .map(|(index, _)| index)
        .collect();

    let mut inferred = false;
    let decimal = match separators.last() {
        None => None,
        Some(&last) => {
            let tail = amount.len() - last - 1;
            // Two different separator characters in one number explain each other: `1.234,567`
            // cannot be read the other way round, whatever the length of the last group.
            let mixed = separators.len() > 1
                && amount.as_bytes()[separators[separators.len() - 2]] != amount.as_bytes()[last];
            if tail == 3 && !mixed {
                // Grouping, and where it is the only separator the reading was a choice: `1,234`
                // is a thousand or one-and-a-bit depending on who wrote it.
                inferred = separators.len() == 1;
                None
            } else {
                Some(last)
            }
        }
    };

    // Every separator that is not the decimal mark is a thousands group, and a thousands group is
    // exactly three digits. This is what rejects `1.2.3` and every other dotted run that is a
    // version, a chapter number or an address rather than a number.
    let groups: Vec<usize> = separators
        .iter()
        .copied()
        .filter(|index| Some(*index) != decimal)
        .collect();
    if !groups.is_empty() {
        let first = groups[0];
        if first == 0 || first > 3 {
            return None;
        }
        let mut previous = first;
        for &index in &groups[1..] {
            if index - previous != 4 {
                return None;
            }
            previous = index;
        }
        let after_last = decimal.unwrap_or(amount.len());
        if after_last - previous != 4 {
            return None;
        }
        // Mixed separators are self-explaining: `1.234,56` cannot be read the other way round.
        let group_char = amount.as_bytes()[first];
        if groups
            .iter()
            .any(|index| amount.as_bytes()[*index] != group_char)
        {
            return None;
        }
        if let Some(decimal) = decimal {
            if amount.as_bytes()[decimal] == group_char {
                return None;
            }
        }
    }

    let (units, fraction) = match decimal {
        Some(index) => (&amount[..index], &amount[index + 1..]),
        None => (&amount[..], ""),
    };
    let units: String = units.chars().filter(char::is_ascii_digit).collect();
    if units.len() > 24 || (units.is_empty() && decimal.is_none()) {
        return None;
    }

    // A currency with two minor units is not written with four decimal places, and something that
    // is written that way is a rate, a measurement or a version, not a sum of money.
    let exponent = usize::from(exponent);
    if fraction.len() > exponent {
        return None;
    }
    let minor = format!("{units}{fraction}{}", "0".repeat(exponent - fraction.len()));
    let minor: String = minor.trim_start_matches('0').to_string();
    Some((
        if minor.is_empty() {
            "0".to_string()
        } else {
            minor
        },
        inferred,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn separator_inference_follows_the_upstream_rule() {
        // Two decimal places are a fraction, three are a thousands group, and the mixed forms are
        // decided by the pair rather than by either separator alone.
        assert_eq!(
            to_minor_units("1.234,56", 2),
            Some(("123456".into(), false))
        );
        assert_eq!(
            to_minor_units("1,234.56", 2),
            Some(("123456".into(), false))
        );
        assert_eq!(to_minor_units("12,34", 2), Some(("1234".into(), false)));
        assert_eq!(to_minor_units("1200", 2), Some(("120000".into(), false)));
        assert_eq!(
            to_minor_units("1 234,56", 2),
            Some(("123456".into(), false))
        );
        // The one genuinely ambiguous shape: read as a thousand, and said to have been read.
        assert_eq!(to_minor_units("1,234", 2), Some(("123400".into(), true)));
        assert_eq!(to_minor_units("1.234", 2), Some(("123400".into(), true)));
        // The exponent is the currency's, not two.
        assert_eq!(
            to_minor_units("1.234,567", 3),
            Some(("1234567".into(), false))
        );
        assert_eq!(to_minor_units("1200", 0), Some(("1200".into(), false)));
        // The apostrophe is Switzerland's grouping mark, and it carries no ambiguity either.
        assert_eq!(
            to_minor_units("1'049,95", 2),
            Some(("104995".into(), false))
        );
        // A fraction with no integer part is a price, and its integer part is zero.
        assert_eq!(to_minor_units(".75", 2), Some(("75".into(), false)));
    }

    #[test]
    fn shapes_that_are_not_numbers_are_rejected() {
        // A version string, a chapter number and a date all reach this function through some
        // pattern or other, and none of them has three-digit thousands groups.
        assert_eq!(to_minor_units("1.2.3", 2), None);
        assert_eq!(to_minor_units("1.2345.67", 2), None);
        assert_eq!(to_minor_units("12,3456", 2), None);
        assert_eq!(to_minor_units("1.234.56", 2), None);
        assert_eq!(to_minor_units("", 2), None);
        assert_eq!(to_minor_units("1.5", 0), None);
        // A separator with nothing behind it is not a number at all.
        assert_eq!(to_minor_units(".", 2), None);
        assert_eq!(to_minor_units(".750.30", 2), None);
    }
}
