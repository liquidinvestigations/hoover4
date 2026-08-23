//! ISO 8601 / RFC 3339 rule: calendar validity, offset canonicalisation, and the guards that keep
//! identifiers out of the date facet.

mod support;

use regex_entity_scanner::model::{DatePrecision, EntityType, Flag, Value};

fn date_value(text: &str) -> (String, DatePrecision, bool) {
    let scanner = support::scanner();
    let entities = scanner.scan(text, 0);
    assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
    assert_eq!(entities[0].entity_type, EntityType::Date);
    match &entities[0].value {
        Value::Date {
            rfc3339,
            precision,
            tz_known,
        } => (rfc3339.clone(), *precision, *tz_known),
        other => panic!("expected a date value, got {other:?}"),
    }
}

#[test]
fn a_bare_date_carries_day_precision_and_no_zone() {
    let (rfc3339, precision, tz_known) = date_value("filed 2021-03-04 in Bucharest");
    assert_eq!(rfc3339, "2021-03-04");
    assert_eq!(precision, DatePrecision::Day);
    assert!(!tz_known);
}

/// Two spellings of the same instant have to land on the same value, or a range query over the
/// index silently misses half of its own corpus.
#[test]
fn offsets_canonicalise_to_one_spelling() {
    for text in ["2021-03-04T09:12:00+0200", "2021-03-04T09:12:00+02:00"] {
        let (rfc3339, precision, tz_known) = date_value(text);
        assert_eq!(rfc3339, "2021-03-04T09:12:00+02:00");
        assert_eq!(precision, DatePrecision::Second);
        assert!(tz_known);
    }
    let (rfc3339, _, tz_known) = date_value("2021-03-04t09:12:00z");
    assert_eq!(rfc3339, "2021-03-04T09:12:00Z");
    assert!(tz_known);
}

#[test]
fn a_zoneless_timestamp_says_so() {
    let scanner = support::scanner();
    let entities = scanner.scan("2021-03-04 09:12", 0);
    assert_eq!(entities.len(), 1);
    assert!(entities[0].flags.contains(&Flag::NoTimezone));
}

/// The pattern cannot know that February has 28 days. The validator can, which is why the check
/// belongs there and not in a cleverer pattern.
#[test]
fn rejects_dates_the_calendar_does_not_have() {
    let scanner = support::scanner();
    for text in [
        "2021-02-30",
        "2021-13-01",
        "2021-00-10",
        "2021-03-04T25:00:00Z",
    ] {
        let entities = scanner.scan(text, 0);
        assert!(
            entities.iter().all(|e| e.text != text),
            "{text:?} produced {entities:?}"
        );
    }
}

/// A date wedged inside a longer digit run is part of that run, not a date. This is the stripped
/// lookaround being re-imposed in the validator.
#[test]
fn rejects_dates_embedded_in_longer_numbers() {
    let scanner = support::scanner();
    for text in ["ref 992021-03-0412", "id=2021-03-041"] {
        let entities = scanner.scan(text, 0);
        assert!(entities.is_empty(), "{text:?} produced {entities:?}");
    }
}

#[test]
fn rejects_years_outside_the_plausible_window() {
    let scanner = support::scanner();
    let entities = scanner.scan("version 0001-02-03 of the schema", 0);
    assert!(entities.is_empty(), "{entities:?}");
}

/// Within one type the longer, more completely parsed match wins: a full timestamp is not also a
/// bare date.
#[test]
fn a_timestamp_is_emitted_once() {
    let scanner = support::scanner();
    let entities = scanner.scan("2021-03-04T09:12:00Z", 0);
    assert_eq!(entities.len(), 1);
    assert_eq!(entities[0].text, "2021-03-04T09:12:00Z");
}

/// A rejected candidate is not the end of the story. The prefilter takes the longest match, so an
/// impossible clock swallows the perfectly good date in front of it; the scan loop looks inside the
/// rejection and the day survives.
#[test]
fn an_impossible_clock_leaves_the_date_inside_it() {
    let scanner = support::scanner();
    let entities = scanner.scan("logged 2021-03-04T25:00:00Z then 2021-03-05", 0);

    let texts: Vec<&str> = entities.iter().map(|e| e.text.as_str()).collect();
    assert_eq!(texts, ["2021-03-04", "2021-03-05"], "{entities:?}");
}

/// The recovery is bounded, and it does not turn a guard into a suggestion: a date wedged in a
/// longer digit run stays rejected however many times the window is shrunk, because the validator
/// still sees the whole fragment and the real neighbouring bytes.
#[test]
fn shrinking_a_candidate_does_not_defeat_the_adjacent_digit_guard() {
    let scanner = support::scanner();
    let entities = scanner.scan("ref 992021-03-0412 recorded", 0);
    assert!(entities.is_empty(), "{entities:?}");
}

/// Two timestamps run together carry no boundary, so neither of them is reported. The failure
/// comes from the retry: the whole run is refused for the digit behind it, and the window then shrinks to a span
/// that ends at a field boundary. A real-looking instant with its offset amputated, which is a
/// wrong value rather than a miss.
#[test]
fn a_timestamp_is_never_carved_out_of_a_longer_one() {
    let scanner = support::scanner();
    let entities = scanner.scan("2015-03-17t16:37:51+00:002015-03-17t15:24:37+00:00", 0);
    assert!(entities.is_empty(), "{entities:?}");
}

/// The weekday is the strong half of a mail header date: a header whose day of the week disagrees
/// with its calendar date has been mangled or invented.
#[test]
fn a_mail_header_date_needs_a_consistent_weekday() {
    let (rfc3339, precision, tz_known) =
        date_value("Date: Thu, 04 Mar 2021 09:12:00 +0200\r\nFrom: ops");
    assert_eq!(rfc3339, "2021-03-04T09:12:00+02:00");
    assert_eq!(precision, DatePrecision::Second);
    assert!(tz_known);

    let scanner = support::scanner();
    let entities = scanner.scan("Date: Tue, 04 Mar 2021 09:12:00 +0200", 0);
    assert!(entities.is_empty(), "{entities:?}");
}

/// The obsolete zone abbreviations are still emitted by real mail software, and two spellings of
/// the same instant have to land on one value.
#[test]
fn obsolete_zone_abbreviations_normalise() {
    let (rfc3339, ..) = date_value("Sent Thu, 04 Mar 2021 09:12:00 GMT by the gateway");
    assert_eq!(rfc3339, "2021-03-04T09:12:00Z");
    let (rfc3339, ..) = date_value("Sent Thu, 04 Mar 2021 09:12:00 PST by the gateway");
    assert_eq!(rfc3339, "2021-03-04T09:12:00-08:00");
}

/// The brackets make the log timestamp self-identifying, and they are not part of the date the
/// reader sees highlighted.
#[test]
fn a_log_timestamp_reports_the_span_inside_its_brackets() {
    let scanner = support::scanner();
    let entities = scanner.scan(
        r#"10.0.0.4 - - [04/Mar/2021:09:12:00 +0200] "GET / HTTP/1.1" 200"#,
        0,
    );
    // The line also carries the client address, which is a second entity rather than a rival
    // reading of the same span.
    assert_eq!(entities.len(), 2, "{entities:?}");
    let date = entities
        .iter()
        .find(|entity| entity.rule_id == "date.clf")
        .expect("the log timestamp");
    assert_eq!(date.text, "04/Mar/2021:09:12:00 +0200");
    match &date.value {
        Value::Date { rfc3339, .. } => assert_eq!(rfc3339, "2021-03-04T09:12:00+02:00"),
        other => panic!("expected a date value, got {other:?}"),
    }
}

/// Week 53 exists only in the years that have one, which is the arithmetic that makes an ISO week
/// date a checked format rather than a shape.
#[test]
fn iso_week_dates_resolve_to_a_calendar_day() {
    let (rfc3339, precision, tz_known) = date_value("run 2021-W09-4 of the batch");
    assert_eq!(rfc3339, "2021-03-04");
    assert_eq!(precision, DatePrecision::Day);
    assert!(!tz_known);

    let (rfc3339, ..) = date_value("run 2021W094 of the batch");
    assert_eq!(rfc3339, "2021-03-04");

    let scanner = support::scanner();
    for text in ["batch 2021-W53-1", "batch 2021-W09-8", "batch 2021-W00-1"] {
        let entities = scanner.scan(text, 0);
        assert!(entities.is_empty(), "{text:?} produced {entities:?}");
    }
}

/// A date rule emits nothing unless the match fixes year, month and day. A week without a weekday
/// names a week, and a syslog line names no year at all.
#[test]
fn formats_that_do_not_fix_a_whole_day_are_not_matched() {
    let scanner = support::scanner();
    for text in ["reported in 2021-W09", "Mar  4 09:12:00 host sshd[1]: ok"] {
        let entities = scanner.scan(text, 0);
        assert!(entities.is_empty(), "{text:?} produced {entities:?}");
    }
}

/// The ISO week date's whole claim is that week 53 exists only in the years that have one, and no
/// public corpus carries a week date at all, so this sweep is the rule's evidence rather than a
/// sample of it. It is exhaustive over eight chosen years: 2004, 2009, 2015, 2020 and 2026, which
/// are the long years of this century's first three decades, and 2021, 2022 and 2023, which are
/// short. Every week from 1 to 53 and every weekday from 1 to 7 is scanned in both ISO spellings,
/// and each is compared against week-date arithmetic worked out here rather than against the
/// library the rule uses, an oracle that shares the implementation proves nothing.
#[test]
fn every_week_of_a_long_and_a_short_year_resolves_or_is_refused() {
    let scanner = support::scanner();
    let mut accepted = 0usize;
    let mut refused = 0usize;

    for year in [2004, 2009, 2015, 2020, 2026, 2021, 2022, 2023] {
        let weeks = iso_weeks_in_year(year);
        assert_eq!(
            weeks == 53,
            [2004, 2009, 2015, 2020, 2026].contains(&year),
            "{year} is a {weeks}-week year"
        );

        for week in 1..=53 {
            for weekday in 1..=7 {
                let expected = (week <= weeks).then(|| iso_week_date_to_civil(year, week, weekday));
                for text in [
                    format!("batch {year}-W{week:02}-{weekday}"),
                    format!("batch {year}W{week:02}{weekday}"),
                ] {
                    let entities = scanner.scan(&text, 0);
                    match &expected {
                        Some(day) => {
                            assert_eq!(entities.len(), 1, "{text:?} produced {entities:?}");
                            match &entities[0].value {
                                Value::Date { rfc3339, .. } => {
                                    assert_eq!(rfc3339, day, "{text:?}");
                                }
                                other => panic!("expected a date value, got {other:?}"),
                            }
                            accepted += 1;
                        }
                        None => {
                            assert!(entities.is_empty(), "{text:?} produced {entities:?}");
                            refused += 1;
                        }
                    }
                }
            }
        }
    }

    // Five long years and three short ones: (5 × 53 + 3 × 52) × 7 weekdays × 2 spellings.
    assert_eq!(accepted, (5 * 53 + 3 * 52) * 7 * 2);
    assert_eq!(refused, 3 * 7 * 2);

    // The fields either side of the range, in both spellings.
    for text in [
        "batch 2021-W00-1",
        "batch 2021-W54-1",
        "batch 2021-W09-0",
        "batch 2021-W09-8",
        "batch 2021W001",
        "batch 2021W541",
        "batch 2021W090",
        "batch 2021W098",
    ] {
        let entities = scanner.scan(text, 0);
        assert!(entities.is_empty(), "{text:?} produced {entities:?}");
    }
}

/// How many ISO weeks a year has: 53 when 1 January or 31 December falls on a Thursday, 52
/// otherwise.
fn iso_weeks_in_year(year: i64) -> i64 {
    if iso_weekday(year, 1, 1) == 4 || iso_weekday(year, 12, 31) == 4 {
        53
    } else {
        52
    }
}

/// The calendar day an ISO week date names, as an RFC 3339 date. Week 1 is the week holding
/// 4 January, so its Monday is that date pulled back to the start of its own week.
fn iso_week_date_to_civil(year: i64, week: i64, weekday: i64) -> String {
    let january_fourth = days_from_civil(year, 1, 4);
    let first_monday = january_fourth - (iso_weekday(year, 1, 4) - 1);
    let (y, m, d) = civil_from_days(first_monday + (week - 1) * 7 + (weekday - 1));
    format!("{y:04}-{m:02}-{d:02}")
}

/// The ISO weekday, 1 for Monday: the epoch day 1970-01-01 was a Thursday.
fn iso_weekday(year: i64, month: i64, day: i64) -> i64 {
    (days_from_civil(year, month, day) + 3).rem_euclid(7) + 1
}

/// Days from 1970-01-01 to a proleptic Gregorian date, by the era arithmetic that avoids any
/// table of month lengths.
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = if year >= 0 { year } else { year - 399 } / 400;
    let year_of_era = year - era * 400;
    let shifted = if month > 2 { month - 3 } else { month + 9 };
    let day_of_year = (153 * shifted + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

/// The inverse of [`days_from_civil`].
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let shifted = days + 719_468;
    let era = if shifted >= 0 {
        shifted
    } else {
        shifted - 146_096
    } / 146_097;
    let day_of_era = shifted - era * 146_097;
    let year_of_era =
        (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let shifted_month = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * shifted_month + 2) / 5 + 1;
    let month = if shifted_month < 10 {
        shifted_month + 3
    } else {
        shifted_month - 9
    };
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    (year, month, day)
}
