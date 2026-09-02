//! Permission resolution and search query sanitization.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use common::{current_user::CurrentUser, search_query::SearchQuery, search_result::FacetOriginalValue};

use crate::db_auth::collections;

#[derive(Debug, Clone)]
pub enum PermissionSet {
    All,
    Some(HashSet<String>),
}

impl PermissionSet {
    pub fn allows(&self, collection_dataset: &str) -> bool {
        match self {
            PermissionSet::All => true,
            PermissionSet::Some(set) => set.contains(collection_dataset),
        }
    }

    pub fn is_empty(&self) -> bool {
        match self {
            PermissionSet::All => false,
            PermissionSet::Some(set) => set.is_empty(),
        }
    }

    pub fn as_set(&self) -> Option<&HashSet<String>> {
        match self {
            PermissionSet::All => None,
            PermissionSet::Some(set) => Some(set),
        }
    }
}

/// The two faces of one permission decision: which `collection_dataset` values a user
/// may read, and which collections those datasets belong to. Kept in a single cache
/// entry so the two can never drift.
#[derive(Debug, Clone)]
struct CachedPerms {
    datasets: PermissionSet,
    collections: PermissionSet,
}

struct CacheEntry {
    perms: CachedPerms,
    expires: Instant,
}

static PERM_CACHE: LazyLock<Mutex<HashMap<String, CacheEntry>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

const CACHE_TTL: Duration = Duration::from_secs(60);

/// Drop every cached permission set.
///
/// Called from the admin write paths (grant, revoke, publish/unpublish). Without it an
/// access change takes up to [`CACHE_TTL`] to appear, which reads as a bug when an
/// admin flips a switch and reloads. Clearing everything rather than one username is
/// deliberate: a collection-level change affects every member of every granted group.
pub fn invalidate_permission_cache() {
    PERM_CACHE.lock().unwrap().clear();
}

/// The permission set of someone with no group membership at all: exactly the
/// collections flagged public, and the datasets inside them.
async fn public_only_perms() -> anyhow::Result<CachedPerms> {
    let collection_names = collections::public_collections().await?;
    let mut datasets = HashSet::new();
    for name in &collection_names {
        for link in collections::list_collection_datasets(name).await? {
            datasets.insert(link.collection_dataset);
        }
    }
    Ok(CachedPerms {
        datasets: PermissionSet::Some(datasets),
        collections: PermissionSet::Some(collection_names.into_iter().collect()),
    })
}

/// Add every publicly flagged collection and its datasets to a group-derived set.
///
/// A user in no group must still see a public collection, so this runs for every
/// authenticated user, on top of whatever their groups already grant.
fn add_public(perms: CachedPerms, public: CachedPerms) -> CachedPerms {
    match (perms, public) {
        (CachedPerms { datasets: PermissionSet::All, .. }, _) => CachedPerms {
            datasets: PermissionSet::All,
            collections: PermissionSet::All,
        },
        (
            CachedPerms { datasets: PermissionSet::Some(mut datasets), collections: PermissionSet::Some(mut collections) },
            CachedPerms { datasets: PermissionSet::Some(public_datasets), collections: PermissionSet::Some(public_collections) },
        ) => {
            datasets.extend(public_datasets);
            collections.extend(public_collections);
            CachedPerms {
                datasets: PermissionSet::Some(datasets),
                collections: PermissionSet::Some(collections),
            }
        }
        // `public_only_perms` always returns `Some`, so the two `Some` arms above cover
        // every case except the group set already being `All`, handled first.
        (perms, _) => perms,
    }
}

async fn resolve_cached_perms(user: &CurrentUser) -> anyhow::Result<CachedPerms> {
    if user.is_admin {
        return Ok(CachedPerms {
            datasets: PermissionSet::All,
            collections: PermissionSet::All,
        });
    }

    {
        let cache = PERM_CACHE.lock().unwrap();
        if let Some(entry) = cache.get(&user.username) {
            if entry.expires > Instant::now() {
                return Ok(entry.perms.clone());
            }
        }
    }

    let datasets = collections::permitted_collection_datasets(&user.username).await?;
    let collection_names = collections::permitted_collections(&user.username).await?;
    let group_perms = CachedPerms {
        datasets: PermissionSet::Some(datasets.into_iter().collect()),
        collections: PermissionSet::Some(collection_names.into_iter().collect()),
    };
    let perms = add_public(group_perms, public_only_perms().await?);

    {
        let mut cache = PERM_CACHE.lock().unwrap();
        cache.insert(
            user.username.clone(),
            CacheEntry {
                perms: perms.clone(),
                expires: Instant::now() + CACHE_TTL,
            },
        );
    }

    Ok(perms)
}

/// The set of `collection_dataset` values the user may read.
pub async fn resolve_permissions(user: &CurrentUser) -> anyhow::Result<PermissionSet> {
    Ok(resolve_cached_perms(user).await?.datasets)
}

/// The set of collectionnames the user may read.
///
/// `PermissionSet::All` (admins) means "all collections". Callers that fan out per
/// collection must resolve it to the concrete list with
/// `clickhouse_utils::list_collections()` at the point of use (see
/// `list_permitted_collections`), not leave it unbounded.
pub async fn resolve_permitted_collections(user: &CurrentUser) -> anyhow::Result<PermissionSet> {
    Ok(resolve_cached_perms(user).await?.collections)
}

pub fn sanitize_query(query: SearchQuery, perms: &PermissionSet) -> Option<SearchQuery> {
    match perms {
        PermissionSet::All => Some(query),
        PermissionSet::Some(permitted) => {
            if permitted.is_empty() {
                return None;
            }
            let mut query = query;
            let user_selection: BTreeSet<String> = query
                .facet_filters
                .get("collection_dataset")
                .map(|set| {
                    set.iter()
                        .filter_map(|v| {
                            if let FacetOriginalValue::String(s) = v {
                                Some(s.clone())
                            } else {
                                None
                            }
                        })
                        .collect()
                })
                .unwrap_or_default();

            let effective: Vec<String> = if user_selection.is_empty() {
                permitted.iter().cloned().collect()
            } else {
                user_selection
                    .into_iter()
                    .filter(|d| permitted.contains(d))
                    .collect()
            };

            if effective.is_empty() {
                return None;
            }

            let facet_set: BTreeSet<FacetOriginalValue> = effective
                .iter()
                .map(|d| FacetOriginalValue::String(d.clone()))
                .collect();
            query
                .facet_filters
                .insert("collection_dataset".to_string(), facet_set);
            query.collection_datasets = effective;
            Some(query)
        }
    }
}

pub async fn assert_can_read(user: &CurrentUser, collection_dataset: &str) -> anyhow::Result<()> {
    let perms = resolve_permissions(user).await?;
    if perms.allows(collection_dataset) {
        Ok(())
    } else {
        anyhow::bail!("forbidden: no read access to collection_dataset {collection_dataset}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn some_perms(datasets: &[&str]) -> PermissionSet {
        PermissionSet::Some(datasets.iter().map(|s| s.to_string()).collect())
    }

    fn query_with_selection(selection: &[&str]) -> SearchQuery {
        let mut query = SearchQuery::default();
        if !selection.is_empty() {
            query.facet_filters.insert(
                "collection_dataset".to_string(),
                selection
                    .iter()
                    .map(|s| FacetOriginalValue::String(s.to_string()))
                    .collect(),
            );
        }
        query
    }

    #[test]
    fn sanitize_all_passes_query_through() {
        let query = query_with_selection(&["anything"]);
        let sanitized = sanitize_query(query.clone(), &PermissionSet::All).unwrap();
        assert_eq!(sanitized.facet_filters, query.facet_filters);
    }

    #[test]
    fn sanitize_empty_set_blocks_query() {
        let query = query_with_selection(&[]);
        assert!(sanitize_query(query, &some_perms(&[])).is_none());
    }

    #[test]
    fn sanitize_no_selection_defaults_to_permitted() {
        let query = query_with_selection(&[]);
        let sanitized =
            sanitize_query(query, &some_perms(&["a_ds", "b_ds"])).unwrap();
        let mut effective = sanitized.collection_datasets.clone();
        effective.sort();
        assert_eq!(effective, vec!["a_ds", "b_ds"]);
        assert!(sanitized.facet_filters.contains_key("collection_dataset"));
    }

    #[test]
    fn sanitize_user_selection_is_intersected_with_permitted() {
        let query = query_with_selection(&["a_ds", "not_permitted_ds"]);
        let sanitized = sanitize_query(query, &some_perms(&["a_ds", "b_ds"])).unwrap();
        assert_eq!(sanitized.collection_datasets, vec!["a_ds"]);
    }

    #[test]
    fn sanitize_selection_outside_permitted_blocks_query() {
        let query = query_with_selection(&["not_permitted_ds"]);
        assert!(sanitize_query(query, &some_perms(&["a_ds"])).is_none());
    }

    #[test]
    fn permission_set_allows() {
        assert!(PermissionSet::All.allows("anything"));
        let some = some_perms(&["a_ds"]);
        assert!(some.allows("a_ds"));
        assert!(!some.allows("b_ds"));
        assert!(!some.is_empty());
        assert!(some_perms(&[]).is_empty());
        assert!(!PermissionSet::All.is_empty());
    }
}
