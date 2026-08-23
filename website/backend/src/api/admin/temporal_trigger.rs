//! Temporal workflow HTTP trigger helpers.

use crate::db_utils::clickhouse_utils::get_global_client;

/// Registry fields a pipeline workflow input is built from. The lookup goes to the
/// global database — `dataset` is the registry and stays global.
async fn dataset_registry_row(
    collection_dataset: &str,
) -> anyhow::Result<(String, String, String)> {
    let client = get_global_client();
    let rows = client
        .query("SELECT collectionname, dataset_type, dataset_path FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0 LIMIT 1")
        .bind(collection_dataset)
        .fetch_all::<(String, String, String)>()
        .await?;
    rows.into_iter()
        .next()
        .ok_or_else(|| anyhow::anyhow!("dataset not found"))
}

/// `CollectionDataset` search-attribute payload for a workflow start over the HTTP
/// API, so website-triggered runs are found by the same visibility query as the
/// Python-side starts (see `tasks/visibility.py`).
///
/// Temporal payloads are `{metadata, data}` with both values base64: the metadata
/// encoding is `json/plain` (base64 `anNvbi9wbGFpbg==`) and the data is the
/// JSON-encoded keyword value, i.e. the dataset name in quotes.
fn collection_dataset_search_attribute(collection_dataset: &str) -> serde_json::Value {
    use base64::Engine;
    let json_value = serde_json::to_string(collection_dataset).unwrap_or_default();
    serde_json::json!({
        "indexedFields": {
            "CollectionDataset": {
                "metadata": { "encoding": "anNvbi9wbGFpbg==" },
                "data": base64::engine::general_purpose::STANDARD.encode(json_value),
            }
        }
    })
}

/// Start a Temporal workflow over the HTTP API.
///
/// `target` is a `collection_dataset` for the pipeline kinds (`rescan`,
/// `ingest_and_process`, `compute_plans`, `execute_plans`) and a `collectionname` for the
/// collection-database kinds (`ensure_collection`, `drop_collection_database`).
///
/// Pipeline inputs carry `collectionname` alongside `collection_dataset`: the
/// processing side routes every ClickHouse call by collection and never re-derives it
/// inside an activity, so a missing field fails workflow deserialisation immediately.
pub async fn trigger_workflow(target: &str, kind: &str) -> anyhow::Result<String> {
    let collection_dataset = target;
    let base_url = std::env::var("TEMPORAL_HTTP_URL")
        .unwrap_or_else(|_| "http://localhost:21908".to_string());

    let (workflow_type, workflow_id, task_queue, input) = match kind {
        "rescan" => {
            let (collectionname, dataset_type, dataset_path) =
                dataset_registry_row(collection_dataset).await?;
            if dataset_type != "disk" {
                anyhow::bail!("rescan only valid for disk datasets");
            }
            (
                "IngestDiskDataset",
                format!("ingest-disk-{collection_dataset}"),
                "processing-common-queue",
                serde_json::json!({
                    "collectionname": collectionname,
                    "collection_dataset": collection_dataset,
                    "dataset_path": dataset_path,
                }),
            )
        }
        // Scan, plan and execute in sequence. `rescan` only walks the disk — the plan
        // stages must not start until it has finished, or they plan a subset of the
        // files. The CLI blocks in the caller to get that ordering; a browser request
        // cannot, so the ordering lives in a workflow instead. This is what a dataset
        // created from the admin UI is started with.
        "ingest_and_process" => {
            let (collectionname, dataset_type, dataset_path) =
                dataset_registry_row(collection_dataset).await?;
            if dataset_type != "disk" {
                anyhow::bail!("ingest_and_process only valid for disk datasets");
            }
            (
                "IngestAndProcessDataset",
                format!("ingest-and-process-{collection_dataset}"),
                "processing-common-queue",
                serde_json::json!({
                    "collectionname": collectionname,
                    "collection_dataset": collection_dataset,
                    "dataset_path": dataset_path,
                }),
            )
        }
        "compute_plans" => {
            let (collectionname, _, _) = dataset_registry_row(collection_dataset).await?;
            (
                "ComputePlans",
                format!("compute-plans-{collection_dataset}"),
                "processing-common-queue",
                serde_json::json!({
                    "collectionname": collectionname,
                    "collection_dataset": collection_dataset,
                }),
            )
        }
        "execute_plans" => {
            let (collectionname, _, _) = dataset_registry_row(collection_dataset).await?;
            (
                "ExecutePlans",
                format!("execute-plans-{collection_dataset}"),
                "processing-common-queue",
                serde_json::json!({
                    "collectionname": collectionname,
                    "collection_dataset": collection_dataset,
                    "starting_plan_hash": null,
                    "base_temp_dir": "/tmp/hoover4",
                }),
            )
        }
        // The two below take a `collectionname`, not a `collection_dataset`. The workflow
        // id carries a timestamp-free, name-keyed suffix so a repeated create/delete of
        // the same collection reuses the id; both workflows are idempotent.
        "ensure_collection" => (
            "EnsureCollectionDatabase",
            format!("ensure-collection-{target}"),
            "processing-common-queue",
            serde_json::json!({ "collectionname": target }),
        ),
        "drop_collection_database" => (
            "DropCollectionDatabase",
            format!("drop-collection-{target}"),
            "processing-common-queue",
            serde_json::json!({ "collectionname": target }),
        ),
        _ => anyhow::bail!("unknown workflow kind: {kind}"),
    };

    let url = format!(
        "{base_url}/api/v1/namespaces/default/workflows/{workflow_id}"
    );
    let mut body = serde_json::json!({
        "workflowType": { "name": workflow_type },
        "taskQueue": { "name": task_queue },
        "input": [ input ],
    });
    // Dataset-scoped kinds get the CollectionDataset search attribute; the
    // collection-lifecycle kinds have no dataset to tag.
    if matches!(
        kind,
        "rescan" | "ingest_and_process" | "compute_plans" | "execute_plans"
    ) {
        body["searchAttributes"] = collection_dataset_search_attribute(collection_dataset);
    }

    let client = reqwest::Client::new();
    let response = client
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&body)
        .send()
        .await?;

    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        anyhow::bail!("temporal trigger failed: {text}");
    }

    let json: serde_json::Value = response.json().await?;
    let run_id = json
        .get("runId")
        .and_then(|v| v.as_str())
        .unwrap_or("started")
        .to_string();
    Ok(run_id)
}
