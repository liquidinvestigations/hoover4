//! The supported languages and the rules that choose the interface language and the
//! agent language of a person.
//!
//! The interface language is the saved `ui.language` setting, else the first supported
//! language of the browser's `Accept-Language` header, else English. The agent language
//! is the saved `agent.language` setting, else the interface language. The worker
//! repeats `supported_code` in `main_services/processing/tasks/P_agent/language.py`, and
//! both test suites read the cases in `P_agent/language_vectors.json`.

use serde::{Deserialize, Serialize};

/// One supported language: its code, its own name, and its English name.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Language {
    /// The ISO 639-1 code, also the folder name of its catalogs.
    pub code: &'static str,
    /// The name in the language itself, shown in the language controls.
    pub endonym: &'static str,
    /// The English name, used in the English agent instruction.
    pub english: &'static str,
}

/// The fallback language and the source of every catalog.
pub const DEFAULT_LANGUAGE: &str = "en";

/// The 21 supported languages, in the order of the language controls.
pub const LANGUAGES: [Language; 21] = [
    Language { code: "en", endonym: "English", english: "English" },
    Language { code: "de", endonym: "Deutsch", english: "German" },
    Language { code: "es", endonym: "Español", english: "Spanish" },
    Language { code: "fr", endonym: "Français", english: "French" },
    Language { code: "pl", endonym: "Polski", english: "Polish" },
    Language { code: "pt", endonym: "Português", english: "Portuguese" },
    Language { code: "ar", endonym: "العربية", english: "Arabic" },
    Language { code: "he", endonym: "עברית", english: "Hebrew" },
    Language { code: "hi", endonym: "हिन्दी", english: "Hindi" },
    Language { code: "zh", endonym: "中文", english: "Chinese" },
    Language { code: "it", endonym: "Italiano", english: "Italian" },
    Language { code: "nl", endonym: "Nederlands", english: "Dutch" },
    Language { code: "da", endonym: "Dansk", english: "Danish" },
    Language { code: "nb", endonym: "Norsk bokmål", english: "Norwegian Bokmål" },
    Language { code: "sv", endonym: "Svenska", english: "Swedish" },
    Language { code: "el", endonym: "Ελληνικά", english: "Greek" },
    Language { code: "hr", endonym: "Hrvatski", english: "Croatian" },
    Language { code: "ro", endonym: "Română", english: "Romanian" },
    Language { code: "ru", endonym: "Русский", english: "Russian" },
    Language { code: "ja", endonym: "日本語", english: "Japanese" },
    Language { code: "ko", endonym: "한국어", english: "Korean" },
];

/// The setting key of the interface language.
pub const UI_LANGUAGE_KEY: &str = "ui.language";
/// The setting key of the agent language. An empty value means the interface language.
pub const AGENT_LANGUAGE_KEY: &str = "agent.language";

/// The language with this exact supported code.
pub fn language(code: &str) -> Option<&'static Language> {
    LANGUAGES.iter().find(|language| language.code == code)
}

/// The supported code of a language tag, or `None`.
///
/// The comparison ignores case and takes the primary subtag, so `pt-BR`, `zh-Hans-CN`
/// and `DE_at` select `pt`, `zh` and `de`. The Norwegian tags `no` and `nn` select `nb`,
/// and the withdrawn Hebrew code `iw` selects `he`.
pub fn supported_code(tag: &str) -> Option<&'static str> {
    let tag = tag.trim().to_ascii_lowercase().replace('_', "-");
    let primary = tag.split('-').next().unwrap_or_default();
    let primary = match primary {
        "no" | "nn" => "nb",
        "iw" => "he",
        other => other,
    };
    language(primary).map(|language| language.code)
}

/// The first supported language of an `Accept-Language` header, by quality value and
/// then by position. A quality of zero and the `*` range select nothing.
pub fn from_accept_language(header: &str) -> Option<&'static str> {
    let mut ranges: Vec<(f32, usize, &str)> = header
        .split(',')
        .enumerate()
        .filter_map(|(position, part)| {
            let mut fields = part.split(';');
            let tag = fields.next()?.trim();
            let quality = fields
                .filter_map(|field| field.trim().strip_prefix("q="))
                .next()
                .map(|value| value.trim().parse::<f32>().unwrap_or(0.0))
                .unwrap_or(1.0);
            (quality > 0.0 && !tag.is_empty() && tag != "*").then_some((quality, position, tag))
        })
        .collect();
    ranges.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)));
    ranges.into_iter().find_map(|(_, _, tag)| supported_code(tag))
}

/// The interface language: the saved setting, else the browser header, else English.
/// An unsupported saved value counts as no saved value.
pub fn interface_language(saved: Option<&str>, accept_language: Option<&str>) -> &'static str {
    saved
        .and_then(supported_code)
        .or_else(|| accept_language.and_then(from_accept_language))
        .unwrap_or(DEFAULT_LANGUAGE)
}

/// The agent language: the saved agent setting, else the interface language.
pub fn agent_language(saved_agent: Option<&str>, interface: &str) -> &'static str {
    saved_agent
        .and_then(supported_code)
        .or_else(|| supported_code(interface))
        .unwrap_or(DEFAULT_LANGUAGE)
}

/// The language settings of one person and the languages they select.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct LanguageSettings {
    /// The saved interface language code, or empty when none is saved.
    pub saved_interface: String,
    /// The saved agent language code, or empty for "same as the interface".
    pub saved_agent: String,
    /// The language the interface shows.
    pub interface: String,
    /// The language the agent answers in.
    pub agent: String,
}

impl LanguageSettings {
    /// Resolve both languages from the saved values and the browser header.
    pub fn resolve(saved_interface: &str, saved_agent: &str, accept_language: Option<&str>) -> Self {
        let interface = interface_language(Some(saved_interface), accept_language);
        Self {
            saved_interface: supported_code(saved_interface).unwrap_or_default().to_string(),
            saved_agent: supported_code(saved_agent).unwrap_or_default().to_string(),
            interface: interface.to_string(),
            agent: agent_language(Some(saved_agent), interface).to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The cases that the worker's Python resolver also passes.
    fn vectors() -> serde_json::Value {
        let path = std::env::var("HOOVER4_LANGUAGE_VECTORS")
            .unwrap_or_else(|_| "/mirror/processing-tasks/P_agent/language_vectors.json".to_string());
        let text = std::fs::read_to_string(&path)
            .unwrap_or_else(|error| panic!("read the shared language cases at {path}: {error}"));
        serde_json::from_str(&text).expect("the shared language cases are JSON")
    }

    #[test]
    fn shared_cases_resolve_as_in_python() {
        let vectors = vectors();
        for case in vectors["supported_code"].as_array().unwrap() {
            let expected = case["expected"].as_str();
            assert_eq!(supported_code(case["tag"].as_str().unwrap()), expected, "{case}");
        }
        for case in vectors["accept_language"].as_array().unwrap() {
            let expected = case["expected"].as_str();
            assert_eq!(from_accept_language(case["header"].as_str().unwrap()), expected, "{case}");
        }
        for case in vectors["resolve"].as_array().unwrap() {
            let settings = LanguageSettings::resolve(
                case["saved_interface"].as_str().unwrap(),
                case["saved_agent"].as_str().unwrap(),
                case["accept_language"].as_str(),
            );
            assert_eq!(settings.interface, case["interface"].as_str().unwrap(), "{case}");
            assert_eq!(settings.agent, case["agent"].as_str().unwrap(), "{case}");
        }
    }

    #[test]
    fn every_language_is_unique_and_resolves_to_itself() {
        let codes: std::collections::BTreeSet<_> = LANGUAGES.iter().map(|language| language.code).collect();
        assert_eq!(codes.len(), LANGUAGES.len());
        for language in LANGUAGES {
            assert_eq!(supported_code(language.code), Some(language.code));
        }
    }
}
