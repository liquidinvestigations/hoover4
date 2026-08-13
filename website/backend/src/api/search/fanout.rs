//! Bounded fan-out of search queries across Manticore shard tables, with merging.
//!
//! Manticore 14.1.0 cannot run the website's JOIN/stored-field/FACET query shape over
//! distributed tables — measured, and it fails by crashing the daemon or returning
//! NULL stored fields rather than by erroring cleanly. So the
//! backend fans out over **shards**: each permitted collection contributes one query
//! target per entry of its `manticore_shards` ledger
//! (`<collectionname>_<n>_pages LEFT JOIN <collectionname>_<n>_meta`, a plain local
//! join). At most [`MAX_PARALLEL_INDEX_QUERIES`] requests are in flight at once.
//!
//! **Partial-failure policy:** one slow or broken shard must not blank the whole
//! result page. Per-target errors are logged as warnings and dropped, and callers
//! mark the response as partial; an error is propagated only when *every* target
//! failed.
//!
//! **Known ranking limitation:** BM25 statistics are per-table, so `_score` values
//! from different shards/collections are not strictly comparable and cross-shard
//! ranking is approximate. This is inherent to sharded full-text search without a
//! global IDF, and is accepted. Do not "fix" it with a
//! normalisation hack — an unprincipled rescale is worse than this honest note.

use std::collections::BTreeMap;
use std::fmt::Debug;

use futures::stream::{self, StreamExt};

use common::current_user::CurrentUser;
use common::search_query::{SearchQuery, SortSpec};
use common::search_result::FacetOriginalValue;

use crate::api::search::search_sql::{
    build_sql_where_clause, shard_table_names, sql_from_clause,
};
use crate::db_utils::clickhouse_utils;
use crate::db_utils::manticore_utils::RawSarchResult;

/// Default cap on concurrent Manticore queries during fan-out.
/// Override with `HOOVER4_SEARCH_MAX_PARALLELISM` (clamped to 1..=64).
pub const MAX_PARALLEL_INDEX_QUERIES: usize = 8;

pub const PARALLELISM_ENV: &str = "HOOVER4_SEARCH_MAX_PARALLELISM";

/// Number of facet buckets shown in the UI per facet.
pub const FACET_DISPLAY_LIMIT: usize = 21;

/// Hard cap on the per-shard facet bucket limit (see [`per_shard_facet_limit`]).
pub const MAX_PER_SHARD_FACET_BUCKETS: u64 = 200;

/// Parse the parallelism override: unset/unparseable falls back to the default,
/// numbers are clamped to 1..=64.
pub fn parse_max_parallelism(raw: Option<&str>) -> usize {
    raw.and_then(|s| s.trim().parse::<usize>().ok())
        .map(|n| n.clamp(1, 64))
        .unwrap_or(MAX_PARALLEL_INDEX_QUERIES)
}

pub fn max_parallelism() -> usize {
    parse_max_parallelism(std::env::var(PARALLELISM_ENV).ok().as_deref())
}

/// Per-shard facet bucket limit. A bucket that ranks low in one shard but high in
/// another would be truncated away before the merge if every shard only returned
/// the display limit, so each shard over-fetches proportional to the shard count.
/// Facet counts remain approximate when a shard has more distinct values than this
/// limit — documented in `website/Readme.md`.
pub fn per_shard_facet_limit(n_shards: usize) -> u64 {
    (FACET_DISPLAY_LIMIT as u64 * n_shards.max(1) as u64).clamp(FACET_DISPLAY_LIMIT as u64, MAX_PER_SHARD_FACET_BUCKETS)
}

/// One unit of fan-out: a Manticore shard of a collection, or the collection
/// itself (used for ClickHouse-side lookups such as `string_term_id_to_text`).
/// An enum so that "shard target without a shard name" is unrepresentable.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum FanoutTarget {
    /// One Manticore shard `<collectionname>_<n>` of a collection.
    Shard {
        collectionname: String,
        shard_name: String,
    },
    /// The collection database as a whole (no shard).
    Collection(String),
}

impl FanoutTarget {
    pub fn shard(collectionname: impl Into<String>, shard_name: impl Into<String>) -> Self {
        Self::Shard {
            collectionname: collectionname.into(),
            shard_name: shard_name.into(),
        }
    }

    pub fn collection(collectionname: impl Into<String>) -> Self {
        Self::Collection(collectionname.into())
    }

    pub fn collectionname(&self) -> &str {
        match self {
            Self::Shard { collectionname, .. } => collectionname,
            Self::Collection(collectionname) => collectionname,
        }
    }

    /// The shard name of a `Shard` target; an error for a collection-level target.
    pub fn shard_name(&self) -> anyhow::Result<&str> {
        match self {
            Self::Shard { shard_name, .. } => Ok(shard_name),
            Self::Collection(c) => {
                anyhow::bail!("collection-level fan-out target {c} has no shard_name")
            }
        }
    }

    /// Short label for logs and warnings.
    pub fn label(&self) -> &str {
        match self {
            Self::Shard { shard_name, .. } => shard_name,
            Self::Collection(collectionname) => collectionname,
        }
    }
}

/// Everything a per-shard Manticore query needs, built once per fan-out target:
/// validated table names, the JOIN clause, the WHERE clause and the cache salt
/// (shard-ledger generation, so an indexing run invalidates cached searches).
/// The four search endpoints share this prologue instead of rebuilding it.
pub struct ShardQueryParts {
    pub shard_name: String,
    pub pages_table: String,
    pub meta_table: String,
    pub from_clause: String,
    pub where_clause: String,
    pub salt: String,
}

pub async fn shard_query_parts(
    target: &FanoutTarget,
    query: &SearchQuery,
) -> anyhow::Result<ShardQueryParts> {
    let shard_name = target.shard_name()?.to_string();
    let generation = clickhouse_utils::shard_generation(target.collectionname()).await?;
    let salt = format!("{}@{generation}", target.collectionname());
    let (pages_table, meta_table) = shard_table_names(&shard_name)?;
    let from_clause = sql_from_clause(&shard_name)?;
    let where_clause = build_sql_where_clause(query, &pages_table, &meta_table)?;
    Ok(ShardQueryParts {
        shard_name,
        pages_table,
        meta_table,
        from_clause,
        where_clause,
        salt,
    })
}

/// Outcome of a fan-out: the per-target successes plus the targets that failed
/// (and were dropped per the partial-failure policy).
pub struct FanoutOutcome<T> {
    pub results: Vec<(FanoutTarget, T)>,
    pub failed: Vec<FanoutTarget>,
}

impl<T> FanoutOutcome<T> {
    /// Whether at least one target failed — callers surface this as a
    /// partial-results notice.
    pub fn is_partial(&self) -> bool {
        !self.failed.is_empty()
    }
}

/// Run `run(target)` for every target with at most [`max_parallelism`] futures in
/// flight, collecting `(target, value)` pairs.
///
/// Per-target errors are logged and dropped unless ALL targets fail, in which case
/// the first error is propagated.
pub async fn fan_out<T, F, Fut>(
    targets: Vec<FanoutTarget>,
    run: F,
) -> anyhow::Result<FanoutOutcome<T>>
where
    T: Send + 'static,
    F: Fn(FanoutTarget) -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<T>>,
{
    let had_targets = !targets.is_empty();
    let outcomes: Vec<(FanoutTarget, anyhow::Result<T>)> = stream::iter(targets)
        .map(|target| {
            let label = target.clone();
            let fut = run(target);
            async move { (label, fut.await) }
        })
        .buffer_unordered(max_parallelism())
        .collect()
        .await;

    let mut results = Vec::new();
    let mut failed = Vec::new();
    let mut first_error = None;
    for (target, outcome) in outcomes {
        match outcome {
            Ok(value) => results.push((target, value)),
            Err(e) => {
                // A query the caller malformed fails identically on every target, so it
                // is one 400 and not N broken shards. Logged at WARN it produced a burst
                // of shard-failure lines per keystroke — the exact signal this level is
                // reserved for, spent on a normal outcome.
                if crate::auth::guard::is_bad_request(&e) {
                    tracing::debug!("fan_out: target {} cannot run this query: {e:#}", target.label());
                } else {
                    tracing::warn!("fan_out: target {} failed, dropping it from results: {e:#}", target.label());
                }
                if first_error.is_none() {
                    first_error = Some(e);
                }
                failed.push(target);
            }
        }
    }
    // Deterministic ordering for merging and tests, independent of completion order.
    results.sort_by(|a, b| a.0.cmp(&b.0));
    failed.sort();

    if results.is_empty() && had_targets {
        return Err(first_error.unwrap_or_else(|| anyhow::anyhow!("all fan-out targets failed")));
    }
    Ok(FanoutOutcome { results, failed })
}

/// What the merge needs from a hit's `_source` to order results deterministically.
///
/// `sort_value` is what makes the merge sort-aware: each shard has already ordered its
/// own rows by the same key, and the merge has to reproduce that order across shards.
/// It returns the value of the ACTIVE sort key, which the per-shard SELECT is required
/// to include — a merge sorting on a column the query did not select would silently
/// order everything by the default and produce pages that overlap.
pub trait HitIdentity {
    fn collection_dataset(&self) -> &str;
    fn file_hash(&self) -> &str;

    /// The comparable value of the active sort key. `None` means "use `_score`", which
    /// is the Relevance case and the only one the unsorted merge handles.
    ///
    /// Takes the whole `SortSpec`, not just the key, because `Date` compares a
    /// different column per direction (`date_min` ascending, `date_max` descending) —
    /// exactly as `search_sql::sort_column` builds it. Handing the implementor only the
    /// key would let the merge compare one end while the SQL ordered by the other.
    fn sort_value(&self, _sort: SortSpec) -> Option<SortValue> {
        None
    }
}

/// One hit's position under the active sort key. An enum because the four keys are two
/// different orderings (numeric and lexicographic) and comparing them through a common
/// string would sort `10` before `9`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SortValue {
    Int(i64),
    Text(String),
}

/// Text compares WITHOUT case, because Manticore's `collation_connection` is `libc_ci`
/// and the per-shard `ORDER BY` already ran under it. `primary_filename` keeps the
/// filesystem's own case, so a byte-wise merge would sort `README` before `alpha.pdf`
/// while every shard sorted it after — and a document at a shard's truncation boundary
/// would land on two pages or on none.
impl Ord for SortValue {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        match (self, other) {
            (SortValue::Int(a), SortValue::Int(b)) => a.cmp(b),
            (SortValue::Text(a), SortValue::Text(b)) => a
                .to_lowercase()
                .cmp(&b.to_lowercase())
                .then_with(|| a.cmp(b)),
            (SortValue::Int(_), SortValue::Text(_)) => std::cmp::Ordering::Less,
            (SortValue::Text(_), SortValue::Int(_)) => std::cmp::Ordering::Greater,
        }
    }
}

impl PartialOrd for SortValue {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

/// Merge per-shard search responses into one ordered window.
///
/// Ordering: `_score` descending, tie-broken on `(collection_dataset, file_hash)`
/// so pagination is stable across requests. Cross-shard scores are only
/// approximately comparable (see the module doc) — the tie-break exists for
/// stability, not for ranking quality.
///
/// Every source must have been queried with `LIMIT offset+limit OFFSET 0` (deep
/// pagination across N sources requires over-fetching from every source); this
/// function only merges and slices the `[offset, offset+limit)` window.
pub fn merge_hits<T: HitIdentity>(
    sources: Vec<(FanoutTarget, RawSarchResult<T>)>,
    offset: usize,
    limit: usize,
) -> Vec<crate::db_utils::manticore_utils::RawSearchResultHit<T>> {
    merge_hits_sorted(sources, SortSpec::default(), offset, limit)
}

/// Merge per-shard responses under an arbitrary sort key.
///
/// The per-shard queries were built with the SAME `SortSpec` (see
/// `search_sql::sort_order_by`), so each source is already a sorted prefix; this
/// reproduces that order globally and slices the `[offset, offset+limit)` window. The
/// tie-break on `(collection_dataset, file_hash)` must stay identical to the SQL's, or
/// a document tied at a shard's truncation boundary lands on two pages or on none.
pub fn merge_hits_sorted<T: HitIdentity>(
    sources: Vec<(FanoutTarget, RawSarchResult<T>)>,
    sort: SortSpec,
    offset: usize,
    limit: usize,
) -> Vec<crate::db_utils::manticore_utils::RawSearchResultHit<T>> {
    let mut hits: Vec<_> = sources
        .into_iter()
        .flat_map(|(_, response)| response.hits.hits)
        .collect();
    hits.sort_by(|a, b| {
        let primary = match (a._source.sort_value(sort), b._source.sort_value(sort)) {
            // Relevance, or a source that does not carry the key: fall back to the
            // score, which Manticore always returns.
            (None, None) => b._score.cmp(&a._score),
            (left, right) => {
                let ordering = left.cmp(&right);
                if sort.desc { ordering.reverse() } else { ordering }
            }
        };
        primary
            .then_with(|| a._source.collection_dataset().cmp(b._source.collection_dataset()))
            .then_with(|| a._source.file_hash().cmp(b._source.file_hash()))
    });
    hits.into_iter().skip(offset).take(limit).collect()
}

/// Merge per-shard facet buckets: sum `doc_count` per key across all sources,
/// re-sort by count descending (ties broken on the key itself, so the output is
/// deterministic), and truncate to `limit`.
///
/// Counts remain approximate when a shard had more distinct values than its
/// per-shard bucket limit — those values never reached the merge.
pub fn merge_facet_pairs(
    sources: impl IntoIterator<Item = Vec<(serde_json::Value, u64)>>,
    limit: usize,
) -> Vec<(serde_json::Value, u64)> {
    let mut totals: BTreeMap<String, (serde_json::Value, u64)> = BTreeMap::new();
    for buckets in sources {
        for (key, count) in buckets {
            // serde_json::Value is not Ord; the canonical JSON string is a stable,
            // collision-free map key for deduplication.
            let map_key = serde_json::to_string(&key).unwrap_or_default();
            totals
                .entry(map_key)
                .and_modify(|(_, total)| *total += count)
                .or_insert((key, count));
        }
    }
    let mut merged: Vec<(serde_json::Value, u64)> = totals.into_values().collect();
    merged.sort_by(|(ka, ca), (kb, cb)| {
        cb.cmp(ca).then_with(|| {
            serde_json::to_string(ka)
                .unwrap_or_default()
                .cmp(&serde_json::to_string(kb).unwrap_or_default())
        })
    });
    merged.truncate(limit);
    merged
}

/// Extract the `collection_dataset` facet selection (string values only) from a query.
fn dataset_selection(query: &SearchQuery) -> Vec<String> {
    query
        .facet_filters
        .get("collection_dataset")
        .map(|set| {
            set.iter()
                .filter_map(|v| match v {
                    FacetOriginalValue::String(s) => Some(s.clone()),
                    FacetOriginalValue::Int(_) => None,
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Resolve each selected dataset to its owning collection. Datasets that cannot
/// be resolved (deleted since the UI rendered) are logged and skipped.
async fn resolve_selected_collections<F, Fut>(selection: &[String], resolve: F) -> Vec<String>
where
    F: Fn(&str) -> Fut,
    Fut: std::future::Future<Output = anyhow::Result<String>>,
{
    let mut selected = Vec::new();
    for dataset in selection {
        match resolve(dataset).await {
            Ok(collectionname) => selected.push(collectionname),
            Err(e) => tracing::warn!("fan_out: cannot resolve selected dataset {dataset:?}: {e:#}"),
        }
    }
    selected
}

/// Intersect the permitted collections with the resolved selection, sorted and deduped.
fn intersect_permitted_with_selection(
    permitted: Vec<String>,
    selected_collections: &[String],
) -> Vec<String> {
    let mut result: Vec<String> = permitted
        .into_iter()
        .filter(|c| selected_collections.contains(c))
        .collect();
    result.sort();
    result.dedup();
    result
}

/// The collections a search should fan out to: the user's permitted collections
/// (with `PermissionSet::All` materialised), intersected with the user's
/// `collection_dataset` facet selection — every selected dataset maps to its
/// collection, and collections with no selected dataset are pruned. That pruning
/// is the main performance win of this design: filtering by dataset skips whole
/// indexes.
pub async fn permitted_search_collections(
    user: &CurrentUser,
    query: &SearchQuery,
) -> anyhow::Result<Vec<String>> {
    let collections = clickhouse_utils::list_permitted_collections(user).await?;
    let selection = dataset_selection(query);
    if selection.is_empty() {
        return Ok(collections);
    }
    let selected_collections = resolve_selected_collections(&selection, |d| {
        let d = d.to_string();
        async move { clickhouse_utils::resolve_collection(&d).await }
    })
    .await;
    Ok(intersect_permitted_with_selection(collections, &selected_collections))
}

/// Expand collections into one [`FanoutTarget`] per shard recorded in each
/// collection's `manticore_shards` ledger. A collection with no shards yet (never
/// indexed) contributes no targets; a collection whose ledger cannot be read is
/// logged and skipped, so one broken collection cannot blank the search page.
pub async fn shard_targets(collections: &[String]) -> Vec<FanoutTarget> {
    let mut targets = Vec::new();
    for collectionname in collections {
        match clickhouse_utils::list_shards(collectionname).await {
            Ok(shards) => {
                targets.extend(
                    shards
                        .into_iter()
                        .map(|shard_name| FanoutTarget::shard(collectionname.clone(), shard_name)),
                );
            }
            Err(e) => {
                tracing::warn!("fan_out: cannot list shards of collection {collectionname}: {e:#}");
            }
        }
    }
    targets
}

#[cfg(test)]
mod tests {
    use super::*;
    use common::search_query::SortKey;
    use crate::db_utils::manticore_utils::{
        RawSarchResult, RawSearchResultHit, RawSearchResultHits,
    };
    use serde::{Deserialize, Serialize};

    #[test]
    fn parse_max_parallelism_defaults_to_8() {
        assert_eq!(parse_max_parallelism(None), 8);
    }

    #[test]
    fn parse_max_parallelism_parses_and_clamps() {
        assert_eq!(parse_max_parallelism(Some("1")), 1);
        assert_eq!(parse_max_parallelism(Some("16")), 16);
        assert_eq!(parse_max_parallelism(Some(" 4 ")), 4);
        assert_eq!(parse_max_parallelism(Some("0")), 1);
        assert_eq!(parse_max_parallelism(Some("999")), 64);
    }

    #[test]
    fn parse_max_parallelism_invalid_falls_back_to_default() {
        for bad in ["", "abc", "-3", "8.5", "1e2"] {
            assert_eq!(parse_max_parallelism(Some(bad)), 8, "should fall back for {bad:?}");
        }
    }

    #[test]
    fn per_shard_facet_limit_scales_and_clamps() {
        assert_eq!(per_shard_facet_limit(0), 21);
        assert_eq!(per_shard_facet_limit(1), 21);
        assert_eq!(per_shard_facet_limit(3), 63);
        assert_eq!(per_shard_facet_limit(100), 200);
    }

    #[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
    struct FixtureSource {
        collection_dataset: String,
        file_hash: String,
    }

    impl HitIdentity for FixtureSource {
        fn collection_dataset(&self) -> &str {
            &self.collection_dataset
        }
        fn file_hash(&self) -> &str {
            &self.file_hash
        }
    }

    fn hit(collection_dataset: &str, file_hash: &str, score: u64) -> RawSearchResultHit<FixtureSource> {
        RawSearchResultHit {
            _source: FixtureSource {
                collection_dataset: collection_dataset.to_string(),
                file_hash: file_hash.to_string(),
            },
            _score: score,
        }
    }

    fn source(collection: &str, shard: &str, hits: Vec<RawSearchResultHit<FixtureSource>>) -> (FanoutTarget, RawSarchResult<FixtureSource>) {
        (
            FanoutTarget::shard(collection, shard),
            RawSarchResult {
                hits: RawSearchResultHits {
                    total: hits.len() as u64,
                    total_relation: "eq".to_string(),
                    hits,
                },
                timed_out: false,
                took: 1,
                aggregations: None,
            },
        )
    }

    fn ids(hits: &[RawSearchResultHit<FixtureSource>]) -> Vec<(String, String)> {
        hits.iter()
            .map(|h| (h._source.collection_dataset.clone(), h._source.file_hash.clone()))
            .collect()
    }

    #[test]
    fn merge_hits_orders_by_score_descending() {
        let a = source("testdata", "testdata_1", vec![hit("td_a", "h1", 10), hit("td_a", "h2", 30)]);
        let b = source("other", "other_1", vec![hit("ot_b", "h3", 20)]);
        let merged = merge_hits(vec![a, b], 0, 10);
        assert_eq!(
            ids(&merged),
            vec![
                ("td_a".to_string(), "h2".to_string()),
                ("ot_b".to_string(), "h3".to_string()),
                ("td_a".to_string(), "h1".to_string()),
            ]
        );
    }

    fn two_sources() -> Vec<(FanoutTarget, RawSarchResult<FixtureSource>)> {
        vec![
            source("testdata", "testdata_1", vec![hit("td_b", "h2", 10), hit("td_a", "h1", 10)]),
            source("other", "other_1", vec![hit("ot_a", "h9", 10)]),
        ]
    }

    #[test]
    fn merge_hits_tie_breaks_deterministically() {
        let first = merge_hits(two_sources(), 0, 10);
        let mut reversed = two_sources();
        reversed.reverse();
        let second = merge_hits(reversed, 0, 10);
        let expect = vec![
            ("ot_a".to_string(), "h9".to_string()),
            ("td_a".to_string(), "h1".to_string()),
            ("td_b".to_string(), "h2".to_string()),
        ];
        assert_eq!(ids(&first), expect);
        assert_eq!(ids(&second), expect, "order must not depend on source order");
    }

    #[test]
    fn merge_hits_slices_stable_pages() {
        // 6 documents spread over two shards; pages of 2 must be disjoint and complete.
        let six_docs = || {
            vec![
                source(
                    "testdata",
                    "testdata_1",
                    vec![hit("td_a", "h1", 60), hit("td_a", "h3", 40), hit("td_a", "h5", 20)],
                ),
                source(
                    "testdata",
                    "testdata_2",
                    vec![hit("td_a", "h2", 50), hit("td_a", "h4", 30), hit("td_a", "h6", 10)],
                ),
            ]
        };
        let page0 = merge_hits(six_docs(), 0, 2);
        let page1 = merge_hits(six_docs(), 2, 2);
        let page2 = merge_hits(six_docs(), 4, 2);
        assert_eq!(ids(&page0), vec![("td_a".to_string(), "h1".to_string()), ("td_a".to_string(), "h2".to_string())]);
        assert_eq!(ids(&page1), vec![("td_a".to_string(), "h3".to_string()), ("td_a".to_string(), "h4".to_string())]);
        assert_eq!(ids(&page2), vec![("td_a".to_string(), "h5".to_string()), ("td_a".to_string(), "h6".to_string())]);
    }

    #[test]
    fn merge_hits_with_short_source() {
        // One source returned fewer rows than requested (end of its result set):
        // the window must be filled from the other source.
        let a = source("testdata", "testdata_1", vec![hit("td_a", "h1", 50)]);
        let b = source("other", "other_1", vec![hit("ot_b", "h2", 40), hit("ot_b", "h3", 30)]);
        let merged = merge_hits(vec![a, b], 1, 2);
        assert_eq!(ids(&merged), vec![("ot_b".to_string(), "h2".to_string()), ("ot_b".to_string(), "h3".to_string())]);
    }

    #[test]
    fn merge_hits_empty_sources() {
        assert!(merge_hits::<FixtureSource>(vec![], 0, 10).is_empty());
    }

    /// A source that DOES carry sort values, for the sort-aware merge.
    #[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
    struct SortableSource {
        collection_dataset: String,
        file_hash: String,
        date_min: i64,
        date_max: i64,
        file_size_bytes: i64,
        primary_filename: String,
    }

    impl HitIdentity for SortableSource {
        fn collection_dataset(&self) -> &str {
            &self.collection_dataset
        }
        fn file_hash(&self) -> &str {
            &self.file_hash
        }
        fn sort_value(&self, sort: SortSpec) -> Option<SortValue> {
            match sort.key {
                SortKey::Relevance => None,
                SortKey::Date if sort.desc => Some(SortValue::Int(self.date_max)),
                SortKey::Date => Some(SortValue::Int(self.date_min)),
                SortKey::FileSize => Some(SortValue::Int(self.file_size_bytes)),
                SortKey::Name => Some(SortValue::Text(self.primary_filename.clone())),
            }
        }
    }

    fn sortable(
        file_hash: &str,
        date_min: i64,
        date_max: i64,
        size: i64,
        name: &str,
    ) -> RawSearchResultHit<SortableSource> {
        RawSearchResultHit {
            _source: SortableSource {
                collection_dataset: "td".to_string(),
                file_hash: file_hash.to_string(),
                date_min,
                date_max,
                file_size_bytes: size,
                primary_filename: name.to_string(),
            },
            // Every hit has the SAME score on purpose: a merge that silently fell back
            // to the score would look correct here only by accident, and this way it
            // cannot.
            _score: 100,
        }
    }

    fn mk(
        shard: &str,
        hits: Vec<RawSearchResultHit<SortableSource>>,
    ) -> (FanoutTarget, RawSarchResult<SortableSource>) {
        (
            FanoutTarget::shard("testdata", shard),
            RawSarchResult {
                hits: RawSearchResultHits {
                    total: hits.len() as u64,
                    total_relation: "eq".to_string(),
                    hits,
                },
                timed_out: false,
                took: 1,
                aggregations: None,
            },
        )
    }

    fn sortable_sources() -> Vec<(FanoutTarget, RawSarchResult<SortableSource>)> {
        vec![
            mk("testdata_1", vec![
                sortable("h1", 100, 900, 30, "delta.pdf"),
                sortable("h3", 300, 700, 10, "bravo.pdf"),
            ]),
            mk("testdata_2", vec![
                sortable("h2", 200, 800, 20, "charlie.pdf"),
                sortable("h4", -400, -400, 40, "alpha.pdf"),
            ]),
        ]
    }

    fn sorted_hashes(sort: SortSpec) -> Vec<String> {
        merge_hits_sorted(sortable_sources(), sort, 0, 10)
            .into_iter()
            .map(|h| h._source.file_hash)
            .collect()
    }

    /// Every `SortKey` in both directions. Without this the merge and the per-shard
    /// `ORDER BY` can disagree silently: each shard comes back correctly ordered, the
    /// merge reorders them by score, and the result is a page that looks plausible and
    /// is wrong.
    #[test]
    fn merge_hits_sorted_orders_by_every_key() {
        // Date descending compares date_max; ascending compares date_min. The pre-1970
        // document (h4, negative epoch) must sort below everything ascending.
        assert_eq!(sorted_hashes(SortSpec { key: SortKey::Date, desc: true }),
                   vec!["h1", "h2", "h3", "h4"]);
        assert_eq!(sorted_hashes(SortSpec { key: SortKey::Date, desc: false }),
                   vec!["h4", "h1", "h2", "h3"]);
        assert_eq!(sorted_hashes(SortSpec { key: SortKey::FileSize, desc: true }),
                   vec!["h4", "h1", "h2", "h3"]);
        assert_eq!(sorted_hashes(SortSpec { key: SortKey::FileSize, desc: false }),
                   vec!["h3", "h2", "h1", "h4"]);
        assert_eq!(sorted_hashes(SortSpec { key: SortKey::Name, desc: false }),
                   vec!["h4", "h3", "h2", "h1"]);
        assert_eq!(sorted_hashes(SortSpec { key: SortKey::Name, desc: true }),
                   vec!["h1", "h2", "h3", "h4"]);
    }

    /// The name merge ignores case, because the per-shard `ORDER BY` does: Manticore's
    /// `collation_connection` is `libc_ci`, and `primary_filename` carries the
    /// filesystem's own case. A byte-wise merge puts every capitalised name first.
    #[test]
    fn merge_hits_sorted_by_name_is_case_insensitive() {
        let sources = vec![
            mk("testdata_1", vec![
                sortable("h1", 0, 0, 1, "README"),
                sortable("h2", 0, 0, 1, "apple.txt"),
            ]),
            mk("testdata_2", vec![
                sortable("h3", 0, 0, 1, "Banana.txt"),
                sortable("h4", 0, 0, 1, "zebra.txt"),
            ]),
        ];
        let order: Vec<String> = merge_hits_sorted(sources, SortSpec { key: SortKey::Name, desc: false }, 0, 10)
            .into_iter()
            .map(|h| h._source.file_hash)
            .collect();
        assert_eq!(order, vec!["h2", "h3", "h1", "h4"], "apple, Banana, README, zebra");
    }

    /// Pages must be disjoint and complete under every key — the property the acceptance
    /// checklist calls "no skipped or duplicated results at page boundaries".
    #[test]
    fn merge_hits_sorted_pages_are_disjoint_and_complete() {
        for key in SortKey::ALL {
            for desc in [true, false] {
                let sort = SortSpec { key, desc };
                let full = sorted_hashes(sort);
                let mut paged: Vec<String> = Vec::new();
                for page in 0..2 {
                    paged.extend(
                        merge_hits_sorted(sortable_sources(), sort, page * 2, 2)
                            .into_iter()
                            .map(|h| h._source.file_hash),
                    );
                }
                assert_eq!(paged, full, "{key:?} desc={desc}: paging changed the order");
                let unique: std::collections::BTreeSet<_> = paged.iter().collect();
                assert_eq!(unique.len(), paged.len(), "{key:?} desc={desc}: duplicate rows");
            }
        }
    }

    /// Relevance is `_score` descending. `merge_hits` is the same call with the default
    /// spec, so the unsorted-merge tests above pin this path too.
    #[test]
    fn merge_hits_sorted_falls_back_to_score_for_relevance() {
        let by_relevance = merge_hits_sorted(two_sources(), SortSpec::default(), 0, 10);
        let by_default = merge_hits(two_sources(), 0, 10);
        assert_eq!(ids(&by_relevance), ids(&by_default));
    }

    #[test]
    fn merge_facet_pairs_sums_and_resorts() {
        let s1 = vec![
            (serde_json::json!("alpha"), 5),
            (serde_json::json!("beta"), 3),
        ];
        let s2 = vec![
            (serde_json::json!("beta"), 10),
            (serde_json::json!("gamma"), 1),
        ];
        let merged = merge_facet_pairs(vec![s1, s2], 21);
        assert_eq!(
            merged,
            vec![
                (serde_json::json!("beta"), 13),
                (serde_json::json!("alpha"), 5),
                (serde_json::json!("gamma"), 1),
            ]
        );
    }

    #[test]
    fn merge_facet_pairs_truncates_to_limit() {
        let s1: Vec<(serde_json::Value, u64)> = (0..30).map(|i| (serde_json::json!(format!("k{i:02}")), 100 - i)).collect();
        let merged = merge_facet_pairs(vec![s1], 21);
        assert_eq!(merged.len(), 21);
        assert_eq!(merged[0], (serde_json::json!("k00"), 100));
        assert_eq!(merged[20], (serde_json::json!("k20"), 80));
    }

    #[test]
    fn merge_facet_pairs_key_present_in_only_one_source() {
        let s1 = vec![(serde_json::json!(7), 4)];
        let s2: Vec<(serde_json::Value, u64)> = vec![];
        assert_eq!(merge_facet_pairs(vec![s1, s2], 21), vec![(serde_json::json!(7), 4)]);
    }

    #[test]
    fn merge_facet_pairs_deterministic_on_ties() {
        let s1 = vec![(serde_json::json!("b"), 1), (serde_json::json!("a"), 1)];
        let merged = merge_facet_pairs(vec![s1], 21);
        assert_eq!(
            merged,
            vec![(serde_json::json!("a"), 1), (serde_json::json!("b"), 1)]
        );
    }

    #[tokio::test]
    async fn fan_out_drops_single_failure() {
        let targets = vec![
            FanoutTarget::collection("a"),
            FanoutTarget::collection("b"),
        ];
        let outcome = fan_out(targets, |t| async move {
            if t.collectionname() == "b" {
                anyhow::bail!("boom")
            }
            Ok(t.collectionname().to_string())
        })
        .await
        .unwrap();
        assert_eq!(outcome.results.len(), 1);
        assert_eq!(outcome.results[0].1, "a");
        assert!(outcome.is_partial());
        assert_eq!(outcome.failed, vec![FanoutTarget::collection("b")]);
    }

    #[tokio::test]
    async fn fan_out_errors_only_when_all_fail() {
        let targets = vec![FanoutTarget::collection("a"), FanoutTarget::collection("b")];
        let result: anyhow::Result<FanoutOutcome<String>> =
            fan_out(targets, |_| async move { anyhow::bail!("down") }).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn fan_out_empty_targets_is_ok() {
        let outcome: FanoutOutcome<String> = fan_out(vec![], |_| async move { anyhow::bail!("never") })
            .await
            .unwrap();
        assert!(outcome.results.is_empty());
        assert!(!outcome.is_partial());
    }

    #[test]
    fn merge_hits_keeps_same_file_hash_from_two_shards() {
        // The same content ingested into two datasets (or two collections) indexes
        // the same file_hash into two shards. The merged page currently shows such a
        // document twice — once per (collection_dataset, file_hash) identity. This
        // pins that behaviour; changing it must be a deliberate decision.
        let sources = vec![
            source("testdata", "testdata_1", vec![hit("td_a", "same", 10)]),
            source("testdata", "testdata_2", vec![hit("td_b", "same", 10)]),
        ];
        let merged = merge_hits(sources, 0, 10);
        assert_eq!(
            ids(&merged),
            vec![
                ("td_a".to_string(), "same".to_string()),
                ("td_b".to_string(), "same".to_string()),
            ],
            "one hit per (collection_dataset, file_hash), even when file_hash repeats"
        );
    }

    fn query_with_selection(selection: &[&str]) -> SearchQuery {
        let mut facet_filters = std::collections::BTreeMap::new();
        facet_filters.insert(
            "collection_dataset".to_string(),
            selection
                .iter()
                .map(|s| FacetOriginalValue::String(s.to_string()))
                .collect::<std::collections::BTreeSet<_>>(),
        );
        SearchQuery {
            query_string: "word".to_string(),
            facet_filters,
            ..Default::default()
        }
    }

    #[test]
    fn dataset_selection_reads_string_values_only() {
        let mut q = query_with_selection(&["testdata_testfiles"]);
        q.facet_filters
            .get_mut("collection_dataset")
            .unwrap()
            .insert(FacetOriginalValue::Int(7));
        assert_eq!(dataset_selection(&q), vec!["testdata_testfiles".to_string()]);
        assert!(dataset_selection(&query_with_selection(&[])).is_empty());
    }

    #[tokio::test]
    async fn resolve_selected_collections_maps_and_skips_unknown() {
        let selection = vec!["testdata_testfiles".to_string(), "gone_dataset".to_string()];
        let resolved = resolve_selected_collections(&selection, |d| {
            let d = d.to_string();
            async move {
                match d.as_str() {
                    "testdata_testfiles" => Ok("testdata".to_string()),
                    _ => anyhow::bail!("unknown collection_dataset: {d}"),
                }
            }
        })
        .await;
        assert_eq!(resolved, vec!["testdata".to_string()]);
    }

    #[test]
    fn intersect_permitted_with_selection_prunes_and_dedups() {
        let permitted = vec!["other".to_string(), "testdata".to_string()];
        // Selection resolves to testdata twice (two datasets, one collection) plus a
        // collection outside the permitted set.
        let selected = vec![
            "testdata".to_string(),
            "testdata".to_string(),
            "not_permitted".to_string(),
        ];
        assert_eq!(
            intersect_permitted_with_selection(permitted, &selected),
            vec!["testdata".to_string()]
        );
    }

    #[test]
    fn intersect_permitted_with_selection_empty_selection_prunes_everything() {
        // (The empty-selection early return lives in permitted_search_collections;
        // the intersection itself with an empty resolution yields nothing.)
        let permitted = vec!["testdata".to_string()];
        assert!(intersect_permitted_with_selection(permitted, &[]).is_empty());
    }

    #[test]
    fn fanout_target_shard_name_only_for_shards() {
        let shard = FanoutTarget::shard("testdata", "testdata_1");
        assert_eq!(shard.shard_name().unwrap(), "testdata_1");
        assert_eq!(shard.collectionname(), "testdata");
        assert_eq!(shard.label(), "testdata_1");
        let collection = FanoutTarget::collection("testdata");
        assert!(collection.shard_name().is_err());
        assert_eq!(collection.label(), "testdata");
    }
}
