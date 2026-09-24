//! The normalisation that makes an exact match insensitive to case, punctuation and accents.
//!
//! The same function folds the lexicon's terms at load time and the text at scan time. That shared
//! function is the whole of the matching semantics: a term matches wherever its folded form occurs
//! in the folded text, between two word boundaries. A change here changes what every term matches,
//! in every language, at once.
//!
//! Per source character, in order:
//!
//! 1. Apostrophes are deleted, so `don't`, `don’t` and `dont` are one word.
//! 2. Invisible characters are deleted (joiners, soft hyphen, byte-order mark, bidirectional
//!    controls, variation selectors), because one inside a word is a known way to dodge a list.
//! 3. The character is decomposed under NFKD, which flattens fullwidth forms, ligatures and styled
//!    letters to their plain equivalents.
//! 4. Letters and digits are lowercased (`ß` becomes `ss`, final `ς` becomes `σ`). Katakana become
//!    hiragana, because Japanese writes one word in either.
//! 5. A combining mark is dropped after a Latin, Greek or Cyrillic base, so `illégal` matches
//!    `illegal` and `ё` matches `е`. It is kept after any other base, because in Indic, Arabic and
//!    Hebrew scripts the marks are the vowels.
//! 6. Every run of anything else (whitespace, punctuation, symbols) becomes one space.
//!
//! The folded text starts and ends with a space. Every word boundary is then exactly one space,
//! which is what lets a whole-word match be a literal search for ` term `.

use unicode_normalization::char::{decompose_compatible, is_combining_mark};

/// Folded text and the way back to the source.
pub struct Folded {
    /// The folded text: lowercase words separated by single spaces, with one space at each end.
    pub text: String,
    /// For each byte of `text`, the byte offset in the source of the character that produced it.
    /// Separators map to the first character of the run they replace.
    source_start: Vec<u32>,
    source_len: usize,
}

impl Folded {
    /// The source byte offset where the folded byte `at` came from.
    pub fn source_start(&self, at: usize) -> usize {
        self.source_start[at] as usize
    }

    /// The source byte offset just past the character that produced the folded byte `at`.
    pub fn source_end(&self, source: &str, at: usize) -> usize {
        let start = self.source_start[at] as usize;
        source[start..]
            .chars()
            .next()
            .map_or(self.source_len, |ch| start + ch.len_utf8())
    }
}

/// Folds `source`. The offset map costs four bytes per folded byte; it is transient, and it is
/// what lets a signal carry offsets usable against the document the caller holds.
pub fn fold(source: &str) -> Folded {
    let mut folder = Folder {
        text: String::with_capacity(source.len() + 2),
        source_start: Vec::with_capacity(source.len() + 2),
        pending_space: true,
        strips_marks: false,
    };
    folder.push_space(0);
    for (at, ch) in source.char_indices() {
        let at = at as u32;
        if is_apostrophe(ch) || is_invisible(ch) {
            continue;
        }
        if ch.is_ascii() {
            folder.push(ch, at);
        } else {
            decompose_compatible(ch, |part| folder.push(part, at));
        }
    }
    if !folder.pending_space {
        folder.push_space(source.len() as u32);
    }
    Folded {
        text: folder.text,
        source_start: folder.source_start,
        source_len: source.len(),
    }
}

/// A term's folded form, without the padding spaces.
pub fn fold_term(term: &str) -> String {
    fold(term).text.trim().to_string()
}

struct Folder {
    text: String,
    source_start: Vec<u32>,
    /// Whether the last byte written is a separator, so a run of separators writes one space.
    pending_space: bool,
    /// Whether a combining mark after the last base character is dropped.
    strips_marks: bool,
}

impl Folder {
    fn push(&mut self, ch: char, at: u32) {
        if is_combining_mark(ch) {
            if !self.strips_marks && !self.pending_space {
                self.push_str_from(ch.encode_utf8(&mut [0; 4]), at);
            }
            return;
        }
        if ch.is_alphanumeric() {
            self.strips_marks = (ch as u32) < 0x0530;
            if ch.is_ascii() {
                self.push_str_from(ch.to_ascii_lowercase().encode_utf8(&mut [0; 1]), at);
                return;
            }
            for lower in ch.to_lowercase() {
                match lower {
                    'ß' => self.push_str_from("ss", at),
                    'ς' => self.push_str_from("σ", at),
                    '\u{30A1}'..='\u{30F6}' => {
                        let hiragana = char::from_u32(lower as u32 - 0x60).unwrap_or(lower);
                        self.push_str_from(hiragana.encode_utf8(&mut [0; 4]), at);
                    }
                    other => self.push_str_from(other.encode_utf8(&mut [0; 4]), at),
                }
            }
        } else if !self.pending_space {
            self.push_space(at);
        }
    }

    fn push_str_from(&mut self, piece: &str, at: u32) {
        self.text.push_str(piece);
        self.source_start
            .extend(std::iter::repeat_n(at, piece.len()));
        self.pending_space = false;
    }

    fn push_space(&mut self, at: u32) {
        self.text.push(' ');
        self.source_start.push(at);
        self.pending_space = true;
        self.strips_marks = false;
    }
}

fn is_apostrophe(ch: char) -> bool {
    matches!(
        ch,
        '\'' | '\u{2018}' | '\u{2019}' | '\u{02BC}' | '`' | '\u{00B4}'
    )
}

fn is_invisible(ch: char) -> bool {
    matches!(
        ch,
        '\u{00AD}'
            | '\u{200B}'..='\u{200F}'
            | '\u{202A}'..='\u{202E}'
            | '\u{2060}'..='\u{2064}'
            | '\u{2066}'..='\u{2069}'
            | '\u{FE00}'..='\u{FE0F}'
            | '\u{FEFF}'
    )
}

#[cfg(test)]
mod tests {
    use super::{fold, fold_term};

    #[test]
    fn case_punctuation_and_apostrophes_fold_away() {
        assert_eq!(fold("Don’t  leave\ta TRAIL!").text, " dont leave a trail ");
        assert_eq!(fold_term("cover-up"), "cover up");
        assert_eq!(fold_term("COVER UP"), "cover up");
        assert_eq!(fold_term("pacs.008"), "pacs 008");
    }

    #[test]
    fn accents_fold_for_latin_greek_and_cyrillic_only() {
        assert_eq!(fold_term("illégal"), "illegal");
        assert_eq!(fold_term("Geldwäsche"), "geldwasche");
        assert_eq!(fold_term("чёрный нал"), "черныи нал");
        assert_eq!(fold_term("Straße"), "strasse");
        // Devanagari vowel signs are marks and must survive, or every Hindi word collapses.
        assert_eq!(fold_term("रिश्वत"), "रिश्वत");
    }

    #[test]
    fn invisible_characters_and_compatibility_forms_do_not_split_a_word() {
        assert_eq!(fold_term("Schmier\u{00AD}geld"), "schmiergeld");
        assert_eq!(fold_term("brib\u{200D}e"), "bribe");
        assert_eq!(fold_term("ｆｒａｕｄ"), "fraud");
        assert_eq!(fold_term("ワイロ"), fold_term("わいろ"));
    }

    #[test]
    fn folding_is_idempotent() {
        for sample in [
            "Off-the-books, «pot-de-vin» — взятка!",
            "Schmiergeld\u{00AD}zahlung ß ｆｕｃｋ",
            "  ",
            "",
        ] {
            let once = fold_term(sample);
            assert_eq!(fold_term(&once), once, "{sample:?}");
        }
    }

    /// Every folded byte maps back to a character boundary in the source, in order, and the span
    /// of a folded word maps back to exactly the source word.
    #[test]
    fn the_offset_map_points_back_into_the_source() {
        let source = "Er zahlte „Schmiergeld“ an Dr. Öz.";
        let folded = fold(source);
        let mut last = 0;
        for at in 0..folded.text.len() {
            let start = folded.source_start(at);
            assert!(source.is_char_boundary(start));
            assert!(start >= last);
            last = start;
        }
        let word = folded.text.find("schmiergeld").expect("the word is folded");
        let start = folded.source_start(word);
        let end = folded.source_end(source, word + "schmiergeld".len() - 1);
        assert_eq!(&source[start..end], "Schmiergeld");
    }
}
