//! Temporal workflow HTTP trigger helpers.

use crate::db_utils::clickhouse_utils::get_clickhouse_client;

pub async fn trigger_workflow(collection_dataset: &str, kind: &str) -> anyhow::Result<String> {
    let base_url = std::env::var("TEMPORAL_HTTP_URL")
        .unwrap_or_else(|_| "http://localhost:7243".to_string());

    let (workflow_type, workflow_id, task_queue, input) = match kind {
        "rescan" => {
            let client = get_clickhouse_client();
            let rows = client
                .query("SELECT dataset_type, dataset_path FROM dataset FINAL WHERE collection_dataset = ? AND is_deleted = 0 LIMIT 1")
                .bind(collection_dataset)
                .fetch_all::<(String, String)>()
                .await?;
            let Some((dataset_type, dataset_path)) = rows.into_iter().next() else {
                anyhow::bail!("dataset not found");
            };
            if dataset_type != "disk" {
                anyhow::bail!("rescan only valid for disk datasets");
            }
            (
                "IngestDiskDataset",
                format!("ingest-disk-{collection_dataset}"),
                "processing-common-queue",
                serde_json::json!({
                    "collection_dataset": collection_dataset,
                    "dataset_path": dataset_path,
                }),
            )
        }
        "compute_plans" => (
            "ComputePlans",
            format!("compute-plans-{collection_dataset}"),
            "processing-common-queue",
            serde_json::json!({ "collection_dataset": collection_dataset }),
        ),
        "execute_plans" => (
            "ExecutePlans",
            format!("execute-plans-{collection_dataset}"),
            "processing-common-queue",
            serde_json::json!({
                "collection_dataset": collection_dataset,
                "starting_plan_hash": null,
                "base_temp_dir": "/tmp/hoover4",
            }),
        ),
        _ => anyhow::bail!("unknown workflow kind: {kind}"),
    };

    let url = format!(
        "{base_url}/api/v1/namespaces/default/workflows/{workflow_id}"
    );
    let body = serde_json::json!({
        "workflowType": { "name": workflow_type },
        "taskQueue": { "name": task_queue },
        "input": [ input ],
    });

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
