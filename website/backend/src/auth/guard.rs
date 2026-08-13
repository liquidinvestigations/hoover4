//! Admin access guard helpers.

use common::current_user::CurrentUser;

pub fn require_admin(user: &CurrentUser) -> anyhow::Result<()> {
    if user.is_admin {
        Ok(())
    } else {
        anyhow::bail!("forbidden")
    }
}

pub fn is_forbidden(err: &anyhow::Error) -> bool {
    err.to_string().contains("forbidden")
}

/// Marker a handler puts in an error message to mean "this does not exist for you".
///
/// Deliberately indistinguishable from "does not exist at all": an id that resolves for
/// its owner and 404s for everyone else is an existence oracle. See `NOT_FOUND`.
pub const NOT_FOUND: &str = "not found";

/// Is this the absence of a resource rather than a failure?
///
/// It matters twice. The status: an anyhow error became a 500, so a bot walking chat URLs
/// with fresh guest cookies made the site look like it was throwing — one crawler put 11
/// errors and 22 % on the admin metrics page overnight. And the telemetry: `is_error` is
/// derived from the status, so those 500s were counted as breakage. A 404 is a correct,
/// complete answer to a question about something that is not there.
pub fn is_not_found(err: &anyhow::Error) -> bool {
    err.to_string().contains(NOT_FOUND)
}

/// Is this something the caller asked for wrongly, rather than something that broke?
///
/// Only one shape qualifies today: a query string the Manticore parser cannot be given
/// at all, which [`crate::db_utils::manticore_match::prepare_match_query`] refuses with a
/// sentence written for the person who typed it. Reported as 500 it reads as the site
/// falling over on a legal keystroke, and it is counted as breakage in the telemetry;
/// the caller can fix it, so it is a 400.
///
/// Matched by TYPE, not by message text: the message is user-facing prose and will be
/// reworded, and a substring test over prose is how an unrelated error starts answering
/// 400. That is also why the search path must propagate the error rather than restate it
/// with `anyhow!("{e}")`.
pub fn is_bad_request(err: &anyhow::Error) -> bool {
    err.chain()
        .any(|cause| cause.is::<crate::db_utils::manticore_match::MatchQueryError>())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_missing_resource_is_not_a_server_error() {
        // The live case: a crawler with fresh guest cookies walked chat URLs, every one
        // of them 500'd, and the admin metrics page reported 22 % errors overnight.
        assert!(is_not_found(&anyhow::anyhow!("chat session not found")));
        assert!(is_not_found(&anyhow::anyhow!("artifact not found")));
        assert!(!is_not_found(&anyhow::anyhow!("clickhouse is unreachable")));
    }

    #[test]
    fn a_refusal_is_still_a_refusal() {
        // 404 is checked first, so a forbidden message must not read as one — the
        // artifact route's 403-vs-404 distinction is deliberate.
        let forbidden = anyhow::anyhow!("forbidden: this artifact belongs to another user");
        assert!(is_forbidden(&forbidden));
        assert!(!is_not_found(&forbidden));
    }
}
