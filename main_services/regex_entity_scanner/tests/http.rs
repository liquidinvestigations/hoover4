//! The HTTP surface, over a real socket.
//!
//! Binding port zero and asking the OS which port it gave keeps the test from colliding with the
//! server a developer already has running.

mod support;

use std::path::PathBuf;
use std::sync::{Arc, OnceLock};

use regex_entity_scanner::lexicon::Lexicon;
use regex_entity_scanner::service::{self, Admission, AppState};

/// The lexicon next to the manifest, loaded once per test binary like the scanner.
fn lexicon() -> Arc<Lexicon> {
    static LEXICON: OnceLock<Arc<Lexicon>> = OnceLock::new();
    LEXICON
        .get_or_init(|| {
            let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("lexicon");
            Arc::new(Lexicon::load(&root).expect("loading the lexicon"))
        })
        .clone()
}

/// Serves the router on an ephemeral port and answers with its base URL.
async fn serve(max_body_bytes: usize) -> String {
    let state = Arc::new(AppState {
        scanner: support::scanner(),
        lexicon: lexicon(),
        max_body_bytes,
        admission: Admission::new(2, 4),
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("binding an ephemeral port");
    let address = listener.local_addr().expect("the bound address");
    tokio::spawn(async move {
        axum::serve(listener, service::router(state)).await.ok();
    });
    format!("http://{address}")
}

#[tokio::test]
async fn health_rules_and_scan() {
    let base = serve(1 << 20).await;
    let client = reqwest::Client::new();

    let health: serde_json::Value = client
        .get(format!("{base}/health"))
        .send()
        .await
        .expect("health request")
        .json()
        .await
        .expect("health json");
    assert_eq!(health["status"], "ok");
    assert!(health["rules"].as_u64().expect("a rule count") > 0);
    assert!(health["rule_set_version"].as_u64().is_some());

    let rules: serde_json::Value = client
        .get(format!("{base}/rules"))
        .send()
        .await
        .expect("rules request")
        .json()
        .await
        .expect("rules json");
    assert!(rules["rule_set_version"].as_u64().is_some());
    let email_rule = rules["rules"]
        .as_array()
        .expect("a rule list")
        .iter()
        .find(|rule| rule["rule_id"] == "email.basic")
        .expect("email.basic listed");
    assert_eq!(email_rule["title"], "Email address");
    assert_eq!(email_rule["compiled"], true);

    let doc: serde_json::Value = client
        .get(format!("{base}/rules/email.basic"))
        .send()
        .await
        .expect("rule doc request")
        .json()
        .await
        .expect("rule doc json");
    assert!(!doc["checks"].as_array().expect("checks").is_empty());
    assert!(!doc["not_checked"]
        .as_array()
        .expect("not_checked")
        .is_empty());

    let missing = client
        .get(format!("{base}/rules/phone.zw.mobile"))
        .send()
        .await
        .expect("missing rule request");
    assert_eq!(missing.status(), reqwest::StatusCode::NOT_FOUND);

    let scanned: serde_json::Value = client
        .post(format!("{base}/scan"))
        .json(&serde_json::json!({
            "text": "filed 2021-03-04 by ops@example.org",
            "offset": 100,
        }))
        .send()
        .await
        .expect("scan request")
        .json()
        .await
        .expect("scan json");

    assert!(scanned["rule_set_version"].as_u64().is_some());
    let entities = scanned["entities"].as_array().expect("an entity list");
    assert_eq!(entities.len(), 2);
    assert_eq!(entities[0]["type"], "date");
    assert_eq!(entities[0]["start"], 106);
    assert_eq!(entities[0]["rule_id"], "date.iso8601");
    assert_eq!(entities[1]["type"], "email");
    assert_eq!(entities[1]["value"]["kind"], "email");
    assert_eq!(entities[1]["value"]["address"], "ops@example.org");

    // The entity goes back exactly as it arrived. This is the whole ergonomics of the endpoint.
    let card: serde_json::Value = client
        .post(format!("{base}/explain"))
        .json(&entities[1])
        .send()
        .await
        .expect("explain request")
        .json()
        .await
        .expect("explain json");
    assert_eq!(card["rule_id"], "email.basic");
    assert_eq!(card["title"], "Email address");
    assert!(card["subtitle"]
        .as_str()
        .expect("a subtitle")
        .contains("example.org"));
    assert!(card["body"].as_str().expect("a body").contains("IANA"));

    let unknown = client
        .post(format!("{base}/explain"))
        .json(&serde_json::json!({ "rule_id": "phone.zw.mobile" }))
        .send()
        .await
        .expect("explain request for an undocumented rule");
    assert_eq!(unknown.status(), reqwest::StatusCode::NOT_FOUND);
}

/// The limit is refused before the body is buffered, so the fixture is kilobytes rather than the
/// production ten mebibytes, a test that allocates the real limit to prove the limit works is the
/// kind of test that eats the battery's budget.
#[tokio::test]
async fn an_oversized_body_is_refused() {
    let base = serve(2_048).await;
    let client = reqwest::Client::new();

    let response = client
        .post(format!("{base}/scan"))
        .header("content-type", "application/json")
        .body("x".repeat(8_192))
        .send()
        .await
        .expect("oversized scan request");
    assert_eq!(response.status(), reqwest::StatusCode::PAYLOAD_TOO_LARGE);

    let error: serde_json::Value = response.json().await.expect("a json error body");
    assert!(!error["error"]
        .as_str()
        .expect("an error message")
        .is_empty());
}

/// A fragment inside a legal body but past the limit is the case the field check exists for: the
/// answer names the size and the limit instead of being a generic transport error.
#[tokio::test]
async fn an_oversized_fragment_inside_a_legal_body_is_refused() {
    let base = serve(2_048).await;
    let client = reqwest::Client::new();

    let response = client
        .post(format!("{base}/scan"))
        .json(&serde_json::json!({ "text": "a".repeat(3_000) }))
        .send()
        .await
        .expect("scan request with an oversized fragment");
    assert_eq!(response.status(), reqwest::StatusCode::PAYLOAD_TOO_LARGE);

    let error: serde_json::Value = response.json().await.expect("a json error body");
    assert!(error["error"]
        .as_str()
        .expect("an error message")
        .contains("3000"));
}

/// A vendored table that loaded empty does not stop a rule from compiling. It stops it from ever
/// matching. The health check is the only place that difference is visible from outside, so a
/// scanner holding one is not `ok` and does not answer 200.
#[tokio::test]
async fn health_refuses_to_be_ok_without_the_vendored_data() {
    use regex_entity_scanner::data::VendoredData;
    use regex_entity_scanner::scan::Scanner;

    let scanner = Arc::new(Scanner::new(VendoredData::default()).expect("compiling the rule set"));
    let state = Arc::new(AppState {
        scanner,
        lexicon: lexicon(),
        max_body_bytes: 1 << 20,
        admission: Admission::new(2, 4),
    });
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("binding an ephemeral port");
    let address = listener.local_addr().expect("the bound address");
    tokio::spawn(async move {
        axum::serve(listener, service::router(state)).await.ok();
    });

    let response = reqwest::get(format!("http://{address}/health"))
        .await
        .expect("health request");
    assert_eq!(response.status(), 503);
    let health: serde_json::Value = response.json().await.expect("health json");
    assert_eq!(health["status"], "degraded");
    let incomplete = health["incomplete_data"]
        .as_array()
        .expect("the incomplete table list");
    assert!(incomplete.iter().any(|name| name == "TLD list"), "{health}");
}

/// The batch route is the pipeline's route, and what it stores is what comes back from here: one
/// entry per distinct normalised value, with an occurrence count. A span list would be the same
/// information at two orders of magnitude the size.
#[tokio::test]
async fn scan_batch_deduplicates_and_counts() {
    let base = serve(1 << 20).await;
    let client = reqwest::Client::new();

    let body: serde_json::Value = client
        .post(format!("{base}/scan_batch"))
        .json(&serde_json::json!({
            "texts": [
                "Write to alice@example.com, or again to alice@Example.COM.",
                "Nothing of interest here."
            ]
        }))
        .send()
        .await
        .expect("scan_batch request")
        .json()
        .await
        .expect("scan_batch json");

    let results = body["results"].as_array().expect("one entry per text");
    assert_eq!(results.len(), 2, "{body}");
    let emails = results[0]["types"]["email"]
        .as_array()
        .expect("the email values");
    assert_eq!(
        emails.len(),
        1,
        "two domain spellings are one value: {body}"
    );
    assert_eq!(emails[0]["value"], "alice@example.com");
    assert_eq!(emails[0]["count"], 2);
    assert!(emails[0]["value_json"].is_object(), "{body}");
    assert!(
        results[1]["types"]
            .as_object()
            .expect("a types map")
            .is_empty(),
        "a text with no entities carries no types: {body}"
    );
    assert!(body["rule_set_version"].as_u64().is_some(), "{body}");
}

/// The bound and its queue are reported, because an operator sizing a deployment against them
/// needs to read them from the running process rather than from a default in the source.
#[tokio::test]
async fn health_reports_the_scan_bound() {
    let base = serve(1 << 20).await;
    let health: serde_json::Value = reqwest::get(format!("{base}/health"))
        .await
        .expect("health request")
        .json()
        .await
        .expect("health json");
    assert_eq!(health["scan_threads"], 2, "{health}");
    assert_eq!(health["queue_depth"], 4, "{health}");
    assert_eq!(health["in_flight"], 0, "{health}");
}

/// The lexicon routes end to end: the categories and their documentation, spans on `/scan` only
/// when asked for, and per-category summaries from `/signal_batch`, with offsets usable against the
/// source and the version that produced them.
#[tokio::test]
async fn signals_on_scan_and_in_batch() {
    let base = serve(1 << 20).await;
    let client = reqwest::Client::new();

    let catalogue: serde_json::Value = client
        .get(format!("{base}/signals"))
        .send()
        .await
        .expect("signals request")
        .json()
        .await
        .expect("signals json");
    let version = catalogue["signal_set_version"]
        .as_str()
        .expect("a version")
        .to_string();
    let bribery = catalogue["categories"]
        .as_array()
        .expect("a category list")
        .iter()
        .find(|category| category["id"] == "bribery")
        .expect("bribery listed");
    assert!(bribery["does_not_prove"]
        .as_str()
        .is_some_and(|s| !s.is_empty()));
    assert!(
        bribery["terms"]["en"].as_u64().is_some_and(|n| n > 0),
        "{bribery}"
    );

    let text = "Keep it off the books, nobody will find out.";
    let plain: serde_json::Value = client
        .post(format!("{base}/scan"))
        .json(&serde_json::json!({ "text": text }))
        .send()
        .await
        .expect("scan request")
        .json()
        .await
        .expect("scan json");
    assert!(
        plain.get("signals").is_none(),
        "signals only when asked: {plain}"
    );

    let with_signals: serde_json::Value = client
        .post(format!("{base}/scan"))
        .json(&serde_json::json!({ "text": text, "offset": 100, "signals": true }))
        .send()
        .await
        .expect("scan request")
        .json()
        .await
        .expect("scan json");
    assert_eq!(with_signals["signal_set_version"], version.as_str());
    let signals = with_signals["signals"].as_array().expect("a signal list");
    let books = signals
        .iter()
        .find(|signal| signal["concept"] == "off the books")
        .expect("off the books found");
    let start = books["start"].as_u64().expect("a start") as usize - 100;
    let end = books["end"].as_u64().expect("an end") as usize - 100;
    assert_eq!(&text[start..end], "off the books");
    assert_eq!(books["text"], "off the books");

    let batch: serde_json::Value = client
        .post(format!("{base}/signal_batch"))
        .json(&serde_json::json!({ "texts": [
            text,
            "Die Provision lief über eine schwarze Kasse, das merkt keiner.",
            "The quarterly report is attached."
        ]}))
        .send()
        .await
        .expect("batch request")
        .json()
        .await
        .expect("batch json");
    assert_eq!(batch["signal_set_version"], version.as_str());
    let results = batch["results"].as_array().expect("a result list");
    assert_eq!(results.len(), 3);
    assert!(results[0]["categories"]["concealment"]["score"]
        .as_f64()
        .is_some_and(|s| s > 0.5));
    assert!(
        results[1]["categories"]["accounting"].is_object(),
        "{batch}"
    );
    assert!(
        results[1]["categories"]["concealment"].is_object(),
        "{batch}"
    );
    assert!(
        results[2]["categories"]
            .as_object()
            .expect("a map")
            .is_empty(),
        "an ordinary sentence carries no signal: {batch}"
    );
}
