//! The email viewer: the parent banner, the envelope, the attachment cards, and the
//! body.
//!
//! Everything above the body comes from ONE server call ([`get_email_envelope`]). It
//! could have been four — headers, participants, attachments, cluster — but they all
//! describe the same message and four resources on one card is four loading states that
//! settle in an unpredictable order, which reads as the card rebuilding itself.
//!
//! The details panel expands IN FLOW rather than as a popover: it pushes the attachments
//! and the body down. A popover over a document body hides the thing the reader is
//! looking at, and the expanded state is a reading state, not a menu.

use common::document_sources::{DocumentEmailSourceItem, DocumentTextSourceItem, EMAIL_TEXT_EXTRACTOR};
use common::email_graph::{EmailEnvelope, EmailParty};
use common::search_result::DocumentIdentifier;
use dioxus::prelude::*;
use dioxus_free_icons::{
    Icon,
    icons::{
        md_action_icons::{MdDescription, MdOpenInNew},
        md_communication_icons::MdEmail,
        md_content_icons::{MdForward, MdReply},
        md_editor_icons::MdAttachFile,
        md_image_icons::{MdImage, MdPictureAsPdf},
        md_navigation_icons::{MdExpandLess, MdExpandMore},
    },
};

use crate::components::document_view_components::doc_preview_for_search::text_preview_with_search::DocumentPreviewTextWithSearch;
use crate::routes::Route;

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
    font-size: 14px;
";

const LINK_ROW_STYLE: &str = "
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 2px;
    font-size: 14px;
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
    // By value through `use_reactive`: a `ReadSignal` prop is a fresh signal on every
    // parent render, so a resource that subscribes to the prop never re-runs when the
    // selected document changes.
    let envelope = use_resource(use_reactive!(|document_identifier_value| {
        async move { get_email_envelope(document_identifier_value).await }
    }));

    // The fallback is the flat header blob the source item already carries, so a failed
    // or still-loading envelope degrades to what this viewer showed before rather than
    // to a blank card.
    let envelope_value: Option<EmailEnvelope> = match envelope() {
        Some(Ok(Some(value))) => Some(value),
        _ => None,
    };

    let preamble = match envelope_value {
        Some(value) => rsx! {
            EmailEnvelopeCard { document_identifier, envelope: value }
        },
        None => rsx! {
            div {
                style: CARD_STYLE,
                div { style: "font-size: 18px; font-weight: 600; margin-bottom: 6px;", "{source.read().subject}" }
                div {
                    style: "font-size: 14px; color: rgba(0, 0, 0, 0.75); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%;",
                    "{source.read().addresses}"
                }
            }
        },
    };

    // An email whose body was never extracted has no `email_parser` row to ask for, and
    // asking anyway is what put the text endpoint's `document not found!` where the body
    // belongs. Say what is true instead: the headers are here, the body is not. The other
    // text variants — the raw MIME envelope among them — stay in the source selector.
    if !source.read().has_body {
        return rsx! {
            div {
                style: "padding: 10px; overflow: auto; height: 100%;",
                {preamble}
                div {
                    style: "font-size: 14px; color: rgba(0, 0, 0, 0.6); font-style: italic; padding: 8px 2px;",
                    "No body text was extracted from this email. Its headers are above; the message itself may be an attachment, may have carried no plain-text part, or may be too short to store."
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
    let mut show_details = use_signal(|| false);

    let value = envelope.read().clone();
    let date_label = value.date_sent.map(common::document_provenance::format_epoch_utc);
    let from_line = value.from.iter().map(EmailParty::full).collect::<Vec<_>>().join(", ");
    let recipients = value.collapsed_recipients();
    let secondary = value.secondary_counts();

    rsx! {
        div {
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
                            "{parent.banner_verb()} "
                            span { style: "font-weight: 600;", "\u{201c}{parent.subject}\u{201d}" }
                            if parent.is_inferred() {
                                // Said, not implied. This banner is the one place an
                                // inferred relation is stated as a sentence, and a
                                // sentence without a hedge reads as a fact.
                                span {
                                    style: "margin-left: 6px; font-size: 12px; color: rgba(0,0,0,0.55);",
                                    "(inferred)"
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
                        "Open parent"
                        Icon { icon: MdOpenInNew, style: "width: 15px; height: 15px;" }
                    }
                }
            }

            div {
                style: "display: flex; align-items: baseline; gap: 8px;",
                Icon { icon: MdEmail, style: "width: 20px; height: 20px; flex: 0 0 auto; align-self: center;" }
                div {
                    style: "flex: 1 1 auto; min-width: 0; font-size: 17px; font-weight: 500; overflow-wrap: anywhere;",
                    "{value.subject}"
                }
                if let Some(date) = date_label.clone() {
                    div { style: "flex: 0 0 auto; font-size: 14px; color: rgba(0,0,0,0.75);", "{date}" }
                }
            }

            if !from_line.is_empty() {
                div { style: "margin-top: 8px; font-size: 14px; overflow-wrap: anywhere;", "{from_line}" }
            }
            if let Some(line) = recipients {
                div { style: "font-size: 14px; color: rgba(0,0,0,0.85); overflow-wrap: anywhere;", "to {line}" }
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
                    span { if show_details() { "hide details" } else { "details" } }
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
                        style: "font-size: 14px; color: #1a73e8; text-decoration: none;",
                        "Open Connected Emails ({value.cluster_size})"
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
                    span { style: "font-size: 13px; letter-spacing: 0.08em;", "ATTACHMENTS" }
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
                                    style: "font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;",
                                    title: "{attachment.file_name}",
                                    "{attachment.file_name}"
                                }
                                div { style: "font-size: 12px; color: rgba(0,0,0,0.5);", "{attachment.size_label()}" }
                            }
                            Icon { icon: MdOpenInNew, style: "width: 15px; height: 15px; flex: 0 0 auto; align-self: flex-start;" }
                        }
                    }
                }
            }

            div {
                style: "margin-top: 14px; font-size: 14px; color: rgba(0,0,0,0.6);",
                "Email text Message"
            }
        }
    }
}

/// The expanded two-column participant table.
#[component]
fn EmailDetailsPanel(envelope: ReadSignal<EmailEnvelope>) -> Element {
    let value = envelope.read().clone();
    let roles = [
        ("From:", value.from.clone()),
        ("To:", value.to.clone()),
        ("Cc:", value.cc.clone()),
        ("Bcc:", value.bcc.clone()),
    ];
    rsx! {
        div {
            class: "x-email-details-panel",
            style: "
                margin-top: 8px;
                padding: 10px 12px;
                border-radius: 8px;
                background: rgba(0, 0, 0, 0.04);
                font-size: 14px;
            ",
            table {
                style: "border-collapse: collapse;",
                tbody {
                    for (label, people) in roles {
                        if !people.is_empty() {
                            tr {
                                key: "{label}",
                                td {
                                    style: "padding: 1px 16px 1px 0; vertical-align: top; white-space: nowrap; color: rgba(0,0,0,0.75);",
                                    "{label}"
                                }
                                td {
                                    style: "padding: 1px 0; overflow-wrap: anywhere;",
                                    for person in people {
                                        div { key: "{person.address}-{person.display_name}", "{person.full()}" }
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
    let style = "width: 22px; height: 22px; flex: 0 0 auto; color: rgba(0,0,0,0.55);";
    rsx! {
        match coarse_type.as_str() {
            "pdf" => rsx! { Icon { icon: MdPictureAsPdf, style } },
            "image" => rsx! { Icon { icon: MdImage, style } },
            "email" => rsx! { Icon { icon: MdEmail, style } },
            _ => rsx! { Icon { icon: MdDescription, style } },
        }
    }
}

#[server]
async fn get_email_envelope(
    document_identifier: DocumentIdentifier,
) -> Result<Option<EmailEnvelope>, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::get_email_graph::get_email_envelope(&user, document_identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}
