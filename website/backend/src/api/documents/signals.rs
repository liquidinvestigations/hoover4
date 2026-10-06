//! Read scanner terms and the stored red flag evidence.

use crate::{auth::permissions, db_utils::clickhouse_utils::get_client_for_dataset};
use anyhow::Context;
use common::{current_user::CurrentUser, search_result::DocumentIdentifier, signals::*};
use std::time::Duration;

async fn scanner_get(route: &str) -> anyhow::Result<serde_json::Value> {
    let base = std::env::var("REGEX_SCANNER_URL").context("The scanner URL is unavailable.")?;
    let client = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(2))
        .timeout(Duration::from_secs(15))
        .build()?;
    Ok(client
        .get(format!("{}{route}", base.trim_end_matches('/')))
        .send()
        .await?
        .error_for_status()?
        .json()
        .await?)
}

pub async fn signal_catalog(
    _user: &CurrentUser,
    include_terms: bool,
) -> anyhow::Result<SignalCatalog> {
    let catalog = scanner_get("/signals").await?;
    let path = std::env::var("HOOVER4_SIGNAL_CALIBRATION")
        .unwrap_or_else(|_| "/mirror/processing-tasks/signal_calibration.json".to_string());
    let calibration: serde_json::Value =
        serde_json::from_str(&tokio::fs::read_to_string(path).await?)?;
    let categories = catalog["categories"]
        .as_array()
        .context("The scanner category list is absent.")?
        .iter()
        .map(|category| {
            let mut value = category.clone();
            let id = category["id"]
                .as_str()
                .context("A signal category has no identifier.")?;
            let settings = calibration["categories"][id]
                .as_object()
                .context("A signal category has no calibration.")?;
            value
                .as_object_mut()
                .context("A signal category is invalid.")?
                .extend(settings.clone());
            Ok(serde_json::from_value(value)?)
        })
        .collect::<anyhow::Result<Vec<SignalCategory>>>()?;
    let version = catalog["signal_set_version"]
        .as_str()
        .context("The scanner version is absent.")?
        .to_string();
    let terms = if include_terms {
        let terms = scanner_get("/signal_terms").await?;
        anyhow::ensure!(
            terms["signal_set_version"].as_str() == Some(version.as_str()),
            "The signal catalog changed during the request."
        );
        serde_json::from_value(terms["terms"].clone())?
    } else {
        Vec::new()
    };
    Ok(SignalCatalog {
        signal_set_version: version,
        categories,
        terms,
    })
}

pub async fn signal_titles() -> anyhow::Result<std::collections::HashMap<String, String>> {
    let catalog = scanner_get("/signals").await?;
    catalog["categories"]
        .as_array()
        .context("The scanner category list is absent.")?
        .iter()
        .map(|row| {
            Ok((
                row["id"]
                    .as_str()
                    .context("A signal category has no identifier.")?
                    .to_string(),
                row["title"]
                    .as_str()
                    .context("A signal category has no title.")?
                    .to_string(),
            ))
        })
        .collect()
}

#[derive(clickhouse::Row, serde::Deserialize)]
struct ClusterRow {
    category: String,
    extracted_by: String,
    page_id: u32,
    points: f64,
    excerpt: String,
    hit_starts: Vec<u32>,
    hit_ends: Vec<u32>,
    start: u32,
    end: u32,
}

#[derive(clickhouse::Row, serde::Deserialize)]
struct HitRow {
    category: String,
    extracted_by: String,
    page_id: u32,
    starts: Vec<u32>,
    ends: Vec<u32>,
    texts: Vec<String>,
    flags: Vec<Vec<String>>,
}

pub async fn document_signals(
    user: &CurrentUser,
    identifier: DocumentIdentifier,
) -> anyhow::Result<DocumentSignals> {
    permissions::assert_can_read(user, &identifier.collection_dataset).await?;
    let client = get_client_for_dataset(&identifier.collection_dataset).await?;
    let clusters: Vec<ClusterRow> = client.query(
        "SELECT category, extracted_by, page_id, points, excerpt, hit_starts, hit_ends, start, end \
         FROM signal_cluster FINAL WHERE collection_dataset = ? AND file_hash = ? \
         ORDER BY category, extracted_by, page_id, start")
        .bind(&identifier.collection_dataset).bind(&identifier.file_hash).fetch_all().await?;
    let hits: Vec<HitRow> = client.query(
        "SELECT h.category, h.extracted_by, h.page_id, h.starts, h.ends, h.texts, h.flags \
         FROM signal_hit AS h FINAL INNER JOIN ( \
           SELECT extracted_by, page_id, argMax(signal_set_version, scan_version) AS signal_set_version, \
                  max(scan_version) AS completed_scan_version FROM signal_scanned \
           WHERE collection_dataset = ? AND file_hash = ? GROUP BY extracted_by, page_id \
         ) AS s ON h.extracted_by = s.extracted_by AND h.page_id = s.page_id \
           AND h.signal_set_version = s.signal_set_version AND h.scan_version = s.completed_scan_version \
         WHERE h.collection_dataset = ? AND h.file_hash = ? ORDER BY h.category, h.extracted_by, h.page_id")
        .bind(&identifier.collection_dataset).bind(&identifier.file_hash)
        .bind(&identifier.collection_dataset).bind(&identifier.file_hash).fetch_all().await?;
    let mut other_hits = Vec::new();
    for row in hits {
        anyhow::ensure!(
            row.texts.len() == row.flags.len()
                && row.texts.len() == row.starts.len()
                && row.texts.len() == row.ends.len(),
            "Stored signal arrays have different lengths."
        );
        for (index, text) in row.texts.into_iter().enumerate() {
            if clusters.iter().any(|cluster| {
                cluster.category == row.category
                    && cluster.extracted_by == row.extracted_by
                    && cluster.page_id == row.page_id
                    && cluster.start <= row.starts[index]
                    && row.ends[index] <= cluster.end
            }) {
                continue;
            }
            other_hits.push(OtherSignalHit {
                category: row.category.clone(),
                extracted_by: row.extracted_by.clone(),
                page_id: row.page_id,
                text,
                flags: row.flags[index].clone(),
            });
        }
    }
    Ok(DocumentSignals {
        clusters: clusters
            .into_iter()
            .map(|row| SignalCluster {
                category: row.category,
                extracted_by: row.extracted_by,
                page_id: row.page_id,
                points: row.points,
                excerpt: row.excerpt,
                hit_starts: row.hit_starts,
                hit_ends: row.hit_ends,
            })
            .collect(),
        other_hits,
    })
}
