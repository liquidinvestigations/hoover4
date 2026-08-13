//! Session cookie middleware and identity resolution.
//!
//! **One route mints, everything else requires.** Session creation — a `web_sessions`
//! row, a `guest-*` user, a `user_login` event, a `set-cookie` header — happens only on
//! the route [`crate::auth::route_policy::is_session_mint_route`] names. Every other
//! server function and every custom byte route answers `401` when nothing resolved an
//! identity; the app shell is served regardless, because the browser needs it to reach
//! the mint route at all.
//!
//! Two things follow from that, and both are the point:
//!
//! * a client that does not store cookies cannot accumulate users. It gets one `401` per
//!   request instead of one `guest-<hex>` and one `user_login` row per request.
//! * with [`demo_mode`] off, nothing mints a guest at all, so an unauthenticated visitor
//!   fails the mint route and the app refuses to render — which is the intended
//!   behaviour of a deployment that expects a reverse proxy to authenticate.

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
/// The grant is applied to the REQUEST, never written to the account: a guest's `users`
/// row keeps `is_admin = false` while `whoami` reports true for the same session, and
/// that disagreement is the design. The elevation belongs to the deployment and lasts
/// exactly as long as the switch does — persisting it would leave real administrators
/// behind the day the switch is turned off. `/admin/users` says so on the page, because
/// the two readings sit side by side there.
///
/// Wired up in Docker via the `HOOVER4_DEMO_MODE` environment variable on the
/// `hoover4-website` service. Accepts `1`, `true`, `yes`, or `on`
/// (case-insensitive); anything else — including unset — means normal auth.
pub fn demo_mode() -> bool {
    std::env::var("HOOVER4_DEMO_MODE")
        .map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(false)
}

/// May a visitor who proved nothing be given an anonymous `guest-*` identity?
///
/// Only in demo mode, and only on the mint route. With it off, a deployment has exactly
/// one way in — a reverse proxy that sets `X-Forwarded-User` — and a visitor arriving
/// without one is refused rather than silently provisioned. That refusal is the whole
/// difference between a public demo and an access-controlled deployment, so it is derived
/// from the demo switch in this one place rather than being a second switch that can
/// disagree with it.
pub fn guest_sessions_allowed() -> bool {
    demo_mode()
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

/// The username refusals are recorded under.
///
/// A constant, never anything derived from the request: `api_events.username` is
/// `LowCardinality`, and a refused caller has by definition not proved a name.
const ANONYMOUS: &str = "anonymous";

/// Read the session id out of the request's `Cookie` header.
fn cookie_session_id(request: &Request) -> Option<String> {
    request
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
        })
}

/// Resolve the caller from a session cookie or a proxy-set identity header, and — only on
/// the mint route — create a session for them when neither exists yet.
///
/// Returns `None` when nothing identified the caller. `may_mint` is the whole of the "one
/// route mints" rule: with it false this function reads state and never writes a session,
/// a user row or a `user_login` event.
///
/// Takes the two things it needs out of the request as owned values rather than borrowing
/// it: `axum::middleware::from_fn` demands a `Send` future, and holding a `&Request` — and
/// therefore a `&Body`, which is not `Sync` — across an await makes it one that is not.
/// The resulting error names the middleware layer and not this function.
async fn resolve_identity(
    cookie_sid: Option<String>,
    header_identity: Option<HeaderIdentity>,
    may_mint: bool,
    session_expiration: u64,
) -> Option<(CurrentUser, Option<NewCookie>)> {
    let existing_session: Option<SessionRow> = if let Some(ref sid) = cookie_sid {
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

    if let Some(identity) = header_identity {
        // A proxy-set identity is proof on its own — the proxy is the thing that
        // authenticated it — so it is honoured on every route, not only the mint route.
        // What is confined to the mint route is *writing a session for it*.
        if let Err(e) = sync_header_user(&identity).await {
            tracing::error!("header identity sync failed for {}: {e}", identity.username);
        }
        let from_headers = || CurrentUser {
            username: identity.username.clone(),
            fullname: identity.fullname.clone(),
            email: identity.email.clone(),
            is_admin: is_admin_from_groups(&identity.groups),
            is_guest: false,
            groups: identity.groups.clone(),
        };

        let session_matches = existing_session
            .as_ref()
            .is_some_and(|s| s.username == identity.username);

        if session_matches {
            let sid = cookie_sid.expect("a matching session implies a cookie");
            if let Some(cached) = get_cached_user(&sid) {
                return Some((cached, None));
            }
            return match build_current_user_from_db(&identity.username).await {
                Ok(user) => {
                    cache_user(&sid, &user);
                    Some((user, None))
                }
                Err(_) => Some((from_headers(), None)),
            };
        }

        if may_mint {
            let expires_at =
                OffsetDateTime::now_utc() + time::Duration::seconds(session_expiration as i64);
            if let Ok(session) = sessions::create_session(&identity.username, expires_at).await {
                telemetry::record_event(&identity.username, telemetry::EVENT_USER_LOGIN, "");
                return Some((
                    from_headers(),
                    Some(NewCookie {
                        session_id: session.session_id,
                        max_age: session_expiration,
                    }),
                ));
            }
        }
        return Some((from_headers(), None));
    }

    // Anonymous. A cookie whose session row is readable identifies its guest with no
    // writes at all, so a browser that already has one never mints again.
    if let (Some(sid), Some(session)) = (cookie_sid.as_ref(), existing_session.as_ref()) {
        if let Some(cached) = get_cached_user(sid) {
            return Some((cached, None));
        }
        // Read the row rather than assuming a guest. A session cookie is resumable
        // identity: the user it names may be a real account whose proxy headers are not on
        // *this* request, and building them from the username alone would silently drop
        // their admin flag and their groups.
        let user = match build_current_user_from_db(&session.username).await {
            Ok(user) => user,
            Err(e) => {
                tracing::error!("session {sid} names {}, which does not resolve: {e}", session.username);
                let groups = load_groups_for_user(&session.username).await.unwrap_or_default();
                CurrentUser {
                    username: session.username.clone(),
                    fullname: String::new(),
                    email: String::new(),
                    is_admin: false,
                    is_guest: session.username.starts_with("guest-"),
                    groups,
                }
            }
        };
        cache_user(sid, &user);
        return Some((user, None));
    }

    if !(may_mint && guest_sessions_allowed()) {
        return None;
    }

    // Mint. The cookie is the durable anchor: a browser holding a cookie whose session row
    // has expired or been lost re-anchors to the SAME id, which derives the SAME guest
    // username — so a re-anchor costs no new user row. Only a caller with no cookie at all
    // creates one.
    let session_id = cookie_sid
        .clone()
        .unwrap_or_else(sessions::generate_session_id);
    let username = guest_username_for_session(&session_id);
    let expires_at = OffsetDateTime::now_utc() + time::Duration::seconds(session_expiration as i64);

    // Best-effort persistence so the admin user list stays populated and the session
    // survives server restarts. A failure here must NOT change the identity the browser
    // sees — the cookie already fixes it — but it is logged so a broken DB is never
    // invisible.
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
    telemetry::record_event(&username, telemetry::EVENT_USER_LOGIN, "");

    let groups = load_groups_for_user(&username).await.unwrap_or_default();
    let user = CurrentUser {
        username,
        fullname: String::new(),
        email: String::new(),
        is_admin: false,
        is_guest: true,
        groups,
    };
    cache_user(&session_id, &user);
    Some((
        user,
        Some(NewCookie {
            session_id,
            max_age: session_expiration,
        }),
    ))
}

/// The response an endpoint gives when nothing identified the caller.
fn no_session_response() -> Response {
    axum::response::Response::builder()
        .status(axum::http::StatusCode::UNAUTHORIZED)
        .header(axum::http::header::CONTENT_TYPE, "text/plain; charset=utf-8")
        .body(axum::body::Body::from(
            crate::auth::route_policy::NO_SESSION_MESSAGE,
        ))
        .unwrap_or_else(|_| axum::response::Response::default())
}

pub async fn session_middleware(mut request: Request, next: Next) -> Response {
    let session_expiration = settings::get_setting_u64("session_expiration_seconds", 604_800)
        .await
        .unwrap_or(604_800);

    let path = request.uri().path().to_string();
    let (route_class, function_name) = telemetry::classify_path(&path);
    let may_mint = crate::auth::route_policy::is_session_mint_route(&path);

    let Some((current_user, new_cookie)) = resolve_identity(
        cookie_session_id(&request),
        parse_headers(&request),
        may_mint,
        session_expiration,
    )
    .await
    else {
        if crate::auth::route_policy::requires_session(&path) {
            // Recorded so a flood of refusals is visible on the metrics page, under a
            // constant username and NOT as an error: a 401 is a correct, complete answer
            // to a request that proved nothing, exactly as a 404 is to one about
            // something that is not there.
            if let Some(fn_name) = function_name {
                telemetry::record_api_event(
                    ANONYMOUS,
                    telemetry::EVENT_USER_OTHER_REQUEST,
                    fn_name,
                    false,
                    0,
                    0,
                    0,
                );
            }
            return no_session_response();
        }
        // The app shell: served open, with no identity attached. A server function
        // reached during server-side rendering finds no `CurrentUser` and says so; the
        // browser then calls the mint route and re-runs it with a session.
        return next.run(request).await;
    };

    // Single demo switch: in demo mode, anonymous guests are administrators.
    let mut current_user = current_user;
    if current_user.is_guest && demo_mode() {
        current_user.is_admin = true;
    }

    // Telemetry + rate limiting for API calls (server functions and the
    // download route). Static assets are neither limited nor recorded.
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
        // A 404 is not breakage: it is a complete, correct answer about something that is
        // not there. Counting it made a crawler walking chat URLs with fresh guest
        // cookies read as a 22 % error rate on the admin metrics page.
        let counts_as_error = (status.is_server_error() || status.is_client_error())
            && status != axum::http::StatusCode::NOT_FOUND;
        telemetry::record_api_event(
            &current_user.username,
            event_type,
            fn_name,
            counts_as_error,
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

#[cfg(test)]
mod tests {
    use super::*;

    /// The property that keeps a returning visitor from becoming a second user.
    ///
    /// A browser holding a cookie whose `web_sessions` row has expired, or been lost to a
    /// database reset, re-anchors to the id it already has — so the derived username is
    /// the one it had before and no row is added. Randomising it instead mints a new
    /// `guest-<hex>` on every such re-anchor, which is one of the ways they accumulate.
    #[test]
    fn a_guest_name_is_derived_from_the_session_and_never_drifts() {
        let sid = "1c0b6754517b641a9d3e5f00aa11bb22cc33dd44ee55ff6600112233445566778";
        assert_eq!(
            guest_username_for_session(sid),
            guest_username_for_session(sid)
        );
        assert!(guest_username_for_session(sid).starts_with("guest-"));
        assert_ne!(
            guest_username_for_session(sid),
            guest_username_for_session("ffffffffffffffff0000000000000000")
        );
    }

    /// The demo switch is one switch. Guest provisioning and guest-as-admin are two
    /// consequences of it, and a deployment cannot end up with one without the other —
    /// which would be a site that hands out anonymous identities and then refuses them
    /// everything, or one that refuses to sign anybody in and treats them as root.
    #[test]
    fn guest_provisioning_follows_the_demo_switch() {
        assert_eq!(guest_sessions_allowed(), demo_mode());
    }
}
