//! Session cookie middleware and identity resolution.

use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use axum::extract::{Request};
use axum::middleware::Next;
use axum::response::Response;
use axum_extra::extract::cookie::{Cookie, SameSite};
use common::current_user::CurrentUser;
use time::OffsetDateTime;

use crate::api::{rate_limit, telemetry};
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

/// Demo deployments set a single env switch so that anonymous `guest-*`
/// sessions are treated as administrators. This is the only place the switch is
/// read; everything downstream (the frontend `AdminGuard` and every backend
/// `require_admin` call) keys off the resulting `CurrentUser::is_admin`.
///
/// Wired up in Docker via the `HOOVER4_DEMO_MODE` environment variable on the
/// `hoover4-website` service. Accepts `1`, `true`, `yes`, or `on`
/// (case-insensitive); anything else — including unset — means normal auth.
pub fn demo_mode() -> bool {
    std::env::var("HOOVER4_DEMO_MODE")
        .map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false)
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

/// Derive a stable guest username from the session id.
///
/// The session id lives in the browser cookie, so deriving the username from it
/// means a refresh always resolves to the *same* guest — even if the backing DB
/// row is momentarily unreadable — instead of minting a new random identity.
fn guest_username_for_session(session_id: &str) -> String {
    let suffix: String = session_id.chars().take(12).collect();
    format!("guest-{suffix}")
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
        match sessions::get_session(sid).await {
            Ok(session) => session,
            Err(e) => {
                // A DB error here is not the same as "no session" — surface it so a
                // down/unreachable ClickHouse is visible instead of silently
                // dropping the user to a fresh guest every request.
                tracing::error!("session lookup failed for cookie session: {e}");
                None
            }
        }
    } else {
        None
    };

    let current_user = if let Some(identity) = parse_headers(&request) {
        if let Err(e) = sync_header_user(&identity).await {
            tracing::error!("header identity sync failed for {}: {e}", identity.username);
        }

        let needs_new_session = existing_session
            .as_ref()
            .map(|s| s.username != identity.username)
            .unwrap_or(true);

        if needs_new_session {
            let expires_at =
                OffsetDateTime::now_utc() + time::Duration::seconds(session_expiration as i64);
            if let Ok(session) = sessions::create_session(&identity.username, expires_at).await {
                telemetry::record_event(&identity.username, telemetry::EVENT_USER_LOGIN, "");
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
    } else {
        // Anonymous guest. The session cookie is the durable anchor: whatever id
        // the browser already holds is reused, so a page refresh resolves to the
        // *same* guest instead of minting a new one. Only when there is no cookie
        // at all do we generate a fresh session id.
        let session_id = cookie_session_id
            .clone()
            .unwrap_or_else(sessions::generate_session_id);

        // Prefer the username already stored for this session; otherwise derive a
        // stable one from the session id. Deriving (rather than randomising) means
        // the identity survives even if the DB row can't be read this request.
        let username = existing_session
            .as_ref()
            .map(|s| s.username.clone())
            .unwrap_or_else(|| guest_username_for_session(&session_id));

        // A guest with no valid stored session is a first visit (or a
        // re-anchor of an expired one): that is their "login".
        if existing_session.is_none() {
            telemetry::record_event(&username, telemetry::EVENT_USER_LOGIN, "");
        }

        let user = if let Some(cached) = get_cached_user(&session_id) {
            cached
        } else {
            let expires_at =
                OffsetDateTime::now_utc() + time::Duration::seconds(session_expiration as i64);

            // Best-effort persistence so the admin user list stays populated and
            // the session survives server restarts. A failure here must NOT change
            // the identity the browser sees — the cookie already fixes it — but it
            // is logged so a broken DB is never invisible.
            if let Err(e) = users::upsert_user(UserRow {
                username: username.clone(),
                fullname: String::new(),
                email: String::new(),
                is_admin: false,
                created_at: OffsetDateTime::now_utc(),
                updated_at: OffsetDateTime::now_utc(),
                is_deleted: 0,
            })
            .await
            {
                tracing::error!("guest user upsert failed for {username}: {e}");
            }
            if let Err(e) = sessions::upsert_session(&session_id, &username, expires_at).await {
                tracing::error!("guest session upsert failed for {username}: {e}");
            }

            let groups = match load_groups_for_user(&username).await {
                Ok(groups) => groups,
                Err(e) => {
                    tracing::error!("loading groups for guest {username} failed: {e}");
                    Vec::new()
                }
            };
            let user = CurrentUser {
                username,
                fullname: String::new(),
                email: String::new(),
                is_admin: false,
                is_guest: true,
                groups,
            };
            cache_user(&session_id, &user);
            user
        };

        // Hand the browser this session id whenever it isn't already the one it
        // sent (first visit, or a stale/expired cookie being re-anchored).
        if cookie_session_id.as_deref() != Some(session_id.as_str()) {
            new_cookie = Some(NewCookie {
                session_id: session_id.clone(),
                max_age: session_expiration,
            });
        }

        user
    };

    // Single demo switch: in demo mode, anonymous guests are administrators.
    let mut current_user = current_user;
    if current_user.is_guest && demo_mode() {
        current_user.is_admin = true;
    }

    // Telemetry + rate limiting for API calls (server functions and the
    // download route). Static assets are neither limited nor recorded.
    let path = request.uri().path().to_string();
    let (route_class, function_name) = telemetry::classify_path(&path);
    let bytes_in = request
        .headers()
        .get(axum::http::header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|v| v.parse::<u32>().ok())
        .unwrap_or(0);

    if let Some(_fn_name) = function_name {
        if let Err(limit) = rate_limit::check_and_record(
            &current_user.username,
            rate_limit::RateLimitKind::ApiCall,
        ) {
            tracing::debug!(
                "rate limit refusal for {} ({} window)",
                current_user.username,
                limit.window
            );
            return axum::response::Response::builder()
                .status(axum::http::StatusCode::TOO_MANY_REQUESTS)
                .header(axum::http::header::RETRY_AFTER, limit.retry_after_seconds)
                .body(axum::body::Body::from(limit.to_string()))
                .unwrap_or_else(|_| axum::response::Response::default());
        }
    }

    let started = Instant::now();
    request.extensions_mut().insert(current_user.clone());
    let mut response = next.run(request).await;

    if let Some(fn_name) = function_name {
        let status = response.status();
        let bytes_out = response
            .headers()
            .get(axum::http::header::CONTENT_LENGTH)
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<u32>().ok())
            .unwrap_or(0);
        let event_type = match route_class {
            telemetry::RouteClass::Search => telemetry::EVENT_USER_SEARCH,
            telemetry::RouteClass::Document => telemetry::EVENT_USER_GET_DOCUMENT,
            _ => telemetry::EVENT_USER_OTHER_REQUEST,
        };
        telemetry::record_api_event(
            &current_user.username,
            event_type,
            fn_name,
            status.is_server_error() || status.is_client_error(),
            started.elapsed().as_millis().min(u32::MAX as u128) as u32,
            bytes_in,
            bytes_out,
        );
        // The search and document usage events are recorded by the backend
        // handlers themselves; everything else is the catch-all.
        if route_class == telemetry::RouteClass::Other {
            telemetry::record_event(
                &current_user.username,
                telemetry::EVENT_USER_OTHER_REQUEST,
                "{\"class\":\"api\"}",
            );
        }
    }

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
