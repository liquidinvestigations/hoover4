//! Permission resolution and search query sanitization.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use common::{current_user::CurrentUser, search_query::SearchQuery, search_result::FacetOriginalValue};

use crate::db_auth::{collections, settings};

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

struct CacheEntry {
    perms: PermissionSet,
    expires: Instant,
}

static PERM_CACHE: LazyLock<Mutex<HashMap<String, CacheEntry>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

const CACHE_TTL: Duration = Duration::from_secs(60);

pub async fn resolve_permissions(user: &CurrentUser) -> anyhow::Result<PermissionSet> {
    if user.is_admin {
        return Ok(PermissionSet::All);
    }
    if user.is_guest {
        let mode = settings::get_setting("guest_permissions_mode")
            .await?
            .unwrap_or_else(|| "all".to_string());
        if mode == "all" {
            return Ok(PermissionSet::All);
        }
        return Ok(PermissionSet::Some(HashSet::new()));
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
    let perms = PermissionSet::Some(datasets.into_iter().collect());

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
