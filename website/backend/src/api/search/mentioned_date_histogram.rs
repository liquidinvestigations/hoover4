//! The histogram under the Mentioned Date filter pane.
//!
//! The binning is the same question the document-date histogram answers, so the ladder,
//! the target bin count and the edge placement are reused wholesale from
//! [`super::date_histogram`]. Two copies of that arithmetic would drift, and a filter
//! whose cutoffs no longer land on its own bars is a picture of nothing.
//!
//! The aggregation is NOT the same, in two ways that both matter:
//!
//! * **The domain comes from a pair of scalar bounds, the counts from an MVA.** A
//!   document's own dates are an interval it occupies; the dates it *mentions* are
//!   points. `mentioned_date_min`/`_max` bracket those points for the axis, and nothing
//!   else. The moment either of them filters, a document naming 1936 and 2020 starts
//!   matching 2005.
//! * **The bars count mentions, not documents.** A document naming three days inside one
//!   bin contributes three. Manticore's `GROUP BY` over an MVA yields one row per
//!   distinct value, so summing day buckets into bins sums mentions; getting document
//!   counts instead would need one query per bin. The response says which it is, so the
//!   pane can label its axis and a later reader cannot mistake it for the document
//!   counts the other histogram returns.

use crate::api::search::date_histogram::{DateDomain, histogram_edges};
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

/// Distinct day buckets read back per shard before the result is called partial.
///
/// A bare `SELECT` returns Manticore's implicit `LIMIT 20`, and a result set silently
/// caps at `max_matches` (1000 by default). Either would draw a histogram of an
/// arbitrary handful of days and render it as the whole corpus, so the limit and the
/// `max_matches` are the same explicit number and exceeding it is reported.
const DAY_BUCKET_LIMIT: u64 = 100_000;

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
struct DayRow {
    term: i64,
    mention_count: u64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
struct BoundRow {
    bound: i64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default)]
struct CountRow {
    doc_count: u64,
}

/// Mention counts per computed date bin, plus the count of documents mentioning no date.
///
/// Takes the whole query INCLUDING its `mentioned_dates` filter: the cutoffs place the
/// bin edges and are then stripped, so the bars show the corpus the rest of the query
/// narrows to and the selection is drawn on top of them.
pub async fn search_mentioned_date_histogram(
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
    let cuts = query
        .range_filters
        .get("mentioned_dates")
        .map(|filter| [filter.min, filter.max])
        .unwrap_or([None, None]);
    query.range_filters.remove("mentioned_dates");

    let collections = fanout::permitted_search_collections(user, &query).await?;
    let targets = fanout::shard_targets(&collections).await;
    if targets.is_empty() {
        return Ok(DateHistogram::default());
    }

    let (domain, unknown_count, probe_partial) = probe_domain(&query, targets.clone()).await?;
    let Some(domain) = domain else {
        return Ok(DateHistogram {
            unknown_count,
            partial: probe_partial,
            ..DateHistogram::default()
        });
    };

    let edges = histogram_edges(domain, &cuts);
    let (days, days_partial) = count_days(&query, targets).await?;

    let buckets: Vec<DateHistogramBucket> = edges
        .windows(2)
        .map(|pair| DateHistogramBucket {
            start: pair[0],
            end: pair[1],
            count: sum_days_in(&days, pair[0], pair[1]),
        })
        .collect();

    Ok(DateHistogram {
        buckets,
        unknown_count,
        domain_start: domain.start,
        domain_end: domain.end,
        partial: probe_partial || days_partial,
        counts_mentions: true,
    })
}

/// Sum the day buckets falling in `[start, end)`.
///
/// The binning is done here rather than by `INTERVAL()` because the counts already
/// arrived one row per day: a second aggregation pass in Manticore would need the day
/// list sent back as an edge list, and the edges are chosen from the domain the same
/// query measured.
fn sum_days_in(days: &[(i64, u64)], start: i64, end: i64) -> u64 {
    days.iter()
        .filter(|(day, _)| *day >= start && *day < end)
        .map(|(_, count)| *count)
        .sum()
}

/// The extent of the mentioned days, and the count of documents mentioning none.
///
/// The bounds are read off the scalar pair rather than off the MVA: `min()`/`max()`
/// without a `GROUP BY` is not a shape this codebase gets an answer out of Manticore
/// for, and the two scalars exist precisely so the axis can be measured in one ordered
/// read per direction.
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
            let low = format!(
                "
                SELECT mentioned_date_min AS bound
                {from_clause}
                {where_clause}
                AND mentioned_date_min != {DATE_UNKNOWN}
                GROUP BY bound
                ORDER BY bound ASC
                LIMIT 1
                {options_clause}
                ;"
            );
            let high = format!(
                "
                SELECT mentioned_date_max AS bound
                {from_clause}
                {where_clause}
                AND mentioned_date_min != {DATE_UNKNOWN}
                GROUP BY bound
                ORDER BY bound DESC
                LIMIT 1
                {options_clause}
                ;"
            );
            let unknown = format!(
                "
                SELECT count(distinct file_hash) AS doc_count
                {from_clause}
                {where_clause}
                AND mentioned_date_min = {DATE_UNKNOWN}
                {options_clause}
                ;"
            );
            let low = manticore_search_sql::<BoundRow>(low, &parts.salt).await?;
            let high = manticore_search_sql::<BoundRow>(high, &parts.salt).await?;
            let none = manticore_search_sql::<CountRow>(unknown, &parts.salt).await?;
            Ok((low, high, none))
        }
    })
    .await?;

    let partial = outcome.is_partial();
    let mut start: Option<i64> = None;
    let mut end: Option<i64> = None;
    let mut unknown_count = 0_u64;
    for (_, (low, high, none)) in outcome.results {
        if let Some(hit) = low.hits.hits.first() {
            start = Some(start.map_or(hit._source.bound, |v: i64| v.min(hit._source.bound)));
        }
        if let Some(hit) = high.hits.hits.first() {
            end = Some(end.map_or(hit._source.bound, |v: i64| v.max(hit._source.bound)));
        }
        // An aggregate over an empty match still returns one row, with count 0.
        unknown_count += none.hits.hits.first().map_or(0, |h| h._source.doc_count);
    }

    let domain = match (start, end) {
        (Some(start), Some(end)) => Some(DateDomain {
            start,
            end: end.max(start).saturating_add(1),
        }),
        _ => None,
    };
    Ok((domain, unknown_count, partial))
}

/// `(day, mentions)` pairs merged across every shard.
async fn count_days(
    query: &SearchQuery,
    targets: Vec<FanoutTarget>,
) -> anyhow::Result<(Vec<(i64, u64)>, bool)> {
    let outcome = fanout::fan_out(targets, |target: FanoutTarget| {
        let query = query.clone();
        async move {
            let parts = fanout::shard_query_parts(&target, &query).await?;
            let from_clause = &parts.from_clause;
            let where_clause = &parts.where_clause;
            let options_clause = sql_options_clause(DAY_BUCKET_LIMIT);
            let sql = format!(
                "
                SELECT groupby() term, count(distinct file_hash) AS mention_count
                {from_clause}
                {where_clause}
                AND mentioned_date_min != {DATE_UNKNOWN}
                GROUP BY mentioned_dates
                ORDER BY term ASC
                LIMIT {DAY_BUCKET_LIMIT}
                {options_clause}
                ;"
            );
            manticore_search_sql::<DayRow>(sql, &parts.salt).await
        }
    })
    .await?;

    let mut partial = outcome.is_partial();
    let mut merged: std::collections::BTreeMap<i64, u64> = std::collections::BTreeMap::new();
    for (_, response) in outcome.results {
        if response.hits.hits.len() as u64 >= DAY_BUCKET_LIMIT {
            partial = true;
        }
        for hit in response.hits.hits {
            *merged.entry(hit._source.term).or_insert(0) += hit._source.mention_count;
        }
    }
    Ok((merged.into_iter().collect(), partial))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_day_lands_in_the_bin_that_starts_on_it_and_not_the_one_that_ends_on_it() {
        // Bins are `[start, end)`, so a day exactly on an edge belongs to the bin above
        // it. Off by one here double-counts every boundary day.
        let days = vec![(100, 3), (200, 5), (300, 7)];
        assert_eq!(sum_days_in(&days, 100, 200), 3);
        assert_eq!(sum_days_in(&days, 200, 300), 5);
        assert_eq!(sum_days_in(&days, 300, 400), 7);
    }

    #[test]
    fn a_bin_with_several_days_sums_them() {
        let days = vec![(100, 3), (150, 4), (199, 1), (200, 5)];
        assert_eq!(sum_days_in(&days, 100, 200), 8);
    }

    #[test]
    fn a_bin_with_no_days_is_zero_rather_than_absent() {
        assert_eq!(sum_days_in(&[(100, 3)], 500, 600), 0);
    }

    /// Days before the epoch are ordinary values here: the bounds are signed, which is
    /// the whole reason `mentioned_date_min` is a `bigint` rather than Manticore's
    /// 32-bit unsigned `timestamp`.
    #[test]
    fn days_before_the_epoch_bin_like_any_other() {
        let days = vec![(-1_072_915_200, 2), (1_580_000_000, 1)];
        assert_eq!(sum_days_in(&days, -1_100_000_000, -1_000_000_000), 2);
        assert_eq!(sum_days_in(&days, 0, 2_000_000_000), 1);
    }

    #[test]
    fn the_bucket_cap_and_its_max_matches_are_the_same_number() {
        // A LIMIT above `max_matches` truncates silently, which is the failure this
        // histogram exists to avoid drawing.
        assert!(sql_options_clause(DAY_BUCKET_LIMIT).contains(&format!(
            "max_matches={DAY_BUCKET_LIMIT}"
        )));
        assert!(
            DAY_BUCKET_LIMIT as usize
                > crate::api::search::date_histogram::HISTOGRAM_MAX_BUCKETS
        );
    }
}
