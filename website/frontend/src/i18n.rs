//! Interface languages: the Fluent catalogs, the bundle of the active language, and the
//! `tr!` macro that reads it.
//!
//! Each language has `i18n/<code>/main.ftl`. A bundle holds the English catalog and then
//! the selected catalog, so a message that a translation lacks shows in English. The
//! server renders the page in the language that `language_settings` resolves, and the
//! client starts from the same serialized value, so hydration finds the same text.

use common::language::{DEFAULT_LANGUAGE, LANGUAGES, LanguageSettings};
use dioxus::prelude::*;
use dioxus_i18n::fluent::{FluentBundle, FluentResource};
use dioxus_i18n::prelude::{I18nBundle, use_init_i18n_from_bundle};
use dioxus_i18n::unic_langid::LanguageIdentifier;

/// The catalog text of each supported language, in the order of `LANGUAGES`.
pub const CATALOGS: [(&str, &str); 18] = [
    ("en", include_str!("../i18n/en/main.ftl")),
    ("de", include_str!("../i18n/de/main.ftl")),
    ("es", include_str!("../i18n/es/main.ftl")),
    ("fr", include_str!("../i18n/fr/main.ftl")),
    ("pl", include_str!("../i18n/pl/main.ftl")),
    ("pt", include_str!("../i18n/pt/main.ftl")),
    ("ar", include_str!("../i18n/ar/main.ftl")),
    ("he", include_str!("../i18n/he/main.ftl")),
    ("hi", include_str!("../i18n/hi/main.ftl")),
    ("zh", include_str!("../i18n/zh/main.ftl")),
    ("it", include_str!("../i18n/it/main.ftl")),
    ("nl", include_str!("../i18n/nl/main.ftl")),
    ("da", include_str!("../i18n/da/main.ftl")),
    ("nb", include_str!("../i18n/nb/main.ftl")),
    ("sv", include_str!("../i18n/sv/main.ftl")),
    ("el", include_str!("../i18n/el/main.ftl")),
    ("hr", include_str!("../i18n/hr/main.ftl")),
    ("ro", include_str!("../i18n/ro/main.ftl")),
];

/// Arabic and Hebrew wrap each inserted value in Unicode isolation marks, so a Latin
/// file name or number keeps its order inside right-to-left text. Other languages insert
/// values without marks.
fn is_right_to_left(code: &str) -> bool {
    matches!(code, "ar" | "he")
}

fn catalog(code: &str) -> &'static str {
    CATALOGS.iter().find(|(c, _)| *c == code).map(|(_, text)| *text).unwrap_or_default()
}

fn resource(code: &str) -> FluentResource {
    FluentResource::try_new(catalog(code).to_string()).unwrap_or_else(|(resource, errors)| {
        dioxus::logger::tracing::error!("the {code} catalog has {} syntax errors: {errors:?}", errors.len());
        resource
    })
}

/// The bundle of `code`: the English catalog, overridden by the catalog of `code`.
/// An unsupported code gives the English bundle.
pub fn bundle(code: &str) -> FluentBundle<FluentResource> {
    let code = common::language::supported_code(code).unwrap_or(DEFAULT_LANGUAGE);
    let id: LanguageIdentifier = code.parse().unwrap_or_default();
    let mut bundle = FluentBundle::new(vec![id]);
    bundle.set_use_isolating(is_right_to_left(code));
    bundle.add_resource_overriding(resource(DEFAULT_LANGUAGE));
    if code != DEFAULT_LANGUAGE {
        bundle.add_resource_overriding(resource(code));
    }
    bundle
}

/// The active language settings and the bundle that shows them.
#[derive(Clone, Copy)]
pub struct ActiveLanguage {
    pub settings: Signal<LanguageSettings>,
    bundle: I18nBundle,
}

impl ActiveLanguage {
    /// Show the interface in the language of `settings` from the next render on.
    pub fn apply(&mut self, settings: LanguageSettings) {
        if settings.interface != self.settings.peek().interface {
            self.bundle.set_bundle(bundle(&settings.interface));
        }
        self.settings.set(settings);
    }
}

/// The active language of the page.
pub fn use_active_language() -> ActiveLanguage {
    use_context::<ActiveLanguage>()
}

/// Resolve the caller's languages on the server, then provide the bundle to every child.
/// A failed request shows English, and the next page load asks again.
#[component]
pub fn LanguageProvider(children: Element) -> Element {
    let resolved = use_server_future(crate::api::settings_api::language_settings)?;
    let initial = resolved.read().as_ref().and_then(|result| result.as_ref().ok()).cloned().unwrap_or_else(|| {
        LanguageSettings::resolve("", "", None)
    });
    let interface = initial.interface.clone();
    let bundle = use_init_i18n_from_bundle(move || bundle(&interface));
    let settings = use_signal(move || initial);
    use_context_provider(move || ActiveLanguage { settings, bundle });
    let lang = settings.read().interface.clone();
    rsx! {
        div { lang, style: "display: contents;", {children} }
    }
}

/// The supported languages, for the language controls.
pub fn languages() -> &'static [common::language::Language] {
    &LANGUAGES
}

/// The vendored language flags, one `<code>.svg` each, with their license.
///
/// `#[used]` because nothing reads the binding: `flag_src` names the served path by a
/// string, and `with_hash_suffix(false)` keeps that path `/assets/flags/…`.
#[used]
static FLAGS_FOLDER: Asset = asset!("/assets/flags/", AssetOptions::folder().with_hash_suffix(false));

/// The served path of the flag of a supported language code.
pub fn flag_src(code: &str) -> String {
    format!("/assets/flags/{code}.svg")
}

/// Translate a catalog message. Arguments use the Fluent variable names:
/// `tr!("search-found", count: total)`. A missing message or a bad argument logs an
/// error and shows the message id, so a catalog defect never stops the page.
#[macro_export]
macro_rules! tr {
    ($id:expr $(, $name:ident : $value:expr )* $(,)?) => {{
        match dioxus_i18n::te!($id $(, $name : $value )*) {
            Ok(text) => text,
            Err(error) => {
                dioxus::logger::tracing::error!("translation {}: {}", $id, error);
                String::from($id)
            }
        }
    }};
}

#[cfg(test)]
mod tests {
    use super::*;
    use dioxus_i18n::fluent::FluentArgs;

    /// The messages of a catalog with the sorted variable names that each one uses. A
    /// message starts with an identifier in the first column, and its indented lines
    /// follow it.
    fn messages(code: &str) -> Vec<(String, Vec<String>)> {
        let text = catalog(code);
        if let Err((_, errors)) = FluentResource::try_new(text.to_string()) {
            panic!("{code} catalog syntax: {errors:?}");
        }
        let mut found: Vec<(String, Vec<String>)> = Vec::new();
        for line in text.lines() {
            if line.starts_with('#') {
                continue;
            }
            // A term (`-name =`) starts a block as a message does, and is dropped below.
            if line.chars().next().is_some_and(|c| c.is_ascii_alphabetic() || c == '-') {
                let id = line.split('=').next().unwrap_or_default().trim().to_string();
                found.push((id, Vec::new()));
            }
            if let Some((_, vars)) = found.last_mut() {
                for part in line.split('$').skip(1) {
                    let name: String = part.chars().take_while(|c| c.is_ascii_alphanumeric() || *c == '_' || *c == '-').collect();
                    if !name.is_empty() && !vars.contains(&name) {
                        vars.push(name);
                    }
                }
            }
        }
        found.retain(|(id, _)| !id.starts_with('-'));
        for (_, vars) in &mut found {
            vars.sort();
        }
        found
    }

    #[test]
    fn every_catalog_parses_and_matches_the_english_messages() {
        let english: std::collections::BTreeMap<_, _> = messages(DEFAULT_LANGUAGE).into_iter().collect();
        for (code, _) in CATALOGS {
            for (id, vars) in messages(code) {
                let expected = english.get(&id).unwrap_or_else(|| panic!("{code}: {id} is not an English message"));
                assert_eq!(&vars, expected, "{code}: {id} uses other variables than English");
            }
        }
    }

    #[test]
    fn every_english_message_formats_without_errors() {
        let bundle = bundle(DEFAULT_LANGUAGE);
        for (id, vars) in messages(DEFAULT_LANGUAGE) {
            let mut args = FluentArgs::new();
            for var in vars {
                args.set(var, 2);
            }
            let message = bundle.get_message(&id).unwrap();
            let mut errors = vec![];
            if let Some(pattern) = message.value() {
                bundle.format_pattern(pattern, Some(&args), &mut errors);
            }
            assert!(errors.is_empty(), "{id}: {errors:?}");
        }
    }
}
