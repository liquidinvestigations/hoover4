//! The date histogram drawn under the Date filter pane.
//!
//! Bins are computed per query rather than fixed, so both edges travel on the wire: the
//! client draws bars, decides which of them the current cutoffs cover, and turns a click
//! into a filter using the very same numbers the server binned with. Sending only a label
//! would make the click round-trip through a string, and a bar whose filter does not
//! match the bar is worse than no interaction at all.

use serde::{Deserialize, Serialize};

/// One bin, `[start, end)` in signed epoch seconds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DateHistogramBucket {
    pub start: i64,
    /// Exclusive.
    pub end: i64,
    pub count: u64,
}

impl DateHistogramBucket {
    /// Whether a low-pass/high-pass/band-pass `[min, max]` covers this bin.
    ///
    /// The bin is covered when it lies wholly inside the filter. A bin only partly
    /// covered reads as unselected, which is honest: the filter's cutoffs are bin edges
    /// by construction, so a partly covered bin means the cutoff came from somewhere
    /// else, such as a typed date, or a histogram computed before the last edit.
    pub fn is_covered(&self, min: Option<i64>, max: Option<i64>) -> bool {
        min.is_none_or(|lo| self.start >= lo) && max.is_none_or(|hi| self.end - 1 <= hi)
    }
}

/// Counts per computed bin over the query WITHOUT its own date filter, plus the undated.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct DateHistogram {
    pub buckets: Vec<DateHistogramBucket>,
    /// Documents in the same filtered set with no confirmed date at all. Not a bin: it
    /// has no position on a time axis, and drawing it as one would put "we do not know"
    /// somewhere specific.
    pub unknown_count: u64,
    /// The measured extent of the dated documents, `[start, end)`. Both zero when there
    /// are no dated documents.
    pub domain_start: i64,
    pub domain_end: i64,
    /// At least one shard could not be searched, so every count here is a lower bound.
    #[serde(default)]
    pub partial: bool,
    /// The bars count MENTIONS rather than documents.
    ///
    /// A document naming three days inside one bin contributes three to it. The two
    /// histograms this type serves answer different questions -- a document's own dates
    /// are an interval it occupies, the dates it mentions are points -- and a reader
    /// comparing the two axes without knowing which is which reads one of them wrong.
    /// The pane labels its axis from this flag.
    #[serde(default)]
    pub counts_mentions: bool,
}

impl DateHistogram {
    pub fn is_empty(&self) -> bool {
        self.buckets.is_empty()
    }

    /// The tallest bin, for scaling the bars. Never zero, so it is safe to divide by.
    pub fn max_count(&self) -> u64 {
        self.buckets.iter().map(|b| b.count).max().unwrap_or(0).max(1)
    }

    pub fn total_count(&self) -> u64 {
        self.buckets.iter().map(|b| b.count).sum()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bucket(start: i64, end: i64) -> DateHistogramBucket {
        DateHistogramBucket { start, end, count: 0 }
    }

    #[test]
    fn an_unfiltered_histogram_covers_nothing_and_everything() {
        // No cutoffs at all means no selection to draw, so every bin is "covered",
        // which is exactly right: the whole axis is in scope.
        assert!(bucket(0, 10).is_covered(None, None));
    }

    #[test]
    fn a_low_pass_covers_the_bins_below_the_cutoff() {
        // "before 100", with bins tiling [0,200) at width 100.
        assert!(bucket(0, 100).is_covered(None, Some(99)));
        assert!(!bucket(100, 200).is_covered(None, Some(99)));
    }

    #[test]
    fn a_high_pass_covers_the_bins_above_the_cutoff() {
        assert!(bucket(100, 200).is_covered(Some(100), None));
        assert!(!bucket(0, 100).is_covered(Some(100), None));
    }

    #[test]
    fn a_band_pass_covers_only_the_bins_wholly_inside_it() {
        let (lo, hi) = (100, 299);
        assert!(bucket(100, 200).is_covered(Some(lo), Some(hi)));
        assert!(bucket(200, 300).is_covered(Some(lo), Some(hi)));
        assert!(!bucket(0, 100).is_covered(Some(lo), Some(hi)));
        assert!(!bucket(300, 400).is_covered(Some(lo), Some(hi)));
        // A bin straddling a cutoff is not covered.
        assert!(!bucket(50, 150).is_covered(Some(lo), Some(hi)));
    }

    #[test]
    fn max_count_never_divides_by_zero() {
        let empty = DateHistogram::default();
        assert_eq!(empty.max_count(), 1);
        assert!(empty.is_empty());

        let histogram = DateHistogram {
            buckets: vec![
                DateHistogramBucket { start: 0, end: 10, count: 3 },
                DateHistogramBucket { start: 10, end: 20, count: 7 },
            ],
            ..DateHistogram::default()
        };
        assert_eq!(histogram.max_count(), 7);
        assert_eq!(histogram.total_count(), 10);
    }
}
