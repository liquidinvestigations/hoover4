//! Read-only red flag categories, calibration, and terms.

use crate::components::{error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator};
use common::signals::{SignalCatalog, SignalCategory, SignalTerm};
use dioxus::prelude::*;
use crate::tr;

#[server]
pub async fn get_signal_catalog(include_terms: bool) -> Result<SignalCatalog, ServerFnError> {
    let user = crate::api::server_auth::extract_user().await?;
    backend::api::documents::signals::signal_catalog(&user, include_terms)
        .await
        .map_err(crate::api::error_util::to_server_fn_error)
}

#[component]
pub fn SignalTermsPage() -> Element {
    let catalog = use_resource(|| get_signal_catalog(true));
    match catalog.read().clone() {
        None => rsx! { LoadingIndicator {} },
        Some(Err(error)) => rsx! { ServerErrorDisplay { error } },
        Some(Ok(catalog)) => rsx! {
            main { class: "x-signal-terms",
              div { class: "x-signal-terms-content",
                h1 { {tr!("signal-terms-red-flag-terms")} }
                p { {tr!("signal-terms-these-terms-identify-passages-for")} }
                for category in catalog.categories {
                    SignalCategoryTerms {
                        key: "{category.id}", category: category.clone(),
                        terms: catalog.terms.iter().filter(|term| term.category == category.id).cloned().collect::<Vec<_>>(),
                    }
                }
              }
            }
        },
    }
}

#[component]
fn SignalCategoryTerms(category: SignalCategory, terms: Vec<SignalTerm>) -> Element {
    rsx! {
        section { id: "{category.id}", style: "margin-bottom: 24px;",
            h2 { "{category.title}" }
            p { "{category.catches}" }
            p {
                {tr!("signal-terms-tier-points-are")}
                code { "L = {category.points[\"L\"]}" }
                ", "
                code { "M = {category.points[\"M\"]}" }
                {tr!("signal-terms-and")}
                code { "H = {category.points[\"H\"]}" }
                "."
            }
            p { {tr!("signal-terms-a-passage-needs-points-and", category_threshold: category.threshold.to_string(), category_min_concepts: category.min_concepts.to_string(), category_l_cap: category.l_cap.to_string())} }
            details {
                summary { {tr!("signal-terms-show-lexicon-terms", terms_len: terms.len())} }
                table {
                    thead { tr { th { {tr!("signal-terms-language")} } th { {tr!("signal-terms-tier")} } th { {tr!("signal-terms-term")} } th { {tr!("signal-terms-concept")} } th { {tr!("signal-terms-speaker")} } } }
                    tbody {
                        for (index, term) in terms.iter().enumerate() {
                            tr { key: "{index}",
                                td { "{common::signals::language_name(&term.lang)}" }
                                td { "{term.tier}" } td { "{term.term}" }
                                td { "{term.concept}" } td { "{term.speaker}" }
                            }
                        }
                    }
                }
            }
        }
    }
}
