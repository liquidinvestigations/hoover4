//! The date histogram behind the Date filter pane.
//!
//! Different from a plain range facet, [`super::search_numeric_facet`], which is what
//! the deleted per-year date facet was, in three ways that all matter:
//!
//! * **The bins are computed, not fixed.** A per-year facet is unreadable for a corpus
//!   spanning a week and useless for one spanning four centuries. The domain is measured
//!   first and the bin width is chosen from it.
//! * **The active cutoffs are bin edges.** The pane filters with a low-pass, a high-pass
//!   or a band-pass, and the three resulting intervals (below the low cutoff, between
//!   the cutoffs, above the high one) each get their own run of bins at a similar width.
//!   A bin that straddles a cutoff would show half of itself as selected, which is a
//!   picture of nothing.
//! * **It counts the query WITHOUT its own date filter.** The bars are the corpus the
//!   rest of the query narrows to; the selection is drawn on top of them. A histogram
//!   that filtered itself would be one solid block inside the cutoffs and zero outside.
//!
//! Manticore does the aggregation with the same `INTERVAL()` + `GROUP BY` shape the size
//! facet uses, just with up to thirty edges instead of three. There is no histogram or
//! date-bucketing function in Manticore 14.1.0 to use instead, and `date_min` is a signed
//! `bigint` rather than a `timestamp` precisely because the timestamp type is 32-bit
//! unsigned and cannot hold a 1936 date at all.

use crate::api::search::fanout::{self, FanoutTarget};
use crate::api::search::search_sql::sql_options_clause;
use crate::auth::permissions;
use crate::db_utils::manticore_utils::manticore_search_sql;
use common::{
    current_user::CurrentUser,
    date_histogram::{DateHistogram, DateHistogramBucket},
    search_query::{DATE_UNKNOWN, SearchQuery},
};
use serde::{Deserialize, Serialize};

/// Bins aimed for. The upper bound is the one that is enforced; the target is what the
/// width is derived from.
pub const HISTOGRAM_TARGET_BUCKETS: usize = 24;
pub const HISTOGRAM_MAX_BUCKETS: usize = 30;

const DAY: i64 = 86_400;

/// Bin widths in seconds, smallest first, each one a duration a person names.
///
/// Widths are picked off this ladder rather than computed as `span / 24` so that the
/// axis reads in hours, days, months and years instead of "every 4 days 7 hours". The
/// ladder's step ratio is what bounds how far below [`HISTOGRAM_TARGET_BUCKETS`] the
/// result can land. See `the_bin_count_stays_inside_the_band`.
const WIDTH_LADDER: [i64; 22] = [
    3_600,             // 1 hour
    3 * 3_600,         // 3 hours
    6 * 3_600,         // 6 hours
    12 * 3_600,        // 12 hours
    DAY,               // 1 day
    2 * DAY,           // 2 days
    7 * DAY,           // 1 week
    14 * DAY,          // 2 weeks
    30 * DAY,          // 1 month
    61 * DAY,          // 2 months
    91 * DAY,          // 1 quarter
    182 * DAY,         // 6 months
    365 * DAY,         // 1 year
    2 * 365 * DAY,     // 2 years
    5 * 365 * DAY,     // 5 years
    10 * 365 * DAY,    // 1 decade
    20 * 365 * DAY,    // 2 decades
    50 * 365 * DAY,    // half a century
    100 * 365 * DAY,   // 1 century
    250 * 365 * DAY,   //
    500 * 365 * DAY,   //
    1000 * 365 * DAY,  // 1 millennium, `dates` is a signed bigint, so this is reachable
];

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
struct BucketRow {
    bucket: i64,
    doc_count: u64,
}

/// The measured extent of the dated documents, `[start, end)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DateDomain {
    pub start: i64,
    /// Exclusive. One second past the latest date, so every document falls strictly
    /// inside `[start, end)` and the edge list can tile the domain with no bucket
    /// hanging off either side.
    pub end: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
struct BoundRow {
    bound: i64,
}

/// Document counts per computed date bin, plus the undated count.
///
/// The cutoffs come from the query's own `dates` filter (the caller passes the query it
/// is about to run, cutoffs and all), and are then stripped before counting.
pub async fn search_date_histogram(
    user: &CurrentUser,
    query: SearchQuery,
) -> anyhow::Result<DateHistogram> {
    crate::api::telemetry::record_event(
        &user.username,
        crate::api::telemetry::EVENT_USER_SEARCH,
        "",
    );
    let perms = permissions::resolve_permissions(user).await?;
    let Some(mut query) = permissions::sanitize_query(query, &perms) else {
        return Ok(DateHistogram::default());
    };
    // Read the cutoffs before removing the filter they live in: they place the bin edges,
    // they must not narrow what is counted.
    let cuts = query
        .range_filters
        .get("dates")
        .map(|filter| [filter.min, filter.max])
        .unwrap_or([None, None]);
    query.range_filters.remove("dates");

    let collections = fanout::permitted_search_collections(user, &query).await?;
    let targets = fanout::shard_targets(&collections).await;
    if targets.is_empty() {
        return Ok(DateHistogram::default());
    }

    let (domain, unknown_count, probe_partial) = probe_domain(&query, targets.clone()).await?;
    let Some(domain) = domain else {
        // Every matching document is undated. There is nothing to bin, and saying so is
        // more useful than an axis over an invented range.
        return Ok(DateHistogram {
            unknown_count,
            partial: probe_partial,
            ..DateHistogram::default()
        });
    };

    let edges = histogram_edges(domain, &cuts);
    let counts = count_buckets(&query, targets, &edges).await?;

    let buckets = edges
        .windows(2)
        .enumerate()
        .map(|(index, pair)| DateHistogramBucket {
            start: pair[0],
            end: pair[1],
            // `INTERVAL(x, e0, e1, …)` returns 0 for `x < e0`, so the bin between `e0`
            // and `e1` is index 1, not 0. Off by one here is a histogram shifted by one
            // bar, which looks plausible and is wrong.
            count: counts.totals.get(index + 1).copied().unwrap_or(0),
        })
        .collect();

    Ok(DateHistogram {
        buckets,
        unknown_count,
        domain_start: domain.start,
        domain_end: domain.end,
        partial: probe_partial || counts.partial,
        // These bars are document counts. The mentioned-date histogram is the one that
        // counts mentions, and the flag is how the pane tells them apart.
        counts_mentions: false,
    })
}

/// The extent of the dated documents and the count of the undated ones.
///
/// `min()`/`max()` without a `GROUP BY` is not a query shape this codebase has ever got
/// an answer out of Manticore for, so the bounds come from `ORDER BY … LIMIT 1` instead.
/// The same ordering the result list already sorts by, so it is known to work and known
/// to use the attribute index.
async fn probe_domain(
    query: &SearchQuery,
    targets: Vec<FanoutTarget>,
) -> anyhow::Result<(Option<DateDomain>, u64, bool)> {
    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let where_clause = &parts.where_clause;
            let options_clause = sql_options_clause(1000);
            let bound = |direction: &str| {
                format!(
                    "
                    SELECT date_min AS bound
                    {from_clause}
                    {where_clause}
                    AND date_min != {DATE_UNKNOWN}
                    GROUP BY bound
                    ORDER BY bound {direction}
                    LIMIT 1
                    {options_clause}
                    ;"
                )
            };
            // The upper bound is over `date_max`: a document created in 2007 and last
            // modified in 2020 extends the domain to 2020, and an axis that stopped at
            // 2007 would leave its own bar off the end.
            let upper = format!(
                "
                SELECT date_max AS bound
                {from_clause}
                {where_clause}
                AND date_min != {DATE_UNKNOWN}
                GROUP BY bound
                ORDER BY bound DESC
                LIMIT 1
                {options_clause}
                ;"
            );
            let unknown = format!(
                "
                SELECT count(distinct file_hash) AS doc_count, 0 AS bucket
                {from_clause}
                {where_clause}
                AND date_min = {DATE_UNKNOWN}
                {options_clause}
                ;"
            );
            let low = manticore_search_sql::<BoundRow>(bound("ASC"), &parts.salt).await?;
            let high = manticore_search_sql::<BoundRow>(upper, &parts.salt).await?;
            let undated = manticore_search_sql::<BucketRow>(unknown, &parts.salt).await?;
            Ok((low, high, undated))
        }
    })
    .await?;

    let partial = outcome.is_partial();
    let mut start: Option<i64> = None;
    let mut end: Option<i64> = None;
    let mut unknown_count = 0_u64;
    for (_, (low, high, undated)) in outcome.results {
        if let Some(hit) = low.hits.hits.first() {
            start = Some(start.map_or(hit._source.bound, |v: i64| v.min(hit._source.bound)));
        }
        if let Some(hit) = high.hits.hits.first() {
            end = Some(end.map_or(hit._source.bound, |v: i64| v.max(hit._source.bound)));
        }
        // An aggregate over an empty match still returns one row, with count 0. See
        // `docs/architecture/Search_Architecture.md`. Summing it is correct; assuming a row
        // means a hit is not.
        unknown_count += undated.hits.hits.first().map_or(0, |h| h._source.doc_count);
    }

    let domain = match (start, end) {
        (Some(start), Some(end)) => Some(DateDomain {
            start,
            // Exclusive, and never equal to `start`: a corpus of one document would
            // otherwise have a zero-width domain and no bins at all.
            end: end.max(start).saturating_add(1),
        }),
        _ => None,
    };
    Ok((domain, unknown_count, partial))
}

struct BucketCounts {
    /// Indexed by `INTERVAL()` result, so index 0 is "below the first edge".
    totals: Vec<u64>,
    partial: bool,
}

async fn count_buckets(
    query: &SearchQuery,
    targets: Vec<FanoutTarget>,
    edges: &[i64],
) -> anyhow::Result<BucketCounts> {
    let edge_list = edges.iter().map(|e| e.to_string()).collect::<Vec<_>>().join(",");
    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        let edge_list = edge_list.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let where_clause = &parts.where_clause;
            let options_clause = sql_options_clause(1000);
            let sql = format!(
                "
                SELECT INTERVAL(date_min, {edge_list}) AS bucket,
                       count(distinct file_hash) AS doc_count
                {from_clause}
                {where_clause}
                AND date_min != {DATE_UNKNOWN}
                GROUP BY bucket
                ORDER BY bucket ASC
                LIMIT {}
                {options_clause}
                ;",
                HISTOGRAM_MAX_BUCKETS + 4
            );
            manticore_search_sql::<BucketRow>(sql, &parts.salt).await
        }
    })
    .await?;

    let mut totals = vec![0_u64; edges.len() + 1];
    for (_, response) in &outcome.results {
        for hit in &response.hits.hits {
            if let Ok(index) = usize::try_from(hit._source.bucket)
                && index < totals.len()
            {
                totals[index] += hit._source.doc_count;
            }
        }
    }
    Ok(BucketCounts { totals, partial: outcome.is_partial() })
}

/// `ceil(a / b)` for positive `b`. `i64::div_ceil` is still unstable.
fn ceil_div(a: i64, b: i64) -> i64 {
    (a + b - 1) / b
}

/// The bin edges tiling `domain`, with every in-range cutoff landing exactly on one.
///
/// Returns `n + 1` edges for `n` bins: `edges[0] == domain.start`, `edges[n] ==
/// domain.end`, strictly increasing. Interpolated into `INTERVAL()`, they yield bin `i`
/// as `[edges[i-1], edges[i])` at `INTERVAL` result `i`.
///
/// The width is one value off [`WIDTH_LADDER`] for the whole domain, not per segment, so
/// the three intervals a band-pass creates are drawn at the same scale. The point of the
/// picture is comparing them.
pub fn histogram_edges(domain: DateDomain, cuts: &[Option<i64>]) -> Vec<i64> {
    let span = domain.end.saturating_sub(domain.start).max(1);

    // Segment boundaries: the domain ends plus any cutoff strictly inside it. A cutoff
    // outside the domain is not a boundary. It is a filter that excludes everything on
    // one side, and forcing an edge there would produce an empty run of bins.
    let mut boundaries = vec![domain.start, domain.end];
    for cut in cuts.iter().flatten() {
        if *cut > domain.start && *cut < domain.end {
            boundaries.push(*cut);
        }
    }
    boundaries.sort_unstable();
    boundaries.dedup();

    let ideal = (span / HISTOGRAM_TARGET_BUCKETS.max(1) as i64).max(1);
    let mut width = *WIDTH_LADDER
        .iter()
        .find(|w| **w >= ideal)
        .unwrap_or(WIDTH_LADDER.last().unwrap());

    let bins_at = |width: i64| -> usize {
        boundaries
            .windows(2)
            .map(|pair| {
                let seg = pair[1] - pair[0];
                (ceil_div(seg, width.max(1)) as usize).max(1)
            })
            .sum()
    };
    // Step up the ladder until the total fits. One bin per segment is the irreducible
    // floor; if even that exceeds the cap there is nothing left to widen, and one bin per
    // segment is still a correct (if coarse) picture.
    let mut total = bins_at(width);
    for candidate in WIDTH_LADDER.iter().copied() {
        if total <= HISTOGRAM_MAX_BUCKETS {
            break;
        }
        if candidate <= width {
            continue;
        }
        width = candidate;
        total = bins_at(width);
    }

    let mut edges = vec![boundaries[0]];
    for pair in boundaries.windows(2) {
        let (from, to) = (pair[0], pair[1]);
        let bins = ceil_div(to - from, width.max(1)).max(1);
        for step in 1..=bins {
            // Interpolated rather than `from + step * width` so the last edge of every
            // segment is EXACTLY the boundary: a cutoff one second off its own bin edge
            // is a selection that visibly does not line up with the bars.
            let edge = from + ((to - from) * step) / bins;
            if edge > *edges.last().unwrap() {
                edges.push(edge);
            }
        }
        // Rounding can leave the final edge short of the boundary; the boundary itself is
        // not negotiable.
        if *edges.last().unwrap() < to {
            edges.push(to);
        }
    }
    edges
}

#[cfg(test)]
mod tests {
    use super::*;

    fn domain(start: i64, end: i64) -> DateDomain {
        DateDomain { start, end }
    }

    fn widths(edges: &[i64]) -> Vec<i64> {
        edges.windows(2).map(|p| p[1] - p[0]).collect()
    }

    #[test]
    fn edges_tile_the_domain_and_strictly_increase() {
        for (start, end) in [
            (0_i64, 10 * DAY),
            (0, 365 * DAY),
            (-3_786_825_600, 1_754_611_200), // 1850 to 2025
            (1_700_000_000, 1_700_000_001),  // one document
        ] {
            let edges = histogram_edges(domain(start, end), &[]);
            assert_eq!(edges.first(), Some(&start), "{start}..{end} must start at the domain");
            assert_eq!(edges.last(), Some(&end), "{start}..{end} must end at the domain");
            assert!(
                edges.windows(2).all(|p| p[1] > p[0]),
                "{start}..{end} produced a zero-width or reversed bin: {edges:?}"
            );
        }
    }

    #[test]
    fn the_bin_count_stays_inside_the_band() {
        // Every span from an hour to a millennium, with and without cutoffs.
        let mut span = 3_600_i64;
        while span < 1_000 * 365 * DAY {
            let edges = histogram_edges(domain(0, span), &[]);
            let bins = edges.len() - 1;
            assert!(bins >= 1, "span {span} produced no bins");
            assert!(
                bins <= HISTOGRAM_MAX_BUCKETS,
                "span {span} produced {bins} bins, over the cap"
            );
            span = span * 3 / 2 + 1;
        }
    }

    #[test]
    fn a_cutoff_inside_the_domain_is_always_an_edge() {
        let cut = 137 * DAY;
        let edges = histogram_edges(domain(0, 365 * DAY), &[Some(cut), None]);
        assert!(edges.contains(&cut), "the low-pass cutoff must be a bin edge: {edges:?}");

        let (lo, hi) = (100 * DAY, 250 * DAY);
        let edges = histogram_edges(domain(0, 365 * DAY), &[Some(lo), Some(hi)]);
        assert!(edges.contains(&lo) && edges.contains(&hi), "both cutoffs: {edges:?}");
        assert!(edges.len() - 1 <= HISTOGRAM_MAX_BUCKETS);
    }

    #[test]
    fn the_three_intervals_are_drawn_at_a_similar_width() {
        // The band-pass case the pane exists for: below, between, above. No bin may be
        // more than twice any other, or the middle looks denser than it is.
        let edges = histogram_edges(domain(0, 3_650 * DAY), &[Some(1_000 * DAY), Some(2_000 * DAY)]);
        let widths = widths(&edges);
        let (min, max) = (
            *widths.iter().min().unwrap(),
            *widths.iter().max().unwrap(),
        );
        assert!(max <= 2 * min, "bin widths {min}..{max} are not comparable: {widths:?}");
    }

    #[test]
    fn a_cutoff_outside_the_domain_does_not_force_an_empty_run() {
        // Filtering "before 1990" over a corpus that starts in 2000 must not prepend ten
        // years of empty bars.
        let start = 946_684_800; // 2000-01-01
        let edges = histogram_edges(domain(start, start + 365 * DAY), &[Some(0), None]);
        assert_eq!(edges.first(), Some(&start));
        assert!(!edges.contains(&0));
    }

    #[test]
    fn a_single_instant_domain_still_yields_one_bin() {
        let edges = histogram_edges(domain(42, 43), &[]);
        assert_eq!(edges, vec![42, 43]);
    }

    #[test]
    fn a_negative_domain_bins_the_same_way() {
        // Pre-1970 dates are the whole reason `dates` is signed; integer division
        // truncating towards zero would put an edge on the wrong side of the epoch.
        let edges = histogram_edges(domain(-3_786_825_600, -1_072_915_200), &[]);
        assert!(edges.windows(2).all(|p| p[1] > p[0]), "{edges:?}");
        assert_eq!(edges.first(), Some(&-3_786_825_600));
        assert_eq!(edges.last(), Some(&-1_072_915_200));
    }

    #[test]
    fn the_ladder_is_sorted_and_positive() {
        assert!(WIDTH_LADDER.windows(2).all(|p| p[1] > p[0]));
        assert!(WIDTH_LADDER.iter().all(|w| *w > 0));
    }
}
