//! Telephone numbers, in international form only.
//!
//! A number written with a leading `+` or with an international dialling prefix says which country
//! it belongs to in its own digits, so it can be read without knowing anything about the document.
//! A number in national form cannot: `020 7123 4567` is a London number, a Rome number and a
//! Bucharest number depending on where it was written, and a scanner that assumes one region
//! silently mislabels every document from anywhere else. National form is therefore not matched at
//! all, and no default region exists to be configured.
//!
//! The candidate pattern is deliberately loose about punctuation and says nothing about lengths.
//! Everything that decides truth comes from libphonenumber's metadata, reached through the
//! `phonenumber` crate: which country calling codes exist, which national numbers those countries
//! actually issue, and what kind of line a number is. The guards around it (the characters that
//! may touch the match, the bracket balance, page ranges and timestamps) are the checks
//! libphonenumber's own text matcher applies before it trusts a span it found in prose.

use phonenumber::metadata::DATABASE;
use phonenumber::{Mode, PhoneNumber, Type};

use crate::model::{EntityType, Flag, Value};
use crate::rules::{Candidate, Rule, Verdict};

/// A leading `+` or a `00` dialling prefix, then digits with the punctuation numbers are written
/// with. No `/`, because a slash-separated run is a date or a pair of numbers far more often than
/// it is one number, and no letters, so vanity spellings and extensions are out. Lengths are the
/// validator's business: the pattern only bounds the span so that one candidate cannot cover a
/// paragraph.
const PHONE_PATTERN: &str = r"(?:\+|00)[ ]?[(]?[0-9][0-9 ().\-]{4,22}[0-9]";

/// What the validator can claim when the metadata says the country issues numbers of this shape.
/// No arithmetic confirms a telephone number (nothing in it is redundant), so what it has is the
/// number's structure and its membership of a numbering plan the country publishes, which is the
/// ladder's own description of this row.
const METADATA_VALID: f32 = 0.95;

/// The weaker answer: the region's general pattern accepts the digits but no line type claims
/// them, which is structure and a plausibility window rather than membership.
const GENERAL_PATTERN_ONLY: f32 = 0.85;

/// The markers an extension is written with. The number ends in front of them: an extension is not
/// part of the E.164 number and is dropped rather than parsed, so a match must not be refused
/// merely because one is attached.
const EXTENSION_MARKERS: &[&str] = &["ext.", "ext", "x", "#"];

/// Currency signs commonly written against a number. libphonenumber refuses any character in the
/// Unicode currency-symbol category next to a match, because a sum of money that happens to be
/// punctuated like a phone number is still a sum of money.
const CURRENCY_SIGNS: &[char] = &[
    '$', '£', '€', '¥', '₽', '₹', '¢', '₩', '₪', '₦', '₴', '₺', '₫', '₡', '₱', '₲', '₸', '﷼', '¤',
];

pub struct InternationalRule;

impl Rule for InternationalRule {
    fn id(&self) -> &'static str {
        "phone.international"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Phone
    }

    fn candidate_pattern(&self) -> &'static str {
        PHONE_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        let text = candidate.text();

        if !starts_cleanly(candidate) || !ends_cleanly(candidate) {
            return None;
        }
        if !brackets_balance(text) || looks_like_page_range(text) || looks_like_timestamp(candidate)
        {
            return None;
        }

        let digits: String = text.chars().filter(char::is_ascii_digit).collect();
        // The dialling prefix and the plus sign say the same thing, so the prefix becomes a plus
        // and one parse handles both spellings.
        let dialled = if text.starts_with('+') {
            format!("+{digits}")
        } else {
            format!("+{}", digits.get(2..)?)
        };

        let number = phonenumber::parse(None, &dialled).ok()?;
        let confidence = if number.is_valid() {
            METADATA_VALID
        } else if matches_general_pattern(&number) {
            GENERAL_PATTERN_ONLY
        } else {
            return None;
        };
        // A `00` prefix is two ordinary digits, so any long identifier run can wear one. Requiring
        // both the metadata's confirmation and the punctuation somebody dialling from abroad
        // writes is what keeps an invoice number from being read as a call to another country.
        if !text.starts_with('+')
            && (confidence < METADATA_VALID || digits.len() == text.chars().count())
        {
            return None;
        }

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: value_of(&number),
            confidence,
            // Nothing in a telephone number is redundant, so no arithmetic can confirm it. What
            // confirmed it is that the country issues numbers of this shape.
            flags: vec![Flag::NoChecksum],
        })
    }
}

/// Whether the region's general national-number pattern accepts the digits. It is the weaker of
/// the metadata's two answers: the length and the leading digits are a shape that country issues,
/// but no individual line type claims the number. That is where a number written before a
/// renumbering, or one the metadata has not caught up with, lands.
fn matches_general_pattern(number: &PhoneNumber) -> bool {
    let Some(metadata) = number.metadata(&DATABASE) else {
        return false;
    };
    let national = number.national().to_string();
    // The whole national number has to be the match, not its first nine digits. The metadata's
    // patterns are unanchored, so a prefix test would accept every longer digit run that happens
    // to start with a real number, which is exactly the run this rule must refuse.
    metadata
        .descriptors()
        .general()
        .national_number()
        .find(&national)
        .is_some_and(|found| found.start() == 0 && found.end() == national.len())
}

fn value_of(number: &PhoneNumber) -> Value {
    Value::Phone {
        e164: number.format().mode(Mode::E164).to_string(),
        // `001` is the region libphonenumber gives the global services (+800 freephone, +870
        // Inmarsat) which belong to no country.
        country: number
            .country()
            .id()
            .map_or_else(|| "001".to_string(), |id| id.as_ref().to_string()),
        national: number.national().to_string(),
        number_type: type_name(number.number_type(&DATABASE)).to_string(),
    }
}

/// The line type as the metadata classifies it, in the same snake case the rest of the wire format
/// uses.
fn type_name(kind: Type) -> &'static str {
    match kind {
        Type::FixedLine => "fixed_line",
        Type::Mobile => "mobile",
        Type::FixedLineOrMobile => "fixed_line_or_mobile",
        Type::TollFree => "toll_free",
        Type::PremiumRate => "premium_rate",
        Type::SharedCost => "shared_cost",
        Type::PersonalNumber => "personal_number",
        Type::Voip => "voip",
        Type::Pager => "pager",
        Type::Uan => "uan",
        Type::Emergency => "emergency",
        Type::Voicemail => "voicemail",
        Type::ShortCode => "short_code",
        Type::StandardRate => "standard_rate",
        Type::Carrier => "carrier",
        Type::NoInternational => "no_international",
        Type::Unknown => "unknown",
    }
}

/// Nothing that would make the digits part of a larger token may touch the left edge. A letter
/// there means the run is a plus-addressed mailbox or an identifier with a sign in it rather than
/// a number somebody could dial.
fn starts_cleanly(candidate: &Candidate<'_>) -> bool {
    let Some(previous) = candidate.fragment[..candidate.start].chars().next_back() else {
        return true;
    };
    !(previous.is_alphanumeric()
        || previous == '%'
        || previous == '/'
        || previous == '+'
        || CURRENCY_SIGNS.contains(&previous))
}

/// The right edge, where the scan loop's recovery makes this check decide the result. A candidate that
/// failed as a whole is re-run over its interior, and a shortened run must not be accepted while
/// the rest of the token continues past it.
fn ends_cleanly(candidate: &Candidate<'_>) -> bool {
    let rest = &candidate.fragment[candidate.end..];
    let mut following = rest.chars();
    let Some(next) = following.next() else {
        return true;
    };
    if next.is_alphanumeric() || next == '%' || next == '+' || CURRENCY_SIGNS.contains(&next) {
        return extension_follows(rest);
    }
    // A separator with a digit after it is the same token continuing. A space is not: a number
    // followed by a separate number is two numbers, which is what the recovery is for.
    if matches!(next, '-' | '.' | '/' | '(' | ')') {
        return !following.next().is_some_and(|after| after.is_ascii_digit());
    }
    true
}

/// Whether the text past the right edge is an extension rather than the token continuing. The span
/// still ends where the number does, so what this admits is the number in front of the marker and
/// never the digits behind it.
fn extension_follows(rest: &str) -> bool {
    let head: String = rest
        .chars()
        .take(6)
        .collect::<String>()
        .to_ascii_lowercase();
    EXTENSION_MARKERS.iter().any(|marker| {
        head.strip_prefix(marker)
            .is_some_and(|after| after.trim_start().starts_with(|c: char| c.is_ascii_digit()))
    })
}

/// Brackets inside a number must open, hold digits and close. Anything else is two pieces of text
/// that the pattern joined across a bracket rather than one number written with an area code.
fn brackets_balance(text: &str) -> bool {
    let mut open = false;
    let mut content = 0usize;
    let mut pairs = 0usize;
    for character in text.chars() {
        match character {
            '(' => {
                if open {
                    return false;
                }
                open = true;
                content = 0;
                pairs += 1;
            }
            ')' => {
                if !open || content == 0 {
                    return false;
                }
                open = false;
            }
            digit if open && digit.is_ascii_digit() => content += 1,
            _ => {}
        }
    }
    !open && pairs <= 3
}

/// A citation's page range and year (`211-227 (2003)`) is punctuated exactly like a number with
/// an area code. libphonenumber refuses the shape outright, and so does this.
fn looks_like_page_range(text: &str) -> bool {
    let bytes = text.as_bytes();
    for (index, byte) in bytes.iter().enumerate() {
        if *byte != b'(' {
            continue;
        }
        if !bytes.get(index + 1).is_some_and(u8::is_ascii_digit) {
            continue;
        }
        let mut cursor = index;
        let mut spaces = 0;
        while cursor > 0 && bytes[cursor - 1] == b' ' && spaces < 4 {
            cursor -= 1;
            spaces += 1;
        }
        let Some(cursor) = digits_before(bytes, cursor, 5) else {
            continue;
        };
        if cursor == 0 || bytes[cursor - 1] != b'-' {
            continue;
        }
        let mut cursor = cursor;
        while cursor > 0 && bytes[cursor - 1] == b'-' {
            cursor -= 1;
        }
        if digits_before(bytes, cursor, 5).is_some() {
            return true;
        }
    }
    false
}

/// A timestamp's date and hour (`2012-01-02 08`) followed by the minutes that complete it. The
/// minutes are outside the span, so the check has to look past its right edge to know that what it
/// is holding is the front of a clock reading rather than the back of a number.
fn looks_like_timestamp(candidate: &Candidate<'_>) -> bool {
    let mut following = candidate.fragment[candidate.end..].bytes();
    if following.next() != Some(b':') {
        return false;
    }
    let (Some(tens), Some(units)) = (following.next(), following.next()) else {
        return false;
    };
    if !(b'0'..=b'5').contains(&tens) || !units.is_ascii_digit() {
        return false;
    }

    let bytes = candidate.text().as_bytes();
    let Some(cursor) = hour_at_end(bytes) else {
        return false;
    };
    let mut cursor = cursor;
    let mut spaces = 0;
    while cursor > 0 && bytes[cursor - 1] == b' ' {
        cursor -= 1;
        spaces += 1;
    }
    if spaces == 0 {
        return false;
    }
    date_before(bytes, cursor)
}

/// `[0-2]\d` at the end of the span, answering with the offset it starts at.
fn hour_at_end(bytes: &[u8]) -> Option<usize> {
    let end = bytes.len();
    if end < 2 || !bytes[end - 1].is_ascii_digit() || !(b'0'..=b'2').contains(&bytes[end - 2]) {
        return None;
    }
    Some(end - 2)
}

/// `[12]\d{3}[-]?[01]\d[-]?[0-3]\d` ending at `cursor`.
fn date_before(bytes: &[u8], cursor: usize) -> bool {
    let day = |value: &[u8]| (b'0'..=b'3').contains(&value[0]) && value[1].is_ascii_digit();
    let month = |value: &[u8]| (b'0'..=b'1').contains(&value[0]) && value[1].is_ascii_digit();

    let mut cursor = cursor;
    if cursor < 2 || !day(&bytes[cursor - 2..cursor]) {
        return false;
    }
    cursor -= 2;
    if cursor > 0 && bytes[cursor - 1] == b'-' {
        cursor -= 1;
    }
    if cursor < 2 || !month(&bytes[cursor - 2..cursor]) {
        return false;
    }
    cursor -= 2;
    if cursor > 0 && bytes[cursor - 1] == b'-' {
        cursor -= 1;
    }
    cursor >= 4
        && (b'1'..=b'2').contains(&bytes[cursor - 4])
        && bytes[cursor - 3..cursor].iter().all(u8::is_ascii_digit)
}

/// Walks back over one to `limit` digits ending at `cursor`, answering with where they start.
fn digits_before(bytes: &[u8], cursor: usize, limit: usize) -> Option<usize> {
    let mut start = cursor;
    while start > 0 && bytes[start - 1].is_ascii_digit() && cursor - start < limit {
        start -= 1;
    }
    (start < cursor).then_some(start)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn brackets_must_open_hold_digits_and_close() {
        assert!(brackets_balance("+49 (0) 30 123456"));
        assert!(brackets_balance("+1 202 555 0143"));
        assert!(!brackets_balance("+49 (0 30 123456"));
        assert!(!brackets_balance("+49 () 30 123456"));
        assert!(!brackets_balance("+49 ((0)) 30 123456"));
    }

    #[test]
    fn a_page_range_and_year_is_not_a_number() {
        assert!(looks_like_page_range("+12 211-227 (2003"));
        assert!(!looks_like_page_range("+49 (0) 30 123456"));
    }

    #[test]
    fn the_date_shape_is_the_one_libphonenumber_refuses() {
        assert!(date_before(b"2012-01-02", 10));
        assert!(date_before(b"20120102", 8));
        assert!(!date_before(b"3012-01-02", 10));
        assert!(!date_before(b"2012-41-02", 10));
    }
}
