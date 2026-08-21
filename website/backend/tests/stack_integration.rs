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
        // The whole facet. What is under test is a fan-out with a shard missing, and a
        // restricted facet would narrow the answer for a reason that has nothing to do
        // with the missing shard.
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
const EMAILS: &str = "other_emails";

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
    // snippet. This is the assertion that pins the filename-only hit card.
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
        false,
    )
    .await;
    let denied_children = backend::api::vfs::vfs_tree_children(
        &user,
        TESTFILES.to_string(),
        dataset_root_key(TESTFILES),
        50,
        0,
        false,
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
            false,
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
        false,
    )
    .await
    .unwrap();
    let zip = outer
        .nodes
        .iter()
        .find(|n| n.kind == VfsNodeKind::Container)
        .expect("/location-1 must hold a container");

    // What is inside the archive hangs off the archive FILE. There is no `/` node in
    // between — expanding an archive shows its contents, not a virtual root the user has
    // to open again — so the archive's own node key is what its members' parent is.
    let members = backend::api::vfs::vfs_tree_children(
        &admin_user(),
        "testdata_zips".to_string(),
        zip.node_key.clone(),
        50,
        0,
        false,
    )
    .await
    .unwrap();
    assert!(!members.nodes.is_empty(), "parent.zip has members");
    for member in &members.nodes {
        assert_eq!(member.container_hash, zip.file_hash);
        assert_ne!(member.path, "/", "the synthetic container root is not a node");
        assert_eq!(member.parent_key, zip.node_key);
    }

    let inside = members.nodes[0].node_key.clone();
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
        ["/", "/location-1", "/location-1/parent.zip", members.nodes[0].path.as_str()],
        "root, the folder, the archive, and what is in it — no `/` crumb"
    );
    assert_eq!(chain.last().unwrap().node_key, inside);
    for pair in chain.windows(2) {
        assert_eq!(pair[1].parent_key, pair[0].node_key);
    }
}

/// `folders_only` drops plain files from the page AND from `total`, so the tree's
/// "N more…" row can only ever promise rows the tree will actually draw.
///
/// The second half is the one that bites in the field: `ORDER BY kind ASC` sorts
/// `dir`(0), `file`(1), `container`(2), so a folder with more files than the page size
/// never shows its archives at all — the files fill the page and the containers behind
/// them are starved. The fixture level is FOUND rather than named: an email with an
/// attachment and a couple of inline parts is exactly that shape in miniature, and which
/// of `other_emails`' messages has it is not something this test should hardcode.
#[tokio::test]
#[ignore = "needs live stack"]
async fn folders_only_counts_and_returns_only_what_the_tree_draws() {
    let _budget = Budget::start("folders_only_counts_and_returns_only_what_the_tree_draws");
    use common::vfs::{VfsNodeKind, VfsTreeChildren, dataset_root_key};

    async fn children(node_key: &str, folders_only: bool, limit: u64) -> VfsTreeChildren {
        backend::api::vfs::vfs_tree_children(
            &admin_user(), "other_emails".to_string(), node_key.to_string(),
            limit, 0, folders_only,
        )
        .await
        .unwrap()
    }

    // A level holding plain files AND something folder-like.
    let mut mixed = None;
    let root = children(&dataset_root_key("other_emails"), false, 500).await;
    for candidate in root.nodes.iter().filter(|n| n.kind.is_folder_like()) {
        let level = children(&candidate.node_key, false, 500).await;
        let folders = level.nodes.iter().filter(|n| n.kind.is_folder_like()).count() as u64;
        if folders > 0 && folders < level.total {
            mixed = Some((candidate.node_key.clone(), level, folders));
            break;
        }
    }
    let (node_key, everything, folder_like) =
        mixed.expect("other_emails must hold one message with both an attachment and files");
    let files = everything.total - folder_like;

    let folders = children(&node_key, true, 500).await;
    assert_eq!(folders.total, folder_like, "total counts what the tree draws, not files");
    assert!(folders.nodes.iter().all(|n| n.kind.is_folder_like()));

    // A page exactly as big as the file count. Without the flag the containers are
    // starved off the end of it; with the flag they are the only thing on it.
    let starved = children(&node_key, false, files).await;
    assert_eq!(
        starved.nodes.iter().filter(|n| n.kind == VfsNodeKind::Container).count(),
        0,
        "the unfiltered page is the starvation this flag exists to fix"
    );
    let first_page = children(&node_key, true, files).await;
    assert_eq!(
        first_page.nodes.iter().filter(|n| n.kind.is_folder_like()).count() as u64,
        folder_like,
        "every container is on the FIRST page once the files are gone"
    );
}

/// The "N more…" row's arithmetic: pages tile the level, and no row arrives twice.
///
/// The row raises an OFFSET and appends. It used to raise the limit, which the server
/// clamped straight back to the page it had already sent — so the row could not resolve
/// for any folder in any dataset. `shapes/the-directory` has 334 subfolders, which is
/// three pages of 150 with a short last one.
#[tokio::test]
#[ignore = "needs live stack"]
async fn paging_a_wide_level_tiles_it_exactly_once() {
    let _budget = Budget::start("paging_a_wide_level_tiles_it_exactly_once");
    use common::vfs::make_node_key;
    use std::collections::BTreeSet;

    let node = make_node_key(SHAPES, "", "/the-directory");
    let page_size = 150u64;
    let whole = backend::api::vfs::vfs_tree_children(
        &admin_user(), SHAPES.to_string(), node.clone(), 2000, 0, true,
    )
    .await
    .unwrap();
    assert!(whole.total > 2 * page_size, "the fixture must need three pages: {}", whole.total);
    assert_eq!(whole.nodes.len() as u64, whole.total, "one page holds the level");

    let mut seen: Vec<String> = Vec::new();
    let mut offset = 0u64;
    while offset < whole.total {
        let page = backend::api::vfs::vfs_tree_children(
            &admin_user(), SHAPES.to_string(), node.clone(), page_size, offset, true,
        )
        .await
        .unwrap();
        assert_eq!(page.total, whole.total, "total does not move as the caller pages");
        assert!(!page.nodes.is_empty(), "a page inside the total is never empty");
        offset += page.nodes.len() as u64;
        seen.extend(page.nodes.into_iter().map(|n| n.node_key));
    }

    let unique: BTreeSet<&String> = seen.iter().collect();
    assert_eq!(unique.len(), seen.len(), "a row came back on two pages");
    assert_eq!(
        unique,
        whole.nodes.iter().map(|n| &n.node_key).collect::<BTreeSet<&String>>(),
        "the union of the pages is the whole level"
    );
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
        false,
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
        false,
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

/// The Email source names a page that actually holds the parsed body.
///
/// `text_content.page_id` is 1-based and the email preview renders the body by asking
/// `get_document_text_by_id_and_source` for a single page. A page number of 0 matches no
/// row, so the whole body of every email comes back as "document not found!" — which is
/// what a hardcoded 0 in the preview did. Asserting the range alone is not enough: the
/// page the source names has to resolve to text, which is the half a unit test cannot see.
#[tokio::test]
#[ignore = "needs live stack"]
async fn email_source_names_a_page_that_holds_the_body() {
    let _budget = Budget::start("email_source_names_a_page_that_holds_the_body");
    use common::document_sources::{DocumentSourceItem, EMAIL_TEXT_EXTRACTOR};
    use common::search_result::DocumentIdentifier;

    let client = get_client_for_dataset(EMAILS).await.unwrap();
    let file_hash: String = client
        .query(
            "SELECT file_hash FROM text_content \
             WHERE collection_dataset = ? AND extracted_by = ? LIMIT 1",
        )
        .bind(EMAILS)
        .bind(EMAIL_TEXT_EXTRACTOR)
        .fetch_one()
        .await
        .expect("other_emails must hold at least one parsed email body");

    let document = DocumentIdentifier {
        collection_dataset: EMAILS.to_string(),
        file_hash,
    };
    let sources = backend::api::documents::get_document_sources::get_document_sources(
        &admin_user(),
        document.clone(),
    )
    .await
    .unwrap();
    let email = sources
        .iter()
        .find_map(|source| match source {
            DocumentSourceItem::Email(email) => Some(email.clone()),
            _ => None,
        })
        .expect("a document with an email_parser body offers an Email source");

    assert!(email.has_body, "this document has an email_parser row: {email:?}");
    assert!(
        email.min_page >= 1,
        "page_id is 1-based, so {} names no row at all",
        email.min_page
    );
    assert!(email.max_page >= email.min_page, "{email:?}");

    let body = backend::api::documents::search_document_text::get_document_text_by_id_and_source(
        &admin_user(),
        document,
        EMAIL_TEXT_EXTRACTOR.to_string(),
        email.min_page,
    )
    .await
    .expect("the page the Email source names must resolve to text");
    assert!(!body.is_empty(), "the email body came back empty");
}

/// An email with headers but no parsed body says so, rather than naming a page.
///
/// The two halves of a mail file are stored independently: `email_headers` gets a row
/// whenever the file parses at all, `text_content` gets an `email_parser` row only if the
/// message yielded body text worth storing. Mail whose whole `text/plain` part is a
/// single character — a bare `,` on a line of its own, which the Enron export produces by
/// the dozen — clears the first bar and not the second, exactly like mail whose only body
/// part is HTML. The viewer still offers the Email source for those, so the source has to
/// carry the fact that there is nothing to fetch; when it did not, the body pane rendered
/// the text endpoint's 404 as `document not found!`.
///
/// The fixture is built rather than found, because the corpus is not guaranteed to hold
/// one: a body-less email is written straight into `emails`/`email_headers` with no
/// `text_content` at all, which is precisely the shape of the deployed failures.
#[tokio::test]
#[ignore = "needs live stack"]
async fn an_email_with_no_parsed_body_is_not_offered_as_one() {
    let _budget = Budget::start("an_email_with_no_parsed_body_is_not_offered_as_one");
    use common::document_sources::{DocumentSourceItem, EMAIL_TEXT_EXTRACTOR};
    use common::search_result::DocumentIdentifier;

    let client = get_client_for_dataset(EMAILS).await.unwrap();
    // A hash of its own so the fixture cannot collide with a real document, and so it is
    // removable by exactly the rows this test wrote.
    let file_hash = "0000000000000000000000000000000000000000000000000000bodyless".to_string();
    client
        .query("DELETE FROM emails WHERE collection_dataset = ? AND email_hash = ?")
        .bind(EMAILS)
        .bind(&file_hash)
        .execute()
        .await
        .unwrap();
    client
        .query("DELETE FROM email_headers WHERE collection_dataset = ? AND email_hash = ?")
        .bind(EMAILS)
        .bind(&file_hash)
        .execute()
        .await
        .unwrap();
    client
        .query(
            "INSERT INTO emails (collection_dataset, email_hash, email_type) \
             VALUES (?, ?, 'eml')",
        )
        .bind(EMAILS)
        .bind(&file_hash)
        .execute()
        .await
        .unwrap();
    client
        .query(
            "INSERT INTO email_headers \
             (collection_dataset, email_hash, raw_headers_json, subject, addresses, date_sent, date_sent_known) \
             VALUES (?, ?, '{}', 'one comma and nothing else', 'from: a@b.com', now(), 1)",
        )
        .bind(EMAILS)
        .bind(&file_hash)
        .execute()
        .await
        .unwrap();

    let document = DocumentIdentifier {
        collection_dataset: EMAILS.to_string(),
        file_hash: file_hash.clone(),
    };
    let sources = backend::api::documents::get_document_sources::get_document_sources(
        &admin_user(),
        document.clone(),
    )
    .await
    .unwrap();
    let email = sources
        .iter()
        .find_map(|source| match source {
            DocumentSourceItem::Email(email) => Some(email.clone()),
            _ => None,
        })
        .expect("an email with headers still offers an Email source");

    assert!(
        !email.has_body,
        "no email_parser row exists for this document, so the source must not claim a body: {email:?}"
    );
    assert!(
        !sources.iter().any(|source| matches!(
            source,
            DocumentSourceItem::Text(text) if text.extracted_by == EMAIL_TEXT_EXTRACTOR
        )),
        "the fixture is only meaningful while it has no email_parser text source"
    );
    // The fetch the viewer used to make unconditionally. It fails, and that is correct —
    // which is why the source must not send the viewer to it.
    let body = backend::api::documents::search_document_text::get_document_text_by_id_and_source(
        &admin_user(),
        document,
        EMAIL_TEXT_EXTRACTOR.to_string(),
        email.min_page.max(1),
    )
    .await;
    assert!(
        body.is_err(),
        "asking for a body page that has no row must fail, not return text"
    );

    client
        .query("DELETE FROM emails WHERE collection_dataset = ? AND email_hash = ?")
        .bind(EMAILS)
        .bind(&file_hash)
        .execute()
        .await
        .unwrap();
    client
        .query("DELETE FROM email_headers WHERE collection_dataset = ? AND email_hash = ?")
        .bind(EMAILS)
        .bind(&file_hash)
        .execute()
        .await
        .unwrap();
}

/// In-PDF search answers with real hits, through the sidecar, end to end.
///
/// Two separate things have to be true for a hit to come back and neither is visible from
/// a unit test: the sidecar process is running, and the address this server sends the
/// request to is the sidecar's. The sidecar is a CHILD of this server rather than a
/// service of its own, so that address is loopback — and a deployment that starts the
/// server from a different working directory loses the process entirely, which turns
/// every in-PDF search into a 500 with nothing else affected.
#[tokio::test]
#[ignore = "needs live stack"]
async fn in_pdf_search_returns_hits_through_the_sidecar() {
    let _budget = Budget::start("in_pdf_search_returns_hits_through_the_sidecar");
    use common::search_result::DocumentIdentifier;

    // A PDF picked by the property the test needs — it has a text layer — rather than by
    // name, and a word taken out of that layer rather than guessed: the assertion is
    // about the search path, not about the corpus.
    let client = get_client_for_dataset(TESTFILES).await.unwrap();
    let (file_hash, text): (String, String) = client
        .query(
            "SELECT file_hash, text FROM text_content \
             WHERE collection_dataset = ? AND extracted_by = 'pdftotext' AND length(text) > 200 \
             ORDER BY file_hash, page_id LIMIT 1",
        )
        .bind(TESTFILES)
        .fetch_one()
        .await
        .expect("testdata_testfiles must hold a PDF with a text layer");
    let keyword = text
        .split_whitespace()
        .find(|word| word.chars().all(|c| c.is_ascii_alphabetic()) && word.len() > 4)
        .expect("the PDF's text layer must hold one plain word")
        .to_string();

    let results = backend::api::documents::search_document_pdf::search_document_pdf(
        &admin_user(),
        DocumentIdentifier {
            collection_dataset: TESTFILES.to_string(),
            file_hash,
        },
        keyword.clone(),
    )
    .await
    .expect("in-PDF search must reach the sidecar");
    assert!(
        results.total > 0,
        "{keyword:?} is in the PDF's text layer but the sidecar found it nowhere in the PDF"
    );
}

/// The sidecar's address is configuration, not a literal, and defaults to the loopback
/// the sidecar actually runs on.
///
/// There is no second address to check: the sidecar is handed the PDF's bytes, so nothing
/// tells it a url to fetch them back from. Such a url points at this server's own HTTP
/// port — a request the server makes to itself, carrying no session cookie, which
/// requiring a session on the download route kills silently.
#[test]
fn pdf_search_endpoint_defaults_to_loopback() {
    use backend::api::documents::search_document_pdf::pdf_search_endpoint;
    // Nothing sets this in the test process, so this is the default path.
    assert_eq!(pdf_search_endpoint(), "http://127.0.0.1:13500");
}

/// A hash nothing was ever ingested under is a 404, and a real one still downloads.
///
/// The route answered 500 for the missing hash. That is not a cosmetic difference: a
/// crawler or a stale bookmark then reads as the server throwing, and `is_error` on the
/// admin metrics page is derived from the status, so every such request was counted as
/// breakage. The pair is asserted together — a handler that 404s everything would satisfy
/// the first assertion on its own.
#[tokio::test]
#[ignore = "needs live stack"]
async fn downloading_an_unknown_hash_is_not_found() {
    let _budget = Budget::start("downloading_an_unknown_hash_is_not_found");
    use axum::extract::{Extension, Path};

    let missing = backend::server_extra::download_document::download_document(
        Extension(admin_user()),
        Path((EMAILS.to_string(), "deadbeef".to_string())),
    )
    .await;
    assert_eq!(missing.status(), axum::http::StatusCode::NOT_FOUND);

    let client = get_client_for_dataset(EMAILS).await.unwrap();
    let file_hash: String = client
        .query("SELECT hash FROM vfs_files WHERE collection_dataset = ? ORDER BY hash LIMIT 1")
        .bind(EMAILS)
        .fetch_one()
        .await
        .expect("other_emails must hold a file");
    let found = backend::server_extra::download_document::download_document(
        Extension(admin_user()),
        Path((EMAILS.to_string(), file_hash)),
    )
    .await;
    assert_eq!(found.status(), axum::http::StatusCode::OK);
}

/// `/admin/ai_status` reports the hardware that answered, not the name of the slot.
///
/// This host has no GPU tier, so whichever NER endpoint serves is a CPU twin and the row
/// must say so. The check is made against the serving endpoint's own `/health` rather
/// than against a hardcoded expectation, so it stays true on a host that does have a GPU.
#[tokio::test]
#[ignore = "needs live stack"]
async fn ai_status_reports_the_hardware_that_actually_serves_ner() {
    let _budget = Budget::start("ai_status_reports_the_hardware_that_actually_serves_ner");

    let status = backend::api::admin::ai_status::admin_get_ai_status(&admin_user())
        .await
        .unwrap();
    let ner = status
        .capabilities
        .iter()
        .find(|c| c.name == "ner")
        .expect("the capabilities table always carries a ner row");
    assert!(
        ner.reachable,
        "NER must be serving for this assertion to mean anything: {ner:?}"
    );
    // The detail names the endpoint that answered, so the claim can be checked.
    let endpoint = ner
        .detail
        .split_whitespace()
        .find_map(|word| word.strip_prefix("http"))
        .map(|rest| format!("http{rest}"))
        .expect("the ner row must name the endpoint that served it");
    let endpoint = endpoint.trim_end_matches(';').trim_end_matches("/v1");

    let health: serde_json::Value = reqwest::get(format!("{endpoint}/health"))
        .await
        .expect("the endpoint the page named must answer")
        .json()
        .await
        .unwrap();
    let claims_gpu = health
        .get("cuda_available")
        .and_then(|v| v.as_bool())
        .unwrap_or(false);
    assert_eq!(
        ner.serving_provider,
        if claims_gpu { "gpu" } else { "cpu" },
        "the row says {:?} while {endpoint} reports cuda_available={claims_gpu}",
        ner.serving_provider
    );
}

/// A document that is not an image answers "not an image", not an error.
///
/// Most documents are not images, so an error here is emitted on a large fraction of
/// document opens. Under `err(Debug)` on the tracing attribute that is ERROR level, and it
/// buried every real error in the website log — the log stopped being usable as a signal
/// while nothing at all was failing. The positive half is asserted with it: a probe that
/// answered `None` for everything would satisfy the first assertion by doing nothing.
#[tokio::test]
#[ignore = "needs live stack"]
async fn a_document_that_is_not_an_image_is_not_an_error() {
    let _budget = Budget::start("a_document_that_is_not_an_image_is_not_an_error");
    use common::document_sources::EMAIL_TEXT_EXTRACTOR;
    use common::search_result::DocumentIdentifier;

    let client = get_client_for_dataset(EMAILS).await.unwrap();
    let not_an_image: String = client
        .query(
            "SELECT file_hash FROM text_content \
             WHERE collection_dataset = ? AND extracted_by = ? LIMIT 1",
        )
        .bind(EMAILS)
        .bind(EMAIL_TEXT_EXTRACTOR)
        .fetch_one()
        .await
        .expect("other_emails must hold a parsed email");
    let probed = backend::api::documents::get_document_sources::get_image_sources(
        &admin_user(),
        DocumentIdentifier {
            collection_dataset: EMAILS.to_string(),
            file_hash: not_an_image,
        },
    )
    .await;
    assert!(
        matches!(probed, Ok(None)),
        "an email is not an image, which is an answer: {probed:?}"
    );

    let an_image: String = client
        .query("SELECT image_hash FROM image WHERE collection_dataset = ? LIMIT 1")
        .bind(EMAILS)
        .fetch_one()
        .await
        .expect("other_emails must hold an image");
    let probed = backend::api::documents::get_document_sources::get_image_sources(
        &admin_user(),
        DocumentIdentifier {
            collection_dataset: EMAILS.to_string(),
            file_hash: an_image,
        },
    )
    .await
    .expect("an image with a metadata row must probe cleanly");
    let dimensions = probed.expect("and it must report its dimensions");
    assert!(dimensions.width > 0 && dimensions.height > 0, "{dimensions:?}");
}

/// The Entities facet must not offer MIME header names, encoding fragments or
/// letter-spaced PDF headings.
///
/// The NLP stage stops these before `entity_hit` is written, but a rule applied at write
/// time governs only rows written after it, and every collection ingested earlier keeps
/// its junk until the stage is re-run. `testdata` is such a collection in the fixture
/// stack — it carries single-letter and empty entity values from a PDF — so this asserts
/// the read side filters what the write side would now have rejected.
#[tokio::test]
#[ignore = "needs live stack"]
async fn the_entities_facet_offers_no_extraction_debris() {
    let _budget = Budget::start("the_entities_facet_offers_no_extraction_debris");
    use common::entity_stoplist::{ENTITY_TERM_FIELD, is_stopped_entity};

    let mut offered = 0;
    for column in ["ner_per", "ner_org", "ner_loc", "ner_misc"] {
        let facets = backend::api::search::search_string_facet(
            &admin_user(),
            SearchQuery {
                query_string: "the".to_string(),
                ..Default::default()
            },
            column.to_string(),
            Some(ENTITY_TERM_FIELD.to_string()),
            // The whole facet: every bucket the pane would show with an empty search
            // box. Narrowing the terms would shrink the sweep this test exists to make,
            // and `offered > 0` below is the guard against it passing vacuously.
            None,
        )
        .await
        .unwrap_or_else(|e| panic!("{column} facet failed: {e}"));
        offered += facets.facet_values.len();
        for item in &facets.facet_values {
            assert!(
                !is_stopped_entity(&item.display_string),
                "{column} offers {:?} ({} documents), which is extraction debris",
                item.display_string,
                item.count
            );
        }
    }
    assert!(
        offered > 0,
        "the fixture corpus has entities; an empty facet would pass this vacuously"
    );
}

/// The Collections facet must never offer a value that is not a registered dataset.
///
/// Manticore keeps whatever was written under a dataset name until something deletes it,
/// so an abandoned ingest (or a re-ingest under a new name) goes on producing buckets
/// with real counts long after its registry row is gone — and ticking one applies a
/// filter that matches nothing. `dataset` is the authority; this asserts the facet
/// agrees with it in both directions, against the live index rather than against a
/// hand-built list of values.
#[tokio::test]
#[ignore = "needs live stack"]
async fn the_collections_facet_offers_exactly_the_registered_datasets() {
    let _budget = Budget::start("the_collections_facet_offers_exactly_the_registered_datasets");
    let registered: std::collections::BTreeSet<String> =
        backend::api::list_datasets::list_dataset_ids()
            .await
            .unwrap()
            .into_iter()
            .collect();
    assert!(
        !registered.is_empty(),
        "the fixture corpus has datasets; an empty registry would pass this vacuously"
    );

    let facets = backend::api::search::search_string_facet(
        &admin_user(),
        SearchQuery {
            query_string: "the".to_string(),
            ..Default::default()
        },
        "collection_dataset".to_string(),
        None,
        // The whole facet. The assertion below is set equality against the registry, so
        // any narrowing of the terms makes it false by construction.
        None,
    )
    .await
    .unwrap();

    let offered: std::collections::BTreeSet<String> = facets
        .facet_values
        .iter()
        .map(|item| item.display_string.clone())
        .collect();
    let ghosts: Vec<&String> = offered.difference(&registered).collect();
    assert!(
        ghosts.is_empty(),
        "the Collections facet offers {ghosts:?}, which name no dataset — \
         ticking one returns 0 documents"
    );
    // The other direction: a dataset with no hits for this query is still offered, at
    // zero, so the pane lists the same datasets as the file-location tree beside it.
    assert_eq!(offered, registered);
}

// ---------------------------------------------------------------------------
// Endpoint authentication, over real HTTP
// ---------------------------------------------------------------------------
//
// Everything above this line calls backend functions directly, which is the right shape
// for a query and the wrong shape entirely for an auth rule: the refusal these assert
// lives in the axum middleware, so only a request that actually crosses it can see it.
//
// The rule under test: **exactly one route may create a session**. A fresh `set-cookie` on
// every response lets a client that stores none — a crawler, a `curl` loop — mint a
// `guest-<hex>` user and a `user_login` row per request.
//
// These run inside the website container (`run-stack-tests.sh`), where the site is on
// loopback. They read `HOOVER4_DEMO_MODE` the same way the server does, so the same
// assertions describe both deployment modes rather than one of them being untested.

/// The site, as seen from inside its own container.
fn site_url() -> String {
    std::env::var("HOOVER4_SITE_URL").unwrap_or_else(|_| "http://127.0.0.1:8080".to_string())
}

/// The two server-function URLs these tests need.
///
/// Discovered from the served WASM bundle, never written down: Dioxus mounts a server
/// function at `/api/<name><decimal hash>` and the hash changes whenever the function's
/// signature does, so a literal path here would rot into a 404 that reads as a missing
/// refusal. Fetched once for the whole suite — the bundle is megabytes.
struct ServerFnPaths {
    whoami: String,
    search_hit_count: String,
}

static SERVER_FN_PATHS: tokio::sync::OnceCell<ServerFnPaths> = tokio::sync::OnceCell::const_new();

async fn server_fn_paths() -> &'static ServerFnPaths {
    SERVER_FN_PATHS
        .get_or_init(|| async {
            let client = reqwest::Client::new();
            let index = client.get(site_url()).send().await.unwrap().text().await.unwrap();
            let js = first_match(&index, "/wasm/frontend").unwrap_or("/wasm/frontend.js".to_string());
            let glue = client
                .get(format!("{}{}", site_url(), js.trim_start_matches('.')))
                .send()
                .await
                .unwrap()
                .text()
                .await
                .unwrap();
            let wasm_href = first_match(&glue, "frontend_bg").unwrap_or("frontend_bg.wasm".to_string());
            let wasm_url = if wasm_href.starts_with('/') {
                format!("{}{}", site_url(), wasm_href)
            } else {
                format!("{}/wasm/{}", site_url(), wasm_href)
            };
            let bytes = client.get(&wasm_url).send().await.unwrap().bytes().await.unwrap();
            assert_eq!(
                &bytes[..4],
                b"\0asm",
                "{wasm_url} did not serve a WASM module — the site answers its SPA shell for \
                 any unknown path, so a 200 proves nothing about what came back"
            );
            let text = String::from_utf8_lossy(&bytes);
            ServerFnPaths {
                whoami: hashed_path(&text, "/api/whoami").expect("whoami is in the bundle"),
                search_hit_count: hashed_path(&text, "/api/search_for_results_hit_count")
                    .expect("search_for_results_hit_count is in the bundle"),
            }
        })
        .await
}

/// The first `<prefix>…` token in `haystack`, up to the first quote or whitespace.
fn first_match(haystack: &str, needle: &str) -> Option<String> {
    let start = haystack.find(needle)?;
    let head = &haystack[start..];
    let end = head
        .find(['"', '\'', ' ', '\n', ')', '?'])
        .unwrap_or(head.len());
    Some(head[..end].to_string())
}

/// `<prefix><digits>` — the hash suffix is decimal, so the match stops at the first
/// non-digit and cannot run into whatever the bundle stores next to it.
fn hashed_path(haystack: &str, prefix: &str) -> Option<String> {
    let start = haystack.find(prefix)?;
    let rest = &haystack[start + prefix.len()..];
    let digits: String = rest.chars().take_while(char::is_ascii_digit).collect();
    if digits.is_empty() {
        return None;
    }
    Some(format!("{prefix}{digits}"))
}

/// Every `set-cookie` on a response, so "did this route mint" is a count and not a guess.
fn set_cookies(response: &reqwest::Response) -> Vec<String> {
    response
        .headers()
        .get_all(reqwest::header::SET_COOKIE)
        .iter()
        .filter_map(|v| v.to_str().ok().map(str::to_string))
        .collect()
}

fn session_cookie(response: &reqwest::Response) -> Option<String> {
    set_cookies(response)
        .into_iter()
        .find(|c| c.starts_with("hoover4_session="))
        .and_then(|c| c.split(';').next().map(str::to_string))
}

/// Every path a request can reach that is not a page or a static asset, with the method it
/// takes. Written out rather than derived so that a route added to `main.rs` and forgotten
/// here is a gap somebody can see, not a silently untested endpoint.
fn protected_endpoints(paths: &ServerFnPaths) -> Vec<(&'static str, String)> {
    vec![
        ("POST", paths.search_hit_count.clone()),
        ("GET", "/_download_document/testdata_testfiles/deadbeef".to_string()),
        (
            "GET",
            "/_download_ocr_pdf/testdata_testfiles/deadbeef/tesseract/eng".to_string(),
        ),
        ("GET", "/_chat_artifact/deadbeef/thumb.webp".to_string()),
    ]
}

async fn request_without_session(method: &str, path: &str) -> reqwest::Response {
    let client = reqwest::Client::new();
    let url = format!("{}{}", site_url(), path);
    match method {
        "POST" => client
            .post(url)
            .header("Content-Type", "application/json")
            .body("[]")
            .send()
            .await
            .unwrap(),
        _ => client.get(url).send().await.unwrap(),
    }
}

/// The defect itself: a request with no cookie must not be given a user.
///
/// Before this, `/`, `/_download_document/…` and every server function each answered a
/// fresh `set-cookie`, so 106 `guest-<hex>` users and 106 `user_login` events accumulated
/// on the demo in a day and both the user list and the metrics page became unreadable.
#[tokio::test]
#[ignore = "needs live stack"]
async fn only_the_sign_in_route_hands_out_a_session() {
    let paths = server_fn_paths().await;
    let _budget = Budget::start("only_the_sign_in_route_hands_out_a_session");

    // The app shell is public — the browser has to load the code that signs in — but it
    // is not an identity.
    for path in ["/", "/search/x/0/9g==/9g==", "/admin"] {
        let response = request_without_session("GET", path).await;
        assert!(
            set_cookies(&response).is_empty(),
            "{path} handed out {:?}; only the sign-in route may",
            set_cookies(&response)
        );
    }

    for (method, path) in protected_endpoints(paths) {
        let response = request_without_session(method, &path).await;
        assert!(
            set_cookies(&response).is_empty(),
            "{path} handed out {:?}; only the sign-in route may",
            set_cookies(&response)
        );
    }

    // And the one route that does. With guests disabled it refuses instead — the same
    // rule, the other deployment mode.
    let response = request_without_session("POST", &paths.whoami).await;
    if backend::auth::session_middleware::guest_sessions_allowed() {
        assert_eq!(response.status(), 200);
        assert!(
            session_cookie(&response).is_some(),
            "the sign-in route issued no session in demo mode"
        );
    } else {
        assert!(
            session_cookie(&response).is_none(),
            "guests are disabled, so nothing may be minted for an anonymous visitor"
        );
    }
}

/// Every endpoint refuses a request that carries no session, and says so as a 401.
#[tokio::test]
#[ignore = "needs live stack"]
async fn every_endpoint_refuses_a_request_with_no_session() {
    let paths = server_fn_paths().await;
    let _budget = Budget::start("every_endpoint_refuses_a_request_with_no_session");

    for (method, path) in protected_endpoints(paths) {
        let response = request_without_session(method, &path).await;
        assert_eq!(
            response.status(),
            401,
            "{path} answered {} without a session",
            response.status()
        );
        let body = response.text().await.unwrap_or_default();
        assert!(
            body.contains("no session"),
            "{path} refused without saying why: {body:?}"
        );
    }
}

/// The other half: with a session, the same endpoints work. A refusal that refuses
/// everybody is not an access control, it is an outage.
#[tokio::test]
#[ignore = "needs live stack"]
async fn a_session_from_the_sign_in_route_opens_the_endpoints() {
    let paths = server_fn_paths().await;
    let _budget = Budget::start("a_session_from_the_sign_in_route_opens_the_endpoints");
    if !backend::auth::session_middleware::guest_sessions_allowed() {
        eprintln!("[stack] guests are disabled here; nothing anonymous can sign in");
        return;
    }

    let signin = request_without_session("POST", &paths.whoami).await;
    let cookie = session_cookie(&signin).expect("the sign-in route issues a session");
    let client = reqwest::Client::new();

    // Signing in again with the session already held mints nothing: the cookie is the
    // anchor, so a reload is not a new user.
    let again = client
        .post(format!("{}{}", site_url(), paths.whoami))
        .header("Cookie", &cookie)
        .header("Content-Type", "application/json")
        .body("[]")
        .send()
        .await
        .unwrap();
    assert!(
        set_cookies(&again).is_empty(),
        "signing in with a session already held minted another one: {:?}",
        set_cookies(&again)
    );

    let search = client
        .post(format!("{}{}", site_url(), paths.search_hit_count))
        .header("Cookie", &cookie)
        .header("Content-Type", "application/json")
        .body(r#"[{"collection_datasets":[],"query_string":"the","facet_filters":{}}]"#)
        .send()
        .await
        .unwrap();
    assert_eq!(search.status(), 200, "a signed-in search must work");

    // A dataset that is in no registry row is a complete answer about something that is
    // not there, exactly like an unknown hash — not a 500.
    let unknown = client
        .get(format!(
            "{}/_download_document/no_such_dataset/deadbeef",
            site_url()
        ))
        .header("Cookie", &cookie)
        .send()
        .await
        .unwrap();
    assert_eq!(
        unknown.status(),
        404,
        "an unknown dataset must be a 404, not a server error"
    );

    // The same answer on every custom byte route, not only the one the first report
    // named: the OCR route kept 500ing on an unknown dataset because it matched one
    // error message instead of asking whether the thing was there.
    for path in [
        "/_download_ocr_pdf/no_such_dataset/deadbeef/tesseract/eng",
        "/_download_ocr_pdf/testdata_testfiles/deadbeef/tesseract/eng",
    ] {
        let response = client
            .get(format!("{}{}", site_url(), path))
            .header("Cookie", &cookie)
            .send()
            .await
            .unwrap();
        assert_eq!(response.status(), 404, "{path} must be a 404, not a server error");
    }
}

// ---------------------------------------------------------------------------------
// The email connection graph.
//
// These exercise the READER against a live ClickHouse. The rows are written here in
// exactly the shape P6's `build_email_graph` writes them, because the builder is Python
// and its rules -- the identity join, the attachment containment, the inferred edge's
// three guards -- are unit-tested there. What only a live stack can answer is whether the
// reader walks an edge table that spans two datasets, terminates on a cycle, and reports
// a component's true size rather than the number of nodes it drew.
// ---------------------------------------------------------------------------------

use common::search_result::DocumentIdentifier as GraphDocumentIdentifier;

/// Fixture hashes, long enough that they cannot collide with a real document hash and
/// distinctive enough to be found and deleted by exactly the rows these tests wrote.
const GRAPH_A: &str = "00000000000000000000000000000000000000000000000000graphaa";
const GRAPH_B: &str = "00000000000000000000000000000000000000000000000000graphbb";
const GRAPH_LOOP: &str = "00000000000000000000000000000000000000000000000000graphlp";

async fn clear_graph_fixture() {
    for dataset in [TESTFILES, SHAPES] {
        let client = get_client_for_dataset(dataset).await.unwrap();
        for hash in [GRAPH_A, GRAPH_B, GRAPH_LOOP] {
            for (table, column) in
                [("email_headers", "email_hash"), ("email_identity", "email_hash"),
                 ("email_clusters", "email_hash"), ("email_addresses", "email_hash")]
            {
                client
                    .query(&format!(
                        "DELETE FROM {table} WHERE collection_dataset = ? AND {column} = ?"
                    ))
                    .bind(dataset)
                    .bind(hash)
                    .execute()
                    .await
                    .unwrap();
            }
            client
                .query("DELETE FROM email_edges WHERE src_hash = ? OR dst_hash = ?")
                .bind(hash)
                .bind(hash)
                .execute()
                .await
                .unwrap();
        }
    }
}

async fn insert_graph_message(dataset: &str, hash: &str, subject: &str, epoch: i64) {
    let client = get_client_for_dataset(dataset).await.unwrap();
    client
        .query(
            "INSERT INTO email_headers \
             (collection_dataset, email_hash, raw_headers_json, subject, addresses, date_sent, date_sent_known) \
             VALUES (?, ?, '[]', ?, 'from: a@b.com', toDateTime(?), 1)",
        )
        .bind(dataset)
        .bind(hash)
        .bind(subject)
        .bind(epoch)
        .execute()
        .await
        .unwrap();
    client
        .query(
            "INSERT INTO email_addresses \
             (collection_dataset, email_hash, role, address, display_name) \
             VALUES (?, ?, 'from', 'a@b.com', 'A Sender')",
        )
        .bind(dataset)
        .bind(hash)
        .execute()
        .await
        .unwrap();
    client
        .query(
            "INSERT INTO email_identity \
             (collection_dataset, email_hash, message_id, subject_norm, subject_prefix, \
              date_sent, date_sent_known, from_address, participants) \
             VALUES (?, ?, 'graph-fixture@example.com', ?, '', toDateTime(?), 1, 'a@b.com', ['a@b.com'])",
        )
        .bind(dataset)
        .bind(hash)
        .bind(subject)
        .bind(epoch)
        .execute()
        .await
        .unwrap();
}

async fn insert_graph_edge(
    collection: &str,
    src_dataset: &str,
    src_hash: &str,
    dst_dataset: &str,
    dst_hash: &str,
    kind: &str,
    confidence: f32,
) {
    let client = get_client_for_dataset(src_dataset).await.unwrap();
    client
        .query(
            "INSERT INTO email_edges \
             (collectionname, src_dataset, src_hash, dst_dataset, dst_hash, kind, confidence, evidence) \
             VALUES (?, ?, ?, ?, ?, ?, ?, 'integration fixture')",
        )
        .bind(collection)
        .bind(src_dataset)
        .bind(src_hash)
        .bind(dst_dataset)
        .bind(dst_hash)
        .bind(kind)
        .bind(confidence)
        .execute()
        .await
        .unwrap();
}

async fn insert_graph_cluster(dataset: &str, hash: &str, size: u32) {
    let collection = resolve_collection(dataset).await.unwrap();
    let client = get_client_for_dataset(dataset).await.unwrap();
    client
        .query(
            "INSERT INTO email_clusters \
             (collectionname, collection_dataset, email_hash, cluster_id, cluster_size) \
             VALUES (?, ?, ?, 1, ?)",
        )
        .bind(&collection)
        .bind(dataset)
        .bind(hash)
        .bind(size)
        .execute()
        .await
        .unwrap();
}

#[tokio::test]
#[ignore]
async fn the_same_message_in_two_datasets_is_one_cluster_from_either_centre() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("email_graph_identity_across_datasets");
    clear_graph_fixture().await;
    // The same `.eml` in two datasets: one custodian's copy and another's, which is the
    // relation the identity edge exists for.
    insert_graph_message(TESTFILES, GRAPH_A, "shared fixture message", 1_600_000_000).await;
    insert_graph_message(SHAPES, GRAPH_B, "shared fixture message", 1_600_000_000).await;
    let collection = resolve_collection(TESTFILES).await.unwrap();
    insert_graph_edge(&collection, TESTFILES, GRAPH_A, SHAPES, GRAPH_B, "identity", 1.0).await;
    insert_graph_cluster(TESTFILES, GRAPH_A, 2).await;
    insert_graph_cluster(SHAPES, GRAPH_B, 2).await;

    for (dataset, hash) in [(TESTFILES, GRAPH_A), (SHAPES, GRAPH_B)] {
        let graph = backend::api::documents::get_email_graph::get_email_graph(
            &admin_user(),
            GraphDocumentIdentifier {
                collection_dataset: dataset.to_string(),
                file_hash: hash.to_string(),
            },
            50,
            3,
        )
        .await
        .unwrap();
        assert_eq!(
            graph.nodes.len(),
            2,
            "both renditions must be reachable from {dataset}, got {graph:?}"
        );
        assert_eq!(graph.cluster_size, 2);
        let identity_edges: Vec<_> =
            graph.edges.iter().filter(|e| e.kind == "identity").collect();
        assert_eq!(identity_edges.len(), 1, "exactly one identity edge: {identity_edges:?}");
        assert!(
            graph.nodes.iter().any(|n| n.is_centre && n.document_identifier.file_hash == hash),
            "the centre must be marked as such"
        );
    }

    // The envelope reads the same cluster with one point lookup, which is what decides
    // whether the button appears at all.
    let envelope = backend::api::documents::get_email_graph::get_email_envelope(
        &admin_user(),
        GraphDocumentIdentifier {
            collection_dataset: TESTFILES.to_string(),
            file_hash: GRAPH_A.to_string(),
        },
    )
    .await
    .unwrap()
    .expect("a document with email_headers rows is an email");
    assert_eq!(envelope.cluster_size, 2);
    assert!(envelope.has_connections());

    clear_graph_fixture().await;
}

#[tokio::test]
#[ignore]
async fn a_cycle_in_the_edge_table_terminates_the_walk() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("email_graph_cycle_terminates");
    clear_graph_fixture().await;
    // `eml-7-recursive` is an email that contains itself, so a self edge and a two-cycle
    // are both real input. The reader's visited set is what makes this return instead of
    // looping, exactly as `vfs_tree_path_to` documents for the same fixture.
    insert_graph_message(TESTFILES, GRAPH_A, "cycle fixture", 1_600_000_000).await;
    insert_graph_message(TESTFILES, GRAPH_LOOP, "cycle fixture", 1_600_000_100).await;
    let collection = resolve_collection(TESTFILES).await.unwrap();
    insert_graph_edge(&collection, TESTFILES, GRAPH_A, TESTFILES, GRAPH_LOOP, "attachment", 1.0)
        .await;
    insert_graph_edge(&collection, TESTFILES, GRAPH_LOOP, TESTFILES, GRAPH_A, "attachment", 1.0)
        .await;
    insert_graph_edge(&collection, TESTFILES, GRAPH_LOOP, TESTFILES, GRAPH_LOOP, "attachment", 1.0)
        .await;

    let graph = backend::api::documents::get_email_graph::get_email_graph(
        &admin_user(),
        GraphDocumentIdentifier {
            collection_dataset: TESTFILES.to_string(),
            file_hash: GRAPH_A.to_string(),
        },
        50,
        3,
    )
    .await
    .unwrap();
    assert_eq!(graph.nodes.len(), 2, "a cycle must not multiply the nodes: {graph:?}");
    assert!(
        graph.edges.iter().all(|e| e.kind == "attachment"),
        "only the attachment edges were written"
    );

    clear_graph_fixture().await;
}

#[tokio::test]
#[ignore]
async fn the_node_budget_is_clamped_server_side() {
    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let _budget = Budget::start("email_graph_budget_clamped");
    clear_graph_fixture().await;
    insert_graph_message(TESTFILES, GRAPH_A, "budget fixture", 1_600_000_000).await;
    insert_graph_message(TESTFILES, GRAPH_B, "budget fixture", 1_600_000_100).await;
    let collection = resolve_collection(TESTFILES).await.unwrap();
    insert_graph_edge(&collection, TESTFILES, GRAPH_A, TESTFILES, GRAPH_B, "reply", 0.5).await;
    // The component is claimed to be far larger than what can be drawn, so the reader has
    // to say it was truncated rather than implying the cluster ends at two.
    insert_graph_cluster(TESTFILES, GRAPH_A, 900).await;

    // A client asking for 10 000 nodes gets the budget, not 10 000.
    let graph = backend::api::documents::get_email_graph::get_email_graph(
        &admin_user(),
        GraphDocumentIdentifier {
            collection_dataset: TESTFILES.to_string(),
            file_hash: GRAPH_A.to_string(),
        },
        10_000,
        99,
    )
    .await
    .unwrap();
    assert!(graph.nodes.len() <= 50, "the node budget is clamped server-side");
    assert_eq!(graph.cluster_size, 900);
    assert!(graph.truncated, "a component bigger than the drawn set must say so");
    assert!(
        graph.edges.iter().any(|e| e.is_inferred()),
        "a 0.5-confidence edge must arrive as inferred so the page can dash it"
    );

    clear_graph_fixture().await;
}
