//! `/ai_chat/boards/new`, the form that creates an investigation board. Send opens the new
//! board.
//!
//! The form has no model, explore count or step budget. The worker starts every board at the
//! same budget and grows it with the person's corrections and hints. Every collection that
//! the person can read is selected at first. The Sources group has a Collections checkbox
//! that selects or clears every collection. A board needs a collection or the internet tools,
//! so Create board stays disabled while the group shows the source error. The collections
//! cannot change after creation, and the internet tools can when the deployment enables them
//! (the board settings popup).

use common::board_types::{BoardCreateRequest, MAX_GOALS};
use dioxus::prelude::*;
use dioxus_free_icons::{icons::md_navigation_icons::MdArrowBack, Icon};

use crate::api::board_api::{board_command_status, create_board_command, new_request_id};
use crate::api::error_util::user_facing_message;
use crate::api::storage_api::collections_overview;
use crate::components::admin_components::{ErrorBar, BTN_PRIMARY, BTN_SMALL, HELP_TEXT, INPUT, LABEL, LINK, SUBHEADING};
use crate::routes::Route;
use crate::tr;

const TEXTAREA: &str = "border: 1px solid; border-color: var(--x-border-strong); border-radius: 6px; padding: 6px 8px; font-size: var(--x-text-body); color: var(--x-ink-strong); background: white; width: 100%; box-sizing: border-box; font-family: inherit;";
/// The visible label of a field, above the field.
const FIELD_LABEL: &str = "display: flex; flex-direction: column; gap: 4px; font-size: var(--x-text-body); font-weight: 600; color: var(--x-ink-strong);";
const SOURCE_ERROR: &str = "margin: 0; color: var(--x-danger); font-size: var(--x-text-detail);";

/// The state of the Collections checkbox, from the selected and the listed collections.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Master {
    All,
    Some,
    None,
}

/// `All` when every listed collection is selected, `Some` when some are, `None` when none are.
pub fn master_state(listed: &[String], chosen: &[String]) -> Master {
    let selected = listed.iter().filter(|c| chosen.contains(c)).count();
    if selected == 0 {
        Master::None
    } else if selected == listed.len() {
        Master::All
    } else {
        Master::Some
    }
}

/// The selection after a click on the Collections checkbox: a click on a checked box clears
/// every collection, and a click on a clear or indeterminate box selects every collection.
pub fn master_click(listed: &[String], chosen: &[String]) -> Vec<String> {
    match master_state(listed, chosen) {
        Master::All => Vec::new(),
        Master::Some | Master::None => listed.to_vec(),
    }
}

/// The source error of the form, or `None` while a source is selected.
pub fn source_error(collections: usize, internet_tools: bool, internet_tools_enabled: bool) -> Option<String> {
    if collections > 0 || (internet_tools_enabled && internet_tools) {
        None
    } else if internet_tools_enabled {
        Some(tr!("chat-board-create-select-a-collection-or-turn"))
    } else {
        Some(tr!("chat-board-create-select-at-least-one-collection"))
    }
}

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

    let listed: Vec<String> = match &*collections_res.read() {
        Some(Ok(cols)) => cols.iter().map(|c| c.collectionname.clone()).collect(),
        _ => Vec::new(),
    };

    use_effect(move || {
        if let Some(Ok(list)) = &*collections_res.read() {
            if chosen.peek().is_none() {
                chosen.set(Some(list.iter().map(|c| c.collectionname.clone()).collect()));
            }
        }
    });

    // HTML has no `indeterminate` attribute, so the property is set after each render.
    let master = master_state(&listed, chosen.read().as_deref().unwrap_or_default());
    use_effect(use_reactive!(|master| {
        document::eval(&format!( // i18n: data, JavaScript
            "const box = document.querySelector('.x-board-collections-all'); if (box) box.indeterminate = {};",
            master == Master::Some
        ));
    }));

    let collection_boxes = match &*collections_res.read() {
        Some(Ok(cols)) => rsx! {
            label { style: LABEL,
                input {
                    class: "x-board-collections-all",
                    r#type: "checkbox",
                    checked: master == Master::All,
                    disabled: cols.is_empty(),
                    onchange: {
                        let listed = listed.clone();
                        move |_: FormEvent| {
                            let current = chosen.read().clone().unwrap_or_default();
                            chosen.set(Some(master_click(&listed, &current)));
                        }
                    },
                }
                {tr!("chat-board-create-collections")}
            }
            div { style: "display: flex; gap: 14px; flex-wrap: wrap; align-items: center; padding-left: 22px;",
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
            }
        },
        Some(Err(e)) => rsx! { ErrorBar { message: user_facing_message(e) } },
        None => rsx! { span { style: HELP_TEXT, {tr!("chat-board-create-loading-collections-u")} } },
    };
    let goal_count = goals.read().len();
    // No error while the collections load, because every collection is selected when they arrive.
    let missing_source = chosen.read().as_ref().and_then(|list| {
        source_error(list.len(), internet_tools(), internet_tools_enabled)
    });

    rsx! {
        Title { {tr!("chat-board-create-hoover-search-new-board")} }
        div {
            style: "width: 100%; height: 100%; background: #F5F6F8; box-sizing: border-box; padding: 23px; overflow: auto;",
            div { style: "max-width: 760px; margin: 0 auto;",
                div { style: "display: flex; align-items: center; gap: 15px; margin-bottom: 15px;",
                    Link { to: Route::AiChatPage {}, style: "{LINK} display: inline-flex; align-items: center; gap: 4px;",
                        Icon { icon: MdArrowBack, width: 16, height: 16 }
                        {tr!("chat-board-create-ai-chat")}
                    }
                    h1 {
                        style: "margin: 0; font-size: var(--x-text-page); line-height: var(--x-line-page); font-weight: 600; color: var(--x-ink-strong);",
                        {tr!("chat-board-create-new-investigation-board")}
                    }
                }
                p { style: HELP_TEXT,
                    {tr!("chat-board-create-a-board-runs-its-goals")}
                }
                if let Some(err) = error_msg.read().clone() {
                    ErrorBar { message: err }
                }
                div { style: "display: flex; flex-direction: column; gap: 10px; background: white; border: 1px solid; border-color: var(--x-border); border-radius: 12px; padding: 16px;",
                    label { style: FIELD_LABEL,
                        {tr!("chat-board-create-title")}
                        input {
                            class: "x-board-title",
                            style: "{INPUT} font-weight: 400;",
                            value: "{title}", oninput: move |e| title.set(e.value()),
                        }
                    }
                    for index in 0..goal_count {
                        label { key: "{index}", style: FIELD_LABEL,
                            if goal_count == 1 { {tr!("chat-board-create-goal")} } else { {tr!("chat-board-create-goal-2", index_1: (index + 1).to_string())} }
                            div { style: "display: flex; gap: 6px; align-items: flex-start; font-weight: 400;",
                                textarea {
                                    class: "x-board-goal",
                                    style: TEXTAREA, rows: "3",
                                    value: "{goals.read()[index]}",
                                    oninput: move |e| { goals.write()[index] = e.value(); },
                                }
                                if goal_count > 1 {
                                    button {
                                        style: BTN_SMALL,
                                        title: tr!("chat-board-create-remove-this-goal"),
                                        onclick: move |_| { goals.write().remove(index); },
                                        {tr!("chat-board-create-remove")}
                                    }
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
                                {tr!("chat-board-create-add-a-goal")}
                            }
                        }
                    }
                    label { style: FIELD_LABEL,
                        {tr!("chat-board-create-context-optional")}
                        textarea {
                            style: "{TEXTAREA} font-weight: 400;", rows: "2",
                            class: "x-board-context",
                            value: "{context}", oninput: move |e| context.set(e.value()),
                        }
                    }
                    label { style: FIELD_LABEL,
                        {tr!("chat-board-create-hints-one-per-line-optional")}
                        textarea {
                            style: "{TEXTAREA} font-weight: 400;", rows: "2",
                            class: "x-board-hints",
                            value: "{hints}", oninput: move |e| hints.set(e.value()),
                        }
                    }
                    div { class: "x-board-sources", style: "display: flex; flex-direction: column; gap: 8px;",
                        div { style: SUBHEADING, {tr!("chat-board-create-sources")} }
                        {collection_boxes}
                        if internet_tools_enabled {
                            label { style: LABEL,
                                input {
                                    class: "x-board-internet-tools",
                                    r#type: "checkbox",
                                    checked: internet_tools(),
                                    onchange: move |e: FormEvent| internet_tools.set(e.checked()),
                                }
                                {tr!("chat-board-create-internet-tools")}
                            }
                        }
                        if let Some(text) = missing_source.clone() {
                            p { class: "x-board-source-error", style: SOURCE_ERROR, "{text}" }
                        }
                    }
                    div {
                        button {
                            class: "x-board-create",
                            style: BTN_PRIMARY,
                            disabled: busy() || chosen.read().is_none() || missing_source.is_some(),
                            onclick: move |_| {
                                if *busy.peek() || chosen.peek().is_none() { return; }
                                busy.set(true);
                                let request = BoardCreateRequest {
                                    title: title.read().clone(),
                                    goals: goals.read().iter().map(|g| g.trim().to_string()).filter(|g| !g.is_empty()).collect(),
                                    context: context.read().clone(),
                                    collections: chosen.read().clone().unwrap_or_default(),
                                    internet_tools: internet_tools_enabled && internet_tools(),
                                    hints: hints.read().lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect(),
                                };
                                spawn(async move {
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
                            if busy() { {tr!("chat-board-create-creating-board")} } else { {tr!("chat-board-create-create-board")} }
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

#[cfg(test)]
mod tests {
    use super::*;

    fn names(list: &[&str]) -> Vec<String> {
        list.iter().map(|s| s.to_string()).collect()
    }

    #[test]
    fn the_collections_checkbox_follows_the_selection_and_one_click_clears_or_selects_all() {
        let listed = names(&["enron", "epstein", "tables"]);
        assert_eq!(master_state(&listed, &listed), Master::All);
        assert_eq!(master_state(&listed, &names(&["tables"])), Master::Some);
        assert_eq!(master_state(&listed, &[]), Master::None);
        assert_eq!(master_click(&listed, &listed), Vec::<String>::new());
        assert_eq!(master_click(&listed, &names(&["tables"])), listed);
        assert_eq!(master_click(&listed, &[]), listed);
    }

    #[test]
    fn the_source_error_shows_only_without_a_source() {
        assert_eq!(source_error(0, true, true), None);
        assert_eq!(source_error(2, false, false), None);
        assert_eq!(source_error(0, false, true).as_deref(), Some("Select a collection or turn on internet tools."));
        assert_eq!(source_error(0, true, false).as_deref(), Some("Select at least one collection."));
    }
}
