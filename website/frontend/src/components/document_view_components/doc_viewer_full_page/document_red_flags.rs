//! Stored red flag excerpts in the document Entities tab.

use crate::{
    components::{error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator},
    pages::signal_terms::get_signal_catalog,
    routes::Route,
};
use common::{search_result::DocumentIdentifier, signals::DocumentSignals};
use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::md_action_icons::MdInfo};

#[server]
async fn get_document_signals(
    identifier: DocumentIdentifier,
) -> Result<DocumentSignals, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::signals::document_signals(&user, identifier)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

#[component]
pub fn DocumentRedFlags(document_identifier: ReadSignal<DocumentIdentifier>) -> Element {
    let identifier = document_identifier();
    let evidence = use_resource(use_reactive!(|identifier| get_document_signals(identifier)));
    let catalog = use_resource(|| get_signal_catalog(false));
    let titles = catalog
        .read()
        .as_ref()
        .and_then(|reply| reply.as_ref().ok())
        .map(|catalog| {
            catalog
                .categories
                .iter()
                .map(|row| (row.id.clone(), row.title.clone()))
                .collect::<std::collections::BTreeMap<_, _>>()
        })
        .unwrap_or_default();
    let body = match evidence.read().clone() {
        None => rsx! { LoadingIndicator {} },
        Some(Err(error)) => rsx! { ServerErrorDisplay { error } },
        Some(Ok(evidence)) => rsx! {
            if evidence.clusters.is_empty() { p { "No red flag passage was found in this document." } }
            for (index, cluster) in evidence.clusters.iter().enumerate() {
                section { key: "{index}", class: "x-red-flag-passage",
                    h4 { "{titles.get(&cluster.category).unwrap_or(&cluster.category)}" }
                    h5 {
                        "{common::document_sources::text_source_label(&cluster.extracted_by)}, page {cluster.page_id}, "
                        strong { "{cluster.points} points" }
                        "."
                    }
                    p { class: "x-red-flag-excerpt",
                        for (part, marked) in marked_parts(&cluster.excerpt, &cluster.hit_starts, &cluster.hit_ends) {
                            if marked { mark { "{part}" } } else { span { "{part}" } }
                        }
                    }
                }
            }
            details {
                summary { "Other hits ({evidence.other_hits.len()})" }
                for (index, hit) in evidence.other_hits.iter().enumerate() {
                    p { key: "{index}",
                        "{titles.get(&hit.category).unwrap_or(&hit.category)}. {hit.text}. Page {hit.page_id}."
                        if !hit.flags.is_empty() { span { {format!(" Flags: {}.", hit.flags.join(", "))} } }
                    }
                }
            }
        },
    };
    rsx! {
        section { "data-red-flags": "true", class: "x-document-red-flags",
            h3 {
                Link { to: Route::SignalTermsPage {}, new_tab: true, aria_label: "View category definitions and terms",
                    Icon { icon: MdInfo, style: "width: 16px; height: 16px; flex-shrink: 0;" }
                    "Red flags"
                }
            }
            if let Some(Err(error)) = catalog.read().clone() { ServerErrorDisplay { error } }
            {body}
        }
    }
}

fn marked_parts(text: &str, starts: &[u32], ends: &[u32]) -> Vec<(String, bool)> {
    let mut ranges: Vec<(usize, usize)> = starts
        .iter()
        .zip(ends)
        .map(|(a, b)| (*a as usize, *b as usize))
        .filter(|(a, b)| {
            a < b && *b <= text.len() && text.is_char_boundary(*a) && text.is_char_boundary(*b)
        })
        .collect();
    ranges.sort();
    let mut merged: Vec<(usize, usize)> = Vec::new();
    for (start, end) in ranges {
        if let Some(last) = merged.last_mut()
            && start <= last.1
        {
            last.1 = last.1.max(end);
            continue;
        }
        merged.push((start, end));
    }
    let mut parts = Vec::new();
    let mut offset = 0;
    for (start, end) in merged {
        if start > offset {
            parts.push((text[offset..start].to_string(), false));
        }
        parts.push((text[start..end].to_string(), true));
        offset = end;
    }
    if offset < text.len() {
        parts.push((text[offset..].to_string(), false));
    }
    parts
}

#[cfg(test)]
mod tests {
    use super::marked_parts;

    #[test]
    fn highlights_merge_unicode_ranges_and_preserve_source_text() {
        let text = "á <script> beta";
        let parts = marked_parts(text, &[0, 3, 5, 1, 99], &[2, 11, 11, 2, 100]);
        assert_eq!(
            parts,
            vec![
                ("á".into(), true),
                (" ".into(), false),
                ("<script>".into(), true),
                (" beta".into(), false)
            ]
        );
        assert_eq!(
            parts.into_iter().map(|(text, _)| text).collect::<String>(),
            text
        );
    }
}
