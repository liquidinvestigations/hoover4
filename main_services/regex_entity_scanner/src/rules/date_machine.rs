//! Machine date formats other than ISO 8601: mail headers, web-server logs, ISO week dates.
//!
//! These three share the property that makes a date rule worth having at all: the match itself
//! fixes the whole civil day, and the surface form is a literal marker rather than a digit run.
//! A weekday name, a bracketed log timestamp and a `W` between year and week are each things a
//! version string or an invoice number does not accidentally contain.

use jiff::civil::{Date, Weekday};

use crate::model::{DatePrecision, EntityType, Flag, Value};
use crate::rules::{Candidate, Rule, Verdict};

/// Years outside this window are almost always a version string, an identifier fragment or an
/// off-by-a-digit typo rather than a date somebody meant to write. The same window as
/// [`super::date_iso`], for the same reason.
const PLAUSIBLE_YEARS: std::ops::RangeInclusive<i16> = 1400..=2200;

const MONTHS: [&str; 12] = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

const WEEKDAYS: [&str; 7] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// ---------------------------------------------------------------------------------------------
// RFC 2822 / RFC 5322 date-time
// ---------------------------------------------------------------------------------------------

pub struct Rfc2822Rule;

/// The day-of-week is optional in the grammar and required here: it is a free consistency check
/// against the rest of the date, and it is most of what separates this from a bare `04 Mar 2021`.
/// Seconds are optional, as the grammar has them; the zone is not, because a header without one is
/// rare enough not to be worth the ambiguity.
const RFC2822_PATTERN: &str = concat!(
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), {1,2}\d{1,2} ",
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)",
    r" \d{4} \d{2}:\d{2}(?::\d{2})? ",
    r"(?:[+\-]\d{4}|UT|GMT|EST|EDT|CST|CDT|MST|MDT|PST|PDT)",
);

impl Rule for Rfc2822Rule {
    fn id(&self) -> &'static str {
        "date.rfc2822"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Date
    }

    fn candidate_pattern(&self) -> &'static str {
        RFC2822_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // A weekday name run into by a letter is part of a longer word, and a zone run into by a
        // digit or a letter is a truncated reading of something else.
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
        let fields: Vec<&str> = text.split_whitespace().collect();
        if fields.len() != 6 {
            return None;
        }

        let weekday_name = fields[0].strip_suffix(',')?;
        let weekday_index = WEEKDAYS.iter().position(|name| *name == weekday_name)?;

        let day: i8 = fields[1].parse().ok()?;
        let month = month_number(fields[2])?;
        let year: i16 = fields[3].parse().ok()?;
        if !PLAUSIBLE_YEARS.contains(&year) {
            return None;
        }

        let date = Date::new(year, month, day).ok()?;
        // A header whose weekday contradicts its date is fabricated, mangled or a coincidence in
        // running text. All three are things this facet is better off without.
        let claimed = Weekday::from_monday_one_offset(weekday_index as i8 + 1).ok()?;
        if date.weekday() != claimed {
            return None;
        }

        let (hour, minute, second, precision) = parse_clock(fields[4])?;
        jiff::civil::DateTime::new(year, month, day, hour, minute, second, 0).ok()?;

        let offset = zone_offset(fields[5])?;

        let rfc3339 = match precision {
            DatePrecision::Second => {
                format!("{date}T{hour:02}:{minute:02}:{second:02}{offset}")
            }
            _ => format!("{date}T{hour:02}:{minute:02}{offset}"),
        };

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Date {
                rfc3339,
                precision,
                tz_known: true,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

// ---------------------------------------------------------------------------------------------
// Common Log Format
// ---------------------------------------------------------------------------------------------

pub struct ClfRule;

/// The brackets are part of the match and not part of the span: they are what makes the format
/// self-identifying, and they are not part of the date the reader sees highlighted.
const CLF_PATTERN: &str = concat!(
    r"\[\d{2}/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/",
    r"\d{4}:\d{2}:\d{2}:\d{2} [+\-]\d{4}\]",
);

impl Rule for ClfRule {
    fn id(&self) -> &'static str {
        "date.clf"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Date
    }

    fn candidate_pattern(&self) -> &'static str {
        CLF_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        let text = candidate.text();
        let inner = text.strip_prefix('[')?.strip_suffix(']')?;

        let (date_part, rest) = inner.split_once(':')?;
        let mut parts = date_part.split('/');
        let day: i8 = parts.next()?.parse().ok()?;
        let month = month_number(parts.next()?)?;
        let year: i16 = parts.next()?.parse().ok()?;
        if parts.next().is_some() || !PLAUSIBLE_YEARS.contains(&year) {
            return None;
        }

        let (clock, zone) = rest.split_once(' ')?;
        let date = Date::new(year, month, day).ok()?;
        let (hour, minute, second, _) = parse_clock(clock)?;
        jiff::civil::DateTime::new(year, month, day, hour, minute, second, 0).ok()?;
        let offset = zone_offset(zone)?;

        Some(Verdict {
            // The span is the timestamp, not the brackets around it.
            start: candidate.start + 1,
            end: candidate.end - 1,
            value: Value::Date {
                rfc3339: format!("{date}T{hour:02}:{minute:02}:{second:02}{offset}"),
                precision: DatePrecision::Second,
                tz_known: true,
            },
            confidence: 0.99,
            flags: Vec::new(),
        })
    }
}

// ---------------------------------------------------------------------------------------------
// ISO 8601 week dates
// ---------------------------------------------------------------------------------------------

pub struct IsoWeekRule;

/// Both ISO spellings, extended and basic. `2021-W09` on its own names a week rather than a day and
/// is deliberately absent: a rule that cannot fix the day emits nothing.
const ISO_WEEK_PATTERN: &str = r"\d{4}-W\d{2}-\d|\d{4}W\d{3}";

impl Rule for IsoWeekRule {
    fn id(&self) -> &'static str {
        "date.iso_week"
    }

    fn entity_type(&self) -> EntityType {
        EntityType::Date
    }

    fn candidate_pattern(&self) -> &'static str {
        ISO_WEEK_PATTERN
    }

    fn validate(&self, candidate: &Candidate<'_>) -> Option<Verdict> {
        // Stripped `(?<!\w)` and `(?!\w)`: a week date wedged into a longer alphanumeric run is
        // part of a serial number, not a date.
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
        // The extended spelling `2021-W09-4` and the basic one `2021W094` differ only by the two
        // hyphens, so the fields sit at one of two fixed offsets.
        let (week_at, weekday_at) = if text.as_bytes().get(4) == Some(&b'-') {
            (6, 9)
        } else {
            (5, 7)
        };
        let year: i16 = text.get(0..4)?.parse().ok()?;
        let week: i8 = text.get(week_at..week_at + 2)?.parse().ok()?;
        let weekday: i8 = text.get(weekday_at..weekday_at + 1)?.parse().ok()?;

        if !PLAUSIBLE_YEARS.contains(&year) {
            return None;
        }
        // ISO numbers weekdays 1..=7 from Monday, and week 53 exists only in the years that have
        // one, which is the arithmetic that makes this a real check rather than a range test.
        let weekday = Weekday::from_monday_one_offset(weekday).ok()?;
        let week_date = jiff::civil::ISOWeekDate::new(year, week, weekday).ok()?;
        let date = week_date.date();

        Some(Verdict {
            start: candidate.start,
            end: candidate.end,
            value: Value::Date {
                rfc3339: date.to_string(),
                precision: DatePrecision::Day,
                tz_known: false,
            },
            confidence: 0.99,
            flags: vec![Flag::NoTimezone],
        })
    }
}

// ---------------------------------------------------------------------------------------------
// Shared parsing
// ---------------------------------------------------------------------------------------------

fn month_number(name: &str) -> Option<i8> {
    MONTHS
        .iter()
        .position(|month| *month == name)
        .map(|index| index as i8 + 1)
}

/// `HH:MM` or `HH:MM:SS`, with the precision the presence of seconds implies.
fn parse_clock(clock: &str) -> Option<(i8, i8, i8, DatePrecision)> {
    let mut parts = clock.split(':');
    let hour: i8 = parts.next()?.parse().ok()?;
    let minute: i8 = parts.next()?.parse().ok()?;
    let (second, precision) = match parts.next() {
        Some(text) => (text.parse().ok()?, DatePrecision::Second),
        None => (0, DatePrecision::Minute),
    };
    if parts.next().is_some() {
        return None;
    }
    Some((hour, minute, second, precision))
}

/// `±HHMM`, or one of the North American zone abbreviations the obsolete grammar allows, as the one
/// RFC 3339 spelling. Two identical instants written differently have to land on the same value or
/// a range query over the index misses half its own corpus.
fn zone_offset(zone: &str) -> Option<String> {
    let named = match zone {
        "UT" | "GMT" => Some("Z"),
        "EST" => Some("-05:00"),
        "EDT" => Some("-04:00"),
        "CST" => Some("-06:00"),
        "CDT" => Some("-05:00"),
        "MST" => Some("-07:00"),
        "MDT" => Some("-06:00"),
        "PST" => Some("-08:00"),
        "PDT" => Some("-07:00"),
        _ => None,
    };
    if let Some(named) = named {
        return Some(named.to_string());
    }

    let sign = zone.chars().next()?;
    if sign != '+' && sign != '-' {
        return None;
    }
    let digits = zone.get(1..)?;
    if digits.len() != 4 || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    let hours: u8 = digits[0..2].parse().ok()?;
    let minutes: u8 = digits[2..4].parse().ok()?;
    if hours > 18 || minutes > 59 {
        return None;
    }
    if hours == 0 && minutes == 0 {
        return Some("Z".to_string());
    }
    Some(format!("{sign}{hours:02}:{minutes:02}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The month names the validator accepts are the ones both patterns spell out; if the two ever
    /// diverge, the prefilter finds a month the validator then rejects.
    #[test]
    fn both_patterns_spell_every_month_the_validator_knows() {
        for month in MONTHS {
            assert!(RFC2822_PATTERN.contains(month), "{month}");
            assert!(CLF_PATTERN.contains(month), "{month}");
            assert!(month_number(month).is_some());
        }
    }

    #[test]
    fn zone_abbreviations_normalise_to_offsets() {
        assert_eq!(zone_offset("+0200").as_deref(), Some("+02:00"));
        assert_eq!(zone_offset("-0000").as_deref(), Some("Z"));
        assert_eq!(zone_offset("GMT").as_deref(), Some("Z"));
        assert_eq!(zone_offset("PST").as_deref(), Some("-08:00"));
        assert_eq!(zone_offset("+2500"), None);
    }
}
