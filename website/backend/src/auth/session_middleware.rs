//! Session cookie middleware and identity resolution.
//!
//! **Every path requires an already-resolved identity, except `/favicon.ico`.** An
//! identity comes from one of two places: a cookie naming a session already in
//! `web_sessions`, or the `X-Forwarded-User` header the reverse proxy in front of this
//! deployment asserts on every request. Nothing else produces a user: a caller with
//! neither gets `401` from every route [`crate::auth::route_policy::requires_session`]
//! covers.

use std::collections::HashMap;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use axum::extract::{Request};
use axum::middleware::Next;
use axum::response::Response;
use common::current_user::CurrentUser;

use crate::api::{rate_limit, telemetry};
use crate::db_auth::{
    groups::{self, GroupRow},
    sessions::{self, SessionRow},
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

/// Resolve the caller from a proxy-set identity header, or from a session cookie
/// created before this deployment stopped minting new ones.
///
/// Returns `None` when nothing identified the caller. Writes nothing: no route mints a
/// session any more, because the header identity this deployment relies on is asserted
/// on every request, not only the first, so there is nothing a cookie would buy a caller
/// who already carries it.
///
/// Takes the two things it needs out of the request as owned values rather than borrowing
/// it: `axum::middleware::from_fn` demands a `Send` future, and holding a `&Request` (and
/// therefore a `&Body`, which is not `Sync`) across an await makes it one that is not.
/// The resulting error names the middleware layer and not this function.
async fn resolve_identity(
    cookie_sid: Option<String>,
    header_identity: Option<HeaderIdentity>,
) -> Option<CurrentUser> {
    if let Some(identity) = header_identity {
        // A proxy-set identity is proof on its own, because the proxy authenticated it,
        // so it is honoured on every route.
        if let Err(e) = sync_header_user(&identity).await {
            tracing::error!("header identity sync failed for {}: {e}", identity.username);
        }
        return Some(CurrentUser {
            username: identity.username.clone(),
            fullname: identity.fullname.clone(),
            email: identity.email.clone(),
            is_admin: is_admin_from_groups(&identity.groups),
            groups: identity.groups.clone(),
        });
    }

    // No header on this request. A cookie from a session minted before this deployment
    // resumes the identity it named, read-only.
    let sid = cookie_sid?;
    let session: SessionRow = match sessions::get_session(&sid).await {
        Ok(Some(session)) => session,
        Ok(None) => return None,
        Err(e) => {
            // A DB error here is not the same as "no session". Report it so a
            // down/unreachable ClickHouse is visible instead of silently refusing.
            tracing::error!("session lookup failed for cookie session: {e}");
            return None;
        }
    };
    if let Some(cached) = get_cached_user(&sid) {
        return Some(cached);
    }
    // Read the row rather than assuming the header will return: the user it names may
    // be a real account whose proxy headers are not on *this* request, and building
    // them from the username alone would silently drop their admin flag and their
    // groups.
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
                groups,
            }
        }
    };
    cache_user(&sid, &user);
    Some(user)
}

/// The body of a refusal on the agent prefix: a typed name beside the text, matching the
/// shape every agent handler uses for its own refusals.
fn agent_refusal(status: axum::http::StatusCode, error: &str, message: &str) -> Response {
    let body = serde_json::json!({"error": error, "message": message}).to_string();
    axum::response::Response::builder()
        .status(status)
        .header(axum::http::header::CONTENT_TYPE, "application/json")
        .body(axum::body::Body::from(body))
        .unwrap_or_else(|_| axum::response::Response::default())
}

/// Identify the caller of a request on [`crate::auth::route_policy::AGENT_ROUTE_PREFIX`],
/// from the request's headers alone, with no `.await`.
///
/// The proxy in front of this deployment asserts a `X-Forwarded-User` header, or a
/// session cookie, on every browser request it forwards. A caller presenting either one
/// therefore came through the proxy, and rule 1 refuses it: a browser session must never
/// reach an agent route. A caller with neither is inside the firewalled network and
/// identifies itself with `X-Hoover4-User`, returned here unresolved.
///
/// Kept synchronous and returning an owned `String`, rather than resolving the user row
/// itself, so no borrow of `Request` (and so no `Body`, which is not `Sync`) is ever
/// held across an `.await`. `axum::middleware::from_fn` demands a `Send` future, and a
/// held `&Request` makes the async caller's future not `Send`; the resulting error names
/// the middleware layer's `.layer(...)` call, not this function.
fn agent_caller(request: &Request) -> Result<String, Response> {
    if parse_headers(request).is_some() || cookie_session_id(request).is_some() {
        return Err(agent_refusal(
            axum::http::StatusCode::FORBIDDEN,
            "permission_denied",
            "agent routes are not reachable through the proxy",
        ));
    }
    request
        .headers()
        .get("x-hoover4-user")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(str::to_string)
        .ok_or_else(|| {
            agent_refusal(
                axum::http::StatusCode::UNAUTHORIZED,
                "unauthenticated",
                "agent routes need x-hoover4-user",
            )
        })
}

/// Resolve an already-identified agent caller's username against the existing user
/// table, by [`build_current_user_from_db`]. **No row is written here**: the
/// header-identity sync path above provisions a browser user and would overwrite this
/// user's stored groups with an empty list, which is exactly the write this path must
/// not make.
///
/// Takes the owned username [`agent_caller`] already extracted, never `&Request`: an
/// async fn parameter of type `&Request` stays part of the generated future's state for
/// its whole body, even past the point its last use precedes an `.await`, so a
/// `resolve_agent_identity(request: &Request)` that only *reads* the request before
/// awaiting is not `Send` either. `Request`'s body, `axum::body::Body`, is not `Sync`,
/// so a `&Request` held anywhere in the future's state is not `Send`, and
/// `axum::middleware::from_fn` demands a `Send` future. The resulting error names the
/// middleware layer's `.layer(...)` call, not the function holding the reference.
async fn resolve_agent_user(username: &str) -> Result<CurrentUser, Response> {
    // `build_current_user_from_db` reads the row and errors when it is absent, which
    // covers a deleted user the same way: `users::get_user` filters `is_deleted` (see
    // `db_auth::users::get_user`), so a deleted username resolves to no row and this
    // branch is taken exactly as it is for a username nobody has ever synced.
    match build_current_user_from_db(username).await {
        Ok(user) => Ok(user),
        Err(_) => Err(agent_refusal(
            axum::http::StatusCode::UNAUTHORIZED,
            "unauthenticated",
            "unknown user",
        )),
    }
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

pub async fn session_middleware(request: Request, next: Next) -> Response {
    let path = request.uri().path().to_string();
    let (route_class, function_name) = telemetry::classify_path(&path);

    if crate::auth::route_policy::is_agent_route(&path) {
        // `agent_caller` runs synchronously, before any `.await`, so the `&request` it
        // borrows never becomes part of this function's suspended state. Only the owned
        // `username` it returns crosses into `resolve_agent_user`'s `.await`.
        let refuse = |refusal: Response| {
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
            refusal
        };
        let username = match agent_caller(&request) {
            Ok(username) => username,
            Err(refusal) => return refuse(refusal),
        };
        let current_user = match resolve_agent_user(&username).await {
            Ok(user) => user,
            Err(refusal) => return refuse(refusal),
        };
        return run_authenticated(request, next, current_user, route_class, function_name).await;
    }

    let Some(current_user) =
        resolve_identity(cookie_session_id(&request), parse_headers(&request)).await
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
        // The favicon, served open with no identity attached.
        return next.run(request).await;
    };

    run_authenticated(request, next, current_user, route_class, function_name).await
}

/// The shared tail of [`session_middleware`], once a caller is identified: rate limiting,
/// the `CurrentUser` extension, and the before/after telemetry. A browser request and an
/// agent request reach here the same way, because both are, from this point on, an
/// authenticated call on an instrumented path.
async fn run_authenticated(
    mut request: Request,
    next: Next,
    current_user: CurrentUser,
    route_class: telemetry::RouteClass,
    function_name: Option<&'static str>,
) -> Response {
    // Telemetry + rate limiting for API calls (server functions, the download routes and
    // the agent routes). Static assets are neither limited nor recorded.
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
    let response = next.run(request).await;

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
        // not there. Counting it made a crawler walking chat URLs that held no rows for
        // it read as a 22 % error rate on the admin metrics page.
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

    response
}

#[cfg(test)]
mod agent_identity_tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request as HttpRequest;

    fn request_with_headers(headers: &[(&str, &str)]) -> Request {
        let mut builder = HttpRequest::builder().uri("/api/agent/v1/collections/list");
        for (name, value) in headers {
            builder = builder.header(*name, *value);
        }
        builder.body(Body::empty()).unwrap()
    }

    /// A proxied identity header names a browser session, not an agent caller. An agent
    /// route must refuse it rather than resolve it.
    #[test]
    fn a_proxy_identity_header_is_refused() {
        let request = request_with_headers(&[("x-forwarded-user", "alice")]);
        let refusal = agent_caller(&request).unwrap_err();
        assert_eq!(refusal.status(), axum::http::StatusCode::FORBIDDEN);
    }

    /// A session cookie also names a browser session and is refused the same way.
    #[test]
    fn a_session_cookie_is_refused() {
        let request = request_with_headers(&[(
            "cookie",
            &format!("{SESSION_COOKIE}=some-session-id"),
        )]);
        let refusal = agent_caller(&request).unwrap_err();
        assert_eq!(refusal.status(), axum::http::StatusCode::FORBIDDEN);
    }

    /// No proxy header, no cookie, and no `x-hoover4-user` either: there is nothing to
    /// identify a caller from.
    #[test]
    fn a_request_with_no_agent_header_is_refused() {
        let request = request_with_headers(&[]);
        let refusal = agent_caller(&request).unwrap_err();
        assert_eq!(refusal.status(), axum::http::StatusCode::UNAUTHORIZED);
    }
}
