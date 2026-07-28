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
    assert_eq!(
        resolve_collection("testdata_testfiles").await.unwrap(),
        "testdata"
    );
    assert_eq!(resolve_collection("other_emails").await.unwrap(), "other");
}

#[tokio::test]
#[ignore = "needs live stack"]
async fn client_for_dataset_reads_collection_tables() {
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
    let query = SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
    };
    let results = backend::api::search::search_for_results(&admin_user(), query, 0)
        .await
        .unwrap();
    assert!(!results.results.is_empty(), "expected search hits");
    assert!(!results.partial, "no shard may fail on a healthy stack");
    for hit in &results.results {
        assert!(
            hit.collection_dataset == "testdata_testfiles"
                || hit.collection_dataset == "other_emails",
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
    use common::search_result::FacetOriginalValue;
    let mut query = SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
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


/// I9: pagination completeness. Walk every page of a multi-page result set and
/// assert the pages are disjoint and their union is exactly the hit count. With
/// the fixture corpus both pages still fit one per-shard fetch window, so this
/// pins the merge/window machinery and the stable ORDER BY; it becomes a full
/// B3 regression test once a shard holds more hits than one fetch window.
#[tokio::test]
#[ignore = "needs live stack"]
async fn pagination_pages_are_disjoint_and_complete() {
    use std::collections::BTreeSet;

    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let mk_query = || SearchQuery {
        collection_datasets: vec![],
        query_string: "the".to_string(),
        facet_filters: Default::default(),
    };
    let hit_count = backend::api::search::search_for_results_hit_count(&admin_user(), mk_query())
        .await
        .unwrap();
    assert!(hit_count.total > common::search_const::PAGE_SIZE, "fixture corpus must span more than one page");
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

/// I8: partial-failure round trip. Insert a bogus shard into one collection's
/// ledger (its Manticore tables do not exist), assert the search still returns
/// the surviving shards' hits with partial == true on results, hit count and
/// facets — then remove the row again.
#[tokio::test]
#[ignore = "needs live stack"]
async fn missing_shard_degrades_to_partial_results() {
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

/// I10: permission isolation. A non-admin, non-guest user whose group has access
/// to exactly one collection must get zero hits from the other, and the fan-out
/// must not even target the other collection's shards.
#[tokio::test]
#[ignore = "needs live stack"]
async fn permissions_restrict_search_to_granted_collections() {
    use backend::db_auth::{collections as db_collections, groups};

    let _guard = GLOBAL_SEARCH_LOCK.lock().await;
    let suffix = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let username = format!("i10-user-{suffix}");
    let groupname = format!("i10-group-{suffix}");

    let now = time::OffsetDateTime::now_utc();
    groups::upsert_group(groups::GroupRow {
        groupname: groupname.clone(),
        fullname: "I10 test group".to_string(),
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
