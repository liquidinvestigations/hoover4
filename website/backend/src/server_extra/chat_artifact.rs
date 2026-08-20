//! Serving chat artifacts: the thumbnail, the archived page, the search detail.
//!
//! Three routes, one ACL. An `artifact_id` reaches the browser through a tool payload
//! that an MCP server — driven by an LLM — wrote, so it is **never** treated as a
//! capability. Each request resolves the id back to a `chat_artifacts` row and requires
//! the caller to be the owner or an admin. Unknown id is a 404; someone else's id is a
//! **403**, not a 404: collapsing the two would hide a real permission failure behind an
//! apparent missing row, and the difference is what makes the check testable.
//!
//! ## Why `page.html` needs both the CSP and the sandbox
//!
//! An archived page is attacker-controlled HTML from the open web. It is served with
//!
//! ```text
//! Content-Security-Policy: default-src 'none'; img-src data:; media-src data:;
//!                          style-src 'unsafe-inline' data:; font-src data:;
//!                          frame-ancestors 'self'; form-action 'none'; base-uri 'none'
//! ```
//!
//! and framed as `<iframe sandbox="">`. Both are required and neither is redundant:
//!
//! * the **sandbox** gives the document an opaque origin with scripting disabled, so it
//!   cannot reach cookies, `localStorage` or the parent frame;
//! * the **CSP** forbids every network fetch, so a capture cannot phone home — the CSP
//!   without the sandbox still allows scripts, and the sandbox without the CSP still lets
//!   a stylesheet fetch leak the fact that the capture was viewed.
//!
//! `browser_use_server/mhtml.py` has already stripped every script and `on*` handler.
//! That is defence in depth, not a substitute for either header.

use axum::{
    body::Body,
    extract::{Extension, Path},
    response::{IntoResponse, Response},
};
use common::current_user::CurrentUser;
use reqwest::StatusCode;

use crate::{
    api::telemetry,
    db_chat::artifacts::{self, ChatArtifactRow},
};

const CSP: &str = "default-src 'none'; img-src data:; media-src data:; \
                   style-src 'unsafe-inline' data:; font-src data:; \
                   frame-ancestors 'self'; form-action 'none'; base-uri 'none'";

/// Which file of an artifact a request wants. Parsed from the last path segment rather
/// than taken as a free string: the object key comes from the row, so a caller can never
/// name an object, only choose between the two this artifact has.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Asset {
    Thumb,
    Page,
    Detail,
}

impl Asset {
    fn parse(name: &str) -> Option<Self> {
        match name {
            "thumb.webp" => Some(Self::Thumb),
            "page.html" => Some(Self::Page),
            "detail.json" => Some(Self::Detail),
            _ => None,
        }
    }

    fn content_type(self) -> &'static str {
        match self {
            Self::Thumb => "image/webp",
            Self::Page => "text/html; charset=utf-8",
            Self::Detail => "application/json; charset=utf-8",
        }
    }

    /// Which column of the row holds this asset's object key.
    fn key_of(self, row: &ChatArtifactRow) -> &str {
        match self {
            Self::Thumb => &row.thumb_key,
            Self::Page | Self::Detail => &row.body_key,
        }
    }
}

/// Owner or admin. A **403** rather than a 404 — see the module docstring.
///
/// A pure function so the rule itself is testable. It cannot be exercised end to end on a
/// deployment with `HOOVER4_DEMO_MODE=true`, where every anonymous guest is an
/// administrator and therefore every request is legitimately allowed.
pub fn may_read(caller: &str, caller_is_admin: bool, owner: &str) -> bool {
    if caller_is_admin {
        return true;
    }
    // An empty owner would otherwise match an empty caller and make an unowned artifact
    // world-readable. Rows always carry a username; belt and braces.
    !caller.is_empty() && caller == owner
}

/// Fetch one object out of the blobs bucket.
///
/// The whole object is read into memory rather than streamed: a thumbnail is tens of kB
/// and an archived page is capped at 8 MB by `CAPTURE_MAX_SNAPSHOT_BYTES`, so streaming
/// would add a failure mode (a half-written response with headers already sent) for no
/// benefit at these sizes.
pub async fn fetch_artifact_object(key: &str) -> anyhow::Result<Vec<u8>> {
    let bucket = crate::db_utils::s3_bucket();
    let client = crate::db_utils::s3_client().await?;
    let object = client.get_object().bucket(&bucket).key(key).send().await?;
    Ok(object.body.collect().await?.to_vec())
}

async fn _chat_artifact(
    user: &CurrentUser,
    artifact_id: &str,
    asset_name: &str,
) -> Result<Response, (StatusCode, String)> {
    let Some(asset) = Asset::parse(asset_name) else {
        return Err((StatusCode::NOT_FOUND, "unknown artifact asset".into()));
    };

    let row = artifacts::get_artifact(artifact_id)
        .await
        .map_err(|e| {
            tracing::error!("chat_artifact lookup failed for {artifact_id}: {e:#}");
            (StatusCode::INTERNAL_SERVER_ERROR, "lookup failed".to_string())
        })?
        .ok_or_else(|| (StatusCode::NOT_FOUND, "artifact not found".to_string()))?;

    if !may_read(&user.username, user.is_admin, &row.username) {
        tracing::warn!(
            "user {} was refused artifact {} owned by {}",
            user.username, artifact_id, row.username
        );
        return Err((StatusCode::FORBIDDEN, "not yours".to_string()));
    }

    let key = asset.key_of(&row);
    if key.is_empty() {
        // A row with `status = 'too_large'` or `'failed'` legitimately has no body. The
        // card renders that as an explicit line, so this is a normal outcome, not an
        // error to log loudly.
        return Err((
            StatusCode::NOT_FOUND,
            if row.detail.is_empty() {
                "this artifact has no such file".to_string()
            } else {
                row.detail.clone()
            },
        ));
    }

    let bytes = fetch_artifact_object(key).await.map_err(|e| {
        tracing::error!("chat_artifact object {key} could not be fetched: {e:#}");
        (StatusCode::INTERNAL_SERVER_ERROR, "object unavailable".to_string())
    })?;

    telemetry::record_event(
        &user.username,
        "chat_artifact_read",
        &format!("{{\"artifact_id\":\"{artifact_id}\",\"asset\":\"{asset_name}\"}}"),
    );

    let mut headers = axum::http::HeaderMap::new();
    let mut set = |name: &'static str, value: String| {
        if let Ok(v) = axum::http::HeaderValue::from_str(&value) {
            headers.insert(name, v);
        }
    };
    set("content-type", asset.content_type().to_string());
    set("content-length", bytes.len().to_string());
    set("x-content-type-options", "nosniff".to_string());
    set("content-disposition", "inline".to_string());
    // Private: an artifact belongs to one user, and a shared cache holding it would undo
    // the ACL above.
    set("cache-control", "private, max-age=86400".to_string());
    if asset == Asset::Page {
        set("content-security-policy", CSP.to_string());
    }

    Ok((headers, Body::from(bytes)).into_response())
}

pub async fn chat_artifact(
    Extension(user): Extension<CurrentUser>,
    Path((artifact_id, asset)): Path<(String, String)>,
) -> Response {
    match _chat_artifact(&user, &artifact_id, &asset).await {
        Ok(response) => response,
        Err((status, message)) => (status, Body::from(message)).into_response(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_owner_may_read_their_own_artifact() {
        assert!(may_read("alice", false, "alice"));
    }

    #[test]
    fn another_user_may_not() {
        // The whole point: an artifact_id arrives from an LLM-driven tool payload, so it
        // is a lookup key and never a capability.
        assert!(!may_read("bob", false, "alice"));
    }

    #[test]
    fn an_admin_may_read_anyones() {
        assert!(may_read("root", true, "alice"));
    }

    #[test]
    fn an_unnamed_caller_may_not_read_an_unowned_artifact() {
        // Otherwise "" == "" would make a row with no owner world-readable.
        assert!(!may_read("", false, ""));
    }

    #[test]
    fn only_the_three_known_assets_resolve() {
        assert_eq!(Asset::parse("thumb.webp"), Some(Asset::Thumb));
        assert_eq!(Asset::parse("page.html"), Some(Asset::Page));
        assert_eq!(Asset::parse("detail.json"), Some(Asset::Detail));
        // The object key comes from the row, so a caller can never name an object —
        // only choose between the files this artifact has.
        assert_eq!(Asset::parse("../../etc/passwd"), None);
        assert_eq!(Asset::parse("page.html/../secret"), None);
        assert_eq!(Asset::parse(""), None);
    }

    #[test]
    fn the_page_csp_forbids_every_network_fetch() {
        // The sandbox attribute is the other half and lives in the frontend; neither is
        // redundant. See the module docstring.
        assert!(CSP.contains("default-src 'none'"));
        assert!(CSP.contains("frame-ancestors 'self'"));
        assert!(CSP.contains("form-action 'none'"));
        // Only data: URIs — the inliner has already turned every subresource into one.
        assert!(CSP.contains("img-src data:"));
        assert!(!CSP.contains("script-src"));
    }
}
