//! The email viewer shows headers, attachments, and body text.
//! Header values and body text use the same index highlight engine.

use common::document_sources::{DocumentEmailSourceItem, DocumentTextSourceItem, DocumentSourceItem, EMAIL_TEXT_EXTRACTOR};
use common::email_graph::{EmailEnvelope, EmailParty};
use common::document_matches::{DocumentMatches, DocumentMatchTarget, MatchCompleteness};
use crate::data_definitions::doc_viewer_state::TextMatchSelection;
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        md_action_icons::MdOpenInNew,
        md_communication_icons::MdEmail,
        md_content_icons::{MdForward, MdReply},
        md_editor_icons::MdAttachFile,
        md_navigation_icons::{MdExpandLess, MdExpandMore},
    },
};

use crate::components::document_view_components::doc_preview_for_search::text_preview_with_search::DocumentPreviewTextWithSearch;
use crate::components::document_view_components::doc_preview_shared::PreviewWrapper;
use crate::routes::Route;
use crate::tr;
use crate::i18n::SharedText;

static NEXT_EMAIL_CARD: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// The existing source list lets unified navigation select a body extractor.
#[derive(Clone, Copy)]
pub struct EmailNavigationSources(pub ReadSignal<Option<Vec<DocumentSourceItem>>>);

const CARD_STYLE: &str = "
    padding: 12px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.10);
    margin-bottom: 8px;
";

const BANNER_STYLE: &str = "
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 8px 12px;
    margin-bottom: 10px;
    border-radius: 8px;
    background: rgba(0, 0, 0, 0.04);
    font-size: 13px;
";

const LINK_ROW_STYLE: &str = "
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 2px;
    font-size: 13px;
    color: #1a73e8;
    cursor: pointer;
    user-select: none;
    background: none;
    border: none;
    padding: 0;
";

const BANNER_GLYPH_STYLE: &str = "width: 18px; height: 18px; flex: 0 0 auto; margin-top: 2px;";
const CHEVRON_STYLE: &str = "width: 16px; height: 16px;";

const ATTACHMENT_CARD_STYLE: &str = "
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 190px;
    max-width: 280px;
    padding: 8px 10px;
    border: 1px solid rgba(0, 0, 0, 0.15);
    border-radius: 8px;
    text-decoration: none;
    color: inherit;
    background: transparent;
    cursor: pointer;
";

#[component]
pub fn DocumentPreviewForEmail(
    document_identifier: ReadSignal<DocumentIdentifier>,
    source: ReadSignal<DocumentEmailSourceItem>,
) -> Element {
    let document_identifier_value = document_identifier();
    let control = use_context::<crate::pages::search_page::DocViewerStateControl>();
    let find_query = control.doc_viewer_state.read().clone().unwrap_or_default().find_query;
    // By value through `use_reactive`: a `ReadSignal` prop is a fresh signal on every
    // parent render, so a resource that subscribes to the prop never re-runs when the
    // selected document changes.
    let envelope = use_resource(use_reactive!(|document_identifier_value, find_query| {
        async move {
            let result = get_email_envelope(document_identifier_value.clone(), find_query.clone()).await;
            ((document_identifier_value, find_query), result)
        }
    }));
    let envelope_reply = envelope().filter(|(key, _)| key == &(document_identifier_value.clone(), find_query.clone()));
    let envelope_value = envelope_reply.as_ref().and_then(|(_, result)| result.as_ref().ok()).cloned().flatten();

    let preamble = match envelope_value {
        Some(value) => rsx! {
            EmailEnvelopeCard { document_identifier, envelope: value }
        },
        None => rsx! {
            div {
                style: CARD_STYLE,
                div { style: "font-size: var(--x-text-section); line-height: var(--x-line-section); font-weight: 600; margin-bottom: 4px;", "{source.read().subject}" }
                div {
                    style: "font-size: 13px; color: rgba(0, 0, 0, 0.75); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;",
                    "{source.read().addresses}"
                }
            }
        },
    };

    let preamble = rsx! {
        if let Some((_, Err(error))) = envelope_reply {
            crate::components::error_boundary::ServerErrorDisplay { error }
        }
        {preamble}
    };

    // An email whose body was never extracted has no `email_parser` row to ask for, and
    // asking anyway is what put the text endpoint's `document not found!` where the body
    // belongs. Say what is true instead: the headers are here, the body is not. The other
    // text variants (the raw MIME envelope among them) stay in the source selector.
    if !source.read().has_body {
        return rsx! {
            PreviewWrapper {
                controls: rsx! { EmailMatchControls { document: document_identifier_value.clone(), find_query: find_query.clone() } },
                page: rsx! {
                    div {
                        style: "padding: 10px; overflow: auto; height: 100%;",
                        {preamble}
                        div {
                            style: "font-size: 13px; color: rgba(0, 0, 0, 0.6); font-style: italic; padding: 8px 2px;",
                            {tr!("preview-for-email-no-readable-body-is-available")}
                        }
                    }
                }
            }
        };
    }

    // `text_content.page_id` is 1-based, so page 0 matches no row and the body request
    // 404s. The range comes from the email source's own `email_parser` rows; the floor is
    // here as well because viewer state restored from an older URL carries no range.
    let min_page = source.read().min_page.max(1);
    let max_page = source.read().max_page.max(min_page);

    rsx! {
        DocumentPreviewTextWithSearch {
            document_identifier,
            source: DocumentTextSourceItem {
                extracted_by: EMAIL_TEXT_EXTRACTOR.to_string(),
                min_page,
                max_page,
            },
            preamble,
            flow_layout: true,
            match_controls: rsx! { EmailMatchControls { document: document_identifier_value, find_query } },
        }
    }
}

/// Everything above the body: banner, envelope, details, attachments, and the label.
#[component]
fn EmailEnvelopeCard(
    document_identifier: ReadSignal<DocumentIdentifier>,
    envelope: ReadSignal<EmailEnvelope>,
) -> Element {
    // One boolean, one component. The details panel is the only thing on this card that
    // has state, and it is deliberately NOT in the URL: it is a reading gesture, not a
    // place, and putting it in the URL would push a history entry per click.
    let card_id = use_hook(|| format!("x-email-card-{}", NEXT_EMAIL_CARD.fetch_add(1, std::sync::atomic::Ordering::Relaxed)));
    let mut show_details = use_signal(|| false);
    let control = use_context::<crate::pages::search_page::DocViewerStateControl>();
    let state = control.doc_viewer_state.read().clone().unwrap_or_default();
    let header_selection = state.selected_match.filter(|selection|
        selection.find_query == state.find_query && selection.extracted_by.starts_with("email-header:"));
    let scroll_card_id = card_id.clone();
    use_effect(use_reactive!(|header_selection| {
        if let Some(selection) = header_selection {
            show_details.set(true);
            let key = selection.extracted_by.strip_prefix("email-header:").unwrap_or_default();
            let key = serde_json::to_string(key).unwrap_or_default();
            let start = selection.ordinal;
            document::eval(&format!(r#"requestAnimationFrame(() => requestAnimationFrame(() => {{
                const root = document.getElementById('{scroll_card_id}');
                const field = Array.from(root?.querySelectorAll('[data-email-header]') || []).find(node => node.dataset.emailHeader === {key});
                const mark = field?.querySelector('[data-header-start="{start}"]');
                mark?.scrollIntoView({{block:'center',inline:'nearest'}});
            }}));"#));
        }
    }));

    let value = envelope.read().clone();
    let date_label = value.date_sent.map(common::document_provenance::format_epoch_utc);
    let from_line = value.from.iter().map(EmailParty::full).collect::<Vec<_>>().join(", ");
    let recipients = value.collapsed_recipients().shared();
    let secondary = value.secondary_counts().shared();

    rsx! {
        div {
            id: "{card_id}",
            style: CARD_STYLE,

            if let Some(parent) = value.parent.clone() {
                div {
                    class: "x-email-parent-banner",
                    style: BANNER_STYLE,
                    // Two Icon calls rather than one with a conditional icon: every
                    // icon is its own zero-sized type, so the two arms of an `if` are two
                    // different types and never unify.
                    if parent.kind == "reply" {
                        Icon { icon: MdReply, style: BANNER_GLYPH_STYLE }
                    } else {
                        Icon { icon: MdForward, style: BANNER_GLYPH_STYLE }
                    }
                    div {
                        style: "flex: 1 1 auto; min-width: 0;",
                        div {
                            "{parent.banner_verb().shared()} "
                            span { style: "font-weight: 600;", "\u{201c}{parent.subject}\u{201d}" }
                            if parent.is_inferred() {
                                // Said, not implied. This banner is the one place an
                                // inferred relation is stated as a sentence, and a
                                // sentence without a hedge reads as a fact.
                                span {
                                    style: "margin-left: 6px; font-size: 13px; color: rgba(0,0,0,0.55);",
                                    {tr!("preview-for-email-inferred")}
                                }
                            }
                        }
                        div {
                            style: "color: rgba(0,0,0,0.65); font-size: 13px;",
                            "{parent.from_display}"
                            if let Some(date) = parent.date_sent {
                                " \u{00b7} {common::document_provenance::format_epoch_utc(date)}"
                            }
                        }
                    }
                    Link {
                        to: Route::ViewDocumentPage {
                            document_identifier: parent.document_identifier.clone().into(),
                            doc_viewer_state: None.into(),
                            viewer_right_tab_state: Default::default(),
                        },
                        new_tab: true,
                        style: "display: flex; align-items: center; gap: 4px; color: #1a73e8; text-decoration: none; white-space: nowrap;",
                        {tr!("preview-for-email-open-parent")}
                        Icon { icon: MdOpenInNew, style: "width: 15px; height: 15px;" }
                    }
                }
            }

            div {
                style: "display: flex; align-items: baseline; gap: 8px;",
                Icon { icon: MdEmail, style: "width: 20px; height: 20px; flex: 0 0 auto; align-self: center;" }
                div {
                    style: "flex: 1 1 auto; min-width: 0; font-size: 17px; font-weight: 500; overflow-wrap: anywhere;",
                    {email_header_at(&value.subject, &value, "subject", 0)}
                }
                if let Some(date) = date_label.clone() {
                    div { style: "flex: 0 0 auto; font-size: 13px; color: rgba(0,0,0,0.75);", {email_header_at(&date, &value, "date", 0)} }
                }
            }

            if !from_line.is_empty() {
                div { style: "margin-top: 8px; font-size: 13px; overflow-wrap: anywhere;", {email_header_text(&from_line, &value)} }
            }
            if let Some(line) = recipients {
                div { style: "font-size: 13px; color: rgba(0,0,0,0.85); overflow-wrap: anywhere;", {tr!("preview-for-email-to")} {email_header_text(&line, &value)} }
            }

            div {
                style: "display: flex; align-items: center; gap: 10px; flex-wrap: wrap;",
                button {
                    class: "x-email-details-toggle",
                    style: LINK_ROW_STYLE,
                    onclick: move |_| show_details.toggle(),
                    if !secondary.is_empty() {
                        span { "{secondary}" }
                    }
                    span { if show_details() { {tr!("preview-for-email-hide-details")} } else { {tr!("preview-for-email-details")} } }
                    if show_details() {
                        Icon { icon: MdExpandLess, style: CHEVRON_STYLE }
                    } else {
                        Icon { icon: MdExpandMore, style: CHEVRON_STYLE }
                    }
                }
                if value.has_connections() {
                    Link {
                        class: "x-email-open-graph",
                        to: Route::EmailGraphPage {
                            centre: document_identifier().into(),
                            selected: None.into(),
                            doc_viewer_state: None.into(),
                        },
                        style: "font-size: 13px; color: #1a73e8; text-decoration: none;",
                        {tr!("preview-for-email-open-connected-emails", value_cluster_size: value.cluster_size)}
                    }
                }
            }

            if show_details() {
                EmailDetailsPanel { envelope }
            }

            if !value.attachments.is_empty() {
                div {
                    style: "display: flex; align-items: center; gap: 6px; margin-top: 12px; color: rgba(0,0,0,0.6);",
                    Icon { icon: MdAttachFile, style: "width: 18px; height: 18px;" }
                    span { style: "font-size: 13px; letter-spacing: 0.08em;", {tr!("preview-for-email-attachments")} }
                }
                div {
                    class: "x-email-attachments",
                    style: "display: flex; flex-wrap: wrap; gap: 10px; margin-top: 6px;",
                    for attachment in value.attachments.clone() {
                        a {
                            key: "{attachment.document_identifier.file_hash}-{attachment.file_name}",
                            class: "x-email-attachment-card",
                            style: ATTACHMENT_CARD_STYLE,
                            href: Route::ViewDocumentPage {
                                document_identifier: attachment.document_identifier.clone().into(),
                                doc_viewer_state: None.into(),
                                viewer_right_tab_state: Default::default(),
                            }.to_string(),
                            target: "_blank",
                            AttachmentGlyph { coarse_type: attachment.coarse_type.clone() }
                            div {
                                style: "flex: 1 1 auto; min-width: 0;",
                                div {
                                    style: "font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                                    title: "{attachment.file_name}",
                                    "{attachment.file_name}"
                                }
                                div { style: "font-size: 13px; color: rgba(0,0,0,0.5);", "{attachment.size_label()}" }
                            }
                            Icon { icon: MdOpenInNew, style: "width: 15px; height: 15px; flex: 0 0 auto; align-self: flex-start;" }
                        }
                    }
                }
            }

            div {
                style: "margin-top: 14px; font-size: 13px; color: rgba(0,0,0,0.6);",
                {tr!("preview-for-email-email-text-message")}
            }
        }
    }
}

fn email_header_text(text: &str, envelope: &EmailEnvelope) -> Element {
    match envelope.header_highlights.get(text) {
        Some(spans) => rsx! {
            for span in spans {
                if span.is_highlighted {
                    mark { class: "x-email-header-hit", "{span.text}" }
                } else {
                    span { "{span.text}" }
                }
            }
        },
        None => rsx! { span { "{text}" } },
    }
}

/// Header marks retain their field, occurrence, and character position.
fn email_header_at(text: &str, envelope: &EmailEnvelope, field: &str, occurrence: u32) -> Element {
    let key = format!("{field}:{occurrence}");
    let mut offset = 0u32;
    let spans = envelope.header_highlights.get(text).cloned().unwrap_or_default();
    rsx! {
        span { "data-email-header": "{key}",
            if spans.is_empty() { "{text}" }
            for span in spans {
                {let start = offset; offset += span.text.chars().count() as u32;
                    rsx! {
                        if span.is_highlighted {
                            mark { class: "x-email-header-hit", "data-header-start": "{start}", "{span.text}" }
                        } else { span { "{span.text}" } }
                    }
                }
            }
        }
    }
}

/// The expanded two-column participant table.
#[component]
fn EmailDetailsPanel(envelope: ReadSignal<EmailEnvelope>) -> Element {
    let value = envelope.read().clone();
    let roles = [
        ("from", "From:", value.from.clone()),
        ("to", "To:", value.to.clone()),
        ("cc", "Cc:", value.cc.clone()),
        ("bcc", "Bcc:", value.bcc.clone()),
    ];
    rsx! {
        div {
            class: "x-email-details-panel",
            style: "
                margin-top: 8px;
                padding: 10px 12px;
                border-radius: 8px;
                background: rgba(0, 0, 0, 0.04);
                font-size: 13px;
            ",
            table {
                style: "border-collapse: collapse;",
                tbody {
                    for (field, label, people) in roles {
                        if !people.is_empty() {
                            tr {
                                key: "{label}",
                                td {
                                    style: "padding: 1px 16px 1px 0; vertical-align: top; white-space: nowrap; color: rgba(0,0,0,0.75);",
                                    "{label}"
                                }
                                td {
                                    style: "padding: 1px 0; overflow-wrap: anywhere;",
                                    for (occurrence, person) in people.iter().enumerate() {
                                        div { key: "{label}-{occurrence}", {email_header_at(&person.full(), &value, field, occurrence as u32)} }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}

/// The file-type glyph on an attachment card. Coarse on purpose: the card is 40 px tall
/// and a precise MIME icon set would be a lot of bytes on the wire for a 20 px square.
#[component]
fn AttachmentGlyph(coarse_type: String) -> Element {
    rsx! {
        span {
            style: "flex: 0 0 auto; color: rgba(0,0,0,0.55);",
            crate::components::file_type_icon::FileTypeGlyphIcon { file_type: coarse_type, size: 22 }
        }
    }
}

#[server]
async fn get_email_envelope(
    document_identifier: DocumentIdentifier,
    find_query: String,
) -> Result<Option<EmailEnvelope>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    let mut envelope = backend::api::documents::get_email_graph::get_email_envelope(&user, document_identifier.clone())
        .await.map_err(crate::api::error_util::to_server_fn_error)?;
    if let Some(value) = &mut envelope {
        // The headers do not depend on their highlights. A failed highlight shows the
        // card without them, and the log keeps the error.
        match backend::api::documents::search_document_text::highlight_email_headers(
            &user, &document_identifier, &find_query, value,
        ).await {
            Ok(highlights) => value.header_highlights = highlights,
            Err(e) => dioxus::logger::tracing::error!(
                "email header highlight failed for {}: {e:#}", document_identifier.file_hash
            ),
        }
    }
    Ok(envelope)
}

/// Navigate the validated header and body targets in one order.
#[component]
pub fn EmailMatchControls(document: DocumentIdentifier, find_query: String) -> Element {
    use dioxus_free_icons::icons::md_navigation_icons::{MdArrowDownward, MdArrowUpward};
    use crate::components::search_components::search_result_list_controls::NavigationButton;
    let control = use_context::<crate::pages::search_page::DocViewerStateControl>();
    let sources = try_consume_context::<EmailNavigationSources>();
    let mut retry = use_signal(|| 0u64);
    let attempt = retry();
    let matches = use_resource(use_reactive!(|document, find_query, attempt| {
        async move {
            let result = get_email_document_matches(document.clone(), find_query.clone()).await;
            ((document, find_query, attempt), result)
        }
    }));
    let reply = matches.read().clone().filter(|(key, _)| key == &(document.clone(), find_query.clone(), attempt));
    let selected = control.doc_viewer_state.read().clone().unwrap_or_default().selected_match;
    let value = reply.as_ref().and_then(|(_, result)| result.as_ref().ok());
    let targets = value.map(|value| value.targets.clone()).unwrap_or_default();
    // No current target means the displayed source has no selected match. The counter
    // then shows 0, and the arrows start at the ends of the document order.
    let current = selected.as_ref().and_then(|selection| targets.iter().position(|target|
        selection_for(target, &find_query) == *selection));
    let count = targets.len();
    let number = current.map_or(0, |index| index + 1);
    let previous = current.map_or(count.saturating_sub(1), |index| if index == 0 { count.saturating_sub(1) } else { index - 1 });
    let next = current.map_or(0, |index| (index + 1) % count.max(1));
    let completeness = value.map(|value| value.completeness);
    let pending = reply.is_none();
    let failed = reply.as_ref().is_some_and(|(_, result)| result.is_err());
    let incomplete = completeness == Some(MatchCompleteness::AtLeast);
    let unavailable = completeness == Some(MatchCompleteness::Unavailable);
    let displayed_source = control.doc_viewer_state.read().as_ref().and_then(|state| state.selected_source.clone());
    let initial_index = initial_match_index(&targets, displayed_source.as_ref());
    let selection_current = current.is_some();
    let initial_query = find_query.clone();
    let navigate = Callback::new(move |index: usize| {
        let Some(target) = targets.get(index) else { return };
        let selection = selection_for(target, &find_query);
        let mut state = control.doc_viewer_state.peek().clone().unwrap_or_default();
        if state.find_query != find_query { return; }
        let available = sources.and_then(|sources| sources.0.peek().clone()).unwrap_or_default();
        // The displayed source stays when it shows the target. The Email source and the
        // Email body source both show email parser targets.
        let displayed = state.selected_source.as_ref().is_some_and(|source| target_in_source(target, source));
        if !displayed {
            state.selected_source = available.iter().find(|source| target_in_source(target, source))
                .map(DocumentSourceItem::route_identity).or(state.selected_source);
        }
        if matches!(target, DocumentMatchTarget::Body { .. }) { state.selected_source_page = Some(selection.page_id); }
        state.selected_match = Some(selection);
        control.set_doc_viewer_state.call(state);
    });
    use_effect(use_reactive!(|initial_index, selection_current, initial_query| {
        if control.doc_viewer_state.peek().as_ref().map(|state| state.find_query.clone()).unwrap_or_default() != initial_query { return; }
        if !selection_current {
            if let Some(index) = initial_index { navigate.call(index); }
        }
    }));
    rsx! {
        div { class: "x-email-match-controls", style: "display: flex; align-items: center; gap: 8px;",
            NavigationButton { icon: MdArrowUpward, label: tr!("preview-with-search-previous-hit"), disabled: count == 0,
                onclick: move |_| navigate.call(previous) }
            if pending {
                span { role: "status", {tr!("preview-with-search-searching")} }
            } else if failed {
                span { role: "status", {tr!("preview-with-search-match-search-failed")} }
            } else if unavailable {
                span { role: "status", "data-email-match-unavailable": "true", {tr!("text-data-viewer-highlighting-failed-the-stored-text")} }
            } else {
                span { "data-email-match-count": "{count}", "{number} / {count}" }
            }
            if incomplete { span { role: "status", {tr!("preview-with-search-search-incomplete")} } }
            NavigationButton { icon: MdArrowDownward, label: tr!("preview-with-search-next-hit"), disabled: count == 0,
                onclick: move |_| navigate.call(next) }
            if let Some((_, Err(error))) = reply {
                crate::components::error_boundary::ServerErrorDisplay { error }
                button { onclick: move |_| retry += 1, {tr!("collections-facet-pane-retry")} }
            }
        }
    }
}

/// The first target inside the displayed source. A source without a target gets none, so
/// a source that the person picks stays. A link that names no source opens the first target.
fn initial_match_index(targets: &[DocumentMatchTarget], displayed_source: Option<&DocumentSourceItem>) -> Option<usize> {
    match displayed_source {
        Some(source) => targets.iter().position(|target| target_in_source(target, source)),
        None => (!targets.is_empty()).then_some(0),
    }
}

/// Header targets and email parser body targets show in the Email source. Other body
/// targets show in the text source of their extractor.
fn target_in_source(target: &DocumentMatchTarget, source: &DocumentSourceItem) -> bool {
    match (target, source) {
        (DocumentMatchTarget::Header { .. }, DocumentSourceItem::Email(_)) => true,
        (DocumentMatchTarget::Body { extracted_by, .. }, DocumentSourceItem::Email(_)) => extracted_by == EMAIL_TEXT_EXTRACTOR,
        (DocumentMatchTarget::Body { extracted_by, .. }, DocumentSourceItem::Text(text)) => extracted_by == &text.extracted_by,
        _ => false,
    }
}

fn selection_for(target: &DocumentMatchTarget, query: &str) -> TextMatchSelection {
    match target {
        DocumentMatchTarget::Header { field, occurrence, start_char, end_char } => TextMatchSelection {
            extracted_by: format!("email-header:{field}:{occurrence}"), page_id: *end_char,
            find_query: query.into(), ordinal: *start_char,
        },
        DocumentMatchTarget::Body { extracted_by, page_id, ordinal } => TextMatchSelection {
            extracted_by: extracted_by.clone(), page_id: *page_id, find_query: query.into(), ordinal: *ordinal as u32,
        },
    }
}

#[server]
async fn get_email_document_matches(document: DocumentIdentifier, find_query: String) -> Result<DocumentMatches, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::document_matches::get_document_matches(&user, document, find_query)
        .await.map_err(crate::api::error_util::to_server_fn_error)
}

#[cfg(test)]
mod navigation_tests {
    use super::*;

    fn header() -> DocumentMatchTarget {
        DocumentMatchTarget::Header { field: "subject".into(), occurrence: 0, start_char: 0, end_char: 6 }
    }

    fn body(extracted_by: &str) -> DocumentMatchTarget {
        DocumentMatchTarget::Body { extracted_by: extracted_by.into(), page_id: 1, ordinal: 0 }
    }

    fn email_source() -> DocumentSourceItem {
        DocumentSourceItem::Email(DocumentEmailSourceItem {
            subject: String::new(), addresses: String::new(), date_sent: String::new(), raw_headers_json: String::new(),
            min_page: 1, max_page: 1, has_body: true,
        })
    }

    fn text_source(extracted_by: &str) -> DocumentSourceItem {
        DocumentSourceItem::Text(DocumentTextSourceItem { extracted_by: extracted_by.into(), min_page: 1, max_page: 1 })
    }

    #[test]
    fn the_email_source_selects_its_first_header_target() {
        let targets = vec![header(), body(EMAIL_TEXT_EXTRACTOR), body("raw_text")];
        assert_eq!(initial_match_index(&targets, Some(&email_source())), Some(0));
    }

    #[test]
    fn the_email_source_selects_an_email_body_target_after_other_sources() {
        let targets = vec![body("raw_text"), body(EMAIL_TEXT_EXTRACTOR)];
        assert_eq!(initial_match_index(&targets, Some(&email_source())), Some(1));
    }

    #[test]
    fn a_text_source_selects_the_targets_of_its_extractor() {
        let targets = vec![header(), body(EMAIL_TEXT_EXTRACTOR), body("raw_text")];
        assert_eq!(initial_match_index(&targets, Some(&text_source("raw_text"))), Some(2));
    }

    #[test]
    fn a_source_without_targets_selects_nothing() {
        let targets = vec![header(), body(EMAIL_TEXT_EXTRACTOR)];
        assert_eq!(initial_match_index(&targets, Some(&text_source("raw_text"))), None);
        assert_eq!(initial_match_index(&[body("raw_text")], Some(&email_source())), None);
        assert_eq!(initial_match_index(&[], Some(&email_source())), None);
    }

    #[test]
    fn a_link_without_a_source_selects_the_first_document_target() {
        assert_eq!(initial_match_index(&[body("raw_text"), header()], None), Some(0));
        assert_eq!(initial_match_index(&[], None), None);
    }

    #[test]
    fn repeated_header_values_keep_distinct_url_selections() {
        let first = DocumentMatchTarget::Header { field: "to".into(), occurrence: 0, start_char: 0, end_char: 6 };
        let second = DocumentMatchTarget::Header { field: "to".into(), occurrence: 1, start_char: 0, end_char: 6 };
        assert_ne!(selection_for(&first, "quokka"), selection_for(&second, "quokka"));
        let selected = selection_for(&second, "quokka");
        let encoded = crate::data_definitions::url_param::UrlParam(selected.clone()).to_string();
        let restored: crate::data_definitions::url_param::UrlParam<TextMatchSelection> = encoded.parse().unwrap();
        assert_eq!(restored.0, selected);
    }
}
