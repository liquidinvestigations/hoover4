//! The shared text viewer of every text source. It owns stored-page navigation,
//! source-scoped match steps, and the request state of the displayed page.
//!
//! The full viewer, the search and Storage previews, the chat preview and the email
//! preview all render this component, so they offer the same page and match controls.
//! The match controls are in the toolbar. The page controls are one overlay in the
//! lower-right corner of the text viewport, shown only when the loaded source has more
//! than one stored entry.
//!
//! One request key names what the reader asked for. It holds the document, the source,
//! the explicit page and the find query. The last page that loaded for the current
//! document and source stays on screen until the next page arrives. A failed request
//! keeps that page on screen beside the error and a Retry action.

use std::sync::atomic::{AtomicU64, Ordering};

use common::document_sources::DocumentTextSourceItem;
use common::document_text_pages::{MatchDirection, TextMatchStep, TextPageBody, TextPageNavigation, TextPageView};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;

use dioxus_free_icons::icons::md_navigation_icons::{MdArrowDownward, MdArrowUpward};

use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::components::{
    document_view_components::doc_preview_for_search::text_data_viewer,
    search_components::search_result_list_controls::NavigationButton,
};
use crate::data_definitions::doc_viewer_state::{
    ContinuationOutcome, ContinuationPhase, MatchContinuation, MatchOperationKey, STEPS_PER_MATCH_ACTION, TextMatchSelection,
};
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

/// The nearest matching pages on both sides of the displayed page, for one operation.
#[derive(Debug, Clone, PartialEq)]
pub struct MatchNeighbours {
    /// The operation that the steps belong to: its anchor page, query and generation.
    pub key: MatchOperationKey,
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
    /// The displayed page answers the current request, so its highlights belong to the
    /// current query. Match actions wait while it is false.
    pub body_current: ReadSignal<bool>,
    /// The highlighted matches of the displayed page under the current query, 0 while
    /// another request loads.
    pub match_count: ReadSignal<u32>,
    /// The selected 0-based match of the displayed page.
    pub current_match: ReadSignal<u32>,
    /// The neighbour steps of the current operation only.
    pub match_neighbours: ReadSignal<Option<Result<Option<MatchNeighbours>, ServerFnError>>>,
    /// The continuation of the current operation only.
    pub continuation: ReadSignal<Option<MatchContinuation>>,
    /// The search for the first matching page read its allowance, and the first match is
    /// still unknown.
    pub initial_incomplete: ReadSignal<bool>,
    /// A match step that crosses pages is running.
    pub match_step_pending: ReadSignal<bool>,
    pub match_step_error: ReadSignal<Option<String>>,
    pub go_to_page: Callback<u32>,
    pub select_match: Callback<u32>,
    pub step_match: Callback<MatchDirection>,
    pub retry: Callback<()>,
    pub retry_matches: Callback<()>,
    /// The page overlay shows, so the text keeps space below its last line.
    pub page_overlay: ReadSignal<bool>,
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
    // The last page of the current document and source, with the request it answered.
    let shown_entry: Memo<Option<(TextRequestKey, TextPageView)>> = use_memo(move || {
        let (document, extracted_by) = source_identity();
        displayed
            .read()
            .as_ref()
            .filter(|(key, _)| key.document == document && key.extracted_by == extracted_by)
            .cloned()
    });
    let shown: Memo<Option<TextPageView>> = use_memo(move || shown_entry().map(|(_, view)| view));
    let body_current = use_memo(move || shown_entry().is_some_and(|(key, _)| key == request()));
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
    let match_count = use_memo(move || if body_current() { shown().map_or(0, |view| view.body.match_count()) } else { 0 });
    let current_match = use_memo(move || {
        if !body_current() {
            return 0;
        }
        let Some(view) = shown() else { return 0 };
        let TextPageBody::Text { page_id, .. } = &view.body else { return 0 };
        selected_match()
            .and_then(|selection| selection.ordinal_for(&view.navigation.extracted_by, *page_id, &find_query(), match_count()))
            .unwrap_or(0)
    });

    // A new document, source, query or page starts a new generation, so the results of
    // earlier match operations never apply.
    let mut generation = use_signal(|| 0u64);
    let operation_key = use_memo(move || {
        let generation = generation();
        let query = find_query();
        if query.trim().is_empty() || !body_current() {
            return None;
        }
        let (document, extracted_by) = source_identity();
        let view = shown()?;
        let anchor = anchor_page(&view)?;
        Some(MatchOperationKey { document, extracted_by, find_query: query, anchor, revision: view.navigation.revision, generation })
    });

    let mut match_neighbours = use_resource(move || {
        let key = operation_key();
        async move {
            let Some(key) = key else { return (None, Ok(None)) };
            let steps = async {
                let previous = find_text_match_page(
                    key.document.clone(), key.extracted_by.clone(), key.find_query.clone(), Some(key.anchor), MatchDirection::Backward,
                ).await?;
                let next = find_text_match_page(
                    key.document.clone(), key.extracted_by.clone(), key.find_query.clone(), Some(key.anchor), MatchDirection::Forward,
                ).await?;
                Ok(Some(MatchNeighbours { key: key.clone(), previous, next }))
            };
            let result = steps.await;
            (Some(key), result)
        }
    });
    let neighbours = use_memo(move || {
        let current = operation_key();
        match match_neighbours.read().clone() {
            Some((key, result)) if key == current => Some(result),
            _ => None,
        }
    });

    let mut scroll_intent = use_signal(|| Some(ScrollIntent::Match));
    let mut continuation_state = use_signal(|| None::<MatchContinuation>);
    let mut match_task = use_signal(|| None::<dioxus_core::Task>);
    let continuation = use_memo(move || {
        let current = operation_key();
        continuation_state.read().clone().filter(|c| Some(&c.key) == current.as_ref())
    });
    let match_step_pending = use_memo(move || continuation().is_some_and(|c| c.phase == ContinuationPhase::Running));
    let match_step_error = use_memo(move || match continuation() {
        Some(MatchContinuation { phase: ContinuationPhase::Failed(message), .. }) => Some(message),
        _ => None,
    });
    let initial_incomplete = use_memo(move || {
        body_current()
            && shown_entry().is_some_and(|(key, view)| {
                key.page.is_none() && matches!(view.initial_match, Some(TextMatchStep::Incomplete { .. }))
            })
    });

    // A new query or source moves to its first match once it renders.
    use_effect(move || {
        let _ = find_query();
        let _ = source_identity();
        scroll_intent.set(Some(ScrollIntent::Match));
        *generation.write() += 1;
    });
    // Work of an obsolete operation stops. A result that arrives after the cancellation is
    // still discarded by its key.
    use_effect(move || {
        let current = operation_key();
        let obsolete = continuation_state.peek().as_ref().is_some_and(|c| Some(&c.key) != current.as_ref());
        if obsolete {
            if let Some(task) = match_task.write().take() {
                task.cancel();
            }
            continuation_state.set(None);
        }
    });

    let go_to_page = Callback::new(move |page: u32| {
        let mut next = state.peek().clone().unwrap_or_default();
        next.selected_source_page = Some(page);
        next.selected_match = None;
        *generation.write() += 1;
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
        if !*body_current.peek() {
            return;
        }
        if let Some(page_id) = shown.peek().as_ref().and_then(anchor_page) {
            select_on_page.call((page_id, ordinal));
        }
    });
    // Runs at most `STEPS_PER_MATCH_ACTION` server steps from `boundary`, and keeps the
    // last boundary for the next action.
    let run_continuation = Callback::new(move |(key, direction, boundary): (MatchOperationKey, MatchDirection, u32)| {
        let ordinal = match direction {
            MatchDirection::Forward => 0,
            MatchDirection::Backward => TextMatchSelection::LAST,
        };
        if let Some(task) = match_task.write().take() {
            task.cancel();
        }
        continuation_state.set(Some(MatchContinuation { key: key.clone(), direction, boundary, phase: ContinuationPhase::Running }));
        let task = spawn(async move {
            let mut state = MatchContinuation { key: key.clone(), direction, boundary, phase: ContinuationPhase::Running };
            for _ in 0..STEPS_PER_MATCH_ACTION {
                let result = find_text_match_page(
                    key.document.clone(), key.extracted_by.clone(), key.find_query.clone(), Some(state.boundary), direction,
                )
                .await
                .map_err(|error| crate::api::error_util::user_facing_message(&error));
                let Some(outcome) = state.outcome(operation_key.peek().as_ref(), result) else { return };
                match outcome {
                    ContinuationOutcome::Select(page_id) => {
                        continuation_state.set(None);
                        select_on_page.call((page_id, ordinal));
                        return;
                    }
                    ContinuationOutcome::Continue(next) => {
                        state.boundary = next;
                        continuation_state.set(Some(state.clone()));
                    }
                    ContinuationOutcome::Stop(phase, at) => {
                        continuation_state.set(Some(MatchContinuation { boundary: at, phase, ..state }));
                        return;
                    }
                }
            }
            continuation_state.set(Some(MatchContinuation { phase: ContinuationPhase::Incomplete, ..state }));
        });
        match_task.set(Some(task));
    });
    let step_match = Callback::new(move |direction: MatchDirection| {
        let Some(key) = operation_key.peek().clone() else { return };
        let count = *match_count.peek();
        let current = *current_match.peek();
        match direction {
            MatchDirection::Forward if count > 0 && current + 1 < count => return select_on_page.call((key.anchor, current + 1)),
            MatchDirection::Backward if count > 0 && current > 0 => return select_on_page.call((key.anchor, current - 1)),
            _ => {}
        }
        // An earlier action of this operation kept its boundary.
        if let Some(kept) = continuation.peek().clone().filter(|c| c.direction == direction) {
            match kept.phase {
                ContinuationPhase::Incomplete | ContinuationPhase::Failed(_) => {
                    return run_continuation.call((key, direction, kept.boundary));
                }
                ContinuationPhase::Running | ContinuationPhase::Exhausted => return,
            }
        }
        // The initial search of this page stopped at its allowance. It continues there.
        if direction == MatchDirection::Forward && *initial_incomplete.peek() {
            if let Some(TextMatchStep::Incomplete { resume_after }) = shown.peek().as_ref().and_then(|view| view.initial_match.clone()) {
                return run_continuation.call((key, direction, resume_after));
            }
        }
        let Some(Ok(Some(found))) = neighbours.peek().clone() else { return };
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
            TextMatchStep::Incomplete { resume_after } => run_continuation.call((key, direction, resume_after)),
        }
    });

    // Moves the viewport once the requested page has rendered, then forgets the intent,
    // so a count update or an ordinary render never scrolls. The intent waits while the
    // displayed body answers an earlier request.
    use_effect(move || {
        let view = shown();
        let current = current_match();
        let waiting = pending();
        let current_body = body_current();
        let Some(intent) = *scroll_intent.peek() else { return };
        if waiting || view.is_none() || !current_body {
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

    let page_overlay = use_memo(move || has_page_overlay(shown.read().as_ref()));

    use_context_provider(move || DocumentViewerResultStore {
        displayed: shown.into(),
        pending: pending.into(),
        request: request.into(),
        request_error: request_error.into(),
        body_current: body_current.into(),
        match_count: match_count.into(),
        current_match: current_match.into(),
        match_neighbours: neighbours.into(),
        continuation: continuation.into(),
        initial_incomplete: initial_incomplete.into(),
        match_step_pending: match_step_pending.into(),
        match_step_error: match_step_error.into(),
        go_to_page,
        select_match,
        step_match,
        retry: Callback::new(move |_| {
            retry_count += 1;
            page_request.restart();
        }),
        // A failed continuation resumes at its boundary. Its error clears when the retry
        // starts, and only for this operation.
        retry_matches: Callback::new(move |_| {
            let Some(key) = operation_key.peek().clone() else { return };
            match continuation.peek().clone() {
                Some(MatchContinuation { direction, boundary, phase: ContinuationPhase::Failed(_), .. }) => {
                    run_continuation.call((key, direction, boundary))
                }
                _ => match_neighbours.restart(),
            }
        }),
        page_overlay: page_overlay.into(),
        viewer_key,
        flow_layout,
    });

    rsx! {
        PreviewWrapper {
            controls: rsx! {
                TextMatchControls {}
            },
            // The overlay is a sibling of the scroll container, so it keeps its place in the
            // viewport while the text scrolls.
            page: rsx! {
                div {
                    style: "position: relative; height: 100%; width: 100%;",
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
                    if page_overlay() {
                        TextPageOverlay {}
                    }
                }
            }
        }
    }
}

/// Whether the page overlay shows: the loaded source has more than one stored entry. It
/// stays hidden while the first metadata loads, so no unit shows before the source names it.
fn has_page_overlay(view: Option<&TextPageView>) -> bool {
    view.is_some_and(|view| view.navigation.stored_count > 1)
}

/// The compact stored position under the page field, and its accessible name. `2/3` is
/// the second of three stored entries. An identifier with no stored text has no position.
fn position_text(navigation: &TextPageNavigation) -> (String, String) {
    let count = navigation.stored_count;
    match navigation.position {
        Some(position) => (format!("{position}/{count}"), format!("Stored entry {position} of {count}")),
        None => (format!("-/{count}"), format!("No stored text. {count} stored entries")),
    }
}

/// The width of the page field in characters: the longest stored or requested identifier.
fn identifier_width(navigation: &TextPageNavigation) -> usize {
    [navigation.last_page, navigation.requested_page, navigation.page]
        .into_iter()
        .flatten()
        .map(|page| page.to_string().len())
        .max()
        .unwrap_or(1)
        .max(2)
}

/// The page control in the lower-right corner of the text viewport, arranged as the PDF
/// overlay: the editable identifier, the stored position, then the previous and next
/// stored entry. Enter or leaving the field commits a valid identifier once. Escape
/// restores the displayed identifier. An invalid entry stays in the field for correction.
#[component]
fn TextPageOverlay() -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let navigation = use_memo(move || store.displayed.read().as_ref().map(|view| view.navigation.clone()));
    let shown_page = use_memo(move || navigation().and_then(|nav| nav.page.or(nav.requested_page)));
    let previous = use_memo(move || navigation().and_then(|nav| nav.previous_page));
    let next = use_memo(move || navigation().and_then(|nav| nav.next_page));
    let no_previous = use_memo(move || previous().is_none());
    let no_next = use_memo(move || next().is_none());
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

    let Some(nav) = navigation() else { return rsx! {} };
    let viewer_key = store.viewer_key;
    let label = nav.unit.label();
    let description = nav.unit.description();
    let (position, position_label) = position_text(&nav);
    let width = identifier_width(&nav);
    let input_border = if invalid() { "var(--x-danger)" } else { "var(--x-border-strong)" };
    let loading_text = pending_destination().map(|page| format!("Loading {label} {page}")).unwrap_or_default();

    rsx! {
        div {
            role: "group",
            "aria-label": "{label} navigation",
            "data-text-page-controls": "true",
            style: "position: absolute; right: {OVERLAY_INSET_PX}px; bottom: {OVERLAY_INSET_PX}px; z-index: 5; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 4px; min-width: 40px; box-sizing: border-box; background-color: white; border: 1px solid; border-color: var(--x-border-strong); border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); font-size: var(--x-text-sm); line-height: var(--x-line-body);",
            input {
                r#type: "text",
                inputmode: "numeric",
                title: "{description}",
                "aria-label": "{label}",
                "data-text-page-input": "true",
                "aria-invalid": if invalid() { "true" } else { "false" },
                "aria-describedby": "x-text-unit-{viewer_key}",
                style: "width: calc({width}ch + 12px); box-sizing: border-box; text-align: center; padding: 2px 4px; border: 1px solid; border-color: {input_border}; border-radius: 6px; font: inherit; font-weight: 600;",
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
            span {
                "data-text-page-position": "true",
                "aria-label": "{position_label}",
                style: "white-space: nowrap; color: var(--x-ink-muted); padding-bottom: 2px; border-bottom: 1px solid; border-bottom-color: var(--x-border); width: 100%; text-align: center;",
                "{position}"
            }
            span {
                id: "x-text-unit-{viewer_key}",
                style: VISUALLY_HIDDEN,
                "{description}"
            }
            span {
                role: "status",
                "data-text-page-status": "true",
                style: VISUALLY_HIDDEN,
                "{loading_text}"
            }
            NavigationButton {
                icon: MdArrowUpward,
                label: format!("Previous {label}"),
                disabled: no_previous,
                onclick: move |_| if let Some(page) = previous() { store.go_to_page.call(page) },
            }
            NavigationButton {
                icon: MdArrowDownward,
                label: format!("Next {label}"),
                disabled: no_next,
                onclick: move |_| if let Some(page) = next() { store.go_to_page.call(page) },
            }
        }
    }
}

/// The distance of the page overlay from the lower-right corner of the text viewport.
const OVERLAY_INSET_PX: u32 = 16;

/// The space below the text that keeps its last line clear of the page overlay at the end
/// of the scroll: the overlay height of about 140 px, its inset, and one line of margin.
pub const OVERLAY_CLEARANCE: &str = "padding-bottom: 176px;";

const VISUALLY_HIDDEN: &str = "position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;";

/// Previous and next match, and the editable match number of the displayed page. The
/// number counts the matches of this page only. The arrows continue to the nearest
/// matching page of this source in page order and stop at both ends. A search that read
/// its allowance keeps its boundary, and the next step continues it.
#[component]
fn TextMatchControls() -> Element {
    let store = use_context::<DocumentViewerResultStore>();
    let count = store.match_count;
    let current = store.current_match;
    let neighbours = use_memo(move || match store.match_neighbours.read().clone() {
        Some(Ok(Some(found))) => Some(found),
        _ => None,
    });
    let neighbour_error = use_memo(move || match store.match_neighbours.read().clone() {
        Some(Err(error)) => Some(crate::api::error_util::user_facing_message(&error)),
        _ => None,
    });
    let busy = use_memo(move || store.match_step_pending.read().clone() || !*store.body_current.read());
    // A direction whose continuation found no further match has no step.
    let exhausted = move |direction: MatchDirection| {
        store.continuation.read().as_ref().is_some_and(|c| c.direction == direction && c.phase == ContinuationPhase::Exhausted)
    };
    let disable_previous = use_memo(move || {
        let local = count() > 0 && current() > 0;
        let earlier = neighbours().is_some_and(|found| step_available(&found.previous)) && !exhausted(MatchDirection::Backward);
        busy() || !(local || earlier)
    });
    let disable_next = use_memo(move || {
        let local = count() > 0 && current() + 1 < count();
        let later = (neighbours().is_some_and(|found| step_available(&found.next)) || *store.initial_incomplete.read())
            && !exhausted(MatchDirection::Forward);
        busy() || !(local || later)
    });
    let incomplete = use_memo(move || {
        let kept = store.continuation.read().as_ref().is_some_and(|c| c.phase == ContinuationPhase::Incomplete);
        kept || (*store.initial_incomplete.read() && count() == 0)
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
    let searching = *store.match_step_pending.read();

    rsx! {
        div {
            role: "group",
            "aria-label": "Matches",
            "data-text-match-controls": "true",
            style: "display: flex; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 4px; flex: 0 1 auto; min-width: 0;",
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
            span {
                role: "status",
                "aria-busy": if searching { "true" } else { "false" },
                "data-text-match-status": if searching { "searching" } else if incomplete() { "incomplete" } else { "" },
                style: "white-space: nowrap; color: var(--x-ink-muted); font-size: var(--x-text-sm);",
                if searching {
                    "Searching"
                } else if incomplete() {
                    "Search incomplete"
                }
            }
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
