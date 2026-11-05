//! Top navigation bar component.

#![allow(unused_imports)]
use dioxus::prelude::*;
use dioxus_primitives::ContentAlign;
use dioxus_primitives::ContentSide;

use crate::components::error_boundary::GlobalErrorBoundary;
use crate::components::feedback_control::{use_feedback_provider, FeedbackRailButton};
use crate::components::hover_card::HoverCard;
use crate::components::hover_card::HoverCardContent;
use crate::components::hover_card::HoverCardTrigger;
use crate::components::session_context::use_session_user;
use crate::data_definitions::url_param::UrlParam;
use crate::routes::Route;
use crate::tr;
use common::search_query::SearchQuery;

use crate::pages::file_browser_page::FileBrowserPage;
use crate::pages::home_page::HomePage;
use crate::pages::search_page::SearchPage;

use dioxus_free_icons::icons::md_action_icons::MdHome;
use dioxus_free_icons::icons::md_action_icons::MdSearch;
use dioxus_free_icons::icons::md_action_icons::MdSettings;
use dioxus_free_icons::icons::md_communication_icons::MdChat;
use dioxus_free_icons::icons::md_file_icons::MdFolder;
use dioxus_free_icons::{Icon, IconShape};

/// Shared navbar component.
#[component]
pub fn Navbar() -> Element {
    // The rail control and the home page card share one feedback state.
    use_feedback_provider();
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
                    height: 100%;
                    background-color: #1C212D;
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

            // The page frame is the containing block of every fixed overlay of a page, so a
            // page overlay covers the page area and the rail stays usable (`main.css`). The
            // frame does not scroll: a scrolling containing block would move its overlays
            // with the content.
            div {
                class: "x-page-frame",
                div {
                    id:"x-page-container",
                    // A page that does not fit scrolls inside this container, so a narrow
                    // window or a high browser zoom never hides a control.
                    style: "width: 100%; height: 100%; overflow: auto;",
                    GlobalErrorBoundary {
                        boundary_name: "Navbar".to_string(),
                        Outlet::<Route> {}
                    }
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
            img { src: asset!("assets/nav-logo.svg"), alt: tr!("navbar-hoover"), style: "width: 100%; height: auto;" }
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
                width: 100%;
                align-items: center;
                justify-content: center;
            ",
            IconLink { to: Route::HomePage { }, icon: MdHome, label: tr!("nav-home") }
            IconLink { to: Route::search_page_from_query(SearchQuery::default()), icon: MdSearch, label: tr!("nav-search") }
            IconLink {
                to: Route::storage_root(),
                icon: MdFolder,
                label: tr!("nav-file-browser"),
            }
            IconLink { to: Route::AiChatPage {}, icon: MdChat, label: tr!("nav-ai-chat") }
        }
    }
}

#[component]
fn NavbarBottomIconLinks() -> Element {
    // The Admin link reads the shared session. A second whoami here would send
    // another identity request on every navbar render.
    let user = use_session_user();
    let show_admin = user.as_ref().is_some_and(|u| u.is_admin);
    rsx! {

        div {
            style: "
                display:flex;
                flex-direction: column;
                gap: 24px;
                padding-bottom: max(12px, env(safe-area-inset-bottom));
                width: 100%;
                align-items: center;
                justify-content: center;
            ",

            if show_admin {
                IconLink { to: Route::AdminDashboardPage { }, icon: MdSettings, label: tr!("nav-admin") }
            }
            FeedbackRailButton {}
            LanguageSettingsLink {}
        }
    }
}

/// The language settings link at the bottom of the rail: the flag of the interface language
/// that the page shows.
#[component]
fn LanguageSettingsLink() -> Element {
    let code = crate::i18n::use_active_language().settings.read().interface.clone();
    rsx! {
        RailHint {
            label: tr!("nav-language-settings"),
            Link {
                to: Route::LanguageSettingsPage {},
                class: "x-rail-language",
                "data-interface-language": "{code}",
                style: "display: flex;",
                img { src: crate::i18n::flag_src(&code), alt: tr!("nav-language-settings"), width: "26", height: "26" }
            }
        }
    }
}

#[component]
fn IconLink<T: IconShape + Clone + PartialEq + 'static>(
    to: Route,
    icon: T,
    label: String,
) -> Element {
    rsx! {
        RailHint {
            label,
            Link {
                to: to,
                style: "color: white; display: flex;",
                Icon { icon: icon, style: "width: 26px; height: 26px;" }
            }
        }
    }
}

/// A rail control with its name in a card to the right, level with the icon.
/// `main.css` sizes the card under `#x-nav-sidebar`.
#[component]
pub fn RailHint(label: String, children: Element) -> Element {
    rsx! {
        HoverCard {
            HoverCardTrigger { {children} }
            HoverCardContent {
                side: ContentSide::Right,
                align: ContentAlign::Center,
                div { class: "x-rail-hint", "{label}" }
            }
        }
    }
}
