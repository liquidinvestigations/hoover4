//! `/admin/ai_status` — configured vs serving, circuits, dims, traffic.

use std::time::Duration;

use common::current_user::CurrentUser;
use common::llm_types::{
    AdminAiStatus, AiCapabilityStatus, AiServiceUse, AiShardDimCheck, AiTrafficRow,
};

use crate::auth::guard;
use crate::db_auth::settings;
use crate::db_utils::clickhouse_utils::get_global_client;

/// Model ids written by smoke tests and by `verify-stack.sh`, never by a real turn.
///
/// They are excluded from the traffic and use% panels rather than deleted: the rows are
/// evidence that the check ran, and dropping them would make a failed smoke test look
/// identical to one that was never run. But a single 12 ms synthetic call dominated the
/// p50 of a panel whose whole job is showing how slow real turns are — a median computed
/// over two populations describes neither.
const SYNTHETIC_MODEL_IDS: &[&str] = &["phase5-smoke", "test-model"];

fn ai_server_url() -> String {
    // Prefer the embeddings URL's origin; fall back to the well-known compose name.
    if let Ok(url) = std::env::var("EMBEDDINGS_URL") {
        if let Some(base) = url.split("/v1").next() {
            if !base.is_empty() {
                return base.trim_end_matches('/').to_string();
            }
        }
    }
    "http://hoover4-ai-server:8000".into()
}

fn browser_url() -> String {
    std::env::var("HOOVER4_BROWSER_MCP_URL")
        .or_else(|_| std::env::var("BROWSER_MCP_URL"))
        .unwrap_or_else(|_| "http://hoover4-mcp-browser:8087".into())
        .trim_end_matches("/mcp")
        .to_string()
}

fn fingerprint_local() -> String {
    std::env::var("HOOVER4_CONFIG_FINGERPRINT").unwrap_or_default()
}

/// What the endpoint that answered is **actually** running on.
///
/// Read out of the health body, never out of the name of the slot the endpoint occupies.
/// `NER_URL` is a url, not a promise: point it at the CPU twin — which is exactly what a
/// deployment with no GPU does — and a row that prints its slot's name says `gpu` on a
/// host that has no GPU at all. This page exists to make "configured versus actually
/// serving" legible, so the one thing it must not do is repeat the configuration back.
///
/// `cuda_available` is published by the GPU server and absent from the CPU twins, so a
/// body that does not claim a GPU is not credited with one.
fn serving_hardware(health_body: &serde_json::Value) -> &'static str {
    match health_body
        .get("cuda_available")
        .and_then(|v| v.as_bool())
        .unwrap_or(false)
    {
        true => "gpu",
        false => "cpu",
    }
}

/// One NER endpoint's health body, or `None` if it cannot serve.
///
/// The probe stands on its own and is **never** widened to "the main AI server answered".
/// That server hosts three capabilities behind independent model loads, so
/// `ner_model_loaded` can be false while the process is perfectly healthy — and the panel
/// then reported NER up in exactly the situation it exists to report it down. A twin that
/// does not publish the flag is taken at its word: answering `/health` is all it claims.
async fn probe_ner(url: &str) -> Option<serde_json::Value> {
    if url.is_empty() {
        return None;
    }
    let body = probe_json(
        &format!("{}/health", url.trim_end_matches('/').trim_end_matches("/v1")),
        2,
    )
    .await
    .ok()?;
    let loaded = body
        .get("ner_model_loaded")
        .and_then(|v| v.as_bool())
        .unwrap_or(true);
    loaded.then_some(body)
}

async fn probe_json(url: &str, timeout_s: u64) -> Result<serde_json::Value, String> {
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(timeout_s))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .get(url)
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    resp.json().await.map_err(|e| e.to_string())
}

pub async fn admin_get_ai_status(user: &CurrentUser) -> anyhow::Result<AdminAiStatus> {
    guard::require_admin(user)?;

    let embeddings_model = settings::get_setting("embeddings_serving_model")
        .await?
        .unwrap_or_default();
    let embeddings_dim: u32 = settings::get_setting("embeddings_serving_dim")
        .await?
        .and_then(|s| s.parse().ok())
        .unwrap_or(0);

    let ai_health = probe_json(&format!("{}/health", ai_server_url()), 3).await;
    let (ai_ok, ai_body) = match &ai_health {
        Ok(v) => (true, v.clone()),
        Err(e) => (false, serde_json::json!({"error": e})),
    };
    let fingerprint_ai = ai_body
        .get("config_fingerprint")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let fp_local = fingerprint_local();

    let mut capabilities = Vec::new();

    // Embeddings
    let emb_provider = std::env::var("EMBEDDINGS_PROVIDER").unwrap_or_else(|_| "none".into());
    let emb_serving = if ai_ok {
        ai_body
            .get("embedding_model")
            .and_then(|v| v.as_str())
            .unwrap_or("—")
            .to_string()
    } else {
        "unreachable".into()
    };
    capabilities.push(AiCapabilityStatus {
        name: "embeddings".into(),
        configured_provider: emb_provider,
        serving_provider: if ai_ok {
            serving_hardware(&ai_body).into()
        } else {
            "down".into()
        },
        serving_model: emb_serving,
        reachable: ai_ok
            && ai_body
                .get("embedding_model_loaded")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
        detail: format!(
            "probed dim {}; configured serving dim {}",
            ai_body
                .get("embedding_dim")
                .and_then(|v| v.as_u64())
                .unwrap_or(0),
            embeddings_dim
        ),
        circuit_open_remaining_s: 0,
    });

    // Reranker
    let rerank_url = std::env::var("RERANK_URL").unwrap_or_default();
    capabilities.push(AiCapabilityStatus {
        name: "rerank".into(),
        configured_provider: if rerank_url.is_empty() {
            "none".into()
        } else {
            "gpu".into()
        },
        serving_provider: if ai_ok {
            serving_hardware(&ai_body).into()
        } else {
            "down".into()
        },
        serving_model: ai_body
            .get("reranker_model")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        reachable: ai_ok
            && ai_body
                .get("reranker_model_loaded")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
        detail: if rerank_url.is_empty() {
            "RERANK_URL unset".into()
        } else {
            rerank_url
        },
        circuit_open_remaining_s: 0,
    });

    // NER — GPU with CPU twin fallback
    let ner_url = std::env::var("NER_URL").unwrap_or_default();
    let ner_fallback = std::env::var("NER_URL_FALLBACK").unwrap_or_default();
    // The NER probe stands on its own — **never** `|| ai_ok`.
    //
    // That fallback made "NER is reachable" mean "the main AI server answered /health",
    // which is a different question with a different answer: the AI server hosts three
    // capabilities behind independent model loads, and `ner_model_loaded` can be false
    // while the process is perfectly healthy. The panel reported NER up in exactly the
    // situation it exists to report it down. If the endpoint's own /health does not
    // answer, that is what the row says.
    let ner_primary = probe_ner(&ner_url).await;
    // The fallback is probed only when the primary did not answer: it is what would
    // serve, and probing it regardless would cost a round trip nobody reads.
    let ner_secondary = match &ner_primary {
        Some(_) => None,
        None => probe_ner(&ner_fallback).await,
    };
    let ner_serving_body = ner_primary.clone().or_else(|| ner_secondary.clone());
    let (ner_slot, ner_endpoint) = match (&ner_primary, &ner_secondary) {
        (Some(_), _) => ("primary", ner_url.as_str()),
        (None, Some(_)) => ("fallback", ner_fallback.as_str()),
        (None, None) => ("none", ""),
    };
    // `serving` is what answered and what it runs on, never which slot it sits in: a
    // deployment with no GPU points NER_URL straight at the CPU twin, and naming the slot
    // there reports `gpu` on a host that has none.
    let ner_serving = match &ner_serving_body {
        Some(body) => serving_hardware(body).to_string(),
        None => "down".to_string(),
    };
    capabilities.push(AiCapabilityStatus {
        name: "ner".into(),
        configured_provider: std::env::var("NER_PROVIDER").unwrap_or_else(|_| "none".into()),
        serving_provider: ner_serving,
        // From the endpoint that actually answered, not from the main AI server's body —
        // when the twin is serving, the AI server's `ner_model` is a different process's
        // model or nothing at all.
        serving_model: ner_serving_body
            .as_ref()
            .and_then(|body| body.get("ner_model").and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string(),
        reachable: ner_serving_body.is_some(),
        detail: format!(
            "serving={ner_slot} {ner_endpoint}; primary={ner_url}; fallback={ner_fallback}"
        ),
        circuit_open_remaining_s: 0,
    });

    // OCR
    let ocr_url = std::env::var("OCR_TESSERACT_URL").unwrap_or_default();
    let ocr_ok = if ocr_url.is_empty() {
        false
    } else {
        let health = ocr_url
            .trim_end_matches("/ocr")
            .to_string()
            + "/health";
        probe_json(&health, 2).await.is_ok()
    };
    capabilities.push(AiCapabilityStatus {
        name: "ocr".into(),
        configured_provider: std::env::var("PDF_OCR_PROVIDER").unwrap_or_else(|_| "tesseract".into()),
        serving_provider: if ocr_ok {
            "tesseract".into()
        } else {
            "down".into()
        },
        serving_model: "tesseract".into(),
        reachable: ocr_ok,
        detail: ocr_url,
        circuit_open_remaining_s: 0,
    });

    // LLM
    let llm_base = std::env::var("LLM_BASE_URL").unwrap_or_default();
    let llm_model = settings::get_setting("llm_default_chat_model")
        .await?
        .unwrap_or_else(|| std::env::var("LLM_MODEL").unwrap_or_default());
    let llm_ok = if llm_base.is_empty() {
        false
    } else {
        let client = reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(2))
            .timeout(Duration::from_secs(5))
            .build()?;
        let mut req = client.get(format!("{}/models", llm_base.trim_end_matches('/')));
        if let Ok(path) = std::env::var("LLM_API_KEY_FILE") {
            if let Ok(key) = std::fs::read_to_string(&path) {
                req = req.bearer_auth(key.trim());
            }
        }
        req.send().await.map(|r| r.status().is_success()).unwrap_or(false)
    };
    capabilities.push(AiCapabilityStatus {
        name: "llm".into(),
        configured_provider: if llm_base.is_empty() {
            "none".into()
        } else {
            "configured".into()
        },
        serving_provider: if llm_ok {
            "live".into()
        } else {
            "down".into()
        },
        serving_model: llm_model.clone(),
        reachable: llm_ok,
        detail: llm_base.clone(),
        circuit_open_remaining_s: 0,
    });

    // Browser router
    let browser = probe_json(&format!("{}/health", browser_url()), 3).await;
    let (browser_live, browser_max, browser_detail) = match &browser {
        Ok(v) => (
            v.get("live_sessions")
                .and_then(|x| x.as_u64())
                .unwrap_or(0) as u32,
            v.get("max_sessions")
                .and_then(|x| x.as_u64())
                .unwrap_or(8) as u32,
            format!(
                "spawn_failures={}; sidecar_restarts={}; template_ready={}",
                v.get("spawn_failures").and_then(|x| x.as_u64()).unwrap_or(0),
                v.get("sidecar_restarts")
                    .and_then(|x| x.as_u64())
                    .unwrap_or(0),
                v.get("template_ready")
                    .and_then(|x| x.as_bool())
                    .unwrap_or(false)
            ),
        ),
        Err(e) => (0, 8, e.clone()),
    };
    capabilities.push(AiCapabilityStatus {
        name: "browser".into(),
        configured_provider: "playwright-mcp".into(),
        serving_provider: if browser.is_ok() {
            "router".into()
        } else {
            "down".into()
        },
        serving_model: format!("{browser_live}/{browser_max} sessions"),
        reachable: browser.is_ok(),
        detail: browser_detail.clone(),
        circuit_open_remaining_s: 0,
    });

    // Shard knn_dims vs probe
    let shard_dims = list_shard_dim_checks(embeddings_dim).await;

    // Traffic + use%
    let client = get_global_client();
    #[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
    struct TrafficRow {
        username: String,
        calls: u64,
        errors: u64,
        median_ms: f64,
    }
    let recent_traffic = client
        .query(
            "SELECT username, count() AS calls, sum(ok = 0) AS errors, \
                    quantile(0.5)(latency_ms) AS median_ms \
             FROM llm_call_events \
             WHERE event_time >= now() - INTERVAL 24 HOUR \
               AND model_id NOT IN ({synthetic:Array(String)}) \
             GROUP BY username ORDER BY calls DESC LIMIT 20",
        )
        .param("synthetic", SYNTHETIC_MODEL_IDS)
        .fetch_all::<TrafficRow>()
        .await
        .unwrap_or_default()
        .into_iter()
        .map(|r| AiTrafficRow {
            username: r.username,
            calls: r.calls,
            errors: r.errors,
            median_latency_ms: r.median_ms as u32,
        })
        .collect();

    #[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
    struct UseRow {
        service: String,
        calls: u64,
        errors: u64,
        busy_ms: u64,
    }
    let service_use: Vec<AiServiceUse> = client
        .query(
            "SELECT service, count() AS calls, sum(ok = 0) AS errors, \
                    sum(latency_ms) AS busy_ms \
             FROM ai_service_telemetry \
             WHERE event_time >= now() - INTERVAL 24 HOUR \
               AND detail NOT IN ({synthetic:Array(String)}) \
             GROUP BY service ORDER BY service",
        )
        .param("synthetic", SYNTHETIC_MODEL_IDS)
        .fetch_all::<UseRow>()
        .await
        .unwrap_or_default()
        .into_iter()
        .map(|r| {
            let busy_s = r.busy_ms as f64 / 1000.0;
            let use_pct = (busy_s / 86_400.0 * 100.0).min(100.0);
            AiServiceUse {
                service: r.service,
                calls_24h: r.calls,
                errors_24h: r.errors,
                busy_seconds_24h: busy_s,
                use_pct,
            }
        })
        .collect();

    // Also fold llm_call_events into use% when the telemetry table is still empty.
    let mut service_use = service_use;
    if !service_use.iter().any(|s| s.service == "llm") {
        #[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
        struct LlmUse {
            calls: u64,
            errors: u64,
            busy_ms: u64,
        }
        if let Ok(row) = client
            .query(
                "SELECT count() AS calls, sum(ok = 0) AS errors, sum(latency_ms) AS busy_ms \
                 FROM llm_call_events WHERE event_time >= now() - INTERVAL 24 HOUR",
            )
            .fetch_one::<LlmUse>()
            .await
        {
            if row.calls > 0 {
                let busy_s = row.busy_ms as f64 / 1000.0;
                service_use.push(AiServiceUse {
                    service: "llm".into(),
                    calls_24h: row.calls,
                    errors_24h: row.errors,
                    busy_seconds_24h: busy_s,
                    use_pct: (busy_s / 86_400.0 * 100.0).min(100.0),
                });
            }
        }
    }

    Ok(AdminAiStatus {
        capabilities,
        embeddings_serving_model: embeddings_model,
        embeddings_serving_dim: embeddings_dim,
        fingerprint_local: fp_local.clone(),
        fingerprint_ai_server: fingerprint_ai.clone(),
        fingerprint_match: !fp_local.is_empty()
            && !fingerprint_ai.is_empty()
            && fp_local == fingerprint_ai,
        ai_server_present: ai_ok,
        shard_dims,
        browser_live_sessions: browser_live,
        browser_max_sessions: browser_max,
        browser_detail,
        recent_traffic,
        service_use,
        llm_configured: !llm_base.is_empty() && !llm_model.is_empty(),
    })
}

async fn list_shard_dim_checks(probe_dim: u32) -> Vec<AiShardDimCheck> {
    // `manticore_shards` tracks the text shards (`testdata_1`), not the `_vectors`
    // companions. Derive the vector table name and ask Manticore for the live DDL —
    // knn_dims is fixed at CREATE and is what the index builder refuses on.
    let client = get_global_client();
    #[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
    struct ColRow {
        collectionname: String,
    }
    let collections = client
        .query(
            "SELECT collectionname FROM collections FINAL WHERE is_deleted = 0 ORDER BY collectionname",
        )
        .fetch_all::<ColRow>()
        .await
        .unwrap_or_default();

    let manticore = std::env::var("MANTICORE_URL").unwrap_or_else(|_| "http://manticore:9308".into());
    let http = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(5))
        .build()
        .ok();

    let mut out = Vec::new();
    for col in collections {
        let db = format!("Hoover4_Collection_{}", col.collectionname);
        #[derive(Debug, Clone, clickhouse::Row, serde::Deserialize)]
        struct ShardRow {
            shard_name: String,
        }
        let shards = client
            .query(&format!(
                "SELECT shard_name FROM {db}.manticore_shards FINAL \
                 WHERE NOT endsWith(shard_name, '_vectors') \
                   AND NOT endsWith(shard_name, '_pages') \
                   AND NOT endsWith(shard_name, '_meta') \
                 ORDER BY shard_index LIMIT 50"
            ))
            .fetch_all::<ShardRow>()
            .await
            .unwrap_or_default();
        if shards.is_empty() {
            out.push(AiShardDimCheck {
                collection: col.collectionname,
                table: "(no shards)".into(),
                knn_dims: 0,
                matches_probe: probe_dim == 0,
            });
            continue;
        }
        for s in shards {
            let vectors = if s.shard_name.ends_with("_vectors") {
                s.shard_name.clone()
            } else {
                format!("{}_vectors", s.shard_name)
            };
            let knn_dims = match &http {
                Some(h) => probe_knn_dims(h, &manticore, &vectors).await,
                None => None,
            };
            let Some(dims) = knn_dims else {
                out.push(AiShardDimCheck {
                    collection: col.collectionname.clone(),
                    table: format!("{vectors} (missing)"),
                    knn_dims: 0,
                    matches_probe: false,
                });
                continue;
            };
            out.push(AiShardDimCheck {
                collection: col.collectionname.clone(),
                table: vectors,
                knn_dims: dims,
                matches_probe: probe_dim > 0 && dims == probe_dim,
            });
        }
    }
    out
}

async fn probe_knn_dims(http: &reqwest::Client, manticore: &str, table: &str) -> Option<u32> {
    // Manticore HTTP SQL returns [{columns, data:[{"Create Table":"..."}]}].
    let url = format!("{}/sql?mode=raw", manticore.trim_end_matches('/'));
    let body = format!("SHOW CREATE TABLE {table}");
    let resp = http.post(&url).body(body).send().await.ok()?;
    if !resp.status().is_success() {
        return None;
    }
    let text = resp.text().await.ok()?;
    // knn_dims='384' (single or double quotes). Avoid a regex dep — one find is enough.
    let marker = "knn_dims=";
    let idx = text.find(marker)?;
    let rest = &text[idx + marker.len()..];
    let rest = rest.trim_start_matches(['\'', '"']);
    let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A CPU twin must never be reported as a GPU, whichever slot it was configured into.
    ///
    /// The bodies below are what the two servers actually publish. The twin's carries no
    /// `cuda_available` at all, which is the whole signal: a deployment with no GPU points
    /// `NER_URL` — the variable named "gpu" throughout this file — straight at the twin,
    /// and a row that prints the name of the slot then claims a GPU on a host that has
    /// none, on the one page whose subtitle promises to notice exactly that.
    #[test]
    fn a_cpu_twin_is_not_reported_as_a_gpu() {
        let twin = serde_json::json!({
            "status": "healthy",
            "ner_model_loaded": true,
            "ner_model": "xx_ent_wiki_sm",
            "nlp_model_id": "ner-spacy-xx",
        });
        assert_eq!(serving_hardware(&twin), "cpu");

        let gpu = serde_json::json!({
            "status": "healthy",
            "ner_model_loaded": true,
            "ner_model": "some-transformer",
            "cuda_available": true,
            "gpu_count": 1,
        });
        assert_eq!(serving_hardware(&gpu), "gpu");

        // A server that answers but says it has no CUDA is taken at its word, and so is
        // one that says nothing — an absent field is not evidence of a GPU.
        let gpu_less = serde_json::json!({"status": "healthy", "cuda_available": false});
        assert_eq!(serving_hardware(&gpu_less), "cpu");
        assert_eq!(serving_hardware(&serde_json::json!({})), "cpu");
    }
}
