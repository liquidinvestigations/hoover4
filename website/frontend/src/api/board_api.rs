//! Investigation board server function wrappers. Every user can own boards, and the backend
//! lets only the owner read or act on one (`backend::api::boards`).
//!
//! A person action is one board command (`board_command`). `run_board_action` makes the
//! request id of the action, sends the action again with the same id after a lost response,
//! and reads the command state until the command writer decides it. The functions without a
//! request id serve pages loaded before the board commands, and refuse.

use std::time::Duration;

use common::board_types::{
    BoardAction, BoardAssessment, BoardCommandReceipt, BoardCreateRequest, BoardListItem, BoardSnapshot,
};
use dioxus::prelude::*;

#[cfg(feature = "server")]
use crate::api::error_util::to_server_fn_error;

macro_rules! board_server_fn {
    ($name:ident, ($($arg:ident : $ty:ty),*)) => {
        #[server]
        pub async fn $name($($arg: $ty),*) -> Result<(), ServerFnError> {
            let user = crate::api::server_auth::extract_user().await?;
            backend::api::boards::$name(&user, $($arg),*)
                .await
                .map_err(to_server_fn_error)
        }
    };
    ($name:ident, ($($arg:ident : $ty:ty),*) -> $ret:ty) => {
        #[server]
        pub async fn $name($($arg: $ty),*) -> Result<$ret, ServerFnError> {
            let user = crate::api::server_auth::extract_user().await?;
            backend::api::boards::$name(&user, $($arg),*)
                .await
                .map_err(to_server_fn_error)
        }
    };
}

board_server_fn!(list_boards, () -> Vec<BoardListItem>);
board_server_fn!(create_board_command, (request_id: String, request: BoardCreateRequest) -> String);
board_server_fn!(board_snapshot, (board_id: String) -> BoardSnapshot);
board_server_fn!(board_command, (board_id: String, request_id: String, action: BoardAction) -> BoardCommandReceipt);
board_server_fn!(board_command_status, (board_id: String, request_id: String) -> BoardCommandReceipt);
board_server_fn!(board_fact_for_intent, (board_id: String, intent_id: String) -> Option<String>);
board_server_fn!(board_drop, (board_id: String));
board_server_fn!(board_assessment, (board_id: String, reason_no: u32) -> BoardAssessment);

// The endpoints of a page loaded before the board commands. The backend refuses each.
board_server_fn!(create_board, (request: BoardCreateRequest) -> String);
board_server_fn!(board_add_hint, (board_id: String, text: String));
board_server_fn!(board_reject_fact, (board_id: String, fact_id: String, reason: String));
board_server_fn!(board_set_paused, (board_id: String, paused: bool));
board_server_fn!(board_set_internet_tools, (board_id: String, on: bool));
board_server_fn!(board_review, (board_id: String, accept: bool, correction: String));
board_server_fn!(board_add_goal, (board_id: String, text: String));
board_server_fn!(board_explore_question, (board_id: String, fact_id: String, index: u32));
board_server_fn!(board_answer, (board_id: String, goal: String, reason_no: u32, accept: bool, correction: String));

/// No page of this build calls the endpoints above. This function names them, so the build
/// keeps them without a warning. The address of a server function comes from its module, so
/// they stay in this module.
#[allow(dead_code)]
fn outdated_endpoints() {
    let _ = (create_board, board_add_hint, board_reject_fact, board_set_paused, board_set_internet_tools,
             board_review, board_add_goal, board_explore_question, board_answer);
}

/// Sends of one action before the page shows the failure.
const SEND_ATTEMPTS: u32 = 3;
/// Reads of the command state, one each `STATUS_POLL_MS`, before the page reports the
/// command as pending.
const STATUS_READS: u32 = 90;
const STATUS_POLL_MS: u64 = 1000;

/// A new request id for one deliberate action: 32 hex characters from the browser's random
/// source, else from `Math.random`.
pub fn new_request_id() -> String {
    let mut bytes = [0_u8; 16];
    let filled = web_sys::window()
        .and_then(|w| w.crypto().ok())
        .is_some_and(|c| c.get_random_values_with_u8_array(&mut bytes).is_ok());
    if !filled {
        for byte in bytes.iter_mut() {
            *byte = (web_sys::js_sys::Math::random() * 256.0) as u8;
        }
    }
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Run one action of a person on a board: send it, then read its state until the command
/// writer commits or refuses it. Returns the decided receipt, or the text to show. A pending
/// receipt after `STATUS_READS` reads is returned as it is, and the page reads the board as
/// usual.
pub async fn run_board_action(board_id: String, action: BoardAction) -> Result<BoardCommandReceipt, String> {
    let request_id = new_request_id();
    let mut sent = None;
    let mut last_error = String::new();
    for _ in 0..SEND_ATTEMPTS {
        match board_command(board_id.clone(), request_id.clone(), action.clone()).await {
            Ok(receipt) => {
                sent = Some(receipt);
                break;
            }
            Err(e) => last_error = crate::api::error_util::user_facing_message(&e),
        }
    }
    let mut receipt = sent.ok_or(last_error)?;
    for _ in 0..STATUS_READS {
        if receipt.is_done() {
            break;
        }
        n0_future::time::sleep(Duration::from_millis(STATUS_POLL_MS)).await;
        if let Ok(next) = board_command_status(board_id.clone(), request_id.clone()).await {
            receipt = next;
        }
    }
    if receipt.state == "rejected" {
        return Err(receipt.error);
    }
    Ok(receipt)
}
