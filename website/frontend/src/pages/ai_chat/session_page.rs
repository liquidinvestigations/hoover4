//! `/ai_chat/c/:session_id/...` — conversation transcript + document preview (60/40).

use common::chat_types::{rate_limited_seconds, ChatMessageItem, ChatOptions};
use common::search_query::SearchQuery;
use common::search_result::{DocumentIdentifier, SearchResultDocuments, SearchResultHitCount};
use dioxus::prelude::*;

use crate::api::admin_api::{chat_list_models, chat_llm_configured};
use crate::api::auth_api::whoami;
use crate::api::chat_api::{
    chat_get_session, chat_poll, chat_send_message, chat_start_research, chat_stop,
    chat_dismiss_interrupted,
};
use crate::components::chat_components::{
    ChatComposer, ChatTranscript, ConversationFindBar, LockedOptionsBar, ModelSelector,
};
use crate::components::document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot;
use crate::components::search_components::search_panel_left_view::SearchResultsState;
use crate::components::suspend_boundary::SuspendWrapper;
use crate::data_definitions::doc_viewer_state::{DocViewerState, DocViewerStateControl};
use crate::data_definitions::url_param::UrlParam;
use crate::routes::Route;

/// What of an in-flight turn is still worth rendering.
///
/// While the turn is live, everything. Once it reads as interrupted, only a partial the
/// model actually produced — an empty stream turn renders as "The assistant is
/// working…", which is the one thing an interrupted turn must not claim.
fn keep_stream(
    stream: Option<common::chat_types::StreamTurn>,
    interrupted: bool,
) -> Option<common::chat_types::StreamTurn> {
    match stream {
        Some(turn) if !interrupted || !turn.content.trim().is_empty() => Some(turn),
        _ => None,
    }
}

#[component]
pub fn AiChatSessionPage(
    session_id: String,
    selected_result_hash: UrlParam<Option<DocumentIdentifier>>,
    doc_viewer_state: UrlParam<Option<DocViewerState>>,
) -> Element {
    rsx! {
        Title { "Hoover Search - AI Chat" }
        AiChatSessionRoot {
            session_id,
            selected_result_hash: selected_result_hash.0.clone(),
            doc_viewer_state: doc_viewer_state.0.clone(),
        }
    }
}

#[component]
fn AiChatSessionRoot(
    session_id: ReadSignal<String>,
    selected_result_hash: ReadSignal<Option<DocumentIdentifier>>,
    doc_viewer_state: ReadSignal<Option<DocViewerState>>,
) -> Element {
    // NOTE: nothing below may capture a `String` copy of the session id.
    //
    // The router **reuses this component** when it navigates between two chat URLs — the
    // props change, the component does not remount. Every handler here used to close over
    // a `String` cloned on first render, so after a back/forward between two
    // conversations the page fetched, polled, sent, stopped and dismissed against the
    // conversation the user had *left*: the resource never refetched, and session A's
    // poll loop kept writing its stream into signals now rendering session B. Read the
    // signal at the point of use instead; `use_resource` also subscribes to it, which is
    // what makes the refetch happen at all.

    use_context_provider(move || DocViewerStateControl {
        doc_viewer_state: doc_viewer_state.into(),
        set_doc_viewer_state: Callback::new(move |state: DocViewerState| {
            navigator().push(Route::ai_chat_session(
                session_id.read().clone(),
                selected_result_hash.read().clone(),
                Some(state),
            ));
        }),
    });

    // Reuse SearchResultItemCard by providing the selection fields it reads from context.
    let hit_count = use_signal(|| None::<Result<SearchResultHitCount, ServerFnError>>);
    let search_result = use_signal(|| None::<Result<SearchResultDocuments, ServerFnError>>);
    let current_page = use_signal(|| 0_u64);
    let set_selected = Callback::new(move |id: Option<DocumentIdentifier>| {
        navigator().push(Route::ai_chat_session(
            session_id.read().clone(),
            id,
            doc_viewer_state.read().clone(),
        ));
    });
    use_context_provider(move || SearchResultsState {
        hit_count: hit_count.into(),
        search_result: search_result.into(),
        current_search_result_page: current_page.into(),
        set_current_page: Callback::new(|_| {}),
        selected_result_hash: selected_result_hash.into(),
        set_selected_result_hash: set_selected,
        set_selected_result_hash_and_page: Callback::new({
            let set_selected = set_selected;
            move |(id, _page): (Option<DocumentIdentifier>, u64)| {
                set_selected.call(id);
            }
        }),
    });

    let detail_res = use_resource(move || chat_get_session(session_id.read().clone()));

    let mut draft = use_signal(String::new);
    let mut options = use_signal(ChatOptions::default);
    let mut selected_model = use_signal(String::new);
    let mut sending = use_signal(|| false);
    let mut error = use_signal(|| None::<String>);
    let mut retry_after = use_signal(|| None::<u64>);
    let mut messages = use_signal(Vec::<ChatMessageItem>::new);
    let mut stream_turn = use_signal(|| None::<common::chat_types::StreamTurn>);
    let mut interrupted = use_signal(|| false);
    let mut loaded_for = use_signal(String::new);
    let mut find_query = use_signal(String::new);
    let mut match_index = use_signal(|| 0_usize);
    let mut match_count = use_signal(|| 0_usize);
    // Incremented to retire a running poll loop (a second send, leaving the page).
    let mut poll_gen = use_signal(|| 0_u64);

    let models_res = use_resource(chat_list_models);
    let configured_res = use_resource(chat_llm_configured);
    let whoami_res = use_resource(whoami);
    let configured = configured_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .copied()
        .unwrap_or(true);
    // `None` while `whoami` is in flight, not `false`: defaulting to "not a guest" drew
    // the model picker for a moment on every guest's first paint and then removed it.
    let is_guest = whoami_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .map(|u| u.is_guest);
    let choices = models_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned()
        .unwrap_or_default();
    let show_models = is_guest == Some(false) && !choices.is_empty();
    // In an effect, not in the render body — a signal written during render schedules a
    // render from inside one. It also has to re-run per conversation: the switch below
    // clears `selected_model`, and this is what re-seeds it.
    use_effect(move || {
        let choices = models_res
            .read()
            .as_ref()
            .and_then(|r| r.as_ref().ok())
            .cloned()
            .unwrap_or_default();
        // Read, not peeked: this effect must re-run when the value is *cleared*, which
        // is how a conversation switch asks for a fresh default. The write below then
        // re-runs it once more and it returns immediately.
        if !selected_model.read().is_empty() {
            return;
        }
        if let Some(def) = choices.iter().find(|c| c.is_default) {
            selected_model.set(def.model_id.clone());
        } else if let Some(first) = choices.first() {
            selected_model.set(first.model_id.clone());
        }
    });

    // Filtered on the session on screen: while the resource refetches it still holds the
    // *previous* conversation's detail, and using that would re-seed the transcript the
    // switch below just cleared and put the old conversation's title in the header.
    let detail = detail_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .filter(|d| d.session.session_id == *session_id.read())
        .cloned();

    if let Some(ref d) = detail {
        if *loaded_for.read() != d.session.session_id {
            messages.set(d.messages.clone());
            // Seed from the session, not from Default: on a conversation that has
            // already frozen its switches these are the values in force, and showing
            // the composer defaults instead is what made a chat started with internet
            // tools quietly continue without them.
            options.set(d.session.options);
            interrupted.set(d.interrupted);
            loaded_for.set(d.session.session_id.clone());
            // A refresh mid-answer picks the turn up exactly where a poller left it.
            if d.active && !d.interrupted {
                stream_turn.set(d.stream.clone());
                sending.set(true);
            } else if d.interrupted {
                stream_turn.set(keep_stream(d.stream.clone(), true));
            }
        }
    }

    // Long-poll the turn to completion. One loop per generation; sending flips false
    // only here, when the turn has actually ended (or read as interrupted).
    // A Callback rather than a plain closure so the submit handler can call it without
    // moving it.
    let start_polling: Callback<()> = Callback::new(move |_: ()| {
        *poll_gen.write() += 1;
        let generation = *poll_gen.read();
        // Bound to the conversation on screen *when polling starts*. A later switch bumps
        // `poll_gen`, which retires this loop on its next iteration.
        let poll_sid = session_id.read().clone();
        spawn(async move {
            let mut sig = String::new();
            let mut failures = 0_u32;
            loop {
                if *poll_gen.read() != generation {
                    return;
                }
                let after_seq = messages.read().last().map(|m| m.seq);
                match chat_poll(poll_sid.clone(), after_seq, sig.clone()).await {
                    Ok(result) => {
                        failures = 0;
                        sig = result.sig;
                        if !result.messages.is_empty() {
                            let mut current = messages.read().clone();
                            current.extend(result.messages);
                            messages.set(current);
                        }
                        interrupted.set(result.interrupted);
                        // An interrupted turn keeps whatever partial text it produced —
                        // under the banner, which is its marker — but never the
                        // "working…" placeholder: the banner already says it stopped,
                        // and a spinner beside it says the opposite.
                        stream_turn.set(keep_stream(result.stream, result.interrupted));
                        // `active`, not the presence of a stream row, decides whether to
                        // keep going: a turn is registered before the agent is called and
                        // its first stream row only lands with the first event, so
                        // stopping on an absent stream would abandon every turn during
                        // the model's first few seconds.
                        if result.interrupted || !result.active {
                            sending.set(false);
                            return;
                        }
                    }
                    Err(e) => {
                        // A rate limit is not lost contact — it is the server answering,
                        // promptly, to say "slower". Counting it toward `failures` made
                        // three tabs on one conversation declare the chat lost while the
                        // turn was still running. Wait exactly as long as it asked and
                        // carry on; `failures` is untouched, because nothing failed.
                        if let Some(secs) = rate_limited_seconds(&e.to_string()) {
                            n0_future::time::sleep(std::time::Duration::from_secs(
                                secs.clamp(1, 30),
                            ))
                            .await;
                            continue;
                        }
                        failures += 1;
                        if failures >= 3 {
                            error.set(Some(format!("lost contact with the chat: {e}")));
                            sending.set(false);
                            return;
                        }
                        // `n0_future::time::sleep` rather than `gloo_timers`: this file
                        // is compiled into the server-side render build too, where
                        // gloo's futures module does not exist.
                        n0_future::time::sleep(std::time::Duration::from_secs(2)).await;
                    }
                }
            }
        });
    });

    // Resume polling after a refresh that found a turn in flight.
    let mut poll_resumed = use_signal(|| false);
    if *sending.read() && !*poll_resumed.read() && !loaded_for.read().is_empty() {
        poll_resumed.set(true);
        start_polling.call(());
    }

    // Switching conversations without remounting: retire the previous conversation's poll
    // loop and drop every signal that describes *a* conversation rather than the page.
    // Without this, session A's transcript, draft, error, banner and model choice all
    // survived into session B, and its poll loop went on appending A's stream rows to B's
    // message list. An effect rather than render-time work: it must run once per switch,
    // after the render that observed it.
    let mut wired_for = use_signal(String::new);
    use_effect(move || {
        let id = session_id.read().clone();
        if *wired_for.peek() == id {
            return;
        }
        wired_for.set(id);
        *poll_gen.write() += 1;
        loaded_for.set(String::new());
        messages.set(Vec::new());
        stream_turn.set(None);
        sending.set(false);
        interrupted.set(false);
        poll_resumed.set(false);
        draft.set(String::new());
        error.set(None);
        retry_after.set(None);
        // Cleared rather than kept: it re-seeds from the model list on the next render,
        // and the model in force is a property of the conversation being read.
        selected_model.set(String::new());
        find_query.set(String::new());
        match_index.set(0);
        match_count.set(0);
    });

    let preview_query = use_memo(move || {
        // Prefer the most recent search_collections query for in-document highlighting.
        for m in messages.read().iter().rev() {
            if m.tool_name == "search_collections" {
                if let Ok(v) = serde_json::from_str::<serde_json::Value>(&m.tool_input) {
                    if let Some(q) = v.get("query").and_then(|x| x.as_str()) {
                        return SearchQuery {
                            query_string: q.to_string(),
                            ..Default::default()
                        };
                    }
                }
            }
        }
        SearchQuery::default()
    });

    let on_submit = move |_| {
        let text = draft.read().trim().to_string();
        if text.is_empty() || *sending.read() {
            return;
        }
        let opts = *options.read();
        let model = selected_model.read().clone();
        let id = session_id.read().clone();
        draft.set(String::new());
        sending.set(true);
        error.set(None);
        retry_after.set(None);
        interrupted.set(false);
        stream_turn.set(None);
        spawn(async move {
            if opts.deep_research {
                match chat_start_research(id.clone(), text, opts).await {
                    Ok(_) => {
                        // The Temporal task streams into the same table the poll loop
                        // reads, so a research turn renders live like an inline one.
                        let mut o = *options.peek();
                        o.locked = true;
                        options.set(o);
                        start_polling.call(());
                    }
                    Err(e) => {
                        let msg = e.to_string();
                        // Searched for, not stripped: ServerFnError wraps the message.
                        if let Some(secs) = rate_limited_seconds(&msg) {
                            retry_after.set(Some(secs));
                        } else {
                            error.set(Some(msg));
                        }
                        sending.set(false);
                    }
                }
            } else {
                let model_id = if model.is_empty() { None } else { Some(model) };
                match chat_send_message(id, text, opts, model_id).await {
                    Ok(result) => {
                        if let Some(secs) = result.retry_after_seconds {
                            retry_after.set(Some(secs));
                            sending.set(false);
                        } else {
                            // The turn runs server-side; the poll loop follows it and
                            // clears `sending` when it ends.
                            messages.set(result.messages);
                            let mut o = *options.peek();
                            o.locked = true;
                            options.set(o);
                            start_polling.call(());
                        }
                    }
                    Err(e) => {
                        error.set(Some(e.to_string()));
                        sending.set(false);
                    }
                }
            }
        });
    };

    let on_stop = move |_| {
        let id = session_id.read().clone();
        spawn(async move {
            // The turn finalises its partial with a marker; the poll loop sees the
            // finished row and clears `sending`.
            //
            // A failure here was swallowed, so a stop that did not happen was
            // indistinguishable from one that did: the button reacted, the answer kept
            // arriving, and there was nothing to read. `Ok(false)` is not a failure — it
            // means the turn had already finished, which is the outcome the user wanted.
            if let Err(e) = chat_stop(id).await {
                error.set(Some(format!(
                    "could not stop the answer: {e} \u{2014} it is still running"
                )));
            }
        });
    };

    let on_dismiss_interrupted = move |_| {
        let id = session_id.read().clone();
        spawn(async move {
            if chat_dismiss_interrupted(id).await.is_ok() {
                interrupted.set(false);
                stream_turn.set(None);
            }
        });
    };

    let load_error = detail_res.read().as_ref().is_some_and(|r| r.is_err());
    let Some(detail) = detail else {
        return rsx! {
            div {
                style: "padding: 24px; color: #64748B;",
                if load_error { "This conversation could not be loaded." } else { "Loading\u{2026}" }
            }
        };
    };

    rsx! {
        div {
            style: "height: 100%; width: 100%; display: flex; flex-direction: row; \
                    background: #F5F6F8; overflow: hidden;",
            // Left — transcript (≈60%)
            div {
                style: "height: 100%; width: 60%; min-width: 360px; display: flex; \
                        flex-direction: column; background: #ECEEF2; border-right: 1px solid #D1D5DB;",
                div {
                    style: "padding: 10px 14px; display: flex; align-items: center; gap: 12px; \
                            background: white; border-bottom: 1px solid #E5E7EB; flex-shrink: 0;",
                    Link {
                        to: Route::AiChatPage {},
                        style: "color: #4F46E5; text-decoration: none; font-size: 13px; \
                                white-space: nowrap;",
                        "\u{2190} Chats"
                    }
                    Link {
                        to: Route::AiChatHistoryPage {},
                        style: "color: #64748B; text-decoration: none; font-size: 13px; \
                                white-space: nowrap;",
                        "History"
                    }
                    // The conversation's own name, so a chat opened from the history
                    // list still says which one it is once you have scrolled away from
                    // the first message.
                    div {
                        style: "flex: 1; min-width: 0; font-size: 14px; font-weight: 600; \
                                color: #0F172A; overflow: hidden; text-overflow: ellipsis; \
                                white-space: nowrap;",
                        title: "{detail.session.title}",
                        "{detail.session.title}"
                    }
                }
                // The frozen switches live here once the conversation has started —
                // out of the composer, where they would look editable.
                if options.read().locked {
                    LockedOptionsBar { options: *options.read() }
                }
                ConversationFindBar {
                    query: find_query,
                    match_index,
                    match_count,
                }
                ChatTranscript {
                    messages: messages.read().clone(),
                    find_query,
                    match_index,
                    match_count,
                    stream: stream_turn.read().clone(),
                    stream_live: !*interrupted.read(),
                }
                if *interrupted.read() {
                    div {
                        style: "margin: 0 18px 8px; padding: 8px 12px; background: #FEF3C7; \
                                border: 1px solid #FDE68A; border-radius: 8px; font-size: 13px; \
                                color: #92400E; display: flex; align-items: center; gap: 10px;",
                        span { style: "flex: 1;",
                            "This answer was interrupted before it finished — the page or the \
                             server stopped mid-turn. Ask again to retry."
                        }
                        button {
                            style: "background: none; border: 1px solid #D97706; border-radius: 6px; \
                                    color: #92400E; cursor: pointer; font-size: 12px; padding: 2px 8px;",
                            onclick: on_dismiss_interrupted,
                            "Dismiss"
                        }
                    }
                }
                if *sending.read() && stream_turn.read().is_none() {
                    div {
                        style: "padding: 0 18px 8px; color: #64748B; font-size: 13px; font-style: italic;",
                        "The assistant is searching your collections\u{2026}"
                    }
                }
                if let Some(e) = error.read().clone() {
                    div { style: "padding: 0 18px 8px; color: #B91C1C; font-size: 13px;", "{e}" }
                }
                div { style: "padding: 12px 14px; flex-shrink: 0;",
                    if !configured {
                        div {
                            style: "background: #FEF3C7; border: 1px solid #F59E0B; border-radius: 12px; \
                                    padding: 14px 16px; color: #92400E; font-size: 14px; line-height: 1.5;",
                            "No LLM provider is configured. An administrator can add one under "
                            Link {
                                to: Route::AdminLlmPage {},
                                style: "color: #92400E; font-weight: 600;",
                                "/admin/llm"
                            }
                            "."
                        }
                    } else {
                        if show_models {
                            div { style: "margin-bottom: 8px;",
                                ModelSelector {
                                    choices: choices.clone(),
                                    selected: selected_model,
                                    disabled: *sending.read(),
                                }
                            }
                        }
                        ChatComposer {
                            draft,
                            options,
                            sending,
                            retry_after_seconds: retry_after,
                            on_submit,
                            on_stop,
                        }
                    }
                }
            }
            // Right — document pane (≈40%)
            div {
                style: "height: 100%; width: 40%; min-width: 300px;",
                SuspendWrapper {
                    DocumentPreviewForSearchRoot {
                        query: preview_query,
                        selected_result_hash,
                        show_finder: true,
                    }
                }
            }
        }
    }
}
