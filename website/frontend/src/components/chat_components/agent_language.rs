//! The agent language control of the chat composer: the flag and the code of the language
//! that the agent answers in. A click opens the settings page in a new tab. When the page
//! gets the focus again, the control reads the settings again, so a change in that tab
//! shows here and applies to the next message.

use dioxus::prelude::*;
use dioxus_free_icons::{Icon, icons::md_navigation_icons::MdArrowDropDown};

use crate::api::settings_api::language_settings;
use crate::i18n::{flag_src, use_active_language};
use crate::pages::settings_page::language_name;
use crate::tr;

/// Sends one message each time the window gets the focus.
// i18n: data, a script
const FOCUS_SCRIPT: &str = "window.addEventListener('focus', () => dioxus.send(true));";

#[component]
pub fn AgentLanguageControl() -> Element {
    let mut active = use_active_language();
    use_future(move || async move {
        let mut focus = document::eval(FOCUS_SCRIPT);
        while focus.recv::<bool>().await.is_ok() {
            if let Ok(settings) = language_settings().await {
                if settings != *active.settings.peek() {
                    active.apply(settings);
                }
            }
        }
    });
    let code = active.settings.read().agent.clone();
    let name = language_name(&code);
    rsx! {
        a {
            class: "x-agent-language",
            "data-agent-language": "{code}",
            href: "/settings",
            target: "_blank",
            rel: "noopener",
            title: tr!("chat-composer-agent-language-title", language: name.clone()),
            "aria-label": tr!("chat-composer-agent-language-title", language: name),
            img { src: flag_src(&code), alt: "", width: "18", height: "18" }
            span { "{code}" }
            Icon { icon: MdArrowDropDown, style: "width: 18px; height: 18px;" }
        }
    }
}
