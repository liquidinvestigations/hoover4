//! Investigation board server function wrappers. Every user can own boards, and the backend
//! lets only the owner read or act on one (`backend::api::boards`).

use common::board_types::{BoardAssessment, BoardCreateRequest, BoardListItem, BoardSnapshot};
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
board_server_fn!(create_board, (request: BoardCreateRequest) -> String);
board_server_fn!(board_snapshot, (board_id: String) -> BoardSnapshot);
board_server_fn!(board_add_hint, (board_id: String, text: String));
board_server_fn!(board_reject_fact, (board_id: String, fact_id: String, reason: String));
board_server_fn!(board_set_paused, (board_id: String, paused: bool));
board_server_fn!(board_set_internet_tools, (board_id: String, on: bool));
board_server_fn!(board_review, (board_id: String, accept: bool, correction: String));
board_server_fn!(board_drop, (board_id: String));
board_server_fn!(board_add_goal, (board_id: String, text: String));
board_server_fn!(board_explore_question, (board_id: String, fact_id: String, index: u32));
board_server_fn!(board_answer, (board_id: String, goal: String, reason_no: u32, accept: bool, correction: String));
board_server_fn!(board_assessment, (board_id: String, reason_no: u32) -> BoardAssessment);
