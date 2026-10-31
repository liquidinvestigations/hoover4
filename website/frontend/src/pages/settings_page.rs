//! The settings of the signed-in person: the interface language and the agent language.

use common::language::Language;
use dioxus::prelude::*;
use dioxus_free_icons::Icon;
use dioxus_free_icons::icons::md_action_icons::MdLanguage;

use crate::api::settings_api::save_language_settings;
use crate::components::error_boundary::ServerErrorDisplay;
use crate::i18n::{flag_src, languages, use_active_language};
use crate::tr;

/// `/settings`. Each choice is saved when it is selected. The interface changes at once.
/// The agent uses the new language from the next message.
#[component]
pub fn SettingsPage() -> Element {
    let mut active = use_active_language();
    let settings = active.settings.read().clone();
    let mut failure = use_signal(|| None::<ServerFnError>);
    let mut saved = use_signal(|| false);
    let save = move |interface: String, agent: String| {
        spawn(async move {
            saved.set(false);
            match save_language_settings(interface, agent).await {
                Ok(settings) => {
                    failure.set(None);
                    active.apply(settings);
                    saved.set(true);
                }
                Err(error) => failure.set(Some(error)),
            }
        });
    };
    let agent_for_interface = settings.saved_agent.clone();
    let interface_for_agent = settings.saved_interface.clone();
    rsx! {
        document::Title { {tr!("settings-title")} }
        main { id: "x-settings-page", class: "x-settings-page",
            h1 { {tr!("settings-title")} }
            section { "aria-labelledby": "x-settings-interface-language",
                h2 { id: "x-settings-interface-language", {tr!("settings-interface-language")} }
                p { {tr!("settings-interface-language-explanation")} }
                LanguageChoices {
                    id: "x-settings-interface-choices",
                    selected: settings.saved_interface.clone(),
                    automatic_label: tr!("settings-browser-language"),
                    automatic_detail: tr!("settings-now-showing", language: language_name(&settings.interface)),
                    on_select: move |code: String| save(code, agent_for_interface.clone()),
                }
            }
            section { "aria-labelledby": "x-settings-agent-language",
                h2 { id: "x-settings-agent-language", {tr!("settings-agent-language")} }
                p { {tr!("settings-agent-language-explanation")} }
                LanguageChoices {
                    id: "x-settings-agent-choices",
                    selected: settings.saved_agent.clone(),
                    automatic_label: tr!("settings-same-as-interface"),
                    automatic_detail: tr!("settings-agent-answers-in", language: language_name(&settings.agent)),
                    on_select: move |code: String| save(interface_for_agent.clone(), code),
                }
            }
            div { role: "status", class: "x-settings-status",
                if saved() { {tr!("settings-saved")} }
            }
            if let Some(error) = failure() {
                ServerErrorDisplay { error }
            }
        }
    }
}

/// The name and code of a supported language, as the controls show it.
pub fn language_name(code: &str) -> String {
    common::language::language(code)
        .map(|language| format!("{} ({})", language.endonym, language.code))
        .unwrap_or_else(|| code.to_string())
}

/// One radio group: the automatic choice, then every supported language with its flag.
#[component]
fn LanguageChoices(
    id: String,
    selected: String,
    automatic_label: String,
    automatic_detail: String,
    on_select: EventHandler<String>,
) -> Element {
    rsx! {
        div { id, role: "radiogroup", class: "x-language-choices",
            button {
                r#type: "button",
                role: "radio",
                class: "x-language-choice",
                "aria-checked": "{selected.is_empty()}",
                "data-language": "",
                onclick: move |_| on_select.call(String::new()),
                Icon { icon: MdLanguage, style: "width: 24px; height: 24px; flex-shrink: 0;" }
                span { class: "x-language-choice-text",
                    span { "{automatic_label}" }
                    span { class: "x-language-choice-detail", "{automatic_detail}" }
                }
            }
            for language in languages().iter().copied() {
                LanguageChoice {
                    key: "{language.code}",
                    language,
                    checked: selected == language.code,
                    on_select,
                }
            }
        }
    }
}

#[component]
fn LanguageChoice(language: Language, checked: bool, on_select: EventHandler<String>) -> Element {
    rsx! {
        button {
            r#type: "button",
            role: "radio",
            class: "x-language-choice",
            "aria-checked": "{checked}",
            "data-language": "{language.code}",
            lang: "{language.code}",
            onclick: move |_| on_select.call(language.code.to_string()),
            img { src: flag_src(language.code), alt: "", width: "24", height: "24", style: "flex-shrink: 0;" }
            span { class: "x-language-choice-text",
                span { "{language.endonym}" }
                span { class: "x-language-choice-detail", "{language.code}" }
            }
        }
    }
}

