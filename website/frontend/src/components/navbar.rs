//! Top navigation bar component.

#![allow(unused_imports)]
use dioxus::prelude::*;
use dioxus_primitives::ContentAlign;
use dioxus_primitives::ContentSide;

use crate::components::error_boundary::GlobalErrorBoundary;
use crate::components::hover_card::HoverCard;
use crate::components::hover_card::HoverCardContent;
use crate::components::hover_card::HoverCardTrigger;
use crate::data_definitions::url_param::UrlParam;
use common::search_query::SearchQuery;
use crate::routes::Route;

use crate::pages::home_page::HomePage;
use crate::pages::search_page::SearchPage;
use crate::pages::file_browser_page::FileBrowserPage;
use crate::pages::chatbot_page::ChatbotPage;

use dioxus_free_icons::icons::md_action_icons::MdHome;
use dioxus_free_icons::icons::md_action_icons::MdSearch;
use dioxus_free_icons::icons::md_file_icons::MdFolder;
use dioxus_free_icons::icons::md_communication_icons::MdChat;
use dioxus_free_icons::icons::md_social_icons::MdPerson;
use dioxus_free_icons::{Icon, IconShape};


/// Shared navbar component.
#[component]
pub fn Navbar() -> Element {
    rsx! {

        div {
            id:"x-nav-container",

            style:"
                display:flex;
                flex-direction: row;
                width: 100%;
                height: 100%;
            ",


            div {
                id:"x-nav-sidebar",
                style:"
                    display:flex;
                    flex-direction: column;
                    gap: 40px;
                    width: 70px;
                    height: 100%;
                    background-color: #1C212D;
                    border: 1px solid #000000;
                    padding: 16px;
                ",

                // top part
                NavbarTopLogo{},
                NavbarTopIconLinks{},

                // empty space
                div {
                    style: "flex-grow:1;"
                }
                // bottom part
                NavbarBottomIconLinks{},
            },

            div {
                id:"x-page-container",
                style: "flex-grow:1; min-width: 100px;",
                GlobalErrorBoundary {
                    boundary_name: "Navbar".to_string(),
                    Outlet::<Route> {}
                }
            }
        }

    }
}

#[component]
fn NavbarTopLogo() -> Element {
    rsx! {
        Link {
            to: Route::HomePage { },
            img { src: asset!("assets/favicon-filled.png"), style: "width: 38px; height: 38px;" }
        }
    }
}

#[component]
fn NavbarTopIconLinks() -> Element {
    rsx! {
        div {
            style: "
                display:flex;
                flex-direction: column;
                gap: 24px;
                width: 38px;
                align-items: center;
                justify-content: center;
            ",
            IconLink { to: Route::HomePage { }, icon: MdHome, label: "Home" }
            IconLink { to: Route::search_page_from_query(SearchQuery::default()), icon: MdSearch, label: "Search" }
            IconLink { to: Route::FileBrowserPage { }, icon: MdFolder, label: "File Browser" }
            // IconLink { to: Route::ChatbotPage { }, icon: MdChat, label: "Chatbot" }
        }
    }
}


#[component]
fn NavbarBottomIconLinks() -> Element {
    rsx! {

        div {
            style: "
                display:flex;
                flex-direction: column;
                gap: 24px;
                width: 38px;
                align-items: center;
                justify-content: center;
            ",

            IconLink { to: Route::HomePage { }, icon: MdPerson, label: "Profile" }
        }
    }
}

#[component]
fn IconLink<T: IconShape + Clone + PartialEq + 'static> (to: Route, icon: T, label: String) -> Element {
    rsx! {
        HoverCard {
            HoverCardTrigger {

                Link {
                    to: to,
                    span {
                        style: "color:white;",
                        Icon { icon: icon, style: "width: 26px; height: 26px;" }
                        // "{label}"
                    }
                }
            },
            HoverCardContent {
                side: ContentSide::Right,
                align: ContentAlign::Start,
                div {
                    style: "
                        color:black;
                        background-color:white;
                        padding:10px;
                        border-radius:5px;
                        border: 1px solid black;
                        width: fit-content;
                    ",
                    "{label}",
                }
            }

        }
    }
}