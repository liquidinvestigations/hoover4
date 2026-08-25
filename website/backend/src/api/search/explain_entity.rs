//! The explainer proxy: one card for one matched value, fetched from the scanner.
//!
//! The card is not written here and must not be. The scanner owns the rule catalogue
//! (which standard defines a format, which authority administers it, what its validator
//! checked and what acceptance does *not* prove), and a second copy of that knowledge in
//! the website would drift from the rules with nothing to notice it had.
//!
//! Two properties this proxy has to preserve:
//!
//! * **The entity is the whole input.** The scanner explains an entity posted back
//!   unchanged, with only `rule_id` required, so a value stored under an older rule set
//!   still explains itself. The proxy therefore passes the stored value JSON through
//!   rather than re-deriving anything from it.
//! * **A card is a decoration, never a dependency.** The scanner being down degrades
//!   `View Details` to nothing and must never fail a search, a facet or a document view.
//!   Every failure here comes back as `None`.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use common::{current_user::CurrentUser, entity_cards::EntityExplanation};

/// How long a cached card is served before it is fetched again.
///
/// A card is a function of the rule set, which changes only when the scanner is
/// redeployed, so this is long. It is not infinite because a redeploy must not need a
/// website restart to be visible.
const CACHE_TTL: Duration = Duration::from_secs(30 * 60);

/// Cards held in memory. Small and bounded: the cache is cleared wholesale when it grows
/// past this, rather than evicted one entry at a time, because a card is cheap to refetch
/// and an LRU here would be more machinery than the problem needs.
const CACHE_CAPACITY: usize = 4096;

/// The scanner is a sidecar on the same network. A card that takes longer than this is
/// not worth the reader waiting for, and the two-tuple is deliberate: a dead host is
/// detected in a second rather than after the whole read budget.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(2);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);

struct CacheEntry {
    card: Option<EntityExplanation>,
    stored_at: Instant,
}

fn cache() -> &'static Mutex<HashMap<(String, String), CacheEntry>> {
    static CACHE: OnceLock<Mutex<HashMap<(String, String), CacheEntry>>> = OnceLock::new();
    CACHE.get_or_init(|| Mutex::new(HashMap::new()))
}

fn scanner_url() -> Option<String> {
    normalise_scanner_url(std::env::var("REGEX_SCANNER_URL").ok().as_deref())
}

/// The scanner's base URL, or `None` when there is not one.
///
/// The compose file renders `${REGEX_SCANNER_URL:-…}`, which is an EMPTY STRING when the
/// variable is unset rather than an absent variable, so "set" is not the same question
/// as "usable", and treating an empty value as a host produces a request with no
/// authority and an error that names the wrong thing.
fn normalise_scanner_url(raw: Option<&str>) -> Option<String> {
    let url = raw?.trim().trim_end_matches('/').to_string();
    if url.is_empty() { None } else { Some(url) }
}

/// The explainer card for one matched value, or `None` when there is no card to show.
///
/// `value_json` is the canonical value object exactly as the scan stage stored it. It is
/// parsed here only to hand the scanner an object rather than a string; a value shape
/// this build has never seen is passed through untouched, which is what lets an entity
/// from an older rule set still explain itself.
///
/// `None` covers every reason a card is absent (an undocumented rule, an unreachable
/// scanner, a timeout), because the caller does the same thing in all of them.
pub async fn explain_entity(
    user: &CurrentUser,
    rule_id: String,
    value_json: String,
    surface_text: Option<String>,
) -> anyhow::Result<Option<EntityExplanation>> {
    // Not a document route: a card is a property of a rule and a value, and carries
    // nothing from any collection. It is still gated on being a logged-in user with
    // something to read, so an unauthenticated caller cannot use the site as an open
    // proxy to the scanner.
    let collections = crate::db_utils::clickhouse_utils::list_permitted_collections(user).await?;
    if collections.is_empty() {
        return Ok(None);
    }
    if rule_id.trim().is_empty() {
        return Ok(None);
    }

    let key = (rule_id.clone(), value_json.clone());
    if let Some(card) = read_cache(&key) {
        return Ok(card);
    }

    let card = fetch_card(&rule_id, &value_json, surface_text.as_deref()).await;
    // A failure is cached too, and deliberately: a scanner that is down would otherwise
    // be asked once per chip on every render of a document with fifty values.
    write_cache(key, card.clone());
    Ok(card)
}

fn read_cache(key: &(String, String)) -> Option<Option<EntityExplanation>> {
    let guard = cache().lock().ok()?;
    let entry = guard.get(key)?;
    if entry.stored_at.elapsed() > CACHE_TTL {
        return None;
    }
    Some(entry.card.clone())
}

fn write_cache(key: (String, String), card: Option<EntityExplanation>) {
    let Ok(mut guard) = cache().lock() else {
        return;
    };
    if guard.len() >= CACHE_CAPACITY {
        guard.clear();
    }
    guard.insert(key, CacheEntry { card, stored_at: Instant::now() });
}

async fn fetch_card(
    rule_id: &str,
    value_json: &str,
    surface_text: Option<&str>,
) -> Option<EntityExplanation> {
    let base = scanner_url()?;
    let value: serde_json::Value =
        serde_json::from_str(value_json).unwrap_or(serde_json::Value::Null);
    let mut body = serde_json::json!({ "rule_id": rule_id, "value": value });
    if let Some(text) = surface_text
        && !text.is_empty()
    {
        body["text"] = serde_json::Value::String(text.to_string());
    }

    let client = reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(REQUEST_TIMEOUT)
        .build()
        .ok()?;
    let response = match client.post(format!("{base}/explain")).json(&body).send().await {
        Ok(response) => response,
        Err(error) => {
            tracing::warn!("entity explainer at {base} is unreachable: {error}");
            return None;
        }
    };
    if !response.status().is_success() {
        // 404 is the scanner saying it has no card for that rule, which is an answer
        // rather than a fault. Anything else is worth a line in the log.
        if response.status() != reqwest::StatusCode::NOT_FOUND {
            tracing::warn!("entity explainer returned {} for {rule_id}", response.status());
        }
        return None;
    }
    match response.json::<EntityExplanation>().await {
        Ok(card) => Some(card),
        Err(error) => {
            tracing::warn!("entity explainer returned a card this build cannot read: {error}");
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn card(title: &str) -> EntityExplanation {
        EntityExplanation { title: title.to_string(), ..EntityExplanation::default() }
    }

    #[test]
    fn a_cached_card_is_returned_and_a_missing_key_is_not() {
        let key = ("bank.iban".to_string(), r#"{"kind":"identifier"}"#.to_string());
        write_cache(key.clone(), Some(card("IBAN")));
        assert_eq!(read_cache(&key).unwrap().unwrap().title, "IBAN");
        assert!(read_cache(&("nope".to_string(), String::new())).is_none());
    }

    /// A scanner that is down must be asked once, not once per chip. The absence is a
    /// cached answer, distinguishable from "not cached" by the two levels of Option.
    #[test]
    fn an_absent_card_is_cached_as_an_answer() {
        let key = ("date.iso8601".to_string(), "null".to_string());
        write_cache(key.clone(), None);
        let cached = read_cache(&key).expect("the key is cached");
        assert!(cached.is_none(), "and the cached value is 'no card'");
    }

    /// The value JSON is part of the key: one rule explains many values, and a money
    /// card names its own amount.
    #[test]
    fn two_values_of_one_rule_are_two_cache_entries() {
        let rule = "money.iso_code".to_string();
        write_cache((rule.clone(), r#"{"amount":"100"}"#.to_string()), Some(card("one")));
        write_cache((rule.clone(), r#"{"amount":"200"}"#.to_string()), Some(card("two")));
        assert_eq!(
            read_cache(&(rule.clone(), r#"{"amount":"100"}"#.to_string()))
                .unwrap()
                .unwrap()
                .title,
            "one"
        );
        assert_eq!(
            read_cache(&(rule, r#"{"amount":"200"}"#.to_string())).unwrap().unwrap().title,
            "two"
        );
    }

    #[test]
    fn an_empty_scanner_url_is_not_a_url() {
        assert!(normalise_scanner_url(None).is_none());
        assert!(normalise_scanner_url(Some("")).is_none());
        assert!(normalise_scanner_url(Some("   ")).is_none());
        assert_eq!(
            normalise_scanner_url(Some("http://scanner:19705/")).unwrap(),
            "http://scanner:19705"
        );
    }
}
