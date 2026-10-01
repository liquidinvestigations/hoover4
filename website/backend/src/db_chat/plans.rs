//! Storage of the plan decisions and the plan run reads of the website.
//!
//! The tables are in migration `00031_agent_plans.sql`. The website writes the decision
//! rows, and it writes one plan run state: `cancelled` for a plan in `awaiting_review`,
//! when no run of the plan is open. The worker writes every other plan run state.
//!
//! **Every function here takes a `username` and a `session_id` and filters on both**, as
//! every read of `db_chat` does. Every read uses `FINAL`.

use crate::db_utils::clickhouse_utils::get_global_client;

/// One `agent_plan_runs` row, as the website reads it. The UUID columns come as text.
#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct PlanRunRow {
    pub rid: String,
    pub pid: String,
    pub start_seq: u32,
    pub state: String,
    pub reviewed_version: u64,
    pub approved_version: u64,
    pub review_round: u64,
    pub sections_json: String,
    pub state_version: u64,
}

impl PlanRunRow {
    pub fn is_terminal(&self) -> bool {
        common::plan_types::PLAN_TERMINAL_STATES.contains(&self.state.as_str())
    }
}

const PLAN_RUN_SELECT: &str = "SELECT toString(run_id) AS rid, toString(plan_id) AS pid, \
     start_seq, state, reviewed_version, approved_version, review_round, sections_json, \
     state_version FROM agent_plan_runs FINAL";

pub async fn read_plan_run(
    username: &str,
    session_id: &str,
    plan_run_id: &str,
) -> anyhow::Result<Option<PlanRunRow>> {
    let rows = get_global_client()
        .query(&format!(
            "{PLAN_RUN_SELECT} WHERE username = ? AND session_id = ? AND run_id = toUUID(?)"
        ))
        .bind(username)
        .bind(session_id)
        .bind(plan_run_id)
        .fetch_all::<PlanRunRow>()
        .await?;
    Ok(rows.into_iter().next())
}

/// Whether the session has a plan run that is not terminal: planned, waiting for review,
/// or executing. The pending plan rule reads it.
pub async fn session_has_open_plan(username: &str, session_id: &str) -> anyhow::Result<bool> {
    let n = get_global_client()
        .query(
            "SELECT count() FROM agent_plan_runs FINAL WHERE username = ? AND session_id = ? \
             AND state NOT IN ('completed', 'failed', 'cancelled')",
        )
        .bind(username)
        .bind(session_id)
        .fetch_one::<u64>()
        .await?;
    Ok(n > 0)
}

/// Write `state` into a plan run row at `state_version + 1`. The only caller is the cancel
/// of a plan in `awaiting_review`.
pub async fn write_plan_run_state(
    username: &str,
    session_id: &str,
    row: &PlanRunRow,
    state: &str,
) -> anyhow::Result<()> {
    get_global_client()
        .query(
            "INSERT INTO agent_plan_runs (run_id, plan_id, username, session_id, start_seq, \
             state, reviewed_version, approved_version, review_round, sections_json, \
             state_version, updated_at) VALUES (toUUID(?), toUUID(?), ?, ?, ?, ?, ?, ?, ?, ?, \
             ?, now64(3))",
        )
        .bind(&row.rid)
        .bind(&row.pid)
        .bind(username)
        .bind(session_id)
        .bind(row.start_seq)
        .bind(state)
        .bind(row.reviewed_version)
        .bind(row.approved_version)
        .bind(row.review_round)
        .bind(&row.sections_json)
        .bind(row.state_version + 1)
        .execute()
        .await?;
    Ok(())
}

/// One `agent_plan_decisions` row.
#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct DecisionRow {
    pub did: String,
    pub action: String,
    pub reviewed_version: u64,
    pub outcome: String,
    pub start_seq: u32,
    pub turn_uuid: String,
}

/// The outcome a decision row holds while its start is accepted.
pub const OUTCOME_ACCEPTED: &str = "accepted";
/// The outcome a decision row holds after its start failed. A click with the same id
/// decides again.
pub const OUTCOME_START_FAILED: &str = "start_failed";

pub async fn read_decisions(
    username: &str,
    session_id: &str,
    plan_run_id: &str,
) -> anyhow::Result<Vec<DecisionRow>> {
    let rows = get_global_client()
        .query(
            "SELECT toString(decision_id) AS did, action, reviewed_version, outcome, start_seq, \
             turn_uuid FROM agent_plan_decisions FINAL \
             WHERE username = ? AND session_id = ? AND run_id = toUUID(?) \
             ORDER BY created_at, decision_id",
        )
        .bind(username)
        .bind(session_id)
        .bind(plan_run_id)
        .fetch_all::<DecisionRow>()
        .await?;
    Ok(rows)
}

/// Write one decision row with a synchronous insert. A later write of the same id replaces
/// it, so a failed start rewrites the outcome.
#[allow(clippy::too_many_arguments)]
pub async fn write_decision(
    username: &str,
    session_id: &str,
    plan_run_id: &str,
    decision_id: &str,
    action: &str,
    reviewed_version: u64,
    comment: &str,
    outcome: &str,
    start_seq: u32,
    turn_uuid: &str,
) -> anyhow::Result<()> {
    get_global_client()
        .query(
            "INSERT INTO agent_plan_decisions (decision_id, run_id, username, session_id, \
             action, reviewed_version, comment, outcome, start_seq, turn_uuid, created_at) \
             VALUES (toUUID(?), toUUID(?), ?, ?, ?, ?, ?, ?, ?, ?, now64(3))",
        )
        .bind(decision_id)
        .bind(plan_run_id)
        .bind(username)
        .bind(session_id)
        .bind(action)
        .bind(reviewed_version)
        .bind(comment)
        .bind(outcome)
        .bind(start_seq)
        .bind(turn_uuid)
        .execute()
        .await?;
    Ok(())
}

/// One `agent_runs` row of a plan run, with the fields a cancel reads.
#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct PlanAgentRun {
    pub workflow_id: String,
    pub state: String,
    pub depth: u8,
    pub turn_seq: u32,
    pub started_ms: i64,
    /// Empty for a run that answered. `step_budget` or `empty_response` for a run that
    /// stopped before an answer. An older run can hold `repeated_call`.
    pub end_reason: String,
}

/// Every agent run of a plan run, oldest first.
pub async fn plan_agent_runs(
    username: &str,
    session_id: &str,
    plan_run_id: &str,
) -> anyhow::Result<Vec<PlanAgentRun>> {
    let rows = get_global_client()
        .query(
            "SELECT workflow_id, state, depth, turn_seq, \
             toUnixTimestamp64Milli(started_at) AS started_ms, \
             toString(end_reason) AS end_reason FROM agent_runs FINAL \
             WHERE username = ? AND session_id = ? AND plan_run_id = toUUID(?) \
             ORDER BY started_at, run_id",
        )
        .bind(username)
        .bind(session_id)
        .bind(plan_run_id)
        .fetch_all::<PlanAgentRun>()
        .await?;
    Ok(rows)
}

/// The tree of a plan at `version`, or the newest when `version` is 0, as
/// `(version, nodes_json)`.
pub async fn read_snapshot(
    username: &str,
    session_id: &str,
    plan_id: &str,
    version: u64,
) -> anyhow::Result<Option<(u64, String)>> {
    let rows = get_global_client()
        .query(
            "SELECT version, nodes_json FROM agent_plan_snapshots FINAL \
             WHERE username = ? AND session_id = ? AND plan_id = toUUID(?) \
             AND (? = 0 OR version = ?) ORDER BY version DESC LIMIT 1",
        )
        .bind(username)
        .bind(session_id)
        .bind(plan_id)
        .bind(version)
        .bind(version)
        .fetch_all::<(u64, String)>()
        .await?;
    Ok(rows.into_iter().next())
}

/// One report document of a plan run: the text `report` or the typed `report_data` of a
/// sub-agent thread. A body above the worker's inline limit is in the artifact
/// `artifact_id`, and `body_inline` is empty.
#[derive(Debug, Clone, clickhouse::Row, serde::Serialize, serde::Deserialize)]
pub struct PlanReportDocument {
    pub did: String,
    pub nid: String,
    pub kind: String,
    pub attempt: u8,
    pub body_inline: String,
    pub artifact_id: String,
    pub created_ms: i64,
}

/// Every `report` and `report_data` document of a plan run, oldest first.
pub async fn read_report_documents(
    username: &str,
    session_id: &str,
    plan_run_id: &str,
) -> anyhow::Result<Vec<PlanReportDocument>> {
    let rows = get_global_client()
        .query(
            "SELECT toString(document_id) AS did, toString(node_id) AS nid, kind, attempt, \
             body_inline, artifact_id, toUnixTimestamp64Milli(created_at) AS created_ms \
             FROM agent_plan_documents FINAL WHERE username = ? AND session_id = ? \
             AND run_id = toUUID(?) AND kind IN ('report', 'report_data') \
             ORDER BY created_at, document_id",
        )
        .bind(username)
        .bind(session_id)
        .bind(plan_run_id)
        .fetch_all::<PlanReportDocument>()
        .await?;
    Ok(rows)
}

/// The whole body of a report document of the owner. A body in an artifact is read only
/// when the artifact row has the same owner and session.
async fn report_body(
    username: &str,
    session_id: &str,
    doc: &PlanReportDocument,
) -> anyhow::Result<String> {
    if doc.artifact_id.is_empty() {
        return Ok(doc.body_inline.clone());
    }
    let Some(row) = crate::db_chat::artifacts::get_artifact(&doc.artifact_id).await? else {
        anyhow::bail!("the body of report {} has no artifact row", doc.did);
    };
    if row.username != username || row.session_id != session_id || row.body_key.is_empty() {
        anyhow::bail!("the body of report {} belongs to another owner", doc.did);
    }
    let bytes = crate::server_extra::chat_artifact::fetch_artifact_object(&row.body_key).await?;
    Ok(String::from_utf8(bytes)?)
}

/// The document of each citation in the typed reports of the session's plan runs. A
/// sub-agent's `cite_documents` result names only the file hash, and its typed report
/// keeps the whole identity. A report whose body cannot be read is skipped.
pub async fn session_report_citations(
    username: &str,
    session_id: &str,
) -> anyhow::Result<Vec<common::chat_types::ChatDocRef>> {
    let docs = get_global_client()
        .query(
            "SELECT toString(document_id) AS did, toString(node_id) AS nid, kind, attempt, \
             body_inline, artifact_id, toUnixTimestamp64Milli(created_at) AS created_ms \
             FROM agent_plan_documents FINAL WHERE username = ? AND session_id = ? \
             AND kind = 'report_data' ORDER BY created_at, document_id",
        )
        .bind(username)
        .bind(session_id)
        .fetch_all::<PlanReportDocument>()
        .await?;
    let mut refs = Vec::new();
    for doc in &docs {
        let body = match report_body(username, session_id, doc).await {
            Ok(body) => body,
            Err(e) => {
                tracing::warn!("report {} citations skipped: {e:#}", doc.did);
                continue;
            }
        };
        let Ok(data) = serde_json::from_str::<common::report_types::ReportData>(&body) else {
            continue;
        };
        for entry in data.citations {
            if let Ok(doc_ref) = serde_json::from_value::<common::chat_types::ChatDocRef>(
                serde_json::Value::Object(entry.reference),
            ) {
                refs.push(doc_ref);
            }
        }
    }
    Ok(refs)
}

/// The newest report of each section node of a plan run, typed when the `report_data`
/// document parses, else the text report. A node whose documents are both missing is
/// not listed.
pub async fn read_section_reports(
    username: &str,
    session_id: &str,
    plan_run_id: &str,
) -> anyhow::Result<Vec<(String, common::report_types::SectionReport)>> {
    let docs = read_report_documents(username, session_id, plan_run_id).await?;
    let mut nodes: Vec<String> = Vec::new();
    for doc in &docs {
        if !nodes.contains(&doc.nid) {
            nodes.push(doc.nid.clone());
        }
    }
    let mut out = Vec::new();
    for node in nodes {
        let newest = |kind: &str| docs.iter().filter(|d| d.nid == node && d.kind == kind).last();
        let data = match newest("report_data") {
            Some(doc) => Some(report_body(username, session_id, doc).await?),
            None => None,
        };
        let text = match newest("report") {
            Some(doc) => Some(report_body(username, session_id, doc).await?),
            None => None,
        };
        out.push((
            node,
            common::report_types::parse_section_report(data.as_deref(), text.as_deref()),
        ));
    }
    Ok(out)
}

/// The frozen execution settings of a plan run: the `execution_settings` document that the
/// worker writes before the first planner model call. `None` for a plan run from before
/// the settings.
#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize)]
pub struct ExecutionSettings {
    pub model: String,
    #[serde(default)]
    pub internet_tools: bool,
    #[serde(default)]
    pub plan_contract: u64,
    #[serde(default)]
    pub model_source: String,
}

/// The execution settings of a plan run, or `None` when the plan run has none. The body is
/// small, so the document holds it inline.
pub async fn read_execution_settings(
    username: &str,
    session_id: &str,
    plan_run_id: &str,
) -> anyhow::Result<Option<ExecutionSettings>> {
    let rows = get_global_client()
        .query(
            "SELECT body_inline FROM agent_plan_documents FINAL WHERE username = ? \
             AND session_id = ? AND run_id = toUUID(?) AND kind = 'execution_settings' \
             ORDER BY created_at DESC LIMIT 1",
        )
        .bind(username)
        .bind(session_id)
        .bind(plan_run_id)
        .fetch_all::<String>()
        .await?;
    Ok(rows.first().and_then(|body| serde_json::from_str(body).ok()))
}

/// The model of the newest assistant row of a plan run that names one, or `None`. A plan
/// run from before the execution settings freezes this model at its next start.
pub async fn recorded_planner_model(
    username: &str,
    session_id: &str,
    start_seq: u32,
) -> anyhow::Result<Option<String>> {
    let rows = get_global_client()
        .query(
            "SELECT model FROM chat_messages FINAL WHERE username = ? AND session_id = ? \
             AND seq >= ? AND role = 'assistant' AND model != '' ORDER BY seq DESC LIMIT 1",
        )
        .bind(username)
        .bind(session_id)
        .bind(start_seq)
        .fetch_all::<String>()
        .await?;
    Ok(rows.into_iter().next())
}
