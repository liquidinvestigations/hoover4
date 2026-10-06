//! Read-only red flag categories, calibration, and terms.

use crate::components::{error_boundary::ServerErrorDisplay, suspend_boundary::LoadingIndicator};
use common::signals::{SignalCatalog, SignalCategory, SignalTerm};
use dioxus::prelude::*;

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
            main { style: "max-width: 1100px; margin: auto; padding: 24px;",
                h1 { "Red flag terms" }
                p { "These terms identify passages for review. A match does not establish misconduct." }
                for category in catalog.categories {
                    SignalCategoryTerms {
                        key: "{category.id}", category: category.clone(),
                        terms: catalog.terms.iter().filter(|term| term.category == category.id).cloned().collect::<Vec<_>>(),
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
            p { "{category.does_not_prove}" }
            p { {format!("Tier points are L {}, M {}, and H {}.", category.points["L"], category.points["M"], category.points["H"])} }
            p { "A passage needs {category.threshold} points and {category.min_concepts} distinct concepts. L points contribute at most {category.l_cap}." }
            if category.low_recall {
                p { role: "note", "This category has low recall on business mail. Documents without a flag can still be relevant." }
            }
            details {
                summary { "Show {terms.len()} lexicon terms." }
                table {
                    thead { tr { th { "Language" } th { "Tier" } th { "Term" } th { "Concept" } th { "Speaker" } } }
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
