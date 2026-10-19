//! The shared text viewer of every text source. It owns stored-page navigation,
//! source-scoped match steps, and the request state of the displayed page.
//!
//! The full viewer, the search and Storage previews, the chat preview and the email
//! preview all render this component, so they offer the same page and match controls.
//!
//! One request key names what the reader asked for. It holds the document, the source,
//! the explicit page and the find query. The last page that loaded for the current
//! document and source stays on screen until the next page arrives. A failed request
//! keeps that page on screen beside the error and a Retry action.

use std::sync::atomic::{AtomicU64, Ordering};

use common::document_sources::DocumentTextSourceItem;
use common::document_text_pages::{MatchDirection, TextMatchStep, TextPageBody, TextPageNavigation, TextPageView, TextSourceUnit};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use dioxus_free_icons::icons::md_navigation_icons::{MdArrowBack, MdArrowDownward, MdArrowForward, MdArrowUpward};

use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::components::{
    document_view_components::doc_preview_for_search::text_data_viewer,
    search_components::search_result_list_controls::NavigationButton,
};
use crate::data_definitions::doc_viewer_state::TextMatchSelection;
use crate::pages::search_page::DocViewerStateControl;

/// What one page request asks for. A response under another key belongs to an obsolete
/// selection and never replaces the displayed page.
#[derive(Debug, Clone, PartialEq)]
pub struct TextRequestKey {
    pub document: DocumentIdentifier,
    pub extracted_by: String,
    pub page: Option<u32>,
    pub find_query: String,
}

/// Where the text viewport moves after the requested page renders.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ScrollIntent {
    /// To the start of the text, after explicit page navigation.
    Top,
    /// To the selected match, after match navigation or a query change.
    Match,
}

/// The nearest matching pages on both sides of the displayed page.
#[derive(Debug, Clone, PartialEq)]
pub struct MatchNeighbours {
    /// The page the steps start from, and the query they used.
    pub anchor: u32,
    pub find_query: String,
    pub previous: TextMatchStep,
    pub next: TextMatchStep,
}

/// Gives each viewer its own DOM identity, so two viewers on one screen never scroll
/// each other's text.
static NEXT_VIEWER_KEY: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, PartialEq)]
pub struct DocumentViewerResultStore {
    /// The last page view that loaded for the current document and source.
    pub displayed: ReadSignal<Option<TextPageView>>,
    /// The page request has not answered yet.
    pub pending: ReadSignal<bool>,
    /// What the current request asks for.
    pub request: ReadSignal<TextRequestKey>,
    /// The current page request failed.
    pub request_error: ReadSignal<Option<ServerFnError>>,
    /// The selected 0-based match of the displayed page.
    pub current_match: ReadSignal<u32>,
    pub match_neighbours: ReadSignal<Option<Result<Option<MatchNeighbours>, ServerFnError>>>,
    /// A match step that crosses pages is running.
    pub match_step_pending: ReadSignal<bool>,
    pub match_step_error: ReadSignal<Option<String>>,
    pub go_to_page: Callback<u32>,
    pub select_match: Callback<u32>,
    pub step_match: Callback<MatchDirection>,
    pub retry: Callback<()>,
    pub retry_matches: Callback<()>,
    pub viewer_key: u64,
    /// True when the preamble and the text share one scroll container. See
    /// [`DocumentPreviewTextWithSearch`].
    pub flow_layout: bool,
}

/// The page that a view stands on: the displayed stored page, or the requested
/// identifier that has no stored text.
fn anchor_page(view: &TextPageView) -> Option<u32> {
    match &view.body {
        TextPageBody::Text { page_id, .. } => Some(*page_id),
        TextPageBody::Absent => view.navigation.requested_page.or(view.navigation.page),
        TextPageBody::EmptySource => None,
    }
}

/// Whether a match step leads somewhere.
fn step_available(step: &TextMatchStep) -> bool {
    !matches!(step, TextMatchStep::NoMore)
}

#[component]
pub fn DocumentPreviewTextWithSearch(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentTextSourceItem>,
    preamble: Element,
    /// Put the preamble and the text in one scroll container, in normal vertical flow.
    ///
    /// The email preview sets it: its expanded header list can be taller than the
    /// viewer, and in the default layout only the text below it scrolls, so the list is
    /// cut off. Without it the preamble keeps its natural height and the text scrolls on
    /// its own, which is what a plain text source needs.
    #[props(default)]
    flow_layout: bool,
) -> Element {
    let control = use_context::<DocViewerStateControl>();
    let state = control.doc_viewer_state;
    let set_state = control.set_doc_viewer_state;
    let viewer_key = use_hook(|| NEXT_VIEWER_KEY.fetch_add(1, Ordering::Relaxed));

    let find_query = use_memo(move || state.read().as_ref().map(|s| s.find_query.clone()).unwrap_or_default());
    let requested_page = use_memo(move || state.read().as_ref().and_then(|s| s.selected_source_page));
    let selected_match = use_memo(move || state.read().as_ref().and_then(|s| s.selected_match.clone()));

    // By value through `use_reactive`: a changed prop re-renders this component, and the
    // memo re-runs on the new values.
    let document_value = document_identifier();
    let extracted_by_value = source.read().extracted_by.clone();
    let source_identity = use_memo(use_reactive!(|document_value, extracted_by_value| (document_value, extracted_by_value)));
    let request = use_memo(move || {
        let (document, extracted_by) = source_identity();
        TextRequestKey { document, extracted_by, page: requested_page(), find_query: find_query() }
    });

    // ================ PAGE REQUEST ================
    let mut displayed = use_signal(|| None::<(TextRequestKey, TextPageView)>);
    let mut retry_count = use_signal(|| 0u64);
    let mut page_request = use_resource(move || {
        let key = request();
        let _ = retry_count();
        // The revision the reader sees now. `peek`, so a newly displayed page does not
        // start this request again.
        let expected = displayed
            .peek()
            .as_ref()
            .filter(|(shown, _)| shown.document == key.document && shown.extracted_by == key.extracted_by)
            .map(|(_, view)| view.navigation.revision.clone());
        async move {
            let result = get_text_page_view(
                key.document.clone(),
                key.extracted_by.clone(),
                key.page,
                key.find_query.clone(),
                expected,
            )
            .await;
            (key, result)
        }
    });
    use_effect(move || {
        let Some((key, Ok(view))) = page_request.read().clone() else {
            return;
        };
        if key == *request.peek() {
            displayed.set(Some((key, view)));
        }
    });
    let shown: Memo<Option<TextPageView>> = use_memo(move || {
        let (document, extracted_by) = source_identity();
        displayed
            .read()
            .as_ref()
            .filter(|(key, _)| key.document == document && key.extracted_by == extracted_by)
            .map(|(_, view)| view.clone())
    });
    let pending = use_memo(move || {
        let key = request();
        let running = matches!(*page_request.state().read(), UseResourceState::Pending);
        let answered = page_request.read().as_ref().is_some_and(|(answered, _)| *answered == key);
        running || !answered
    });
    let request_error = use_memo(move || {
        let key = request();
        match &*page_request.read() {
            Some((answered, Err(error))) if *answered == key => Some(error.clone()),
            _ => None,
        }
    });

    // ================ MATCH SELECTION ================
    let current_match = use_memo(move || {
        let Some(view) = shown() else { return 0 };
        let TextPageBody::Text { page_id, .. } = &view.body else { return 0 };
        let count = view.body.match_count();
        selected_match()
            .and_then(|selection| selection.ordinal_for(&view.navigation.extracted_by, *page_id, &find_query(), count))
            .unwrap_or(0)
    });

    let mut match_neighbours = use_resource(move || {
        let query = find_query();
        let (document, extracted_by) = source_identity();
        let anchor = shown().as_ref().and_then(anchor_page);
        async move {
            if query.trim().is_empty() {
                return Ok(None);
            }
            let Some(anchor) = anchor else { return Ok(None) };
            let previous =
                find_text_match_page(document.clone(), extracted_by.clone(), query.clone(), Some(anchor), MatchDirection::Backward).await?;
            let next = find_text_match_page(document, extracted_by, query.clone(), Some(anchor), MatchDirection::Forward).await?;
            Ok(Some(MatchNeighbours { anchor, find_query: query, previous, next }))
        }
    });
    let neighbours = use_memo(move || match_neighbours.read().clone());

    let mut scroll_intent = use_signal(|| Some(ScrollIntent::Match));
    let mut match_step_pending = use_signal(|| false);
    let mut match_step_error = use_signal(|| None::<String>);

    // A new query or source moves to its first match once it renders.
    use_effect(move || {
        let _ = find_query();
        let _ = source_identity();
        scroll_intent.set(Some(ScrollIntent::Match));
        match_step_error.set(None);
    });

    let go_to_page = Callback::new(move |page: u32| {
        let mut next = state.peek().clone().unwrap_or_default();
        next.selected_source_page = Some(page);
        next.selected_match = None;
        match_step_error.set(None);
        scroll_intent.set(Some(ScrollIntent::Top));
        set_state.call(next);
    });
    let select_on_page = Callback::new(move |(page_id, ordinal): (u32, u32)| {
        let mut next = state.peek().clone().unwrap_or_default();
        next.selected_source_page = Some(page_id);
        next.selected_match = Some(TextMatchSelection {
            extracted_by: source_identity.peek().1.clone(),
            page_id,
            find_query: find_query.peek().clone(),
            ordinal,
        });
        scroll_intent.set(Some(ScrollIntent::Match));
        set_state.call(next);
    });
    let select_match = Callback::new(move |ordinal: u32| {
        if let Some(page_id) = shown.peek().as_ref().and_then(anchor_page) {
            select_on_page.call((page_id, ordinal));
        }
    });
    let step_match = Callback::new(move |direction: MatchDirection| {
        let Some(view) = shown.peek().clone() else { return };
        let Some(anchor) = anchor_page(&view) else { return };
        let count = view.body.match_count();
        let current = *current_match.peek();
        match direction {
            MatchDirection::Forward if count > 0 && current + 1 < count => return select_on_page.call((anchor, current + 1)),
            MatchDirection::Backward if count > 0 && current > 0 => return select_on_page.call((anchor, current - 1)),
            _ => {}
        }
        let query = find_query.peek().clone();
        let Some(Ok(Some(found))) = neighbours.peek().clone() else { return };
        if found.anchor != anchor || found.find_query != query {
            return;
        }
        let first = match direction {
            MatchDirection::Forward => found.next,
            MatchDirection::Backward => found.previous,
        };
        let ordinal = match direction {
            MatchDirection::Forward => 0,
            MatchDirection::Backward => TextMatchSelection::LAST,
        };
        match first {
            TextMatchStep::Found { page_id } => select_on_page.call((page_id, ordinal)),
            TextMatchStep::NoMore => {}
            TextMatchStep::Incomplete { resume_after } => {
                let (document, extracted_by) = source_identity.peek().clone();
                match_step_pending.set(true);
                match_step_error.set(None);
                spawn(async move {
                    let mut from = resume_after;
                    // Each step reads a bounded allowance. A source with many obsolete
                    // index rows needs more than one.
                    for _ in 0..20 {
                        match find_text_match_page(document.clone(), extracted_by.clone(), query.clone(), Some(from), direction).await {
                            Ok(TextMatchStep::Found { page_id }) => {
                                match_step_pending.set(false);
                                select_on_page.call((page_id, ordinal));
                                return;
                            }
                            Ok(TextMatchStep::NoMore) => break,
                            Ok(TextMatchStep::Incomplete { resume_after }) => from = resume_after,
                            Err(error) => {
                                match_step_error.set(Some(crate::api::error_util::user_facing_message(&error)));
                                break;
                            }
                        }
                    }
                    match_step_pending.set(false);
                });
            }
        }
    });

    // Moves the viewport once the requested page has rendered, then forgets the intent,
    // so a count update or an ordinary render never scrolls.
    use_effect(move || {
        let view = shown();
        let current = current_match();
        let waiting = pending();
        let Some(intent) = *scroll_intent.peek() else { return };
        if waiting || view.is_none() {
            return;
        }
        let script = match intent {
            ScrollIntent::Top => format!(
                r#"requestAnimationFrame(() => {{
                    const root = document.querySelector('[data-text-viewer-key="{viewer_key}"]');
                    if (!root) return;
                    root.scrollTop = 0;
                    const flow = root.closest('[data-text-flow-key="{viewer_key}"]');
                    if (flow) flow.scrollTop = Math.max(0, root.offsetTop - flow.offsetTop);
                }});"#
            ),
            ScrollIntent::Match => format!(
                r#"requestAnimationFrame(() => {{
                    const root = document.querySelector('[data-text-viewer-key="{viewer_key}"]');
                    const hit = root?.querySelector('[data-text-hit="{current}"]');
                    hit?.scrollIntoView({{block:'center', inline:'nearest'}});
                }});"#
            ),
        };
        document::eval(&script);
        scroll_intent.set(None);
    });

    use_context_provider(move || DocumentViewerResultStore {
        displayed: shown.into(),
        pending: pending.into(),
        request: request.into(),
        request_error: request_error.into(),
        current_match: current_match.into(),
        match_neighbours: neighbours.into(),
        match_step_pending: match_step_pending.into(),
        match_step_error: match_step_error.into(),
        go_to_page,
        select_match,
        step_match,
        retry: Callback::new(move |_| {
            retry_count += 1;
            page_request.restart();
        }),
        retry_matches: Callback::new(move |_| match_neighbours.restart()),
        viewer_key,
        flow_layout,
    });

    rsx! {
        PreviewWrapper {
            controls: rsx! {
                TextNavigationControls {}
            },
            page: rsx! {
                if flow_layout {
                    div {
                        id: "x-document-flow-scroll",
                        "data-text-flow-key": "{viewer_key}",
                        style: "height: 100%; width: 100%; overflow-y: auto;",
                        {preamble}
                        text_data_viewer::TextDataViewer {}
                    }
                } else {
                    div {
                        style: "
                            height: 100%;
                            width: 100%;
                            display: flex;
                            flex-direction: column;
                            overflow: hidden;
                        ",
                        {preamble}
                        div {
                            style: "flex: 1; min-height: 0;",
                            text_data_viewer::TextDataViewer {}
                        }
                    }
                }
            }
        }
    }
}

/// The page group and the match group, each kept whole when the toolbar wraps.
#[component]
fn TextNavigationControls() -> Element {
    rsx! {
        div {
            class: "x-text-navigation",
            style: "
                display: flex;
                flex-direction: row;
                flex-wrap: wrap;
                align-items: center;
                justify-content: flex-start;
                gap: 6px 10px;
                min-width: 0;
                padding: 0;
            ",
            TextPageControls {}
            TextMatchControls {}
        }
    }
}

/// The text of the position beside the page field. The identifier and the position are
/// combined only when every stored identifier equals its position.
fn position_text(navigation: &TextPageNavigation) -> (String, String) {
    let contiguous = navigation.first_page == Some(1) && navigation.last_page == Some(navigation.stored_count as u32);
    let count = navigation.stored_count;
    match navigation.position {
        Some(_) if contiguous => (format!("of {count}"), format!("{count} stored in total")),
        Some(position) => (format!("{position} of {count} stored"), format!("Stored entry {position} of {count}")),
        None => ("not stored".to_string(), format!("No stored text. {count} stored entries")),
    }
}

/// Previous and next stored page, the unit and editable identifier, and the stored
/// position. Enter or leaving the field commits a valid identifier once. Escape restores
/// the displayed identifier. An invalid entry stays in the field for correction.
#[component]
fn TextPageControls() -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let navigation = use_memo(move || store.displayed.read().as_ref().map(|view| view.navigation.clone()));
    let shown_page = use_memo(move || navigation().and_then(|nav| nav.page.or(nav.requested_page)));
    let unit = use_memo(move || navigation().map_or(TextSourceUnit::StoredEntry, |nav| nav.unit));
    let previous = use_memo(move || navigation().and_then(|nav| nav.previous_page));
    let next = use_memo(move || navigation().and_then(|nav| nav.next_page));
    let mut draft = use_signal(String::new);
    let mut invalid = use_signal(|| false);
    let mut committed = use_signal(|| None::<String>);
    use_effect(move || {
        let page = shown_page();
        draft.set(page.map(|page| page.to_string()).unwrap_or_default());
        invalid.set(false);
        committed.set(None);
    });
    let mut commit = move || {
        let text = draft.peek().trim().to_string();
        if committed.peek().as_deref() == Some(text.as_str()) {
            return;
        }
        committed.set(Some(text.clone()));
        match text.parse::<u32>() {
            Ok(page) if page > 0 => {
                invalid.set(false);
                if Some(page) != *shown_page.peek() || store.request_error.peek().is_some() {
                    store.go_to_page.call(page);
                }
            }
            _ => invalid.set(true),
        }
    };
    let pending_destination = use_memo(move || {
        let request = store.request.read();
        (*store.pending.read() && store.displayed.read().is_some()).then(|| request.page).flatten()
    });

    let viewer_key = store.viewer_key;
    let label = unit().label();
    let description = unit().description();
    let (position, position_label) = navigation().as_ref().map(position_text).unwrap_or_default();
    let input_border = if invalid() { "var(--x-danger)" } else { "var(--x-border-strong)" };
    let previous_label = format!("Previous {label}");
    let next_label = format!("Next {label}");
    let loading_text = pending_destination().map(|page| format!("Loading {label} {page}")).unwrap_or_default();

    rsx! {
        div {
            role: "group",
            "aria-label": "{label} navigation",
            "data-text-page-controls": "true",
            style: "display: flex; flex-direction: row; align-items: center; gap: 4px; flex: 0 1 auto; min-width: 0; max-width: 100%;",
            NavigationButton {
                icon: MdArrowBack,
                label: previous_label,
                disabled: previous().is_none(),
                onclick: move |_| if let Some(page) = previous() { store.go_to_page.call(page) },
            }
            div {
                style: "display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; column-gap: 4px; flex: 0 1 auto; min-width: 0; font-size: var(--x-text-body); line-height: var(--x-line-body);",
                label {
                    style: "display: inline-flex; flex-wrap: wrap; align-items: center; gap: 2px 4px; min-width: 0;",
                    title: "{description}",
                    span { style: "white-space: nowrap;", "{label}" }
                    input {
                        r#type: "text",
                        inputmode: "numeric",
                        "data-text-page-input": "true",
                        "aria-invalid": if invalid() { "true" } else { "false" },
                        "aria-describedby": "x-text-unit-{viewer_key}",
                        style: "width: 48px; box-sizing: border-box; text-align: center; padding: 2px 4px; border: 1px solid; border-color: {input_border}; border-radius: 6px; font: inherit;",
                        value: "{draft}",
                        oninput: move |event| {
                            draft.set(event.value());
                            invalid.set(false);
                            committed.set(None);
                        },
                        onkeydown: move |event| {
                            if event.key() == Key::Enter {
                                event.prevent_default();
                                commit();
                            } else if event.key() == Key::Escape {
                                event.prevent_default();
                                let page = (*shown_page.peek()).map(|page| page.to_string()).unwrap_or_default();
                                committed.set(Some(page.clone()));
                                draft.set(page);
                                invalid.set(false);
                            }
                        },
                        onblur: move |_| commit(),
                    }
                }
                span {
                    "data-text-page-position": "true",
                    "aria-label": "{position_label}",
                    style: "white-space: nowrap; color: var(--x-ink-muted);",
                    "{position}"
                }
                span {
                    id: "x-text-unit-{viewer_key}",
                    style: "position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;",
                    "{description}"
                }
                span {
                    role: "status",
                    "data-text-page-status": "true",
                    style: "white-space: nowrap; color: var(--x-ink-muted);",
                    "{loading_text}"
                }
            }
            NavigationButton {
                icon: MdArrowForward,
                label: next_label,
                disabled: next().is_none(),
                onclick: move |_| if let Some(page) = next() { store.go_to_page.call(page) },
            }
        }
    }
}

/// Previous and next match, and the editable match number of the displayed page. The
/// number counts the matches of this page only. The arrows continue to the nearest
/// matching page of this source in page order and stop at both ends.
#[component]
fn TextMatchControls() -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let count = use_memo(move || store.displayed.read().as_ref().map_or(0, |view| view.body.match_count()));
    let current = store.current_match;
    let neighbours = use_memo(move || {
        let view = store.displayed.read().clone();
        let anchor = view.as_ref().and_then(anchor_page);
        let query = store.request.read().find_query.clone();
        match store.match_neighbours.read().clone() {
            Some(Ok(Some(found))) if Some(found.anchor) == anchor && found.find_query == query => Some(found),
            _ => None,
        }
    });
    let neighbour_error = use_memo(move || match store.match_neighbours.read().clone() {
        Some(Err(error)) => Some(crate::api::error_util::user_facing_message(&error)),
        _ => None,
    });
    let busy = store.match_step_pending;
    let disable_previous = use_memo(move || {
        let local = count() > 0 && current() > 0;
        let earlier = neighbours().is_some_and(|found| step_available(&found.previous));
        busy() || !(local || earlier)
    });
    let disable_next = use_memo(move || {
        let local = count() > 0 && current() + 1 < count();
        let later = neighbours().is_some_and(|found| step_available(&found.next));
        busy() || !(local || later)
    });

    let mut draft = use_signal(String::new);
    let mut invalid = use_signal(|| false);
    let mut committed = use_signal(|| None::<String>);
    use_effect(move || {
        let shown = if count() > 0 { (current() + 1).to_string() } else { String::new() };
        draft.set(shown);
        invalid.set(false);
        committed.set(None);
    });
    let mut commit = move || {
        let text = draft.peek().trim().to_string();
        if committed.peek().as_deref() == Some(text.as_str()) {
            return;
        }
        committed.set(Some(text.clone()));
        match text.parse::<u32>() {
            Ok(number) if number >= 1 && number <= *count.peek() => {
                invalid.set(false);
                if number - 1 != *current.peek() {
                    store.select_match.call(number - 1);
                }
            }
            _ => invalid.set(true),
        }
    };
    let input_border = if invalid() { "var(--x-danger)" } else { "var(--x-border-strong)" };
    let step_error = store.match_step_error.read().clone().or(neighbour_error());

    rsx! {
        div {
            role: "group",
            "aria-label": "Matches",
            "data-text-match-controls": "true",
            style: "display: flex; flex-direction: row; align-items: center; gap: 4px; flex: 0 0 auto; padding-left: 10px; border-left: 1px solid; border-left-color: var(--x-border);",
            NavigationButton { icon: MdArrowUpward, label: "Previous Hit", disabled: disable_previous, onclick: move |_| store.step_match.call(MatchDirection::Backward) }
            if count() > 0 {
                label {
                    "data-match-counter": "{current() + 1} / {count()}",
                    style: "display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; font-size: var(--x-text-body); line-height: var(--x-line-body);",
                    input {
                        r#type: "text",
                        inputmode: "numeric",
                        "aria-label": "Match number on this page",
                        "aria-invalid": if invalid() { "true" } else { "false" },
                        style: "width: 40px; box-sizing: border-box; text-align: center; padding: 2px 4px; border: 1px solid; border-color: {input_border}; border-radius: 6px; font: inherit;",
                        value: "{draft}",
                        oninput: move |event| {
                            draft.set(event.value());
                            invalid.set(false);
                            committed.set(None);
                        },
                        onkeydown: move |event| {
                            if event.key() == Key::Enter {
                                event.prevent_default();
                                commit();
                            } else if event.key() == Key::Escape {
                                event.prevent_default();
                                let shown = (*current.peek() + 1).to_string();
                                committed.set(Some(shown.clone()));
                                draft.set(shown);
                                invalid.set(false);
                            }
                        },
                        onblur: move |_| commit(),
                    }
                    span { "aria-label": "of {count()} on this page", "/ {count()}" }
                }
            } else {
                div {
                    "data-match-counter": "- / -",
                    style: "min-width: 40px; font-size: var(--x-text-body); line-height: var(--x-line-body); text-align:center;",
                    "- / -"
                }
            }
            NavigationButton { icon: MdArrowDownward, label: "Next Hit", disabled: disable_next, onclick: move |_| store.step_match.call(MatchDirection::Forward) }
            if let Some(error) = step_error {
                span {
                    role: "alert",
                    style: "display: inline-flex; align-items: center; gap: 6px; color: var(--x-danger); font-size: var(--x-text-sm); white-space: nowrap;",
                    title: "{error}",
                    "Match search failed"
                    button {
                        style: "background-color: white; color: var(--x-ink-strong); border: 1px solid; border-color: var(--x-border-strong); border-radius: 16px; padding: 1px 10px; cursor: pointer; font: inherit;",
                        onclick: move |_| store.retry_matches.call(()),
                        "Retry"
                    }
                }
            }
        }
    }
}

#[server]
async fn get_text_page_view(
    document_identifier: DocumentIdentifier,
    extracted_by: String,
    page: Option<u32>,
    find_query: String,
    expected_revision: Option<String>,
) -> Result<TextPageView, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::document_text::get_text_page_view(
        &user,
        document_identifier,
        extracted_by,
        page,
        find_query,
        expected_revision,
    )
    .await
    .map_err(crate::api::error_util::to_server_fn_error)
}

#[server]
async fn find_text_match_page(
    document_identifier: DocumentIdentifier,
    extracted_by: String,
    find_query: String,
    from: Option<u32>,
    direction: MatchDirection,
) -> Result<TextMatchStep, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::document_text::find_text_match_page(
        &user,
        document_identifier,
        extracted_by,
        find_query,
        from,
        direction,
    )
    .await
    .map_err(crate::api::error_util::to_server_fn_error)
}
