//! ClickHouse query helpers for the backend.
//!
//! Two families of databases exist since the collections split:
//!
//! - the global database `Hoover4_Processing` (users, groups, collections, the dataset
//!   registry, sessions, settings, search cache) — [`get_global_client`];
//! - one database per collection, `Hoover4_Collection_<collectionname>` (blobs, VFS,
//!   parsed content, plans, errors, term dictionaries) — [`get_collection_client`] and
//!   [`get_client_for_dataset`].
//!
//! Callers that hold a `collection_dataset` must resolve it to a collection first
//! ([`resolve_collection`]); never derive the collection by splitting the id string.

use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use common::current_user::CurrentUser;

use crate::api::admin::collections::collectionname_valid;
use crate::auth::permissions::{self, PermissionSet};

/// Name of the global ClickHouse database.
pub const GLOBAL_DB: &str = "Hoover4_Processing";

/// Configured ClickHouse URL (from `CLICKHOUSE_URL`, with a localhost default).
pub fn clickhouse_url() -> String {
    std::env::var("CLICKHOUSE_URL").unwrap_or_else(|_| "http://localhost:21900".to_string())
}

fn client_with_database(database: &str) -> clickhouse::Client {
    clickhouse::Client::default()
        .with_url(clickhouse_url())
        .with_user("hoover4")
        .with_password("hoover4")
        .with_database(database)
}

/// Client bound to the global database `Hoover4_Processing`.
pub fn get_global_client() -> clickhouse::Client {
    client_with_database(GLOBAL_DB)
}

/// `Hoover4_Collection_<collectionname>`, validating the slug first.
///
/// The database name is interpolated into the client configuration and cannot be a
/// bound parameter, so an invalid collectionname is rejected here rather than at the
/// query site.
pub fn collection_db_name(collectionname: &str) -> anyhow::Result<String> {
    if !collectionname_valid(collectionname) {
        anyhow::bail!("invalid collectionname: {collectionname:?}");
    }
    Ok(format!("Hoover4_Collection_{collectionname}"))
}

/// Client bound to the collection's own database.
///
/// Panics on an invalid collectionname — callers that cannot panic (request handlers)
/// should go through [`get_client_for_dataset`] or validate with [`collection_db_name`]
/// first and propagate the error instead.
pub fn get_collection_client(collectionname: &str) -> clickhouse::Client {
    let database = collection_db_name(collectionname)
        .unwrap_or_else(|e| panic!("get_collection_client: {e:#}"));
    client_with_database(&database)
}

/// In-process `collection_dataset → collectionname` cache.
///
/// The mapping is immutable once the dataset exists (a dataset's
/// collection is fixed at creation), so positive entries never expire. Misses and
/// negative lookups are not cached — a dataset created after this process started must
/// resolve on the next attempt.
#[derive(Default)]
struct CollectionResolver {
    cache: HashMap<String, String>,
}

impl CollectionResolver {
    fn get(&self, collection_dataset: &str) -> Option<String> {
        self.cache.get(collection_dataset).cloned()
    }

    fn insert(&mut self, collection_dataset: String, collectionname: String) {
        self.cache.insert(collection_dataset, collectionname);
    }

    /// Testable core of the caching policy: return the cached value, or call `loader`
    /// on a miss and cache a positive result. A negative lookup is never cached.
    #[cfg(test)]
    fn resolve_with(
        &mut self,
        collection_dataset: &str,
        loader: impl FnOnce(&str) -> Option<String>,
    ) -> Option<String> {
        if let Some(cached) = self.get(collection_dataset) {
            return Some(cached);
        }
        let resolved = loader(collection_dataset)?;
        self.insert(collection_dataset.to_string(), resolved.clone());
        Some(resolved)
    }
}

static RESOLVER: LazyLock<Mutex<CollectionResolver>> =
    LazyLock::new(|| Mutex::new(CollectionResolver::default()));

/// Resolve a `collection_dataset` to its owning collectionname via the global
/// `dataset` registry. Cached forever on success; unknown datasets are re-queried.
pub async fn resolve_collection(collection_dataset: &str) -> anyhow::Result<String> {
    if let Some(cached) = RESOLVER.lock().unwrap().get(collection_dataset) {
        return Ok(cached);
    }

    let rows: Vec<String> = get_global_client()
        .query(
            "SELECT collectionname FROM dataset FINAL \
             WHERE collection_dataset = ? AND is_deleted = 0 LIMIT 1",
        )
        .bind(collection_dataset)
        .fetch_all()
        .await?;
    let Some(collectionname) = rows.into_iter().next() else {
        // Carries the `not found` marker (`auth::guard::NOT_FOUND`) on purpose: a dataset
        // that is not in the registry is a complete answer about something that is not
        // there — a stale bookmark, a purged dataset, a crawler guessing names — and the
        // routes above it turn the marker into a 404. Without it every such request is a
        // 500, which reads as the site falling over and is counted as breakage.
        anyhow::bail!("unknown collection_dataset, not found: {collection_dataset}");
    };
    // The name leaves the process as a database name; never trust the registry row
    // blindly.
    collection_db_name(&collectionname)?;

    RESOLVER
        .lock()
        .unwrap()
        .insert(collection_dataset.to_string(), collectionname.clone());
    Ok(collectionname)
}

/// Resolve `collection_dataset` and return a client bound to its collection database.
pub async fn get_client_for_dataset(collection_dataset: &str) -> anyhow::Result<clickhouse::Client> {
    let collectionname = resolve_collection(collection_dataset).await?;
    Ok(client_with_database(&collection_db_name(&collectionname)?))
}

/// Whether an error message is ClickHouse's "database does not exist" (code 81,
/// `UNKNOWN_DATABASE`). A collection row can exist while its database is still
/// provisioning; readers treat that as "no data yet", not as an error.
fn is_unknown_database(message: &str) -> bool {
    message.contains("UNKNOWN_DATABASE")
}

/// Cached shard-ledger state of one collection: the shard names plus a generation
/// string that changes whenever the ledger changes (row count + newest
/// `updated_at`). The generation is mixed into the Manticore search cache key, so
/// a newly opened shard invalidates cached searches for that collection within the
/// TTL instead of serving stale results for up to the cache TTL (1 hour).
#[derive(Clone)]
struct ShardStateEntry {
    shards: Vec<String>,
    generation: String,
    fetched: Instant,
}

static SHARD_STATE_CACHE: LazyLock<Mutex<HashMap<String, ShardStateEntry>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// How long a collection's shard list/generation is cached in-process. A new shard
/// becomes visible to search at most this long after the planner opens it.
const SHARD_STATE_TTL: Duration = Duration::from_secs(30);

async fn fetch_shard_state(collectionname: &str) -> anyhow::Result<ShardStateEntry> {
    {
        let cache = SHARD_STATE_CACHE.lock().unwrap();
        if let Some(entry) = cache.get(collectionname)
            && entry.fetched.elapsed() < SHARD_STATE_TTL
        {
            return Ok(entry.clone());
        }
    }
    // Fallible name validation, NOT get_collection_client (which panics): this is
    // reachable from request handlers with registry rows nothing validated, and one
    // bad `collections` row must degrade that collection, not take down search.
    let database = collection_db_name(collectionname)?;
    let client = client_with_database(&database);
    let shards: Vec<String> = match client
        .query("SELECT shard_name FROM manticore_shards FINAL ORDER BY shard_index")
        .fetch_all()
        .await
    {
        Ok(shards) => shards,
        Err(e) if is_unknown_database(&e.to_string()) => Vec::new(),
        Err(e) => return Err(e.into()),
    };
    let generation: String = if shards.is_empty() {
        "empty".to_string()
    } else {
        client
            .query(
                "SELECT concat(toString(count()), '-', toString(ifNull(max(updated_at), toDateTime(0)))) \
                 FROM manticore_shards FINAL",
            )
            .fetch_one()
            .await?
    };
    let entry = ShardStateEntry {
        shards,
        generation,
        fetched: Instant::now(),
    };
    SHARD_STATE_CACHE
        .lock()
        .unwrap()
        .insert(collectionname.to_string(), entry.clone());
    Ok(entry)
}

/// Shard names (`<collectionname>_<n>`) of a collection, from its `manticore_shards`
/// ledger. A collection whose database is not provisioned yet has no shards.
pub async fn list_shards(collectionname: &str) -> anyhow::Result<Vec<String>> {
    Ok(fetch_shard_state(collectionname).await?.shards)
}

/// Cache-busting generation of a collection's shard ledger (cached ~30 s).
pub async fn shard_generation(collectionname: &str) -> anyhow::Result<String> {
    let epoch = cache_epoch().await;
    Ok(format!("{}#{epoch}", fetch_shard_state(collectionname).await?.generation))
}

/// A deliberate, global cache-invalidation lever, appended to every search cache salt.
///
/// The shard generation invalidates a collection's cached searches when its DATA
/// changes. Nothing invalidated them when the SEMANTICS changed: after a schema or
/// query-shape change every cached response is a correct answer to a question the code
/// no longer asks, and the only remedy was to truncate the cache table by hand. Bumping
/// `server_settings.cache_epoch` (any new value) retires every cached search at once.
///
/// Read through the same 30 s TTL as the shard state, and defaulting to `0`: a missing
/// key, an unprovisioned database or a transient failure must degrade to "no extra
/// invalidation", never to an error on the search path.
pub async fn cache_epoch() -> String {
    {
        let cache = CACHE_EPOCH_CACHE.lock().unwrap();
        if let Some((value, fetched)) = cache.as_ref()
            && fetched.elapsed() < SHARD_STATE_TTL
        {
            return value.clone();
        }
    }
    let value: String = get_global_client()
        .query(
            "SELECT argMax(value, updated_at) FROM server_settings WHERE key = 'cache_epoch'",
        )
        .fetch_one()
        .await
        .unwrap_or_default();
    let value = if value.is_empty() { "0".to_string() } else { value };
    *CACHE_EPOCH_CACHE.lock().unwrap() = Some((value.clone(), Instant::now()));
    value
}

static CACHE_EPOCH_CACHE: LazyLock<Mutex<Option<(String, Instant)>>> =
    LazyLock::new(|| Mutex::new(None));

/// The shard a document was indexed into (`manticore_shard_assignments`), or `None`
/// when the document has not been indexed yet.
pub async fn find_shard_for_document(
    collectionname: &str,
    collection_dataset: &str,
    file_hash: &str,
) -> anyhow::Result<Option<String>> {
    let client = get_collection_client(collectionname);
    let rows: Vec<String> = match client
        .query(
            "SELECT shard_name FROM manticore_shard_assignments FINAL \
             WHERE collection_dataset = ? AND file_hash = ? LIMIT 1",
        )
        .bind(collection_dataset)
        .bind(file_hash)
        .fetch_all()
        .await
    {
        Ok(rows) => rows,
        Err(e) if is_unknown_database(&e.to_string()) => return Ok(None),
        Err(e) => return Err(e.into()),
    };
    Ok(rows.into_iter().next())
}

/// All non-deleted collectionnames, sorted.
///
/// Rows with an invalid collectionname are dropped with a warning: the registry is
/// writable outside the validating admin UI (scripts, fixtures, operators), and one
/// bad row must not poison every reader downstream.
pub async fn list_collections() -> anyhow::Result<Vec<String>> {
    let rows: Vec<String> = get_global_client()
        .query("SELECT collectionname FROM collections FINAL WHERE is_deleted = 0 ORDER BY collectionname")
        .fetch_all()
        .await?;
    let mut result = Vec::with_capacity(rows.len());
    for collectionname in rows {
        if collectionname_valid(&collectionname) {
            result.push(collectionname);
        } else {
            tracing::warn!("dropping invalid collectionname from registry row: {collectionname:?}");
        }
    }
    result.sort();
    Ok(result)
}

/// The concrete collections a user may read.
///
/// `PermissionSet::All` (admins, and guests in `all` mode) means "all collections" and
/// is resolved to the concrete list here, at the point of use, rather than being left
/// unbounded for fan-out purposes.
pub async fn list_permitted_collections(user: &CurrentUser) -> anyhow::Result<Vec<String>> {
    match permissions::resolve_permitted_collections(user).await? {
        PermissionSet::All => list_collections().await,
        PermissionSet::Some(set) => {
            let mut list: Vec<String> = set.into_iter().collect();
            list.sort();
            Ok(list)
        }
    }
}

/// Ping ClickHouse with a trivial query. Returns an error (and logs it) when the
/// database can't be reached, so callers can fail loudly instead of silently
/// degrading. Used by the startup health check and available for readiness probes.
///
/// Also reports every collection whose database is not provisioned yet as a WARNING —
/// that is the expected "provisioning" state right after a collection is created, not
/// an error, so it never fails the check.
pub async fn check_clickhouse_health() -> anyhow::Result<()> {
    let url = clickhouse_url();
    if let Err(e) = get_global_client().query("SELECT 1").execute().await {
        tracing::error!("ClickHouse health check FAILED at {url}: {e}");
        return Err(anyhow::anyhow!("ClickHouse unreachable at {url}: {e}"));
    }
    tracing::info!("ClickHouse reachable at {url}");

    match list_collections().await {
        Ok(collections) => {
            for collectionname in collections {
                let Ok(db_name) = collection_db_name(&collectionname) else {
                    continue;
                };
                let count: u64 = get_global_client()
                    .query("SELECT count() FROM system.databases WHERE name = ?")
                    .bind(&db_name)
                    .fetch_one()
                    .await
                    .unwrap_or(0);
                if count == 0 {
                    tracing::warn!(
                        "collection {collectionname} has no ClickHouse database {db_name} yet (still provisioning?)"
                    );
                }
            }
        }
        Err(e) => {
            tracing::warn!("could not list collections during ClickHouse health check: {e}");
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn collection_db_name_valid_slug() {
        assert_eq!(
            collection_db_name("testdata").unwrap(),
            "Hoover4_Collection_testdata"
        );
        assert_eq!(
            collection_db_name("mycollection2024").unwrap(),
            "Hoover4_Collection_mycollection2024"
        );
    }

    #[test]
    fn collection_db_name_rejects_invalid_slugs() {
        for bad in [
            "",
            "Testdata",
            "a; DROP DATABASE x",
            "../etc",
            "a.b",
            "x_1",     // shard-like suffix
            "x_pages", // reserved Manticore suffix
            "x_meta",  // reserved Manticore suffix
            "processing",
        ] {
            assert!(collection_db_name(bad).is_err(), "should reject {bad:?}");
        }
    }

    #[test]
    #[should_panic(expected = "get_collection_client")]
    fn collection_client_panics_on_invalid_name() {
        let _ = get_collection_client("a; DROP DATABASE x");
    }

    #[test]
    fn resolver_caches_positive_hits() {
        let mut resolver = CollectionResolver::default();
        let mut loads = 0;
        let mut loader = |_: &str| {
            loads += 1;
            Some("testdata".to_string())
        };
        assert_eq!(
            resolver
                .resolve_with("testdata_testfiles", &mut loader)
                .as_deref(),
            Some("testdata")
        );
        // Second resolve must be served from the cache without calling the loader.
        assert_eq!(
            resolver
                .resolve_with("testdata_testfiles", &mut loader)
                .as_deref(),
            Some("testdata")
        );
        assert_eq!(loads, 1);
    }

    #[test]
    fn resolver_does_not_cache_negative_lookups() {
        let mut resolver = CollectionResolver::default();
        let mut loads = 0;
        let mut loader = |_: &str| {
            loads += 1;
            None
        };
        assert_eq!(resolver.resolve_with("nosuch_dataset", &mut loader), None);
        // A miss is re-queried next time (dataset may be created later).
        assert_eq!(resolver.resolve_with("nosuch_dataset", &mut loader), None);
        assert_eq!(loads, 2);
        assert!(resolver.get("nosuch_dataset").is_none());
    }

    #[test]
    fn resolver_miss_then_hit() {
        let mut resolver = CollectionResolver::default();
        assert_eq!(resolver.resolve_with("ds", |_| None), None);
        assert_eq!(
            resolver
                .resolve_with("ds", |_| Some("c".to_string()))
                .as_deref(),
            Some("c")
        );
        assert_eq!(resolver.get("ds").as_deref(), Some("c"));
    }

    /// Integration test against the running stack; run with
    /// `cargo test -- --ignored` while ClickHouse is up and `testdata_testfiles`
    /// ingested.
    #[tokio::test]
    #[ignore = "needs live clickhouse"]
    async fn get_client_for_dataset_resolves_testdata() {
        let collectionname = resolve_collection("testdata_testfiles").await.unwrap();
        assert_eq!(collectionname, "testdata");
        let client = get_client_for_dataset("testdata_testfiles").await.unwrap();
        let count: u64 = client
            .query("SELECT count() FROM vfs_files")
            .fetch_one()
            .await
            .unwrap();
        assert!(count > 0);
    }
}
