//! Admin boards page: the boards of the signed-in administrator and the form that creates a
//! board.
//!
//! A board is a long-running investigation that the worker runs as explore turns in board
//! chat sessions. `docs/architecture/Boards.md` describes it.

use common::board_types::{BoardCreateRequest, BoardListItem};
use dioxus::prelude::*;

use crate::api::admin_api::{admin_board_drop, admin_create_board, admin_list_boards, admin_list_collections};
use crate::api::error_util::user_facing_message;
use crate::components::admin_components::{
    AdminGuard, AdminShell, ErrorBar, SuccessBar, BTN_PRIMARY, BTN_SMALL_DANGER, HELP_TEXT, INPUT, LABEL,
    LINK, MODULE, MODULE_CAPTION, TABLE, TD, TH,
};
use crate::components::suspend_boundary::SuspendWrapper;
use crate::pages::admin::llm_reports::format_utc_ms;
use crate::routes::Route;

const TEXTAREA: &str = "border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-body); color: var(--x-ink-strong); background: white; width: 100%; box-sizing: border-box; font-family: inherit;";
const NUM_TD: &str = "text-align: right; white-space: nowrap;";

#[component]
pub fn AdminBoardsPage() -> Element {
    rsx! {
        Title { "Admin: boards" }
        AdminGuard {
            AdminShell {
                title: "Investigation boards".to_string(),
                breadcrumb: String::new(),
                active: "boards".to_string(),
                SuspendWrapper { BoardsListContent {} }
            }
        }
    }
}

#[component]
fn BoardsListContent() -> Element {
    let mut boards_res = use_resource(admin_list_boards);
    let mut error_msg = use_signal(|| None::<String>);
    let mut success_msg = use_signal(|| None::<String>);

    let on_drop = Callback::new(move |board: BoardListItem| {
        spawn(async move {
            error_msg.set(None);
            success_msg.set(None);
            match admin_board_drop(board.board_id.clone()).await {
                Ok(()) => {
                    success_msg.set(Some(format!("The board \u{201c}{}\u{201d} was dropped.", board.title)));
                    boards_res.restart();
                }
                Err(e) => error_msg.set(Some(user_facing_message(&e))),
            }
        });
    });

    rsx! {
        if let Some(msg) = success_msg.read().clone() {
            SuccessBar { message: msg }
        }
        if let Some(err) = error_msg.read().clone() {
            ErrorBar { message: err }
        }
        section { class: "x-admin-module", style: MODULE,
            p { style: HELP_TEXT,
                "A board runs an investigation goal as a sequence of agent explores. Each explore is a chat turn that ends in one board fact. A person accepts or rejects the result."
            }
            match &*boards_res.read() {
                Some(Ok(boards)) => rsx! { BoardsTable { boards: boards.clone(), on_drop } },
                Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
                None => rsx! { p { style: HELP_TEXT, "Loading boards\u{2026}" } },
            }
        }
        CreateBoardPanel {
            on_created: move |board_id: String| {
                navigator().push(Route::AdminBoardPage { board_id, selected: String::new() });
            },
        }
    }
}

#[component]
fn BoardsTable(boards: Vec<BoardListItem>, on_drop: Callback<BoardListItem>) -> Element {
    // The drop asks once. The id of the board that waits for the second click.
    let mut confirming = use_signal(|| None::<String>);
    if boards.is_empty() {
        return rsx! { p { style: HELP_TEXT, "You have no board. Create one below." } };
    }
    rsx! {
        table { style: TABLE,
            thead {
                tr {
                    th { style: TH, "Board" }
                    th { style: TH, "Status" }
                    th { style: "{TH} text-align: right;", "Sourced" }
                    th { style: "{TH} text-align: right;", "Inferred" }
                    th { style: "{TH} text-align: right;", "Not found" }
                    th { style: "{TH} text-align: right;", "Open" }
                    th { style: "{TH} text-align: right;", "Running" }
                    th { style: "{TH} text-align: right;", "Explores" }
                    th { style: TH, "Last event" }
                    th { style: TH, "" }
                }
            }
            tbody {
                for board in boards {
                    tr { key: "{board.board_id}", class: "x-board-row", "data-board-id": "{board.board_id}",
                        td { style: TD,
                            Link {
                                to: Route::AdminBoardPage { board_id: board.board_id.clone(), selected: String::new() },
                                style: LINK,
                                "{board.title}"
                            }
                        }
                        td { style: TD, StatusText { status: board.status.clone() } }
                        td { style: "{TD} {NUM_TD}", "{board.facts_sourced}" }
                        td { style: "{TD} {NUM_TD}", "{board.facts_inferred}" }
                        td { style: "{TD} {NUM_TD}", "{board.facts_not_found}" }
                        td { style: "{TD} {NUM_TD}", "{board.open}" }
                        td { style: "{TD} {NUM_TD}", "{board.running}" }
                        td { style: "{TD} {NUM_TD}", "{board.explores_used} of {board.max_explores}" }
                        td { style: TD, "{format_utc_ms(board.updated_ms)}" }
                        td { style: TD,
                            if confirming.read().as_deref() == Some(board.board_id.as_str()) {
                                button {
                                    style: BTN_SMALL_DANGER,
                                    onclick: {
                                        let board = board.clone();
                                        move |_| {
                                            confirming.set(None);
                                            on_drop.call(board.clone());
                                        }
                                    },
                                    "Confirm drop"
                                }
                            } else {
                                button {
                                    style: BTN_SMALL_DANGER,
                                    onclick: {
                                        let id = board.board_id.clone();
                                        move |_| confirming.set(Some(id.clone()))
                                    },
                                    "Drop"
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The status of a board in words.
#[component]
pub fn StatusText(status: String) -> Element {
    let (label, colour) = match status.as_str() {
        "active" => ("Active", "var(--x-link)"),
        "paused" => ("Paused", "var(--x-ink-muted)"),
        "review" => ("Waits for review", "var(--x-danger)"),
        "completed" => ("Completed", "var(--x-ok)"),
        "dropped" => ("Dropped", "var(--x-ink-muted)"),
        _ => ("Unknown", "var(--x-ink-muted)"),
    };
    rsx! { span { style: "color: {colour}; font-weight: 500;", "{label}" } }
}

#[component]
fn CreateBoardPanel(on_created: Callback<String>) -> Element {
    let collections_res = use_resource(admin_list_collections);
    let mut title = use_signal(String::new);
    let mut goal = use_signal(String::new);
    let mut context = use_signal(String::new);
    let mut hints = use_signal(String::new);
    let mut chosen = use_signal(Vec::<String>::new);
    let mut llm_model = use_signal(String::new);
    let mut max_explores = use_signal(|| "12".to_string());
    let mut step_budget = use_signal(|| "40".to_string());
    let mut error_msg = use_signal(|| None::<String>);
    let mut busy = use_signal(|| false);

    let collection_boxes = match &*collections_res.read() {
        Some(Ok(cols)) => rsx! {
            for c in cols.clone() {
                label { key: "{c.collectionname}", style: LABEL,
                    input {
                        class: "x-board-collection",
                        "data-collection": "{c.collectionname}",
                        r#type: "checkbox",
                        checked: chosen.read().contains(&c.collectionname),
                        onchange: {
                            let name = c.collectionname.clone();
                            move |e: FormEvent| {
                                let mut list = chosen.read().clone();
                                list.retain(|x| *x != name);
                                if e.checked() {
                                    list.push(name.clone());
                                }
                                chosen.set(list);
                            }
                        },
                    }
                    "{c.collectionname}"
                }
            }
        },
        Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
        None => rsx! { span { style: HELP_TEXT, "Loading collections\u{2026}" } },
    };

    rsx! {
        section { class: "x-admin-module", style: MODULE,
            h2 { style: MODULE_CAPTION, "Create a board" }
            if let Some(err) = error_msg.read().clone() {
                ErrorBar { message: err }
            }
            div { style: "display: flex; flex-direction: column; gap: 10px; max-width: 760px;",
                input {
                    class: "x-board-title",
                    style: INPUT, placeholder: "Title",
                    value: "{title}", oninput: move |e| title.set(e.value()),
                }
                textarea {
                    class: "x-board-goal",
                    style: TEXTAREA, rows: "3",
                    placeholder: "Goal: the question the board must answer, with names, dates and places",
                    value: "{goal}", oninput: move |e| goal.set(e.value()),
                }
                textarea {
                    style: TEXTAREA, rows: "2",
                    class: "x-board-context",
                    placeholder: "Context: what is known before the investigation starts (optional)",
                    value: "{context}", oninput: move |e| context.set(e.value()),
                }
                textarea {
                    style: TEXTAREA, rows: "2",
                    class: "x-board-hints",
                    placeholder: "Hints: one per line (optional)",
                    value: "{hints}", oninput: move |e| hints.set(e.value()),
                }
                div { style: "display: flex; gap: 14px; flex-wrap: wrap; align-items: center;",
                    span { style: HELP_TEXT, "Collections" }
                    {collection_boxes}
                }
                div { style: "display: flex; gap: 14px; flex-wrap: wrap; align-items: center;",
                    label { style: LABEL, "Explore model"
                        input {
                            style: INPUT, placeholder: "The chat profile model",
                            value: "{llm_model}", oninput: move |e| llm_model.set(e.value()),
                        }
                    }
                    label { style: LABEL, "Explores"
                        input {
                            style: "{INPUT} width: 64px;", r#type: "number", min: "1", max: "100",
                            value: "{max_explores}", oninput: move |e| max_explores.set(e.value()),
                        }
                    }
                    label { style: LABEL, "Model steps per explore"
                        input {
                            style: "{INPUT} width: 64px;", r#type: "number", min: "8", max: "200",
                            value: "{step_budget}", oninput: move |e| step_budget.set(e.value()),
                        }
                    }
                }
                div {
                    button {
                        class: "x-board-create",
                        style: BTN_PRIMARY,
                        disabled: busy(),
                        onclick: move |_| {
                            let request = BoardCreateRequest {
                                title: title.read().clone(),
                                goal: goal.read().clone(),
                                context: context.read().clone(),
                                collections: chosen.read().clone(),
                                llm_model: llm_model.read().clone(),
                                max_explores: max_explores.read().trim().parse().unwrap_or(12),
                                max_parallel: 1,
                                explore_step_budget: step_budget.read().trim().parse().unwrap_or(40),
                                hints: hints.read().lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect(),
                            };
                            spawn(async move {
                                busy.set(true);
                                error_msg.set(None);
                                match admin_create_board(request).await {
                                    Ok(board_id) => on_created.call(board_id),
                                    Err(e) => error_msg.set(Some(user_facing_message(&e))),
                                }
                                busy.set(false);
                            });
                        },
                        "Create board"
                    }
                }
            }
        }
    }
}
