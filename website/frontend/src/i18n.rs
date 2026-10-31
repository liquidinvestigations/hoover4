//! Interface languages: the Fluent catalogs, the bundle of the active language, and the
//! `tr!` macro that reads it.
//!
//! Each language has the files `main`, `search`, `document`, `storage`, `chat`, `admin` and
//! `shared` in `i18n/<code>/`. A bundle holds the English catalog and then
//! the selected catalog, so a message that a translation lacks shows in English. The
//! server renders the page in the language that `language_settings` resolves, and the
//! client starts from the same serialized value, so hydration finds the same text.

use common::language::{DEFAULT_LANGUAGE, LANGUAGES, LanguageSettings};
use dioxus::prelude::*;
use dioxus_i18n::fluent::{FluentArgs, FluentBundle, FluentResource};
use dioxus_i18n::prelude::{I18nBundle, use_init_i18n_from_bundle};
use dioxus_i18n::unic_langid::LanguageIdentifier;

/// The catalog files of one language, joined. Each area of the interface has one file.
macro_rules! catalog {
    ($code:literal) => {
        concat!(
            include_str!(concat!("../i18n/", $code, "/main.ftl")),
            "\n",
            include_str!(concat!("../i18n/", $code, "/search.ftl")),
            "\n",
            include_str!(concat!("../i18n/", $code, "/document.ftl")),
            "\n",
            include_str!(concat!("../i18n/", $code, "/storage.ftl")),
            "\n",
            include_str!(concat!("../i18n/", $code, "/chat.ftl")),
            "\n",
            include_str!(concat!("../i18n/", $code, "/admin.ftl")),
            "\n",
            include_str!(concat!("../i18n/", $code, "/shared.ftl")),
        )
    };
}

/// The catalog text of each supported language, in the order of `LANGUAGES`.
pub const CATALOGS: [(&str, &str); 18] = [
    ("en", catalog!("en")),
    ("de", catalog!("de")),
    ("es", catalog!("es")),
    ("fr", catalog!("fr")),
    ("pl", catalog!("pl")),
    ("pt", catalog!("pt")),
    ("ar", catalog!("ar")),
    ("he", catalog!("he")),
    ("hi", catalog!("hi")),
    ("zh", catalog!("zh")),
    ("it", catalog!("it")),
    ("nl", catalog!("nl")),
    ("da", catalog!("da")),
    ("nb", catalog!("nb")),
    ("sv", catalog!("sv")),
    ("el", catalog!("el")),
    ("hr", catalog!("hr")),
    ("ro", catalog!("ro")),
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

thread_local! {
    /// The English bundle for text that is formatted outside a rendered page, such as in a
    /// unit test.
    static ENGLISH: FluentBundle<FluentResource> = bundle(DEFAULT_LANGUAGE);
}

/// The text of catalog message `id` in the active language. Outside a rendered page it
/// uses English. A missing message or a bad argument logs an error and returns `id`, so a
/// catalog defect never stops the page.
pub fn translate(id: &str, args: Option<&FluentArgs>) -> String {
    let in_scope = dioxus::core::Runtime::try_current().is_some_and(|runtime| runtime.try_current_scope_id().is_some());
    let active = if in_scope { try_consume_context::<I18nBundle>() } else { None };
    let result = match active {
        Some(bundle) => bundle.try_translate_with_args(id, args).map_err(|error| error.to_string()),
        None => ENGLISH.with(|bundle| {
            // i18n: data, the log text of a catalog defect
            let message = bundle.get_message(id).ok_or_else(|| format!("no message {id}"))?;
            // i18n: data, the log text of a catalog defect
            let pattern = message.value().ok_or_else(|| format!("message {id} has no value"))?;
            let mut errors = vec![];
            let text = bundle.format_pattern(pattern, args, &mut errors).to_string();
            if errors.is_empty() { Ok(text) } else { Err(format!("{errors:?}")) }
        }),
    };
    result.unwrap_or_else(|error| {
        dioxus::logger::tracing::error!("translation {id}: {error}");
        id.to_string()
    })
}

/// One part of an English `shared` message: literal text or a variable.
enum SharedPart {
    Text(String),
    Variable(String),
}

/// The English `shared` messages, as id and parts, for `tr_shared`.
fn shared_patterns() -> Vec<(String, Vec<SharedPart>)> {
    let english = include_str!("../i18n/en/shared.ftl");
    let mut patterns: Vec<(String, Vec<SharedPart>)> = english
        .lines()
        .filter_map(|line| line.split_once(" = "))
        .filter(|(id, _)| id.starts_with("shared-"))
        .map(|(id, value)| {
            let mut parts = Vec::new();
            let value = value.replace("{\" \"}", " ");
            let mut rest = value.as_str();
            while let Some(start) = rest.find("{ $") {
                if start > 0 {
                    parts.push(SharedPart::Text(rest[..start].to_string()));
                }
                let end = rest[start..].find('}').map(|end| start + end).unwrap_or(rest.len() - 1);
                parts.push(SharedPart::Variable(rest[start + 3..end].trim().to_string()));
                rest = &rest[end + 1..];
            }
            if !rest.is_empty() {
                parts.push(SharedPart::Text(rest.to_string()));
            }
            (id.to_string(), parts)
        })
        // A pattern with variables needs three literal letters, so a pattern such as
        // `{ $a } { $b }` cannot match every text. Longer literal text is tried first.
        .filter(|(_, parts)| literal_letters(parts) >= 3 || parts.iter().all(|part| matches!(part, SharedPart::Text(_))))
        .collect();
    patterns.sort_by_key(|(_, parts)| std::cmp::Reverse(literal_letters(parts)));
    patterns
}

fn literal_letters(parts: &[SharedPart]) -> usize {
    parts.iter().map(|part| match part {
        SharedPart::Text(text) => text.chars().filter(|c| c.is_alphabetic()).count(),
        SharedPart::Variable(_) => 0,
    }).sum()
}



thread_local! {
    static SHARED: Vec<(String, Vec<SharedPart>)> = shared_patterns();
}

/// The variable values of `text` under one English pattern, or `None` when it does not
/// match. A variable takes the text up to the first occurrence of the literal after it.
fn match_shared(parts: &[SharedPart], text: &str) -> Option<Vec<(String, String)>> {
    let mut values = Vec::new();
    let mut rest = text;
    let mut index = 0;
    while index < parts.len() {
        match &parts[index] {
            SharedPart::Text(literal) => rest = rest.strip_prefix(literal.as_str())?,
            SharedPart::Variable(name) => {
                let value = match parts.get(index + 1) {
                    Some(SharedPart::Text(next)) if index + 2 == parts.len() => rest.strip_suffix(next.as_str())?,
                    Some(SharedPart::Text(next)) => &rest[..rest.find(next.as_str())?],
                    _ => rest,
                };
                values.push((name.clone(), value.to_string()));
                rest = &rest[value.len()..];
            }
        }
        index += 1;
    }
    rest.is_empty().then_some(values)
}

/// The translation of English text that the shared Rust code or the server produced, such
/// as a source label or a correctable error. The text is matched against the English
/// `shared` messages, and the matching message is shown in the active language with the
/// same values. Text without a matching message stays in English.
pub fn tr_shared(english: &str) -> String {
    let found = SHARED.with(|patterns| {
        patterns.iter().find_map(|(id, parts)| match_shared(parts, english).map(|values| (id.clone(), values)))
    });
    match found {
        Some((id, values)) => {
            let mut args = FluentArgs::new();
            for (name, value) in values {
                // A value can be shared text itself, such as the OCR part of a PDF label.
                args.set(name, if value.is_empty() { value } else { tr_shared(&value) });
            }
            translate(&id, Some(&args))
        }
        None => english.to_string(),
    }
}

/// `tr_shared` for the text types that shared Rust code returns.
pub trait SharedText {
    type Output;
    /// The text in the active language, through `tr_shared`.
    fn shared(self) -> Self::Output;
}

impl SharedText for &str {
    type Output = String;
    fn shared(self) -> String {
        tr_shared(self)
    }
}

impl SharedText for String {
    type Output = String;
    fn shared(self) -> String {
        tr_shared(&self)
    }
}

impl<T: AsRef<str>> SharedText for Option<T> {
    type Output = Option<String>;
    fn shared(self) -> Option<String> {
        self.map(|text| tr_shared(text.as_ref()))
    }
}

/// Translate a catalog message with `translate`. Arguments use the Fluent variable names:
/// `tr!("search-found", count: total)`.
#[macro_export]
macro_rules! tr {
    ($id:expr $(, $name:ident : $value:expr )* $(,)?) => {{
        #[allow(unused_mut)]
        let mut args = dioxus_i18n::fluent::FluentArgs::new();
        $( args.set(stringify!($name), $value); )*
        $crate::i18n::translate($id, Some(&args))
    }};
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn shared_text_matches_its_english_message() {
        assert_eq!(tr_shared("Virus found: Eicar-Test-Signature."), "Virus found: Eicar-Test-Signature.");
        let parts = SHARED.with(|patterns| {
            patterns.iter().position(|(id, _)| id == "shared-antivirus-virus-found").is_some()
        });
        assert!(parts);
        let matched = SHARED.with(|patterns| {
            let (_, parts) = patterns.iter().find(|(id, _)| id == "shared-antivirus-virus-found").unwrap();
            match_shared(parts, "Virus found: Eicar-Test-Signature.")
        });
        assert_eq!(matched, Some(vec![("value".to_string(), "Eicar-Test-Signature".to_string())]));
        assert_eq!(tr_shared("Text that no message has."), "Text that no message has.");
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
