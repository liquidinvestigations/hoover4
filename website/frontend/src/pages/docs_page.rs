//! The manual pages: `/docs` (the user manual) and `/docs/admin` (the administration manual).
//!
//! The server renders the Markdown of the image to HTML (`backend::api::manual`), and the
//! page shows it beside a list of the sections. The anchor of the address (`#4-search`)
//! scrolls to its section. A user who is not an administrator gets the not-found page for
//! the administration manual.

use dioxus::prelude::*;

use crate::api::error_util::user_facing_message;
use crate::api::manual_api::manual_page;
use crate::components::session_context::use_session_user;
use crate::pages::not_found_page::NotFoundPage;
use crate::routes::Route;
use crate::tr;

#[component]
pub fn DocsPage(section: String) -> Element {
    rsx! { ManualView { admin: false, section } }
}

#[component]
pub fn DocsAdminPage(section: String) -> Element {
    rsx! { ManualView { admin: true, section } }
}

fn section_route(admin: bool, section: String) -> Route {
    if admin { Route::DocsAdminPage { section } } else { Route::DocsPage { section } }
}

#[component]
fn ManualView(admin: bool, section: String) -> Element {
    let page = use_resource(use_reactive!(|admin| async move { manual_page(admin).await }));
    let user = use_session_user();
    let is_admin = user.as_ref().is_some_and(|u| u.is_admin);
    let loaded = matches!(&*page.read(), Some(Ok(_)));
    // After the HTML is in the page, and on each change of the anchor.
    use_effect(use_reactive!(|section, loaded| {
        if loaded && !section.is_empty() {
            let id = serde_json::to_string(&section).unwrap_or_default();
            document::eval(&format!("document.getElementById({id})?.scrollIntoView({{block: 'start'}});"));
        }
    }));
    let result = page.read().clone();
    match result {
        None => rsx! {
            div { class: "x-manual-state", {tr!("docs-loading-the-manual")} }
        },
        Some(Err(ServerFnError::ServerError { code: 404, .. })) => rsx! {
            NotFoundPage { segments: vec!["docs".to_string(), "admin".to_string()] }
        },
        Some(Err(error)) => rsx! {
            div { class: "x-manual-state x-error-display", style: "color: var(--x-danger);",
                {tr!("docs-could-not-load-the-manual", message: user_facing_message(&error))}
            }
        },
        Some(Ok(manual)) => rsx! {
            Title { "{manual.title}" }
            div { class: "x-manual-layout",
                nav { class: "x-manual-contents", "aria-label": tr!("docs-contents"),
                    if is_admin {
                        Link {
                            class: "x-manual-other",
                            to: section_route(!admin, String::new()),
                            if admin { {tr!("docs-user-manual")} } else { {tr!("docs-administration-manual")} }
                        }
                    }
                    for heading in manual.headings.iter().cloned() {
                        Link {
                            key: "{heading.slug}",
                            class: if heading.level > 2 { "x-manual-link x-manual-link-sub" } else { "x-manual-link" },
                            "aria-current": if heading.slug == section { "location" } else { "false" },
                            to: section_route(admin, heading.slug.clone()),
                            "{heading.title}"
                        }
                    }
                }
                article { class: "x-manual", dangerous_inner_html: "{manual.html}" }
            }
        },
    }
}
