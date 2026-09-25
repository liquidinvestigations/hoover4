//! Plan decisions: approve, reject or cancel a deep-research plan, and the plan view the
//! card reads.
//!
//! A plan that waits for review has no workflow open. A decision starts a new run, and
//! nothing waits for a person. [`decide_plan`] holds the session's `turn_lock` for its
//! whole body, so every seq reservation and every decision of one session are serial in
//! the one website process.
//!
//! 1. Read the plan run by owner, and the decision rows of the run. A decision id that
//!    already has an accepted row returns `Duplicate` and starts nothing.
//! 2. A terminal run returns `Terminal`. For approve and reject, a `reviewed_version` other
//!    than the run's returns `StaleVersion`, and a state other than `awaiting_review`
//!    returns `WrongState`. Cancel is accepted in every state that is not terminal.
//! 3. Approve and reject reserve a seq, write the user row and the empty stream row, write
//!    the decision row, and start the run: a planner run `plan-{plan_run_id}-r{round}`
//!    for a reject, an organizer run `plan-{plan_run_id}-o1` for an approve. The run reads
//!    the comment and the version from the decision row, so the row is written before the
//!    start. A failed start rewrites the row's outcome to `start_failed`, writes an `error`
//!    row at the reserved seq, and returns `StartFailed`.
//! 4. A cancel in `awaiting_review` writes the plan run state `cancelled` and its ending
//!    rows. When an accepted approve or reject has started a run that has not opened yet,
//!    the cancel writes the stop row at that decision's turn and no plan state, and the run
//!    closes in its `open_run`. A cancel in `planning`, `revising` or `executing` writes the stop row of the
//!    plan's open turn and cancels the workflow of every `running` run of the plan. The run
//!    that the stop reaches writes `cancelled`.

use common::chat_types::{ChatOptions, ChatRole};
use common::current_user::CurrentUser;
use common::plan_types::{
    PlanAction, PlanDecisionOutcome, PlanDecisionRequest, PlanNodeView, PlanView,
    MAX_PLAN_COMMENT_CHARS,
};

use super::{
    cancel_workflow, intersect_collections, new_run_id, start_agent_workflow,
    AgentWorkflowStart, CHAT_TASK_QUEUE,
};
use crate::db_chat::{self, plans as db_plans, AppendMessageExtras};
use crate::db_utils::clickhouse_utils::list_permitted_collections;

/// The refusal while another request of the session holds the turn lock.
const BUSY: &str = "this conversation is busy, try the decision again";
/// The ending row of a plan that the person stopped.
pub(crate) const PLAN_STOPPED_TEXT: &str = "This plan run was stopped.";
/// The pending plan rule's refusal of a new message or research request.
pub(crate) const PLAN_PENDING_TEXT: &str =
    "a plan is waiting for review or running in this conversation";

/// The workflow id of planner round `round` of a plan run.
pub(crate) fn planner_workflow_id(plan_run_id: &str, round: u64) -> String {
    format!("plan-{plan_run_id}-r{round}")
}

/// The workflow id of organizer step 1 of a plan run.
fn organizer_workflow_id(plan_run_id: &str) -> String {
    format!("plan-{plan_run_id}-o1")
}

/// The outcome of the checks of step 2, or `None` when the decision may go ahead.
fn check_decision(
    run: &db_plans::PlanRunRow,
    action: PlanAction,
    reviewed_version: u64,
) -> Option<PlanDecisionOutcome> {
    if run.is_terminal() {
        return Some(PlanDecisionOutcome::Terminal {
            state: run.state.clone(),
        });
    }
    if action == PlanAction::Cancel {
        return None;
    }
    if reviewed_version != run.reviewed_version {
        return Some(PlanDecisionOutcome::StaleVersion {
            current_version: run.reviewed_version,
        });
    }
    if run.state != "awaiting_review" {
        return Some(PlanDecisionOutcome::WrongState {
            state: run.state.clone(),
        });
    }
    None
}

/// Approve, reject or cancel a plan. See the module documentation for the steps.
pub async fn decide_plan(
    user: &CurrentUser,
    request: PlanDecisionRequest,
) -> anyhow::Result<PlanDecisionOutcome> {
    let username = user.username.as_str();
    let session_id = request.session_id.as_str();
    let comment = request.comment.trim().to_string();
    if request.action == PlanAction::Reject
        && (comment.is_empty() || comment.chars().count() > MAX_PLAN_COMMENT_CHARS)
    {
        anyhow::bail!("a rejection needs a comment of 1 to {MAX_PLAN_COMMENT_CHARS} characters");
    }
    let session = db_chat::get_session(username, session_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("chat session not found"))?;

    let _guard = db_chat::turn_lock(username, session_id)
        .try_lock_owned()
        .map_err(|_| anyhow::anyhow!(BUSY))?;

    let run = db_plans::read_plan_run(username, session_id, &request.run_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("plan run not found"))?;
    let decisions = db_plans::read_decisions(username, session_id, &run.rid).await?;
    if decisions
        .iter()
        .any(|d| d.did == request.decision_id && d.outcome == db_plans::OUTCOME_ACCEPTED)
    {
        return Ok(PlanDecisionOutcome::Duplicate {
            first: Box::new(PlanDecisionOutcome::Accepted),
        });
    }
    if let Some(refusal) = check_decision(&run, request.action, request.reviewed_version) {
        return Ok(refusal);
    }

    match request.action {
        PlanAction::Cancel => cancel_plan(username, session_id, &run, &decisions, &request).await,
        PlanAction::Approve | PlanAction::Reject => {
            start_plan_round(user, &session, &run, &request, &comment).await
        }
    }
}

/// Step 3: reserve the segment, write the decision row, and start the planner or the
/// organizer run.
async fn start_plan_round(
    user: &CurrentUser,
    session: &db_chat::ChatSessionRow,
    run: &db_plans::PlanRunRow,
    request: &PlanDecisionRequest,
    comment: &str,
) -> anyhow::Result<PlanDecisionOutcome> {
    let username = user.username.as_str();
    let session_id = request.session_id.as_str();
    let (text, kind, workflow_id) = match request.action {
        PlanAction::Reject => (
            comment.to_string(),
            "planner",
            planner_workflow_id(&run.rid, run.review_round + 1),
        ),
        _ => (
            format!("Approved plan version {}.", run.reviewed_version),
            "organizer",
            organizer_workflow_id(&run.rid),
        ),
    };
    let turn_uuid = crate::db_auth::sessions::generate_session_id();
    let user_seq = db_chat::next_seq(username, session_id).await?;
    db_chat::append_message(
        username,
        session_id,
        user_seq,
        ChatRole::User,
        &text,
        AppendMessageExtras {
            message_uuid: turn_uuid.clone(),
            ..Default::default()
        },
    )
    .await?;
    let start_seq = user_seq + 1;
    db_chat::append_stream_row(
        username,
        session_id,
        start_seq,
        ChatRole::Assistant,
        "",
        "",
        "",
        0,
        false,
        &turn_uuid,
    )
    .await?;
    let write = |outcome: &'static str| {
        db_plans::write_decision(
            username,
            session_id,
            &run.rid,
            &request.decision_id,
            request.action.as_str(),
            request.reviewed_version,
            comment,
            outcome,
            start_seq,
            &turn_uuid,
        )
    };
    write(db_plans::OUTCOME_ACCEPTED).await?;

    let permitted = list_permitted_collections(user).await?;
    let allowed = intersect_collections(&session.collections, &permitted);
    let started = start_agent_workflow(AgentWorkflowStart {
        workflow_type: "AgentRun",
        task_queue: CHAT_TASK_QUEUE,
        workflow_id: &workflow_id,
        input: serde_json::json!({
            "run_id": new_run_id(),
            "username": username,
            "session_id": session_id,
            "kind": kind,
            "turn_seq": user_seq,
            "start_seq": start_seq,
            "turn_uuid": &turn_uuid,
            "allowed_collections": &allowed,
            "llm_model": "",
            // The frozen switch of the conversation, never the request's.
            "internet_tools": session.options().internet_tools,
            "plan_run_id": &run.rid,
            "decision_id": &request.decision_id,
        }),
    })
    .await;
    if let Err(e) = started {
        tracing::error!("could not start {workflow_id}: {e:#}");
        write(db_plans::OUTCOME_START_FAILED).await?;
        let _ = db_chat::append_message(
            username,
            session_id,
            start_seq,
            ChatRole::Error,
            &format!("The plan run could not be started: {e}"),
            AppendMessageExtras {
                message_uuid: turn_uuid.clone(),
                ..Default::default()
            },
        )
        .await;
        let _ = db_chat::mark_stream_final(username, session_id).await;
        return Ok(PlanDecisionOutcome::StartFailed {
            error: e.to_string(),
        });
    }
    Ok(PlanDecisionOutcome::Accepted)
}

/// The turn of the newest accepted approve or reject whose run has not opened yet, or
/// `None`. The started run writes its `agent_runs` row in `open_run`, at the turn before the
/// decision's `start_seq`. Until then the plan run stays in `awaiting_review`.
fn unopened_decision_turn(
    decisions: &[db_plans::DecisionRow],
    runs: &[db_plans::PlanAgentRun],
) -> Option<u32> {
    let decision = decisions.iter().rev().find(|d| {
        (d.action == PlanAction::Approve.as_str() || d.action == PlanAction::Reject.as_str())
            && d.outcome == db_plans::OUTCOME_ACCEPTED
            && d.start_seq > 0
    })?;
    let turn = decision.start_seq - 1;
    (!runs.iter().any(|r| r.turn_seq == turn)).then_some(turn)
}

/// Step 4: cancel a plan.
async fn cancel_plan(
    username: &str,
    session_id: &str,
    run: &db_plans::PlanRunRow,
    decisions: &[db_plans::DecisionRow],
    request: &PlanDecisionRequest,
) -> anyhow::Result<PlanDecisionOutcome> {
    let runs = db_plans::plan_agent_runs(username, session_id, &run.rid).await?;
    let unopened = if run.state == "awaiting_review" {
        unopened_decision_turn(decisions, &runs)
    } else {
        None
    };
    if let Some(turn_seq) = unopened {
        // A decision started a run that has not opened. The stop row closes that run in
        // its `open_run`, which writes the `cancelled` state and the ending rows.
        db_chat::write_turn_stop(username, session_id, turn_seq).await?;
        db_plans::write_decision(
            username,
            session_id,
            &run.rid,
            &request.decision_id,
            "cancel",
            request.reviewed_version,
            "",
            db_plans::OUTCOME_ACCEPTED,
            0,
            "",
        )
        .await?;
        return Ok(PlanDecisionOutcome::Accepted);
    }
    if run.state == "awaiting_review" {
        // No run is open, so the website writes the state and the ending rows itself.
        let turn_uuid = crate::db_auth::sessions::generate_session_id();
        let user_seq = db_chat::next_seq(username, session_id).await?;
        let extras = || AppendMessageExtras {
            message_uuid: turn_uuid.clone(),
            ..Default::default()
        };
        db_chat::append_message(
            username,
            session_id,
            user_seq,
            ChatRole::User,
            "Stop the plan.",
            extras(),
        )
        .await?;
        db_plans::write_plan_run_state(username, session_id, run, "cancelled").await?;
        db_chat::append_message(
            username,
            session_id,
            user_seq + 1,
            ChatRole::Error,
            PLAN_STOPPED_TEXT,
            extras(),
        )
        .await?;
        db_plans::write_decision(
            username,
            session_id,
            &run.rid,
            &request.decision_id,
            "cancel",
            request.reviewed_version,
            "",
            db_plans::OUTCOME_ACCEPTED,
            user_seq + 1,
            &turn_uuid,
        )
        .await?;
        return Ok(PlanDecisionOutcome::Accepted);
    }
    // The plan's open turn: the depth 0 run that started last. Every run of that round
    // carries its `turn_seq`, so each `open_run` and `continue_run` reads the stop row.
    if let Some(lead) = runs.iter().filter(|r| r.depth == 0).max_by_key(|r| r.started_ms) {
        db_chat::write_turn_stop(username, session_id, lead.turn_seq).await?;
    }
    for agent_run in runs.iter().filter(|r| r.state == "running") {
        // A 404 counts as success: the workflow ended before the request.
        if let Err(e) = cancel_workflow(&agent_run.workflow_id).await {
            tracing::warn!("cancel of plan {}: {e}", run.rid);
        }
    }
    db_plans::write_decision(
        username,
        session_id,
        &run.rid,
        &request.decision_id,
        "cancel",
        request.reviewed_version,
        "",
        db_plans::OUTCOME_ACCEPTED,
        0,
        "",
    )
    .await?;
    Ok(PlanDecisionOutcome::Accepted)
}

/// The plan run state and the tree at `version`, or at the newest version when `version`
/// is 0. `None` for a missing or foreign plan run.
pub async fn get_plan_view(
    user: &CurrentUser,
    session_id: String,
    plan_run_id: String,
    version: u64,
) -> anyhow::Result<Option<PlanView>> {
    let username = user.username.as_str();
    let Some(run) = db_plans::read_plan_run(username, &session_id, &plan_run_id).await? else {
        return Ok(None);
    };
    let Some((version, nodes_json)) =
        db_plans::read_snapshot(username, &session_id, &run.pid, version).await?
    else {
        return Ok(None);
    };
    let nodes: Vec<PlanNodeView> = serde_json::from_str(&nodes_json).unwrap_or_default();
    Ok(Some(PlanView {
        run_id: run.rid,
        plan_id: run.pid,
        state: run.state,
        reviewed_version: run.reviewed_version,
        approved_version: run.approved_version,
        review_round: run.review_round,
        version,
        nodes,
        sections_json: run.sections_json,
    }))
}

/// The input of the planner run that a deep-research request starts.
///
/// `internet_tools` comes from `frozen`, the options that `lock_session_options` returned,
/// and never from the request, so a request that sends a changed switch cannot move a
/// conversation to the other agent service.
#[allow(clippy::too_many_arguments)]
pub(crate) fn research_start_input(
    frozen: ChatOptions,
    run_id: &str,
    plan_run_id: &str,
    username: &str,
    session_id: &str,
    user_seq: u32,
    turn_uuid: &str,
    allowed: &[String],
) -> serde_json::Value {
    serde_json::json!({
        "run_id": run_id,
        "username": username,
        "session_id": session_id,
        "kind": "planner",
        "turn_seq": user_seq,
        "start_seq": user_seq + 1,
        "turn_uuid": turn_uuid,
        "allowed_collections": allowed,
        "llm_model": "",
        "internet_tools": frozen.internet_tools,
        "plan_run_id": plan_run_id,
        "decision_id": "",
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(state: &str, reviewed: u64) -> db_plans::PlanRunRow {
        db_plans::PlanRunRow {
            rid: "r".into(),
            pid: "p".into(),
            start_seq: 2,
            state: state.into(),
            reviewed_version: reviewed,
            approved_version: 0,
            review_round: 0,
            sections_json: String::new(),
            state_version: 3,
        }
    }

    fn decision(action: &str, outcome: &str, start_seq: u32) -> db_plans::DecisionRow {
        db_plans::DecisionRow {
            did: format!("{action}-{start_seq}"),
            action: action.into(),
            reviewed_version: 2,
            outcome: outcome.into(),
            start_seq,
            turn_uuid: String::new(),
        }
    }

    fn agent_run(turn_seq: u32) -> db_plans::PlanAgentRun {
        db_plans::PlanAgentRun {
            workflow_id: String::new(),
            state: "completed".into(),
            depth: 0,
            turn_seq,
            started_ms: 0,
        }
    }

    #[test]
    fn a_cancel_before_open_run_stops_the_decision_turn() {
        let decisions = [decision("reject", "accepted", 5), decision("approve", "accepted", 9)];
        // The reject round opened at turn 4. The approval's run has no row at turn 8.
        assert_eq!(unopened_decision_turn(&decisions, &[agent_run(1), agent_run(4)]), Some(8));
        // After the organizer opened, the decision is no longer unopened.
        assert_eq!(
            unopened_decision_turn(&decisions, &[agent_run(1), agent_run(4), agent_run(8)]),
            None
        );
    }

    #[test]
    fn a_failed_start_or_no_decision_leaves_no_unopened_turn() {
        assert_eq!(unopened_decision_turn(&[], &[agent_run(1)]), None);
        let failed = [decision("approve", "start_failed", 9)];
        assert_eq!(unopened_decision_turn(&failed, &[agent_run(1)]), None);
        let cancel = [decision("cancel", "accepted", 0)];
        assert_eq!(unopened_decision_turn(&cancel, &[agent_run(1)]), None);
    }

    #[test]
    fn stale_decision_returns_the_current_version() {
        assert_eq!(
            check_decision(&run("awaiting_review", 4), PlanAction::Approve, 3),
            Some(PlanDecisionOutcome::StaleVersion { current_version: 4 })
        );
    }

    #[test]
    fn decision_after_terminal_is_refused_for_every_action() {
        for action in [PlanAction::Approve, PlanAction::Reject, PlanAction::Cancel] {
            assert_eq!(
                check_decision(&run("cancelled", 4), action, 4),
                Some(PlanDecisionOutcome::Terminal {
                    state: "cancelled".into()
                })
            );
        }
    }

    #[test]
    fn approve_while_planning_is_the_wrong_state_and_cancel_is_accepted() {
        assert_eq!(
            check_decision(&run("planning", 0), PlanAction::Approve, 0),
            Some(PlanDecisionOutcome::WrongState {
                state: "planning".into()
            })
        );
        assert_eq!(check_decision(&run("executing", 2), PlanAction::Cancel, 1), None);
        assert_eq!(check_decision(&run("awaiting_review", 2), PlanAction::Reject, 2), None);
    }

    #[test]
    fn the_research_start_sends_the_frozen_switch_not_the_requested_one() {
        let frozen = ChatOptions {
            internet_tools: false,
            deep_research: true,
            ..Default::default()
        };
        let input =
            research_start_input(frozen, "run", "plan", "ann", "s1", 7, "t", &["c".into()]);
        assert_eq!(input["internet_tools"], serde_json::json!(false));
        assert_eq!(input["kind"], "planner");
        assert_eq!((input["turn_seq"].as_u64(), input["start_seq"].as_u64()), (Some(7), Some(8)));
        assert_eq!(planner_workflow_id("plan", 0), "plan-plan-r0");
    }
}
