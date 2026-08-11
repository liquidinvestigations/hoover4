//! The page for a URL that names nothing.
//!
//! It is a ROUTE, not an error boundary. A mistyped path and a bookmark whose route
//! parameter does not decode are both ordinary things a user does, and handing them to
//! `GlobalErrorBoundary` gives them a red "Error" heading over a `ParseRouteError` debug
//! dump. The boundary is for genuine panics; this route takes the traffic that is not a
//! panic in the first place.

use dioxus::prelude::*;
use dioxus_free_icons::Icon;
use dioxus_free_icons::icons::md_action_icons::MdSearch;

use crate::routes::Route;

const CARD_STYLE: &str = "
    display: flex;
    flex-direction: column;
    gap: 14px;
    align-items: flex-start;
    max-width: 640px;
    padding: 28px 32px;
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 12px;
";

const LINK_STYLE: &str = "
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 16px;
    border-radius: 10px;
    border: 1px solid #2563EB;
    color: #2563EB;
    text-decoration: none;
    font-size: 16px;
    font-weight: 500;
";

#[component]
pub fn NotFoundPage(segments: Vec<String>) -> Element {
    // Reconstructed rather than read from the location: the router hands this component
    // the segments it matched, which is exactly the part of the URL that named nothing.
    let path = format!("/{}", segments.join("/"));

    rsx! {
        Title { "Hoover Search - Page not found" }
        div {
            id: "x-not-found",
            style: "
                display: flex;
                flex-direction: column;
                gap: 20px;
                width: 100%;
                height: 100%;
                padding: 48px 40px;
                background: #F5F6F8;
                box-sizing: border-box;
                overflow: auto;
            ",
            div {
                style: CARD_STYLE,
                h1 {
                    style: "font-size: 34px; font-weight: 600; color: #111827; margin: 0;",
                    "Page not found"
                }
                p {
                    style: "font-size: 16px; line-height: 24px; color: #4B5563; margin: 0;",
                    "Nothing here answers to"
                }
                code {
                    style: "
                        font-size: 15px;
                        color: #374151;
                        background: #F3F4F6;
                        border-radius: 8px;
                        padding: 8px 12px;
                        max-width: 100%;
                        overflow-wrap: anywhere;
                    ",
                    "{path}"
                }
                p {
                    style: "font-size: 15px; line-height: 23px; color: #6B7280; margin: 0;",
                    "The address may be mistyped, or it may be a link to something that has
                     since been renamed or removed."
                }
                div {
                    style: "display: flex; flex-direction: row; gap: 12px; flex-wrap: wrap;",
                    Link { to: Route::HomePage {}, style: LINK_STYLE, "Go to the home page" }
                    Link {
                        to: Route::search_page_from_query(common::search_query::SearchQuery::default()),
                        style: LINK_STYLE,
                        Icon { icon: MdSearch, style: "width: 18px; height: 18px;" }
                        "Search"
                    }
                }
            }
        }
    }
}
