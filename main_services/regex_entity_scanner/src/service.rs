//! The HTTP surface.
//!
//! Stateless by construction: the scanner is built once and shared, every request carries its own
//! fragment, and nothing is written anywhere. That is what makes the container disposable and
//! horizontally scalable, and it is worth keeping true.

use std::collections::BTreeMap;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

use axum::extract::rejection::JsonRejection;
use axum::extract::{DefaultBodyLimit, Path, State};
use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::{Deserialize, Serialize};
use tokio::sync::Semaphore;

use crate::explain::{self, catalog, ExplainRequest, Explanation};
use crate::model::Entity;
use crate::rules::RULE_SET_VERSION;
use crate::scan::Scanner;

/// Everything a handler needs. The size limit lives here rather than in a global because it is an
/// operational parameter of this process, and a test builds a router with a small one.
pub struct AppState {
    pub scanner: Arc<Scanner>,
    /// The largest fragment this process will scan. Applied twice, deliberately: as the router's
    /// body limit, which is what protects memory because it rejects before buffering, and against
    /// the `text` field, which is what turns an oversized fragment into a precise error instead of
    /// a generic transport failure.
    pub max_body_bytes: usize,
    /// Admission control for the CPU-bound half of the service.
    pub admission: Admission,
}

/// The bound on concurrent scanning, and the queue in front of it.
///
/// Scanning is synchronous and CPU-bound. Without a bound every request that arrives is another
/// blocking thread, and the process degrades into thrashing while still accepting work; without a
/// queue bound the backlog grows until callers time out on requests the server is still going to
/// serve. Refusing with 503 states that, and it is the contract a client already
/// understands as retryable. The alternative is a request that succeeds after the caller has
/// given up on it.
pub struct Admission {
    permits: Arc<Semaphore>,
    /// Requests inside the semaphore or waiting for it. Compared against `scan_threads +
    /// queue_depth` to decide admission, and reported by `/health` so the bound is observable
    /// rather than assumed.
    occupancy: AtomicUsize,
    scan_threads: usize,
    queue_depth: usize,
}

impl Admission {
    pub fn new(scan_threads: usize, queue_depth: usize) -> Self {
        Self {
            permits: Arc::new(Semaphore::new(scan_threads)),
            occupancy: AtomicUsize::new(0),
            scan_threads,
            queue_depth,
        }
    }

    /// Takes a slot, or returns `None` when the queue is already full. The guard releases the slot
    /// on drop, so a handler that returns early (or panics) cannot leak one.
    async fn admit(&self) -> Option<AdmissionGuard<'_>> {
        let capacity = self.scan_threads + self.queue_depth;
        let mut occupancy = self.occupancy.load(Ordering::Acquire);
        loop {
            if occupancy >= capacity {
                return None;
            }
            match self.occupancy.compare_exchange_weak(
                occupancy,
                occupancy + 1,
                Ordering::AcqRel,
                Ordering::Acquire,
            ) {
                Ok(_) => break,
                Err(seen) => occupancy = seen,
            }
        }
        let permit = Arc::clone(&self.permits).acquire_owned().await.ok()?;
        Some(AdmissionGuard {
            admission: self,
            _permit: permit,
        })
    }

    fn in_flight(&self) -> usize {
        self.occupancy.load(Ordering::Acquire)
    }
}

struct AdmissionGuard<'a> {
    admission: &'a Admission,
    _permit: tokio::sync::OwnedSemaphorePermit,
}

impl Drop for AdmissionGuard<'_> {
    fn drop(&mut self) {
        self.admission.occupancy.fetch_sub(1, Ordering::AcqRel);
    }
}

/// How long a refused caller is told to wait. Short, because the queue drains at scanning speed and
/// a long hint turns a brief burst into a stall.
const RETRY_AFTER_SECONDS: u32 = 2;

fn overloaded() -> Response {
    (
        StatusCode::SERVICE_UNAVAILABLE,
        [("retry-after", RETRY_AFTER_SECONDS.to_string())],
        Json(ErrorResponse {
            error: "scan queue is full".to_string(),
        }),
    )
        .into_response()
}

/// The router's body limit is the fragment limit plus room for the JSON around it. Without the
/// allowance a fragment of exactly the advertised size could never be submitted, because the quotes
/// and the field names push its body over the line, and the precise error would be unreachable.
const JSON_ENVELOPE_ALLOWANCE: usize = 1_024;

#[derive(Debug, Deserialize)]
pub struct ScanRequest {
    /// The fragment to scan. Callers windowing a large document overlap their windows by at least
    /// the longest matchable entity, and deduplicate on `(type, start, end)` afterwards.
    pub text: String,
    /// Byte offset of the fragment's first byte within the source document.
    #[serde(default)]
    pub offset: usize,
}

#[derive(Debug, Serialize)]
pub struct ScanResponse {
    pub entities: Vec<Entity>,
    /// Which rule set produced these entities, so a consumer can compute what a reindex has to
    /// cover instead of reprocessing everything.
    pub rule_set_version: u32,
}

#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: &'static str,
    pub rules: usize,
    pub tlds: usize,
    pub rule_set_version: u32,
    /// The concurrency bound, its queue, and what is in them right now.
    pub scan_threads: usize,
    pub queue_depth: usize,
    pub in_flight: usize,
    /// The vendored tables that hold too little for the rules reading them to answer. A rule with
    /// an empty table matches nothing rather than failing, so a green health check over one would
    /// report a service that is quietly missing a whole entity type.
    pub incomplete_data: Vec<&'static str>,
}

#[derive(Debug, Serialize)]
pub struct RulesResponse {
    pub rules: Vec<RuleSummary>,
    pub rule_set_version: u32,
    /// What a confidence number means, once for the whole rule set, so a client can show it beside
    /// a single threshold control instead of repeating it per rule.
    pub confidence_note: &'static str,
}

/// Enough to populate a rule picker without pulling every catalogue entry.
#[derive(Debug, Serialize)]
pub struct RuleSummary {
    pub rule_id: &'static str,
    #[serde(rename = "type")]
    pub entity_type: crate::model::EntityType,
    pub title: &'static str,
    pub compiled: bool,
}

#[derive(Debug, Serialize)]
pub struct ErrorResponse {
    pub error: String,
}

pub fn router(state: Arc<AppState>) -> Router {
    let max_body_bytes = state.max_body_bytes + JSON_ENVELOPE_ALLOWANCE;
    Router::new()
        .route("/health", get(health))
        .route("/rules", get(rules))
        .route("/rules/{rule_id}", get(rule))
        .route("/scan", post(scan))
        .route("/scan_batch", post(scan_batch))
        .route("/explain", post(explain_entity))
        .layer(DefaultBodyLimit::max(max_body_bytes))
        .with_state(state)
}

async fn health(State(state): State<Arc<AppState>>) -> (StatusCode, Json<HealthResponse>) {
    let incomplete_data = state.scanner.data().incomplete_tables();
    let healthy = incomplete_data.is_empty();
    (
        if healthy {
            StatusCode::OK
        } else {
            StatusCode::SERVICE_UNAVAILABLE
        },
        Json(HealthResponse {
            status: if healthy { "ok" } else { "degraded" },
            rules: state.scanner.rule_ids().len(),
            tlds: state.scanner.data().tld_count(),
            rule_set_version: RULE_SET_VERSION,
            scan_threads: state.admission.scan_threads,
            queue_depth: state.admission.queue_depth,
            in_flight: state.admission.in_flight(),
            incomplete_data,
        }),
    )
}

async fn rules(State(state): State<Arc<AppState>>) -> Json<RulesResponse> {
    let compiled = state.scanner.rule_ids();
    Json(RulesResponse {
        rule_set_version: RULE_SET_VERSION,
        confidence_note: catalog::CONFIDENCE_NOTE,
        rules: catalog::all()
            .iter()
            .map(|doc| RuleSummary {
                rule_id: doc.rule_id,
                entity_type: doc.entity_type,
                title: doc.title,
                // A documented rule that is not compiled into this build is a real thing to know
                // about: the catalogue is the repository's knowledge, not this binary's inventory.
                compiled: compiled.contains(&doc.rule_id),
            })
            .collect(),
    })
}

/// The static documentation for one rule, with no match in hand, the same knowledge the explainer
/// builds a card from.
async fn rule(
    Path(rule_id): Path<String>,
) -> Result<Json<&'static catalog::RuleDoc>, (StatusCode, Json<ErrorResponse>)> {
    catalog::lookup(&rule_id).map(Json).ok_or_else(|| {
        (
            StatusCode::NOT_FOUND,
            Json(ErrorResponse {
                error: format!("no rule documented under {rule_id}"),
            }),
        )
    })
}

/// Takes an entity exactly as `/scan` returned it and answers with a card for the reader who
/// clicked it. An undocumented `rule_id` is a 404 rather than an empty card, so a client shows
/// nothing instead of showing an empty box.
async fn explain_entity(
    State(state): State<Arc<AppState>>,
    Json(request): Json<ExplainRequest>,
) -> Result<Json<Explanation>, (StatusCode, Json<ErrorResponse>)> {
    explain::explain(&request, state.scanner.data())
        .map(Json)
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(ErrorResponse {
                    error: format!("no rule documented under {}", request.rule_id),
                }),
            )
        })
}

/// A request that is too large is refused at two layers. The router's body limit is the one that
/// protects memory, because it rejects before the body is buffered; the check on `text` is the one
/// that gives a precise error instead of a generic one. Both answer in the same error shape, so a
/// client parses one thing.
///
/// The scan itself runs on a blocking thread. Calling it inline would put a synchronous CPU-bound
/// call on every async worker under load, and `/health` (the thing a runtime uses to decide
/// whether this process is alive) would be the first casualty.
async fn scan(
    State(state): State<Arc<AppState>>,
    request: Result<Json<ScanRequest>, JsonRejection>,
) -> Response {
    let request = match request {
        Ok(Json(request)) => request,
        Err(rejection) => return json_error(rejection.status(), rejection.body_text()),
    };
    if request.text.len() > state.max_body_bytes {
        return oversized(request.text.len(), state.max_body_bytes);
    }
    let Some(_slot) = state.admission.admit().await else {
        return overloaded();
    };
    let scanner = Arc::clone(&state.scanner);
    let entities = match tokio::task::spawn_blocking(move || {
        scanner.scan(&request.text, request.offset)
    })
    .await
    {
        Ok(entities) => entities,
        Err(err) => {
            return json_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("scan failed: {err}"),
            )
        }
    };
    Json(ScanResponse {
        entities,
        rule_set_version: RULE_SET_VERSION,
    })
    .into_response()
}

#[derive(Debug, Deserialize)]
pub struct ScanBatchRequest {
    /// Fragments to scan, in order. The whole-body limit applies to their sum; the per-fragment
    /// limit applies to each.
    pub texts: Vec<String>,
}

#[derive(Debug, Serialize)]
pub struct ScanBatchResponse {
    /// One entry per input text, in the order they were given.
    pub results: Vec<ScanBatchResult>,
    pub rule_set_version: u32,
}

#[derive(Debug, Serialize)]
pub struct ScanBatchResult {
    /// Deduplicated values grouped by entity type. A type with no accepted match is absent rather
    /// than present and empty. Also empty for the one document whose scan panicked, because the
    /// scan that would have populated it did not finish.
    pub types: BTreeMap<crate::model::EntityType, Vec<ScanBatchValue>>,
    /// Set only for a document whose scan panicked. The field is absent for every document that
    /// scanned cleanly, never `null`, so the response shape a caller already reads does not
    /// change.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// One distinct value in one text.
///
/// Deliberately not a span. A storage consumer wants the normalised value and how often it
/// occurred; sending every occurrence with its surface text and offsets was measured at 325 365
/// objects for 193 segments, nearly all of it discarded by the caller. `/scan` still returns spans
/// for the caller that highlights them.
#[derive(Debug, Serialize)]
pub struct ScanBatchValue {
    pub value: String,
    /// The rule behind the highest-confidence occurrence of this value.
    pub rule_id: String,
    pub count: u32,
    /// The canonical value object, which is what `/explain` is posted back to build a card.
    pub value_json: crate::model::Value,
    /// The surface form of the first occurrence. A normalised value is frequently not a string the
    /// document contains: `+442075623419` never appears in a document that wrote
    /// `+44 (0)20 7562 3419`, so a caller offering find-in-page needs the text that is there.
    pub text: String,
}

/// Scans several fragments under one admission slot and answers with deduplicated values.
async fn scan_batch(
    State(state): State<Arc<AppState>>,
    request: Result<Json<ScanBatchRequest>, JsonRejection>,
) -> Response {
    let request = match request {
        Ok(Json(request)) => request,
        Err(rejection) => return json_error(rejection.status(), rejection.body_text()),
    };
    if let Some(oversize) = request
        .texts
        .iter()
        .map(String::len)
        .find(|len| *len > state.max_body_bytes)
    {
        return oversized(oversize, state.max_body_bytes);
    }
    let Some(_slot) = state.admission.admit().await else {
        return overloaded();
    };
    let scanner = Arc::clone(&state.scanner);
    let results = match tokio::task::spawn_blocking(move || {
        request
            .texts
            .iter()
            .map(|text| scan_one(&scanner, text))
            .collect::<Vec<_>>()
    })
    .await
    {
        Ok(results) => results,
        Err(err) => {
            return json_error(
                StatusCode::INTERNAL_SERVER_ERROR,
                format!("scan failed: {err}"),
            )
        }
    };
    Json(ScanBatchResponse {
        results,
        rule_set_version: RULE_SET_VERSION,
    })
    .into_response()
}

/// Scans one document from a batch and answers for it, whether or not the scan itself finished.
///
/// The isolation sits here, around the one call that can panic, rather than around the whole
/// batch closure in `scan_batch`. `spawn_blocking` already turns a panic that reaches it into a
/// `JoinError` that fails the entire batch. Catching one document's panic here, before it gets
/// that far, is what keeps the other documents answered.
fn scan_one(scanner: &Scanner, text: &str) -> ScanBatchResult {
    match catch_panicking_scan(|| scanner.scan(text, 0)) {
        Ok(entities) => summarise(entities),
        Err(()) => {
            tracing::error!("a document panicked during scan, serving the rest of the batch");
            ScanBatchResult {
                types: BTreeMap::new(),
                error: Some("this document could not be scanned".to_string()),
            }
        }
    }
}

/// Runs `scan`, converting a panic into `Err` instead of letting it unwind past the caller.
///
/// `Scanner` carries no interior mutability, so a panic partway through one document's candidates
/// leaves it fit to scan the next one. `AssertUnwindSafe` is the caller asserting that, because a
/// `Box<dyn Rule>` erases the field information the compiler would need to prove it.
fn catch_panicking_scan<F: FnOnce() -> Vec<Entity>>(scan: F) -> Result<Vec<Entity>, ()> {
    std::panic::catch_unwind(std::panic::AssertUnwindSafe(scan)).map_err(|_| ())
}

/// Collapses a text's spans into one entry per `(type, normalised value)`.
///
/// The representative rule and surface text come from the highest-confidence occurrence, so a value
/// found once by a weak rule and ten times by a strong one is attributed to the strong one.
fn summarise(entities: Vec<Entity>) -> ScanBatchResult {
    // The value's best-seen confidence rides alongside the summary rather than inside it: it is
    // how the representative is chosen, and it is not part of what a storage consumer stores.
    let mut types: BTreeMap<crate::model::EntityType, BTreeMap<String, (ScanBatchValue, f32)>> =
        BTreeMap::new();
    for entity in entities {
        let key = entity.value.facet_key();
        let bucket = types.entry(entity.entity_type).or_default();
        match bucket.get_mut(&key) {
            Some((existing, best)) => {
                existing.count += 1;
                if entity.confidence > *best {
                    *best = entity.confidence;
                    existing.rule_id = entity.rule_id;
                    existing.text = entity.text;
                    existing.value_json = entity.value;
                }
            }
            None => {
                let confidence = entity.confidence;
                bucket.insert(
                    key.clone(),
                    (
                        ScanBatchValue {
                            value: key,
                            rule_id: entity.rule_id,
                            count: 1,
                            value_json: entity.value,
                            text: entity.text,
                        },
                        confidence,
                    ),
                );
            }
        }
    }
    ScanBatchResult {
        types: types
            .into_iter()
            .map(|(entity_type, values)| {
                (
                    entity_type,
                    values.into_values().map(|(value, _)| value).collect(),
                )
            })
            .collect(),
        error: None,
    }
}

fn json_error(status: StatusCode, error: String) -> Response {
    (status, Json(ErrorResponse { error })).into_response()
}

fn oversized(len: usize, limit: usize) -> Response {
    json_error(
        StatusCode::PAYLOAD_TOO_LARGE,
        format!("the fragment is {len} bytes and the limit is {limit}"),
    )
}

#[cfg(test)]
mod tests {
    use super::catch_panicking_scan;

    /// The mechanism `scan_one` relies on, proven directly: a panic inside the scan comes back
    /// as `Err` rather than unwinding into the caller, and a scan that does not panic is
    /// unaffected.
    #[test]
    fn a_panic_is_caught_and_a_normal_scan_is_not() {
        assert!(catch_panicking_scan(|| panic!("synthetic panic for the isolation test")).is_err());
        assert_eq!(
            catch_panicking_scan(Vec::new),
            Ok(Vec::<crate::model::Entity>::new())
        );
    }

    /// The shape `scan_batch` maps a text list through: proves that one panicking item does not
    /// stop the items after it from being answered, which is what keeps a batch's other
    /// documents served when one document's scan panics.
    #[test]
    fn a_panic_on_one_item_does_not_stop_the_rest_of_the_batch() {
        let texts = ["ok", "boom", "also ok"];
        let outcomes: Vec<Result<Vec<crate::model::Entity>, ()>> = texts
            .iter()
            .map(|text| {
                catch_panicking_scan(|| {
                    if *text == "boom" {
                        panic!("synthetic panic for the isolation test");
                    }
                    Vec::new()
                })
            })
            .collect();
        assert!(outcomes[0].is_ok());
        assert!(outcomes[1].is_err());
        assert!(
            outcomes[2].is_ok(),
            "the document after the panic must still be answered"
        );
    }
}
