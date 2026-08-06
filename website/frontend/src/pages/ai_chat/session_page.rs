//! `/ai_chat/c/:session_id/...` — conversation transcript + document preview (60/40).

use common::chat_types::{ChatMessageItem, ChatOptions};
use common::search_query::SearchQuery;
use common::search_result::{DocumentIdentifier, SearchResultDocuments, SearchResultHitCount};
use dioxus::prelude::*;

use crate::api::chat_api::{
    chat_get_session, chat_send_message, chat_start_research,
};
use crate::components::chat_components::{
    ChatComposer, ChatTranscript, ConversationFindBar, LockedOptionsBar,
};
use crate::components::document_view_components::doc_preview_for_search::DocumentPreviewForSearchRoot;
use crate::components::search_components::search_panel_left_view::SearchResultsState;
use crate::components::suspend_boundary::SuspendWrapper;
use crate::data_definitions::doc_viewer_state::{DocViewerState, DocViewerStateControl};
use crate::data_definitions::url_param::UrlParam;
use crate::routes::Route;

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
    let sid = session_id.read().clone();

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

    let load_id = sid.clone();
    let detail_res = use_resource(move || chat_get_session(load_id.clone()));

    let mut draft = use_signal(String::new);
    let mut options = use_signal(ChatOptions::default);
    let mut sending = use_signal(|| false);
    let mut error = use_signal(|| None::<String>);
    let mut retry_after = use_signal(|| None::<u64>);
    let mut messages = use_signal(Vec::<ChatMessageItem>::new);
    let mut loaded_for = use_signal(String::new);
    let mut find_query = use_signal(String::new);
    let mut match_index = use_signal(|| 0_usize);
    let mut match_count = use_signal(|| 0_usize);

    let detail = detail_res
        .read()
        .as_ref()
        .and_then(|r| r.as_ref().ok())
        .cloned();

    if let Some(ref d) = detail {
        if *loaded_for.read() != d.session.session_id {
            messages.set(d.messages.clone());
            // Seed from the session, not from Default: on a conversation that has
            // already frozen its switches these are the values in force, and showing
            // the composer defaults instead is what made a chat started with internet
            // tools quietly continue without them.
            options.set(d.session.options);
            loaded_for.set(d.session.session_id.clone());
        }
    }

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

    let send_id = sid.clone();
    let on_submit = move |_| {
        let text = draft.read().trim().to_string();
        if text.is_empty() || *sending.read() {
            return;
        }
        let opts = *options.read();
        let id = send_id.clone();
        draft.set(String::new());
        sending.set(true);
        error.set(None);
        retry_after.set(None);
        spawn(async move {
            if opts.deep_research {
                match chat_start_research(id.clone(), text, opts).await {
                    Ok(_) => match chat_get_session(id).await {
                        Ok(d) => messages.set(d.messages),
                        Err(e) => error.set(Some(e.to_string())),
                    },
                    Err(e) => {
                        let msg = e.to_string();
                        if let Some(secs) = msg.strip_prefix("rate_limited:").and_then(|s| s.parse().ok())
                        {
                            retry_after.set(Some(secs));
                        } else {
                            error.set(Some(msg));
                        }
                    }
                }
            } else {
                match chat_send_message(id, text, opts).await {
                    Ok(result) => {
                        if let Some(secs) = result.retry_after_seconds {
                            retry_after.set(Some(secs));
                        } else {
                            messages.set(result.messages);
                            // The first turn freezes the switches; reflect that in the
                            // composer without waiting for a reload.
                            let mut o = *options.peek();
                            o.locked = true;
                            options.set(o);
                        }
                    }
                    Err(e) => error.set(Some(e.to_string())),
                }
            }
            sending.set(false);
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
                }
                if *sending.read() {
                    div {
                        style: "padding: 0 18px 8px; color: #64748B; font-size: 13px; font-style: italic;",
                        "The assistant is searching your collections\u{2026}"
                    }
                }
                if let Some(e) = error.read().clone() {
                    div { style: "padding: 0 18px 8px; color: #B91C1C; font-size: 13px;", "{e}" }
                }
                div { style: "padding: 12px 14px; flex-shrink: 0;",
                    ChatComposer {
                        draft,
                        options,
                        sending,
                        retry_after_seconds: retry_after,
                        on_submit,
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
