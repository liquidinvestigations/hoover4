//! Proclitic variants of Arabic and Hebrew terms.
//!
//! Arabic and Hebrew write the conjunction, the article and the one-letter prepositions joined to
//! the next word: `والرشوة` is "and the bribe", `בשוחד` is "with a bribe". A whole-word search for
//! `رشوة` or `שוחד` never sees either. So a term whose first word is in Arabic or Hebrew script also
//! compiles with the common proclitic chains written in front of that word, and a match on a
//! variant reports the term it came from, with the clitic inside the span.
//!
//! A prefix on a short word too often spells a different word: `ك` + `مال` is the name `كمال`, and
//! `מ` + `ספר` is `מספר` (number). A one-word term shorter than [`MIN_LETTERS`] therefore gets no
//! variants, and the lists spell out the joined forms they need. A phrase gets them at any length,
//! because the words after the first keep a joined form from matching anything else, and an Arabic
//! word that already carries the article `ال` is safe at any length, because nothing else begins
//! with it.
//!
//! Only the first word is prefixed. Agreement inside a phrase is the lists' business: an Arabic
//! noun and its adjective both take the article (`مقبرة جماعية`, `المقابر الجماعية`), and a Hebrew
//! construct takes it on its second noun (`קבר אחים`, `קבר האחים`), so the definite forms that
//! matter are rows of their own.

/// The shortest one-word term, in letters, that is given proclitic variants.
const MIN_LETTERS: usize = 4;

/// Joined to an Arabic word without the article: conjunctions, prepositions, and the article
/// itself with what may precede it. `لل` is `ل` + `ال`, which Arabic always contracts.
const ARABIC_BARE: &[&str] = &[
    "و", "ف", "ب", "ل", "ك", "وب", "ول", "فب", "فل", "وك", "ال", "وال", "فال", "بال", "كال",
    "وبال", "فبال", "لل", "ولل", "فلل",
];

/// Joined in front of an Arabic word that already starts with `ال`.
const ARABIC_DEFINITE: &[&str] = &["و", "ف", "ب", "ك", "وب", "فب", "وك"];

/// Replace the `ال` of a definite Arabic word, because `ل` + `ال` is written `لل`.
const ARABIC_LAM_CONTRACTED: &[&str] = &["لل", "ولل", "فلل"];

/// Joined to a Hebrew word: `ו` and, `ה` the, `ש` that, `ב` in, `ל` to, `מ` from, `כ` as, and the
/// chains they form. After `ב`, `ל` and `כ` the article is not written, so those need no `ה`.
const HEBREW: &[&str] = &[
    "ה", "ו", "ש", "ב", "ל", "מ", "כ", "וה", "וב", "ול", "ומ", "וכ", "וש", "שה", "שב", "של", "שמ",
    "שכ", "מה", "כש", "וכש", "ושה", "ושב", "ושל", "ומה",
];

/// The proclitic variants of a folded term, without the term itself. Empty for a term whose first
/// word is not Arabic or Hebrew, or for a single word that is too short.
pub fn variants(folded: &str) -> Vec<String> {
    let (first, rest) = match folded.find(' ') {
        Some(at) => folded.split_at(at),
        None => (folded, ""),
    };
    let Some(lead) = first.chars().next() else {
        return Vec::new();
    };
    let long_enough = !rest.is_empty() || first.chars().count() >= MIN_LETTERS;
    let joined = |prefixes: &[&str], word: &str| -> Vec<String> {
        prefixes
            .iter()
            .map(|prefix| format!("{prefix}{word}{rest}"))
            .collect()
    };
    match lead {
        '\u{0600}'..='\u{06FF}' => {
            if let Some(bare) = first.strip_prefix("ال").filter(|bare| !bare.is_empty()) {
                let mut out = joined(ARABIC_DEFINITE, first);
                out.extend(joined(ARABIC_LAM_CONTRACTED, bare));
                out
            } else if long_enough {
                joined(ARABIC_BARE, first)
            } else {
                Vec::new()
            }
        }
        '\u{05D0}'..='\u{05EA}' if long_enough => joined(HEBREW, first),
        _ => Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::variants;
    use crate::lexicon::fold::fold_term;

    #[test]
    fn arabic_terms_take_the_article_and_conjunctions() {
        let found = variants(&fold_term("رشوة"));
        for joined in ["والرشوه", "بالرشوه", "للرشوه", "ورشوه", "الرشوه"]
        {
            assert!(found.iter().any(|v| v == joined), "{joined} in {found:?}");
        }
        let found = variants(&fold_term("الإبادة الجماعية"));
        for joined in ["والابادة الجماعيه", "للابادة الجماعيه", "بالابادة الجماعيه"]
        {
            let joined = fold_term(joined);
            assert!(found.contains(&joined), "{joined} in {found:?}");
        }
        assert!(!found.iter().any(|v| v.starts_with("الال")), "{found:?}");
    }

    #[test]
    fn hebrew_terms_take_the_one_letter_prefixes() {
        let found = variants("שוחד");
        for joined in ["בשוחד", "והשוחד", "שהשוחד", "לשוחד"] {
            assert!(found.iter().any(|v| v == joined), "{joined} in {found:?}");
        }
        assert_eq!(variants("שוחד גדול")[0], "השוחד גדול");
    }

    #[test]
    fn short_words_and_other_scripts_get_no_variants() {
        assert!(variants("مال").is_empty());
        assert!(variants("ספר").is_empty());
        assert!(variants("bribe").is_empty());
        assert!(variants("взятка").is_empty());
        assert!(!variants("المال").is_empty());
    }

    #[test]
    fn a_phrase_is_prefixed_whatever_the_length_of_its_first_word() {
        assert!(variants("מגן אנושי").contains(&"במגן אנושי".to_string()));
        assert!(variants(&fold_term("لا تكتب هذا")).contains(&"ولا تكتب هذا".to_string()));
    }
}
