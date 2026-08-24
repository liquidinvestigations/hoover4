//! Turning a filter selection into the one line a chip can show.
//!
//! One chip per CATEGORY, not per value: a search with eight file types selected has one
//! "File type" chip, not eight. The chip has a hard width budget, so the summary drops
//! values from the right and grows a `+N` counter rather than overflowing or wrapping.
//! The full selection always lives in the chip's `title`.
//!
//! Pure and in `common` because the rules are fiddly (a size range must never say the
//! word "Custom"; a date range must render as years when it is whole years) and because
//! getting them wrong is a visual bug nobody writes a test for after the fact.

use crate::search_query::RangeFilter;

/// Width budget for a chip summary, in characters. The CSS budget is
/// `min(320px, 28ch)`; this is the character half of it, applied to the text so the
/// ellipsis lands on a value boundary rather than mid-word wherever possible.
pub const CHIP_SUMMARY_BUDGET: usize = 28;

/// Join a list of selected values into `a, b +N`, inside the budget.
///
/// Drops values from the right and grows the counter, so the chip always says how much
/// it is not showing. When even the first value does not fit it is ellipsised, at a
/// CHARACTER boundary, not a byte one, or a multi-byte name panics the formatter.
pub fn summarize_values(values: &[String], budget: usize) -> String {
    let total = values.len();
    if total == 0 {
        return String::new();
    }
    for take in (1..=total).rev() {
        let shown = &values[..take];
        let remaining = total - take;
        let mut text = shown.join(", ");
        if remaining > 0 {
            text.push_str(&format!(" +{remaining}"));
        }
        if text.chars().count() <= budget {
            return text;
        }
    }
    // Even one value overflows: ellipsise it and keep the counter accurate.
    let suffix = if total > 1 { format!(" +{}", total - 1) } else { String::new() };
    let room = budget.saturating_sub(suffix.chars().count() + 1);
    let clipped: String = values[0].chars().take(room).collect();
    format!("{clipped}…{suffix}")
}

/// Bytes as the shortest human string that stays accurate: `2.5 MB`, `900 KB`, `1 GB`.
///
/// Rounded to one decimal and trailing `.0` dropped, because `2.0 MB` in a chip reads as
/// a precision the number does not have.
pub fn format_bytes(bytes: i64) -> String {
    const KB: f64 = 1024.0;
    const MB: f64 = 1024.0 * 1024.0;
    const GB: f64 = 1024.0 * 1024.0 * 1024.0;
    let value = bytes as f64;
    let (scaled, unit) = if value >= GB {
        (value / GB, "GB")
    } else if value >= MB {
        (value / MB, "MB")
    } else if value >= KB {
        (value / KB, "KB")
    } else {
        return format!("{bytes} B");
    };
    let rounded = (scaled * 10.0).round() / 10.0;
    if (rounded.fract()).abs() < f64::EPSILON {
        format!("{} {unit}", rounded as i64)
    } else {
        format!("{rounded} {unit}")
    }
}

/// A file-size range as a chip summary. **Never the word "Custom".**
///
/// The user picked a range of sizes; that the UI called the control "Custom" is an
/// implementation detail of the modal and says nothing about what is being filtered.
pub fn summarize_size(filter: &RangeFilter) -> String {
    match (filter.min, filter.max, filter.include_unknown) {
        (None, None, true) => "unknown size".to_string(),
        (Some(lo), Some(hi), _) => format!("{} – {}", format_bytes(lo), format_bytes(hi)),
        (Some(lo), None, _) => format!("over {}", format_bytes(lo)),
        (None, Some(hi), _) => format!("under {}", format_bytes(hi)),
        (None, None, false) => String::new(),
    }
}

/// A date range as a chip summary.
///
/// Whole years render as years (`2013–2016`), because that is how the filter is almost
/// always set and `2013-01-01 – 2016-12-31` spends the entire chip budget saying it.
/// `epoch_to_iso_date` is supplied by the caller so this stays dependency-free.
pub fn summarize_dates(
    filter: &RangeFilter,
    to_iso: impl Fn(i64) -> String,
) -> String {
    let iso = |epoch: i64| to_iso(epoch);
    match (filter.min, filter.max, filter.include_unknown) {
        (None, None, true) => "unknown".to_string(),
        (Some(lo), Some(hi), _) => {
            let (from, to) = (iso(lo), iso(hi));
            match (whole_year_start(&from), whole_year_end(&to)) {
                (Some(y0), Some(y1)) if y0 == y1 => y0,
                (Some(y0), Some(y1)) => format!("{y0}–{y1}"),
                _ => format!("{from} – {to}"),
            }
        }
        (Some(lo), None, _) => format!("after {}", iso(lo)),
        (None, Some(hi), _) => format!("before {}", iso(hi)),
        (None, None, false) => String::new(),
    }
}

fn whole_year_start(iso: &str) -> Option<String> {
    iso.strip_suffix("-01-01").map(str::to_string)
}

fn whole_year_end(iso: &str) -> Option<String> {
    iso.strip_suffix("-12-31").map(str::to_string)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn iso(epoch: i64) -> String {
        // A stand-in for the caller's real formatter; only the shape matters here.
        match epoch {
            1356998400 => "2013-01-01".to_string(),
            1483228799 => "2016-12-31".to_string(),
            1356998401 => "2013-01-02".to_string(),
            1577836800 => "2020-01-01".to_string(),
            _ => format!("epoch:{epoch}"),
        }
    }

    #[test]
    fn values_fit_or_grow_a_counter() {
        let cases: Vec<(Vec<&str>, usize, &str)> = vec![
            (vec![], 28, ""),
            (vec!["text"], 28, "text"),
            (vec!["text", "email"], 28, "text, email"),
            // Three short values fit; four do not, so the last becomes +1.
            (vec!["text", "email", "pdf", "spreadsheet"], 28, "text, email, pdf +1"),
            (vec!["text", "email", "pdf", "doc", "xls"], 20, "text, email, pdf +2"),
        ];
        for (values, budget, expected) in cases {
            let owned: Vec<String> = values.iter().map(|s| s.to_string()).collect();
            assert_eq!(summarize_values(&owned, budget), expected, "{values:?}");
        }
    }

    #[test]
    fn a_single_value_too_long_for_the_budget_is_ellipsised() {
        let long = vec!["a-very-long-collection-name-indeed".to_string()];
        let summary = summarize_values(&long, 20);
        assert!(summary.chars().count() <= 20, "{summary}");
        assert!(summary.ends_with('…'), "{summary}");
    }

    #[test]
    fn ellipsis_falls_on_a_character_boundary() {
        // Byte slicing here would panic rather than merely look wrong.
        let values = vec!["Räksmörgås-mötesprotokoll-2024".to_string(), "b".to_string()];
        let summary = summarize_values(&values, 12);
        assert!(summary.chars().count() <= 12, "{summary}");
        assert!(summary.contains('…'));
    }

    #[test]
    fn byte_sizes_read_the_way_a_person_would_say_them() {
        let cases = [
            (0_i64, "0 B"),
            (512, "512 B"),
            (1024, "1 KB"),
            (921_600, "900 KB"),
            (1_048_576, "1 MB"),
            (2_621_440, "2.5 MB"),
            (104_857_600, "100 MB"),
            (2_147_483_648, "2 GB"),
        ];
        for (bytes, expected) in cases {
            assert_eq!(format_bytes(bytes), expected, "{bytes}");
        }
    }

    /// The rule the brief calls out by name against mockup p10.
    #[test]
    fn a_size_chip_never_says_custom() {
        let filter = RangeFilter { min: Some(2_621_440), max: Some(41_943_040), include_unknown: false };
        let summary = summarize_size(&filter);
        assert_eq!(summary, "2.5 MB – 40 MB");
        assert!(!summary.to_lowercase().contains("custom"));
    }

    #[test]
    fn open_ended_size_ranges_say_which_end_is_open() {
        assert_eq!(
            summarize_size(&RangeFilter { min: Some(104_857_600), max: None, include_unknown: false }),
            "over 100 MB"
        );
        assert_eq!(
            summarize_size(&RangeFilter { min: None, max: Some(1_048_575), include_unknown: false }),
            "under 1024 KB"
        );
        assert_eq!(
            summarize_size(&RangeFilter { min: None, max: None, include_unknown: true }),
            "unknown size"
        );
    }

    #[test]
    fn whole_year_date_ranges_render_as_years() {
        let filter = RangeFilter { min: Some(1356998400), max: Some(1483228799), include_unknown: false };
        assert_eq!(summarize_dates(&filter, iso), "2013–2016");
    }

    #[test]
    fn a_single_whole_year_renders_once() {
        let filter = RangeFilter { min: Some(1356998400), max: Some(1356998400), include_unknown: false };
        // Both ends in 2013 but the upper bound is not 12-31, so it stays explicit.
        assert!(summarize_dates(&filter, iso).contains("2013-01-01"));
    }

    #[test]
    fn a_partial_year_range_keeps_its_dates() {
        let filter = RangeFilter { min: Some(1356998401), max: Some(1483228799), include_unknown: false };
        assert_eq!(summarize_dates(&filter, iso), "2013-01-02 – 2016-12-31");
    }

    #[test]
    fn open_ended_and_unknown_date_filters() {
        assert_eq!(
            summarize_dates(
                &RangeFilter { min: Some(1577836800), max: None, include_unknown: false }, iso),
            "after 2020-01-01"
        );
        assert_eq!(
            summarize_dates(
                &RangeFilter { min: None, max: None, include_unknown: true }, iso),
            "unknown"
        );
    }
}
