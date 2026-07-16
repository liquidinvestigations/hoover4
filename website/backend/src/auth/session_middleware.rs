//! Session cookie middleware and identity resolution.

use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use axum::extract::{Request};
use axum::middleware::Next;
use axum::response::Response;
use axum_extra::extract::cookie::{Cookie, SameSite};
use common::current_user::CurrentUser;
use rand::Rng;
use time::OffsetDateTime;

use crate::db_auth::{
    groups::{self, GroupRow},
    sessions::{self, SessionRow},
    settings,
    users::{self, UserRow},
};

pub const SESSION_COOKIE: &str = "hoover4_session";

struct SyncCacheEntry {
    expires: Instant,
}

static SYNC_CACHE: LazyLock<Mutex<HashMap<String, SyncCacheEntry>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

struct UserCacheEntry {
    user: CurrentUser,
    expires: Instant,
}

static USER_CACHE: LazyLock<Mutex<HashMap<String, UserCacheEntry>>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

const CACHE_TTL: Duration = Duration::from_secs(60);

struct HeaderIdentity {
    username: String,
    fullname: String,
    email: String,
    groups: Vec<String>,
}

fn parse_headers(request: &Request) -> Option<HeaderIdentity> {
    let headers = request.headers();
    let username = headers
        .get("x-forwarded-user")
        .or_else(|| headers.get("X-Forwarded-User"))
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())?
        .to_string();

    let fullname = headers
        .get("x-forwarded-preferred-username")
        .or_else(|| headers.get("X-Forwarded-Preferred-Username"))
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .trim()
        .to_string();

    let email = headers
        .get("x-forwarded-email")
        .or_else(|| headers.get("X-Forwarded-Email"))
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .trim()
        .to_string();

    let groups: Vec<String> = headers
        .get("x-forwarded-groups")
        .or_else(|| headers.get("X-Forwarded-Groups"))
        .and_then(|v| v.to_str().ok())
        .map(|s| {
            let mut seen = std::collections::HashSet::new();
            s.split(',')
                .map(str::trim)
                .filter(|g| !g.is_empty())
                .filter(|g| seen.insert((*g).to_string()))
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();

    Some(HeaderIdentity {
        username,
        fullname,
        email,
        groups,
    })
}

fn is_admin_from_groups(groups: &[String]) -> bool {
    groups.iter().any(|g| g == "admin" || g == "superuser")
}

fn should_sync(username: &str) -> bool {
    let mut cache = SYNC_CACHE.lock().unwrap();
    if let Some(entry) = cache.get(username) {
        if entry.expires > Instant::now() {
            return false;
        }
    }
    cache.insert(
        username.to_string(),
        SyncCacheEntry {
            expires: Instant::now() + CACHE_TTL,
        },
    );
    true
}

async fn sync_header_user(identity: &HeaderIdentity) -> anyhow::Result<()> {
    if !should_sync(&identity.username) {
        return Ok(());
    }

    let is_admin = is_admin_from_groups(&identity.groups);
    users::upsert_user(UserRow {
        username: identity.username.clone(),
        fullname: identity.fullname.clone(),
        email: identity.email.clone(),
        is_admin,
        created_at: time::OffsetDateTime::now_utc(),
        updated_at: time::OffsetDateTime::now_utc(),
        is_deleted: 0,
    })
    .await?;

    for groupname in &identity.groups {
        if groups::get_group(groupname).await?.is_none() {
            groups::upsert_group(GroupRow {
                groupname: groupname.clone(),
                fullname: groupname.clone(),
                created_at: time::OffsetDateTime::now_utc(),
                updated_at: time::OffsetDateTime::now_utc(),
                is_deleted: 0,
            })
            .await?;
        }
    }

    groups::sync_header_memberships(&identity.username, &identity.groups).await?;
    Ok(())
}

async fn load_groups_for_user(username: &str) -> anyhow::Result<Vec<String>> {
    let memberships = groups::list_memberships_for_user(username).await?;
    Ok(memberships.into_iter().map(|m| m.groupname).collect())
}

async fn build_current_user_from_db(username: &str) -> anyhow::Result<CurrentUser> {
    let user = users::get_user(username)
        .await?
        .ok_or_else(|| anyhow::anyhow!("user not found: {username}"))?;
    let groups = load_groups_for_user(username).await?;
    Ok(CurrentUser {
        username: user.username.clone(),
        fullname: user.fullname,
        email: user.email,
        is_admin: user.is_admin,
        is_guest: user.username.starts_with("guest-"),
        groups,
    })
}

fn get_cached_user(session_id: &str) -> Option<CurrentUser> {
    let cache = USER_CACHE.lock().unwrap();
    cache.get(session_id).and_then(|entry| {
        if entry.expires > Instant::now() {
            Some(entry.user.clone())
        } else {
            None
        }
    })
}

fn cache_user(session_id: &str, user: &CurrentUser) {
    let mut cache = USER_CACHE.lock().unwrap();
    cache.insert(
        session_id.to_string(),
        UserCacheEntry {
            user: user.clone(),
            expires: Instant::now() + CACHE_TTL,
        },
    );
}

fn guest_username() -> String {
    let n: u32 = rand::rng().random_range(1..=1_000_000_000);
    format!("guest-{n}")
}

struct NewCookie {
    session_id: String,
    max_age: u64,
}

pub async fn session_middleware(mut request: Request, next: Next) -> Response {
    let mut new_cookie: Option<NewCookie> = None;
    let session_expiration = settings::get_setting_u64("session_expiration_seconds", 604_800)
        .await
        .unwrap_or(604_800);

    let cookie_session_id = request
        .headers()
        .get(axum::http::header::COOKIE)
        .and_then(|v| v.to_str().ok())
        .and_then(|cookies| {
            cookies.split(';').find_map(|pair| {
                let (name, value) = pair.trim().split_once('=')?;
                if name == SESSION_COOKIE {
                    Some(value.to_string())
                } else {
                    None
                }
            })
        });

    let existing_session: Option<SessionRow> = if let Some(ref sid) = cookie_session_id {
        sessions::get_session(sid).await.ok().flatten()
    } else {
        None
    };

    let current_user = if let Some(identity) = parse_headers(&request) {
        let _ = sync_header_user(&identity).await;

        let needs_new_session = existing_session
            .as_ref()
            .map(|s| s.username != identity.username)
            .unwrap_or(true);

        if needs_new_session {
            let expires_at =
                OffsetDateTime::now_utc() + time::Duration::seconds(session_expiration as i64);
            if let Ok(session) = sessions::create_session(&identity.username, expires_at).await {
                new_cookie = Some(NewCookie {
                    session_id: session.session_id.clone(),
                    max_age: session_expiration,
                });
                CurrentUser {
                    username: identity.username,
                    fullname: identity.fullname,
                    email: identity.email,
                    is_admin: is_admin_from_groups(&identity.groups),
                    is_guest: false,
                    groups: identity.groups,
                }
            } else {
                CurrentUser {
                    username: identity.username.clone(),
                    fullname: identity.fullname,
                    email: identity.email,
                    is_admin: is_admin_from_groups(&identity.groups),
                    is_guest: false,
                    groups: identity.groups,
                }
            }
        } else if let Some(ref sid) = cookie_session_id {
            if let Some(cached) = get_cached_user(sid) {
                cached
            } else if let Ok(user) = build_current_user_from_db(&identity.username).await {
                cache_user(sid, &user);
                user
            } else {
                CurrentUser {
                    username: identity.username,
                    fullname: identity.fullname,
                    email: identity.email,
                    is_admin: is_admin_from_groups(&identity.groups),
                    is_guest: false,
                    groups: identity.groups,
                }
            }
        } else {
            CurrentUser {
                username: identity.username,
                fullname: identity.fullname,
                email: identity.email,
                is_admin: is_admin_from_groups(&identity.groups),
                is_guest: false,
                groups: identity.groups,
            }
        }
    } else if let Some(session) = existing_session {
        let sid = session.session_id.clone();
        if let Some(cached) = get_cached_user(&sid) {
            cached
        } else if let Ok(user) = build_current_user_from_db(&session.username).await {
            cache_user(&sid, &user);
            user
        } else {
            let username = guest_username();
            let _ = users::upsert_user(UserRow {
                username: username.clone(),
                fullname: String::new(),
                email: String::new(),
                is_admin: false,
                created_at: OffsetDateTime::now_utc(),
                updated_at: OffsetDateTime::now_utc(),
                is_deleted: 0,
            })
            .await;
            let expires_at =
                OffsetDateTime::now_utc() + time::Duration::seconds(session_expiration as i64);
            if let Ok(s) = sessions::create_session(&username, expires_at).await {
                new_cookie = Some(NewCookie {
                    session_id: s.session_id,
                    max_age: session_expiration,
                });
            }
            CurrentUser {
                username,
                fullname: String::new(),
                email: String::new(),
                is_admin: false,
                is_guest: true,
                groups: vec![],
            }
        }
    } else {
        let username = guest_username();
        let _ = users::upsert_user(UserRow {
            username: username.clone(),
            fullname: String::new(),
            email: String::new(),
            is_admin: false,
            created_at: OffsetDateTime::now_utc(),
            updated_at: OffsetDateTime::now_utc(),
            is_deleted: 0,
        })
        .await;
        let expires_at =
            OffsetDateTime::now_utc() + time::Duration::seconds(session_expiration as i64);
        if let Ok(session) = sessions::create_session(&username, expires_at).await {
            new_cookie = Some(NewCookie {
                session_id: session.session_id,
                max_age: session_expiration,
            });
        }
        CurrentUser {
            username,
            fullname: String::new(),
            email: String::new(),
            is_admin: false,
            is_guest: true,
            groups: vec![],
        }
    };

    request.extensions_mut().insert(current_user);
    let mut response = next.run(request).await;

    if let Some(cookie) = new_cookie {
        let cookie = Cookie::build((SESSION_COOKIE, cookie.session_id))
            .http_only(true)
            .same_site(SameSite::Lax)
            .path("/")
            .max_age(time::Duration::seconds(cookie.max_age as i64))
            .build();
        if let Ok(header) = cookie.to_string().parse() {
            response.headers_mut().append(axum::http::header::SET_COOKIE, header);
        }
    }

    response
}
