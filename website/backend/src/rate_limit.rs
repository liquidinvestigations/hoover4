//! In-process rate limiter called by AI Chat (and API telemetry).
//!
//! **Plan 2 owns the real sliding-window implementation.** This module exposes the
//! public API Plan 3 calls from `api/chat/`. Until Plan 2 replaces the body,
//! `check_and_record` fails open (always allows) so the chat path compiles and runs.
//! See `plans/6-fix-ai-services/open-questions.md`.

/// Which budget a call counts against.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RateLimitKind {
    ChatMessage,
    ApiCall,
}

/// Returned when the caller is over budget.
#[derive(Debug, Clone)]
pub struct RateLimitError {
    pub retry_after_seconds: u64,
    pub window: &'static str,
}

impl std::fmt::Display for RateLimitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "rate limited: try again in {} s ({})",
            self.retry_after_seconds, self.window
        )
    }
}

impl std::error::Error for RateLimitError {}

/// Record one use of `kind` for `username`. Err when over budget.
///
/// Stub: always allows. Plan 2 replaces this body — keep the signature stable.
pub fn check_and_record(_username: &str, _kind: RateLimitKind) -> Result<(), RateLimitError> {
    Ok(())
}
