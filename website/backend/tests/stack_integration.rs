//! Integration tests against the live docker stack.
//!
//! Run with the stack up and the canonical two-collection corpus ingested
//! (`main_services/verify-stack.sh`): `cargo test -p backend -- --ignored`.
//! They need ClickHouse on `CLICKHOUSE_URL` (default http://localhost:8123) and
//! Manticore on `MANTICORE_URL` (default http://127.0.0.1:9308).

use backend::db_utils::clickhouse_utils::{
    get_client_for_dataset, list_shards, resolve_collection, shard_generation,
};
use common::current_user::CurrentUser;
use common::search_query::SearchQuery;

/// Wall-time budget for a test without a `slow_` prefix. Override with
/// `HOOVER4_STACK_TEST_BUDGET_MS` on a machine where the stack is slower than this.
fn fast_budget() -> std::time::Duration {
    let ms = std::env::var("HOOVER4_STACK_TEST_BUDGET_MS")
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(5_000);
    std::time::Duration::from_millis(ms)
}

/// Start a fast test's clock. The returned guard prints the elapsed time and fails the
/// test if it went over budget — a drop guard rather than a call at the end, so an early
/// `?` or a panic still reports the number.
struct Budget {
    name: &'static str,
    start: std::time::Instant,
}

impl Budget {
    /// Call this AFTER taking [`GLOBAL_SEARCH_LOCK`], never before: a test queued behind
    /// the one slow test would otherwise blow its budget on lock-wait and report the
    /// wrong thing entirely.
    fn start(name: &'static str) -> Self {
        Budget { name, start: std::time::Instant::now() }
    }
}

impl Drop for Budget {
    fn drop(&mut self) {
        let elapsed = self.start.elapsed();
        eprintln!("[stack] {:<52} {:>7.2}s", self.name, elapsed.as_secs_f64());
        // Never turn a real failure into a budget failure: if the test is already
        // unwinding, its own message is the one worth reading.
        if !std::thread::panicking() && elapsed > fast_budget() {
            panic!(
                "{} took {:.2}s, over the {:.2}s budget — rename it slow_* or find out what got slower",
                self.name,
                elapsed.as_secs_f64(),
                fast_budget().as_secs_f64()
            );
        }
    }
}

fn admin_user() -> CurrentUser {
    CurrentUser {
        username: "integration-admin".to_string(),
        fullname: String::new(),
        email: String::new(),
        is_admin: true,
        is_guest: false,
        groups: vec![],
    }
}

/// Serialises the tests that assert the global partial flag: the missing-shard
/// test deliberately makes every search partial for its duration, which would
/// flunk the healthy-stack assertions of tests running concurrently.
static GLOBAL_SEARCH_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());

/// Wait until the in-process shard-state cache (TTL ~30 s, see
/// `clickhouse_utils::SHARD_STATE_TTL`) reflects the presence/absence of a shard.
/// Searches read the ledger through that cache, so a test that mutates the ledger
/// must hold the lock until the cache has converged in BOTH directions.
async fn wait_for_shard_cache(collection: &str, shard: &str, present: bool) {
    for _ in 0..25 {
        let shards = backend::db_utils::clickhouse_utils::list_shards(collection)
            .await
            .unwrap();
        if shards.iter().any(|s| s == shard) == present {
            return;
        }
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
    }
    panic!("shard-state cache did not converge: {shard} present={present}");
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn resolve_collection_for_known_dataset() {
    let _budget = Budget::start("resolve_collection_for_known_dataset");
    assert_eq!(
        resolve_collection("testdata_testfiles").await.unwrap(),
        "testdata"
    );
    assert_eq!(resolve_collection("other_emails").await.unwrap(), "other");
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn client_for_dataset_reads_collection_tables() {
    let _budget = Budget::start("client_for_dataset_reads_collection_tables");
    let client = get_client_for_dataset("testdata_testfiles").await.unwrap();
    let count: u64 = client
        .query("SELECT count() FROM vfs_files")
        .fetch_one()
        .await
        .unwrap();
    assert!(count > 0, "testdata_testfiles must have VFS rows");
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn shard_ledger_lists_shards_with_generation() {
    let _budget = Budget::start("shard_ledger_lists_shards_with_generation");
    let shards = list_shards("testdata").await.unwrap();
    assert!(!shards.is_empty(), "testdata must have at least one shard");
    assert!(shards.iter().all(|s| s.starts_with("testdata_")));
    let generation = shard_generation("testdata").await.unwrap();
    assert!(!generation.is_empty());
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn search_round_trip_returns_hits_from_fixture_collections() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("search_round_trip_returns_hits_from_fixture_collections");
    let query = SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
            ..Default::default()
    };
    let results = backend::api::search::search_for_results(&admin_user(), query, 0)
        .await
        .unwrap();
    assert!(!results.results.is_empty(), "expected search hits");
    assert!(!results.partial, "no shard may fail on a healthy stack");
    for hit in &results.results {
        // By COLLECTION, not by dataset: verify-stack.sh gains datasets over time (zips,
        // shapes) and an allowlist of dataset names turns every such addition into a
        // failure of a test that is about fan-out, not about the fixture list.
        assert!(
            hit.collection_dataset.starts_with("testdata_")
                || hit.collection_dataset.starts_with("other_"),
            "unexpected hit from {}",
            hit.collection_dataset
        );
    }

    let hit_count = backend::api::search::search_for_results_hit_count(
        &admin_user(),
        SearchQuery {
            collection_datasets: vec![],
            query_string: "the".to_string(),
            facet_filters: Default::default(),
            ..Default::default()
        },
    )
    .await
    .unwrap();
    assert!(!hit_count.partial, "no shard may fail on a healthy stack");
    assert!(hit_count.total >= results.results.len() as u64);
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn dataset_facet_selection_prunes_collections() {
    let _budget = Budget::start("dataset_facet_selection_prunes_collections");
    use common::search_result::FacetOriginalValue;
    let mut query = SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
            ..Default::default()
    };
    query.facet_filters.insert(
        "collection_dataset".to_string(),
        [FacetOriginalValue::String("other_emails".to_string())]
            .into_iter()
            .collect(),
    );
    let results = backend::api::search::search_for_results(&admin_user(), query, 0)
        .await
        .unwrap();
    assert!(
        !results.results.is_empty(),
        "selecting other_emails must still return hits (an empty page would pass the filter check vacuously)"
    );
    assert!(
        results
            .results
            .iter()
            .all(|hit| hit.collection_dataset == "other_emails"),
        "facet selection must restrict hits to the selected dataset"
    );

    // Complementary case: selecting testdata_testfiles must return only testdata
    // hits, none from `other`.
    let mut query = SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
            ..Default::default()
    };
    query.facet_filters.insert(
        "collection_dataset".to_string(),
        [FacetOriginalValue::String("testdata_testfiles".to_string())]
            .into_iter()
            .collect(),
    );
    let results = backend::api::search::search_for_results(&admin_user(), query, 0)
        .await
        .unwrap();
    assert!(!results.results.is_empty(), "selecting testdata_testfiles must still return hits");
    assert!(
        results
            .results
            .iter()
            .all(|hit| hit.collection_dataset == "testdata_testfiles"),
        "facet selection must restrict hits to the selected dataset"
    );
}


/// Pagination completeness. Walk every page of a multi-page result set and
/// assert the pages are disjoint and their union is exactly the hit count. With
/// the fixture corpus both pages still fit one per-shard fetch window, so this
/// pins the merge/window machinery and the stable ORDER BY; it becomes a full
/// regression test for the stable-prefix tiebreak once a shard holds more hits than one
/// fetch window.
#[tokio::test]
#[ignore = "needs live stack"]
async fn pagination_pages_are_disjoint_and_complete() {
    use std::collections::BTreeSet;

    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("pagination_pages_are_disjoint_and_complete");
    // The EMPTY query, not "the". Only 16 documents in the minimal verify-stack roots
    // contain "the", which is under PAGE_SIZE, so a term query here silently stops
    // exercising pagination whenever the fixture roots shrink. An empty query returns
    // every document: the largest result set available, and the one pagination is most
    // used on.
    let mk_query = SearchQuery::default;
    let hit_count = backend::api::search::search_for_results_hit_count(&admin_user(), mk_query())
        .await
        .unwrap();
    assert!(
        hit_count.total > common::search_const::PAGE_SIZE,
        "fixture corpus must span more than one page, got {}",
        hit_count.total
    );
    assert!(!hit_count.partial);

    let mut seen: BTreeSet<(String, String)> = BTreeSet::new();
    for page in 0..10_u64 {
        let results = backend::api::search::search_for_results(&admin_user(), mk_query(), page)
            .await
            .unwrap();
        assert!(!results.partial);
        if results.results.is_empty() {
            break;
        }
        for hit in &results.results {
            let id = (hit.collection_dataset.clone(), hit.file_hash.clone());
            assert!(
                seen.insert(id.clone()),
                "document {id:?} appeared on two pages (page {page})"
            );
        }
        if results.next_hash.is_none() {
            break;
        }
    }
    assert_eq!(
        seen.len() as u64,
        hit_count.total,
        "union of all pages must equal the hit count"
    );
}

/// Partial-failure round trip. Insert a bogus shard into one collection's
/// ledger (its Manticore tables do not exist), assert the search still returns
/// the surviving shards' hits with partial == true on results, hit count and
/// facets — then remove the row again.
///
/// `slow_`: it waits out the 30 s shard-state cache in both directions and then a
/// ClickHouse mutation, so it costs one to two minutes and no amount of tuning will make
/// it cheap. Run it with `./run-stack-tests.sh --slow`.
#[tokio::test]
#[ignore = "needs live stack"]
async fn slow_missing_shard_degrades_to_partial_results() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let client = backend::db_utils::clickhouse_utils::get_collection_client("other");
    // Start from a converged clean cache (a previous run may have poisoned it).
    wait_for_shard_cache("other", "other_9999", false).await;
    client
        .query("INSERT INTO manticore_shards (shard_name, shard_index, text_bytes, doc_count, is_open) VALUES (?, ?, ?, ?, ?)")
        .bind("other_9999")
        .bind(9999_u32)
        .bind(0_u64)
        .bind(0_u64)
        .bind(1_u8)
        .execute()
        .await
        .unwrap();
    // The searches below read the ledger through the 30 s shard-state cache:
    // wait until it shows the bogus shard, otherwise they would spuriously pass
    // on the stale clean state.
    wait_for_shard_cache("other", "other_9999", true).await;

    let mk_query = || SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
            ..Default::default()
    };
    // Run the assertions on captured outcomes so cleanup happens even on failure.
    let results = backend::api::search::search_for_results(&admin_user(), mk_query(), 0).await;
    let hit_count = backend::api::search::search_for_results_hit_count(&admin_user(), mk_query()).await;
    let facets = backend::api::search::search_string_facet(
        &admin_user(),
        mk_query(),
        "collection_dataset".to_string(),
        None,
    )
    .await;
    // Restricted to the degraded collection: the surviving shard's hits must
    // still come back (partial, not empty). The dataset selection travels as a
    // collection_dataset facet filter (that is what prunes fan-out targets).
    let mut restricted_query = mk_query();
    restricted_query.facet_filters.insert(
        "collection_dataset".to_string(),
        [common::search_result::FacetOriginalValue::String("other_emails".to_string())]
            .into_iter()
            .collect(),
    );
    let restricted = backend::api::search::search_for_results(&admin_user(), restricted_query, 0).await;

    // Cleanup: delete the bogus shard row and wait until the mutation has been
    // APPLIED (mutations_sync) — an asynchronously-pending delete would leak the
    // bogus shard into the next test's fan-out.
    client
        .query("ALTER TABLE manticore_shards DELETE WHERE shard_name = 'other_9999' SETTINGS mutations_sync = 1")
        .execute()
        .await
        .unwrap();
    for _ in 0..30 {
        let remaining: u64 = client
            .query("SELECT count() FROM manticore_shards FINAL WHERE shard_name = 'other_9999'")
            .fetch_one()
            .await
            .unwrap();
        if remaining == 0 {
            break;
        }
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
    }
    let leftover: u64 = client
        .query("SELECT count() FROM manticore_shards FINAL WHERE shard_name = 'other_9999'")
        .fetch_one()
        .await
        .unwrap();
    assert_eq!(leftover, 0, "cleanup failed: bogus shard row other_9999 still present");
    // Hold the lock until the shard-state cache has converged back, so no other
    // test's fan-out ever sees the bogus shard.
    wait_for_shard_cache("other", "other_9999", false).await;

    let results = results.unwrap();
    assert!(results.partial, "a missing shard table must mark results partial");
    assert!(
        !results.results.is_empty(),
        "surviving shards' hits must still come back"
    );
    let hit_count = hit_count.unwrap();
    assert!(hit_count.partial, "a missing shard table must mark the hit count partial");
    assert!(hit_count.total > 0);
    let facets = facets.unwrap();
    assert!(facets.partial, "a missing shard table must mark facets partial");

    let restricted = restricted.unwrap();
    assert!(restricted.partial, "the degraded collection must be marked partial");
    assert!(
        !restricted.results.is_empty(),
        "the surviving shard's hits must still come back"
    );
    assert!(
        restricted.results.iter().all(|h| h.collection_dataset == "other_emails"),
        "a dataset-restricted search may only return that dataset's hits"
    );
}

/// Permission isolation. A non-admin, non-guest user whose group has access
/// to exactly one collection must get zero hits from the other, and the fan-out
/// must not even target the other collection's shards.
#[tokio::test]
#[ignore = "needs live stack"]
async fn permissions_restrict_search_to_granted_collections() {
    use backend::db_auth::{collections as db_collections, groups};

    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("permissions_restrict_search_to_granted_collections");
    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("i10-user-{suffix}");
    let groupname = format!("i10-group-{suffix}");

    let now = time::OffsetDateTime::now_utc();
    groups::upsert_group(groups::GroupRow {
        groupname: groupname.clone(),
        fullname: "isolation test group".to_string(),
        created_at: now,
        updated_at: now,
        is_deleted: 0,
    })
    .await
    .unwrap();
    groups::upsert_membership(groups::MembershipRow {
        username: username.clone(),
        groupname: groupname.clone(),
        is_group_admin: false,
        origin: "test".to_string(),
        created_at: now,
        updated_at: now,
        is_deleted: 0,
    })
    .await
    .unwrap();
    db_collections::grant_permission(&groupname, "other").await.unwrap();

    let user = CurrentUser {
        username: username.clone(),
        fullname: String::new(),
        email: String::new(),
        is_admin: false,
        is_guest: false,
        groups: vec![groupname.clone()],
    };
    let query = SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
            ..Default::default()
    };

    // Capture outcomes first so cleanup always runs.
    let permitted = backend::api::search::fanout::permitted_search_collections(&user, &query).await;
    let results = backend::api::search::search_for_results(&user, query.clone(), 0).await;

    // Cleanup: revoke the permission, membership and group (soft deletes).
    db_collections::revoke_permission(&groupname, "other").await.unwrap();
    groups::soft_delete_membership(&username, &groupname).await.unwrap();
    groups::soft_delete_group(&groupname).await.unwrap();

    assert_eq!(
        permitted.unwrap(),
        vec!["other".to_string()],
        "the fan-out must only target the granted collection"
    );
    let results = results.unwrap();
    assert!(
        !results.results.is_empty(),
        "the user must still see hits from the granted collection"
    );
    assert!(
        results
            .results
            .iter()
            .all(|hit| hit.collection_dataset == "other_emails"),
        "no hit may come from a collection the user's group cannot read"
    );
}

// ---------------------------------------------------------------------------------
// Fixture-bound stack tests.
//
// Every one of these is bound to a named fixture directory ingested by
// `main_services/verify-stack.sh`, and every one asserts a property of that fixture
// rather than a row count of the whole corpus — a count changes whenever a root is
// added and says nothing when it does.
// ---------------------------------------------------------------------------------

use common::search_query::{RangeFilter, SortKey, SortSpec};

const TESTFILES: &str = "testdata_testfiles";
const SHAPES: &str = "testdata_shapes";

fn dated_query(min: Option<i64>, max: Option<i64>, include_unknown: bool) -> SearchQuery {
    let mut query = SearchQuery::default();
    query
        .range_filters
        .insert("dates".to_string(), RangeFilter { min, max, include_unknown });
    query
}

async fn hits(query: SearchQuery) -> u64 {
    let count = backend::api::search::search_for_results_hit_count(&admin_user(), query)
        .await
        .unwrap();
    assert!(!count.partial, "no shard may fail on a healthy stack");
    count.total
}

/// A date range narrows the corpus, and the three range shapes COVER it — a low-pass, a
/// high-pass at the same instant and the undated leave nothing out.
///
/// Not a partition, and that is the point. A date filter is an interval-overlap test
/// against the document's whole date SPAN (`date_min <= hi AND date_max >= lo`, see
/// `search_sql::range_predicate`) rather than `ANY(dates) BETWEEN`, because Manticore
/// cannot evaluate `ANY(mva)` across the pages/meta JOIN.
/// So a document whose span crosses the split satisfies both halves and is counted twice,
/// which is the honest answer to both questions: it does have dates below AND above.
/// `other_emails/cap33.pdf` (2003-03 … 2016-06) is that document here.
#[tokio::test]
#[ignore = "needs live stack"]
async fn range_filter_covers_the_corpus_and_straddlers_are_in_both_halves() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("range_filter_covers_the_corpus_and_straddlers_are_in_both_halves");

    let all = hits(SearchQuery::default()).await;
    assert!(all > 0, "the fixture corpus must be searchable with no query");

    // 2010-01-01. The corpus straddles it: `stanley.ec02.pdf` (2002/2003), `sample (1).doc`
    // (2007) and the oldest emails (2001/2003) sit below, `easychair.odt` (2014/2016), the
    // zip and shapes fixtures (2019/2020) and the rest of the emails above. Do not move
    // it to 1990-01-01: nothing in the corpus predates 1990, so that split puts every
    // document on one side and the test asserts nothing.
    let split = 1_262_304_000_i64;
    // Both halves CLOSE on `split`, deliberately: the overlap between them is then exactly
    // "spans that contain that instant", which is a query — the single-instant band below.
    let before = hits(dated_query(None, Some(split), false)).await;
    let after = hits(dated_query(Some(split), None, false)).await;
    let unknown = hits(dated_query(None, None, true)).await;
    let straddling = hits(dated_query(Some(split), Some(split), false)).await;

    assert!(before > 0, "the 2000s documents must land below the split");
    assert!(after > 0, "the 2010s documents must land above the split");
    assert!(before < all && after < all, "a range must narrow, not pass everything through");
    assert!(
        straddling > 0,
        "the corpus must contain a document whose date SPAN crosses {split} — \
         `other_emails/cap33.pdf` runs 2003-03 to 2016-06 — or this test proves nothing \
         about overlap semantics"
    );
    assert_eq!(
        before + after + unknown,
        all + straddling,
        "the two halves and the undated must COVER the corpus, overlapping only on the \
         documents whose date span contains the split ({before} + {after} + {unknown} != \
         {all} + {straddling}). A date range is an interval-overlap test over the whole \
         span, not `ANY(dates) BETWEEN`, so a document like `cap33.pdf` (2003…2016) is \
         genuinely in BOTH halves; a sum that is too SMALL means a document fell out of \
         every bucket, which is the real bug this guards"
    );

    // Every double-counted document is one of the straddlers, and each is counted twice —
    // so nothing can hide behind the excess.
    assert!(
        before >= straddling && after >= straddling,
        "each straddler is in both halves: {before} / {after} cannot be below {straddling}"
    );

    // The band-pass between them is a subset of both.
    let band = hits(dated_query(Some(split - 86_400), Some(split + 86_400), false)).await;
    assert!(band <= before + after);
}

/// `Unknown only` returns exactly the documents with no confirmed date — no range, and
/// nothing that a range would also return.
#[tokio::test]
#[ignore = "needs live stack"]
async fn unknown_dates_only() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("unknown_dates_only");

    let all = hits(SearchQuery::default()).await;
    let unknown = hits(dated_query(None, None, true)).await;
    // An all-time range excludes the undated: `date_min = DATE_UNKNOWN` is i64::MIN and
    // the open low end is deliberately MIN + 1.
    let dated = hits(dated_query(None, None, false)).await;
    assert_eq!(
        dated, all,
        "an inactive filter must not narrow anything"
    );
    let all_time = hits(dated_query(Some(i64::MIN + 1), Some(i64::MAX), false)).await;
    assert_eq!(
        all_time + unknown,
        all,
        "the dated and the undated must be an exact partition ({all_time} + {unknown} != {all})"
    );
    assert!(unknown > 0, "the fixture corpus must contain undated documents");
}

/// Sorting by size is monotonic across the whole result page, which is the property the
/// cross-shard merge exists to preserve. The sizes are read back from ClickHouse rather
/// than from the hit, because the hit does not carry one — so this checks the ORDER BY
/// and the merge against an independent source of truth.
#[tokio::test]
#[ignore = "needs live stack"]
async fn sort_by_size_is_monotonic_across_shards() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("sort_by_size_is_monotonic_across_shards");

    for desc in [true, false] {
        let query = SearchQuery {
            sort: SortSpec { key: SortKey::FileSize, desc },
            ..SearchQuery::default()
        };
        let results = backend::api::search::search_for_results(&admin_user(), query, 0)
            .await
            .unwrap();
        assert!(!results.partial);
        assert!(results.results.len() > 3, "need several hits to see an order at all");

        let mut sizes = Vec::new();
        for hit in &results.results {
            let client = get_client_for_dataset(&hit.collection_dataset).await.unwrap();
            let size: Vec<i64> = client
                .query(
                    "SELECT toInt64(max(file_size_bytes)) FROM vfs_files FINAL
                     WHERE collection_dataset = ? AND hash = ?",
                )
                .bind(&hit.collection_dataset)
                .bind(&hit.file_hash)
                .fetch_all()
                .await
                .unwrap();
            sizes.push(size.into_iter().next().unwrap_or(-1));
        }
        let ordered = sizes.windows(2).all(|p| if desc { p[0] >= p[1] } else { p[0] <= p[1] });
        assert!(ordered, "sort by size desc={desc} produced {sizes:?}");
    }
}

/// A word that appears only in a FILENAME finds the document. `pdf-doc-txt` is the only
/// fixture whose filenames contain `easychair`, which is why it is the default root.
#[tokio::test]
#[ignore = "needs live stack"]
async fn filename_only_match() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("filename_only_match");

    let query = SearchQuery { query_string: "easychair".to_string(), ..SearchQuery::default() };
    let results = backend::api::search::search_for_results(&admin_user(), query, 0)
        .await
        .unwrap();
    assert!(!results.partial);
    let titles: Vec<&str> = results.results.iter().map(|h| h.title.as_str()).collect();
    assert!(
        titles.iter().any(|t| t.contains("easychair.docx")),
        "the .docx is matched by its NAME, not its text — the filename_index row is what \
         makes that work, and its absence is invisible in every other check: {titles:?}"
    );
    // `easychair` is in the .docx's BODY too (the office_xml extractor reads it), so this
    // query is the wrong one to ask about the flag: it must be false here.
    let docx = results
        .results
        .iter()
        .find(|h| h.title.contains("easychair.docx"))
        .expect("the .docx is in the results");
    assert!(
        !docx.matched_by_filename,
        "easychair.docx has the word in its text as well as its name"
    );

    // `readme` appears in no document's text anywhere in the corpus, so /README is a
    // filename-only hit and the card must say so instead of echoing the title as a
    // snippet. This is the assertion that pins O4.
    let query = SearchQuery { query_string: "readme".to_string(), ..SearchQuery::default() };
    let results = backend::api::search::search_for_results(&admin_user(), query, 0)
        .await
        .unwrap();
    // Case-insensitively, because `primary_filename` now keeps the filesystem's own case
    // (`README`) and a corpus indexed before that change still holds the folded spelling
    // (`readme`). Which one it is says nothing about whether the filename row works.
    let readme = results
        .results
        .iter()
        .find(|h| h.title.eq_ignore_ascii_case("readme"))
        .unwrap_or_else(|| {
            panic!(
                "README is matched by its name only: {:?}",
                results.results.iter().map(|h| &h.title).collect::<Vec<_>>()
            )
        });
    assert!(
        readme.matched_by_filename,
        "the only matching pages row for README is the synthetic filename row, so its \
         body snippet would be the filename spelled out again"
    );
}

/// In-folder search is scoped to the subtree it was asked about, and reaches through it.
#[tokio::test]
#[ignore = "needs live stack"]
async fn in_folder_search_is_scoped() {
    let _budget = Budget::start("in_folder_search_is_scoped");
    use common::vfs::make_node_key;

    // The whole folder name, because that is what a person types. Hyphens are fine; what
    // is NOT is a leading token shorter than the table's `min_infix_len` of 3 —
    // `*a-child-dir-767*` matches nothing while `*many-a-child-dir-767*` and
    // `*child-dir-767*` both match. The fixture's folders are numbered 666..999, so a
    // pattern naming a number outside that range correctly finds nothing.
    let wide = make_node_key(SHAPES, "", "/the-directory");
    let matches = backend::api::vfs::vfs_search_in_folder(
        &admin_user(),
        SHAPES.to_string(),
        wide.clone(),
        "many-a-child-dir-767".to_string(),
        500,
    )
    .await
    .unwrap();
    assert!(!matches.nodes.is_empty(), "the wide folder must contain matching children");
    assert!(
        matches.nodes.iter().all(|n| n.path.starts_with("/the-directory/")),
        "a search rooted at /the-directory may not return anything outside it"
    );

    // The same pattern rooted at the sibling subtree finds nothing: that is the scoping.
    let deep = make_node_key(SHAPES, "", "/deep-stuff");
    let elsewhere = backend::api::vfs::vfs_search_in_folder(
        &admin_user(),
        SHAPES.to_string(),
        deep,
        "many-a-child-dir-767".to_string(),
        500,
    )
    .await
    .unwrap();
    assert!(
        elsewhere.nodes.is_empty(),
        "the pattern lives under /the-directory only, /deep-stuff is 1..42: {:?}",
        elsewhere.nodes.iter().map(|n| &n.path).collect::<Vec<_>>()
    );
}

/// The VFS endpoints refuse a dataset the caller's group has no grant for. Without this
/// the structure index is a way around `permissions::sanitize_query` — it answers
/// "what files exist" for anyone who can name a dataset.
#[tokio::test]
#[ignore = "needs live stack"]
async fn vfs_endpoints_respect_permissions() {
    let _budget = Budget::start("vfs_endpoints_respect_permissions");
    use backend::db_auth::{collections as db_collections, groups};
    use common::vfs::dataset_root_key;

    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("vfs-user-{suffix}");
    let groupname = format!("vfs-group-{suffix}");
    let now = time::OffsetDateTime::now_utc();

    groups::upsert_group(groups::GroupRow {
        groupname: groupname.clone(),
        fullname: "VFS permission test group".to_string(),
        created_at: now,
        updated_at: now,
        is_deleted: 0,
    })
    .await
    .unwrap();
    groups::upsert_membership(groups::MembershipRow {
        username: username.clone(),
        groupname: groupname.clone(),
        is_group_admin: false,
        origin: "test".to_string(),
        created_at: now,
        updated_at: now,
        is_deleted: 0,
    })
    .await
    .unwrap();
    db_collections::grant_permission(&groupname, "other").await.unwrap();

    let user = CurrentUser {
        username: username.clone(),
        fullname: String::new(),
        email: String::new(),
        is_admin: false,
        is_guest: false,
        groups: vec![groupname.clone()],
    };

    // Capture outcomes before cleanup so a failure cannot leak a group.
    let granted = backend::api::vfs::vfs_tree_children(
        &user,
        "other_emails".to_string(),
        dataset_root_key("other_emails"),
        50,
        0,
    )
    .await;
    let denied_children = backend::api::vfs::vfs_tree_children(
        &user,
        TESTFILES.to_string(),
        dataset_root_key(TESTFILES),
        50,
        0,
    )
    .await;
    let denied_path = backend::api::vfs::vfs_tree_path_to(
        &user,
        TESTFILES.to_string(),
        dataset_root_key(TESTFILES),
    )
    .await;
    let denied_search = backend::api::vfs::vfs_search_in_folder(
        &user,
        TESTFILES.to_string(),
        dataset_root_key(TESTFILES),
        "easychair".to_string(),
        50,
    )
    .await;

    db_collections::revoke_permission(&groupname, "other").await.unwrap();
    groups::soft_delete_membership(&username, &groupname).await.unwrap();
    groups::soft_delete_group(&groupname).await.unwrap();

    assert!(granted.is_ok(), "the granted collection must still be browsable: {granted:?}");
    assert!(denied_children.is_err(), "vfs_tree_children must refuse an ungranted dataset");
    assert!(denied_path.is_err(), "vfs_tree_path_to must refuse an ungranted dataset");
    assert!(denied_search.is_err(), "vfs_search_in_folder must refuse an ungranted dataset");
}

/// Structure queries never enter the search result cache. The tree changes while
/// ingestion runs and a stale tree is worse than a slow one, so `api/vfs/tree.rs` uses
/// the uncached primitive on purpose — a change that routed it through the cached one
/// would be invisible except as folders that stop appearing.
#[tokio::test]
#[ignore = "needs live stack"]
async fn structure_queries_are_not_cached() {
    let _budget = Budget::start("structure_queries_are_not_cached");
    use common::vfs::dataset_root_key;

    let client = backend::db_utils::clickhouse_utils::get_global_client();
    let count_vfs_rows = || async {
        let rows: Vec<u64> = client
            .query("SELECT count() FROM search_manticore_cache WHERE position(query_string, '_vfs') > 0")
            .fetch_all()
            .await
            .unwrap();
        rows.into_iter().next().unwrap_or(0)
    };

    let before = count_vfs_rows().await;
    for _ in 0..2 {
        backend::api::vfs::vfs_tree_children(
            &admin_user(),
            SHAPES.to_string(),
            dataset_root_key(SHAPES),
            50,
            0,
        )
        .await
        .unwrap();
    }
    assert_eq!(
        count_vfs_rows().await,
        before,
        "a query against a <collection>_vfs table was written to the search cache"
    );
}

/// The breadcrumb's chain: `vfs_tree_path_to` walks from the dataset root down to a node,
/// in order, crossing container boundaries. This is what replaced `PathDescriptor`'s
/// single `container_hash`, which showed one hop of a nested archive and lost the rest.
#[tokio::test]
#[ignore = "needs live stack"]
async fn vfs_tree_path_to_walks_the_whole_chain() {
    let _budget = Budget::start("vfs_tree_path_to_walks_the_whole_chain");
    use common::vfs::make_node_key;

    // 42 levels of `deep-stuff/1/2/…`, well past the tree's MAX_VISIBLE_ANCESTORS (8)
    // and the breadcrumb's MAX_CRUMBS_SHOWN (3).
    let deep_path = format!("/deep-stuff{}", (1..=20).map(|n| format!("/{n}")).collect::<String>());
    let chain = backend::api::vfs::vfs_tree_path_to(
        &admin_user(),
        SHAPES.to_string(),
        make_node_key(SHAPES, "", &deep_path),
    )
    .await
    .unwrap();

    assert!(chain.len() > 8, "the deep fixture must exceed the elision threshold: {}", chain.len());
    assert_eq!(chain.first().unwrap().node_key, make_node_key(SHAPES, "", "/"), "root first");
    assert_eq!(chain.last().unwrap().path, deep_path, "target last");
    // Every hop is the parent of the next. A set would have lost this, which is why the
    // endpoint walks `parent_key` instead of reading `ancestor_keys`.
    for pair in chain.windows(2) {
        assert_eq!(pair[1].parent_key, pair[0].node_key, "chain is not contiguous: {pair:?}");
    }
    // Depth is strictly increasing, so the breadcrumb renders top-to-bottom as given.
    assert!(chain.windows(2).all(|p| p[1].depth > p[0].depth));
}

/// The chain CROSSES a container boundary. This is the case `PathDescriptor` cannot
/// represent — it carries one `container_hash`, so the archive the container sits in is
/// simply absent from it — and the whole reason the breadcrumb was rewritten.
#[tokio::test]
#[ignore = "needs live stack"]
async fn vfs_tree_path_to_crosses_a_container() {
    let _budget = Budget::start("vfs_tree_path_to_crosses_a_container");
    use common::vfs::{VfsNodeKind, make_node_key};

    // The hash of `parent.zip`, read from the fixture rather than hardcoded.
    let outer = backend::api::vfs::vfs_tree_children(
        &admin_user(),
        "testdata_zips".to_string(),
        make_node_key("testdata_zips", "", "/location-1"),
        50,
        0,
    )
    .await
    .unwrap();
    let zip = outer
        .nodes
        .iter()
        .find(|n| n.kind == VfsNodeKind::Container)
        .expect("/location-1 must hold a container");

    let inside = make_node_key("testdata_zips", &zip.file_hash, "/");
    let chain = backend::api::vfs::vfs_tree_path_to(
        &admin_user(),
        "testdata_zips".to_string(),
        inside.clone(),
    )
    .await
    .unwrap();

    let paths: Vec<&str> = chain.iter().map(|n| n.path.as_str()).collect();
    assert_eq!(
        paths,
        ["/", "/location-1", "/location-1/parent.zip", "/"],
        "root, the folder, the archive, and the archive's own root"
    );
    assert_eq!(chain.last().unwrap().node_key, inside);
    for pair in chain.windows(2) {
        assert_eq!(pair[1].parent_key, pair[0].node_key);
    }
}

/// One hash, two paths, each with its own resolved chain.
///
/// This is the whole reason the FileLocations panel exists: `get_file_path` answers with
/// the first path and the title bar shows only that, so a document that is in two places
/// looks like a document that is in one. `parent.zip` is the fixture that is deliberately
/// at `/location-1` and `/location-2`.
#[tokio::test]
#[ignore = "needs live stack"]
async fn file_locations_lists_every_path_of_a_hash() {
    let _budget = Budget::start("file_locations_lists_every_path_of_a_hash");
    use common::search_result::DocumentIdentifier;
    use common::vfs::{VfsNodeKind, make_node_key};

    let outer = backend::api::vfs::vfs_tree_children(
        &admin_user(),
        "testdata_zips".to_string(),
        make_node_key("testdata_zips", "", "/location-1"),
        50,
        0,
    )
    .await
    .unwrap();
    let zip = outer
        .nodes
        .iter()
        .find(|n| n.kind == VfsNodeKind::Container)
        .expect("/location-1 must hold a container");

    let locations = backend::api::documents::get_file_path::get_file_locations(
        &admin_user(),
        DocumentIdentifier {
            collection_dataset: "testdata_zips".to_string(),
            file_hash: zip.file_hash.clone(),
        },
    )
    .await
    .unwrap();

    assert_eq!(locations.total, 2, "parent.zip is ingested at two paths");
    let paths: Vec<&str> = locations.locations.iter().map(|l| l.path.as_str()).collect();
    assert_eq!(paths, ["/location-1/parent.zip", "/location-2/parent.zip"]);
    for location in &locations.locations {
        // Root, the folder, the file: without the chain the panel would have nothing to
        // link the intermediate folders to.
        let chain: Vec<&str> = location.chain.iter().map(|n| n.path.as_str()).collect();
        assert_eq!(chain.len(), 3, "{location:?}");
        assert_eq!(chain[0], "/");
        assert_eq!(chain[2], location.path);
        assert_eq!(location.file_name(), "parent.zip");
        assert_eq!(location.parent_descriptor().path, chain[1]);
    }
}

/// The fixture the tree's two caps are measured against actually has the shape they need.
/// If this fails, `elide_ancestors` and `window_siblings` are still unit-tested but
/// nothing on screen ever exercises them.
#[tokio::test]
#[ignore = "needs live stack"]
async fn the_shapes_fixture_is_deep_and_wide() {
    let _budget = Budget::start("the_shapes_fixture_is_deep_and_wide");
    use common::vfs::make_node_key;

    let wide = backend::api::vfs::vfs_tree_children(
        &admin_user(),
        SHAPES.to_string(),
        make_node_key(SHAPES, "", "/the-directory"),
        500,
        0,
    )
    .await
    .unwrap();
    assert!(
        wide.total > 20,
        "the wide fixture must exceed 2 * MAX_SIBLINGS_EACH_SIDE, got {}",
        wide.total
    );
    let folders = wide.nodes.iter().filter(|n| n.kind.is_folder_like()).count();
    assert!(folders > 20, "and they must be FOLDERS — the tree renders nothing else: {folders}");
}

/// The histogram bins the corpus, puts the active cutoffs on bin edges, and counts the
/// query WITHOUT its own date filter.
#[tokio::test]
#[ignore = "needs live stack"]
async fn date_histogram_bins_the_corpus_and_honours_the_cutoffs() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("date_histogram_bins_the_corpus_and_honours_the_cutoffs");

    let unfiltered = backend::api::search::search_date_histogram(&admin_user(), SearchQuery::default())
        .await
        .unwrap();
    assert!(!unfiltered.partial);
    assert!(!unfiltered.buckets.is_empty(), "the fixture corpus has dated documents");
    assert!(
        unfiltered.buckets.len() <= backend::api::search::HISTOGRAM_MAX_BUCKETS,
        "{} bins is over the cap",
        unfiltered.buckets.len()
    );
    // Bins tile the domain: contiguous, strictly increasing, ending where they say.
    assert_eq!(unfiltered.buckets.first().unwrap().start, unfiltered.domain_start);
    assert_eq!(unfiltered.buckets.last().unwrap().end, unfiltered.domain_end);
    for pair in unfiltered.buckets.windows(2) {
        assert_eq!(pair[0].end, pair[1].start, "a gap between bins loses documents");
    }

    // Every dated document is in exactly one bin, and the undated are in none of them.
    let all = hits(SearchQuery::default()).await;
    assert_eq!(
        unfiltered.total_count() + unfiltered.unknown_count,
        all,
        "the bins plus the undated must be the whole corpus"
    );

    // A cutoff inside the domain becomes a bin edge, and the counts do NOT change:
    // the histogram must not filter itself.
    let split = unfiltered.buckets[unfiltered.buckets.len() / 2].start;
    let filtered =
        backend::api::search::search_date_histogram(&admin_user(), dated_query(Some(split), None, false))
            .await
            .unwrap();
    assert!(
        filtered.buckets.iter().any(|b| b.start == split),
        "the cutoff {split} must land on a bin edge"
    );
    assert_eq!(
        filtered.total_count(),
        unfiltered.total_count(),
        "the histogram counted its own date filter — the bars would collapse to the selection"
    );
}
