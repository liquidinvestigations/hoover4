//! `/ai_chat/boards/new`, the form that creates an investigation board. Send opens the new
//! board.
//!
//! The form has no model, explore count or step budget. The worker starts every board at the
//! same budget and grows it with the person's corrections and hints. Every collection that
//! the person can read is selected at first. The collections cannot change after creation,
//! and the internet tools can when the deployment enables them (the board settings popup).

use common::board_types::{BoardCreateRequest, MAX_GOALS};
use dioxus::prelude::*;

use crate::api::board_api::{board_command_status, create_board_command, new_request_id};
use crate::api::error_util::user_facing_message;
use crate::api::storage_api::collections_overview;
use crate::components::admin_components::{ErrorBar, BTN_PRIMARY, BTN_SMALL, HELP_TEXT, INPUT, LABEL, LINK, SUBHEADING};
use crate::routes::Route;

const TEXTAREA: &str = "border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-body); color: var(--x-ink-strong); background: white; width: 100%; box-sizing: border-box; font-family: inherit;";

#[component]
pub fn AiBoardCreatePage() -> Element {
    let collections_res = use_resource(collections_overview);
    let mut title = use_signal(String::new);
    let mut goals = use_signal(|| vec![String::new()]);
    let mut context = use_signal(String::new);
    let mut hints = use_signal(String::new);
    // `None` until the collections arrive. Then every collection is selected.
    let mut chosen = use_signal(|| None::<Vec<String>>);
    let mut internet_tools = use_signal(|| true);
    let internet_tools_enabled = crate::api::chat_api::use_internet_tools_enabled();
    let mut error_msg = use_signal(|| None::<String>);
    let mut busy = use_signal(|| false);

    use_effect(move || {
        if let Some(Ok(list)) = &*collections_res.read() {
            if chosen.peek().is_none() {
                chosen.set(Some(list.iter().map(|c| c.collectionname.clone()).collect()));
            }
        }
    });

    let collection_boxes = match &*collections_res.read() {
        Some(Ok(cols)) => rsx! {
            for c in cols.clone() {
                label { key: "{c.collectionname}", style: LABEL,
                    input {
                        class: "x-board-collection",
                        "data-collection": "{c.collectionname}",
                        r#type: "checkbox",
                        checked: chosen.read().as_ref().is_some_and(|list| list.contains(&c.collectionname)),
                        onchange: {
                            let name = c.collectionname.clone();
                            move |e: FormEvent| {
                                let mut list = chosen.read().clone().unwrap_or_default();
                                list.retain(|x| *x != name);
                                if e.checked() {
                                    list.push(name.clone());
                                }
                                chosen.set(Some(list));
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
    let goal_count = goals.read().len();

    rsx! {
        Title { "Hoover Search - New board" }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; padding: 23px; overflow: auto;",
            div { style: "max-width: 760px; margin: 0 auto;",
                div { style: "display: flex; align-items: center; gap: 15px; margin-bottom: 15px;",
                    Link { to: Route::AiChatPage {}, style: LINK, "\u{2190} AI Chat" }
                    h1 {
                        style: "margin: 0; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong);",
                        "New investigation board"
                    }
                }
                p { style: HELP_TEXT,
                    "A board runs its goals as a sequence of agent explores. Each explore is a chat that ends in one board fact. You review the answer of each goal, and you can reject facts and add hints while it runs."
                }
                if let Some(err) = error_msg.read().clone() {
                    ErrorBar { message: err }
                }
                div { style: "display: flex; flex-direction: column; gap: 10px; background: white; border: 1px solid; border-color: var(--x-border); border-radius: 12px; padding: 16px;",
                    input {
                        class: "x-board-title",
                        style: INPUT, placeholder: "Title",
                        value: "{title}", oninput: move |e| title.set(e.value()),
                    }
                    div { style: SUBHEADING, if goal_count == 1 { "Goal" } else { "Goals" } }
                    for index in 0..goal_count {
                        div { key: "{index}", style: "display: flex; gap: 6px; align-items: flex-start;",
                            textarea {
                                class: "x-board-goal",
                                style: TEXTAREA, rows: "3",
                                placeholder: "The question the board must answer, with names, dates and places",
                                value: "{goals.read()[index]}",
                                oninput: move |e| { goals.write()[index] = e.value(); },
                            }
                            if goal_count > 1 {
                                button {
                                    style: BTN_SMALL,
                                    title: "Remove this goal",
                                    onclick: move |_| { goals.write().remove(index); },
                                    "Remove"
                                }
                            }
                        }
                    }
                    if goal_count < MAX_GOALS {
                        div {
                            button {
                                class: "x-board-add-goal",
                                style: BTN_SMALL,
                                onclick: move |_| goals.write().push(String::new()),
                                "Add a goal"
                            }
                        }
                    }
                    p { style: HELP_TEXT, "Each goal gets its own answer. The board completes when you accept the answers of all goals." }
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
                    div { style: SUBHEADING, "Collections" }
                    div { style: "display: flex; gap: 14px; flex-wrap: wrap; align-items: center;",
                        {collection_boxes}
                    }
                    p { style: HELP_TEXT, "The collections cannot change after the board is created." }
                    if internet_tools_enabled {
                        label { style: LABEL,
                            input {
                                class: "x-board-internet-tools",
                                r#type: "checkbox",
                                checked: internet_tools(),
                                onchange: move |e: FormEvent| internet_tools.set(e.checked()),
                            }
                            "Internet tools: the explores can search the web and read web pages. You can change this later in the board settings."
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
                                    goals: goals.read().iter().map(|g| g.trim().to_string()).filter(|g| !g.is_empty()).collect(),
                                    context: context.read().clone(),
                                    collections: chosen.read().clone().unwrap_or_default(),
                                    internet_tools: internet_tools_enabled && internet_tools(),
                                    hints: hints.read().lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect(),
                                };
                                spawn(async move {
                                    busy.set(true);
                                    error_msg.set(None);
                                    match create_and_wait(request).await {
                                        Ok(board_id) => {
                                            navigator().push(Route::ai_board(board_id, String::new()));
                                        }
                                        Err(message) => error_msg.set(Some(message)),
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
}

/// Create a board and wait until its command writer writes its goals, so the board page opens
/// on a board with goals. A lost response sends the same request id again, which names the
/// same board. After the wait the page opens the board as it is.
async fn create_and_wait(request: BoardCreateRequest) -> Result<String, String> {
    let request_id = new_request_id();
    let mut created = Err(String::new());
    for _ in 0..3 {
        created = create_board_command(request_id.clone(), request.clone()).await.map_err(|e| user_facing_message(&e));
        if created.is_ok() {
            break;
        }
    }
    let board_id = created?;
    for _ in 0..60 {
        match board_command_status(board_id.clone(), request_id.clone()).await {
            Ok(receipt) if receipt.state == "rejected" => return Err(receipt.error),
            Ok(receipt) if receipt.is_done() => break,
            _ => n0_future::time::sleep(std::time::Duration::from_millis(1000)).await,
        }
    }
    Ok(board_id)
}
