//! Entity values that are never entities, applied when they are displayed.
//!
//! The pipeline drops these before writing `entity_hit`
//! (`main_services/processing/tasks/entity_stoplist.py`), so on freshly extracted data
//! this module finds nothing. It exists because a rule applied at write time only
//! governs rows written after it: everything extracted earlier keeps its MIME header
//! names, its quoted-printable fragments and its letter-spaced PDF headings until the NLP
//! stage is re-run over the collection, and the Entities facet is the feature those rows
//! ruin.
//!
//! The duplication is deliberate, as with `document_sources.rs`: neither runtime may
//! depend on the other being right. The rules and the canonical cases below mirror the
//! Python module value for value; a case added on one side belongs on the other.
//!
//! Rules reject on **shape** where a shape exists (an `X-` header name, a token ending
//! in the quoted-printable soft break `=`, a long case-shuffled run of base64 characters,
//! four or more single-character tokens from letter-spaced PDF text), and fall back to a
//! named set only for things with no shape: the standard mail headers, the day and month
//! names, a handful of SMTP/MIME protocol words. Every rule matches the **whole value**,
//! so `May` goes and `May Chen` stays.
//!
//! Two rules are positional instead, and they are anchored precisely so they cannot fire
//! on a keyword inside a real name: a value made *entirely* of single characters is
//! letter-spaced text (`U I`), and a value whose *last* token is a reply-block header
//! keyword is the name printed above that header (`Eric Cc`). The second asks for the
//! header's colon as well whenever the keyword is also an ordinary English word, so
//! `Blind Date` stays and `Sara Shackleton To:` goes.

/// The `string_term_id_to_text.term_field` under which entity values are stored, and
/// therefore the facets these rules apply to (`ner_per`, `ner_org`, `ner_loc`,
/// `ner_misc` all map to it). The pipeline writes the same string.
pub const ENTITY_TERM_FIELD: &str = "ner";

/// Standard mail and MIME header names, plus the four Outlook writes into a quoted reply
/// block, which is why message bodies carry them too. Matched against the text before the
/// value's first colon, so `Date: Mon` goes with `Date`. `Organization` is deliberately
/// absent: it is a real word far more often than a header.
const MAIL_HEADER_NAMES: &[&str] = &[
    "accept-language",
    "authentication-results",
    "bcc",
    "cc",
    "content-description",
    "content-disposition",
    "content-id",
    "content-language",
    "content-length",
    "content-transfer-encoding",
    "content-type",
    "date",
    "delivered-to",
    "disposition-notification-to",
    "dkim-signature",
    "errors-to",
    "from",
    "importance",
    "in-reply-to",
    "list-id",
    "list-unsubscribe",
    "mail-followup-to",
    "message-id",
    "mime-version",
    "precedence",
    "priority",
    "received",
    "references",
    "reply-to",
    "return-path",
    "sender",
    "sent",
    "subject",
    "thread-index",
    "thread-topic",
    "to",
    "user-agent",
];

/// Protocol words from every `Received:` chain and MIME preamble.
const PROTOCOL_TOKENS: &[&str] = &[
    "7bit",
    "8bit",
    "application/octet-stream",
    "base64",
    "boundary",
    "charset",
    "ehlo",
    "esmtp",
    "helo",
    "multipart/alternative",
    "multipart/mixed",
    "quoted-printable",
    "smtp",
    "text/html",
    "text/plain",
];

/// Day and month names with their usual abbreviations. Whole-value matches only.
const DAY_AND_MONTH_TOKENS: &[&str] = &[
    "mon", "monday", "tue", "tues", "tuesday", "wed", "weds", "wednesday", "thu", "thur",
    "thurs", "thursday", "fri", "friday", "sat", "saturday", "sun", "sunday", "jan",
    "january", "feb", "february", "mar", "march", "apr", "april", "may", "jun", "june",
    "jul", "july", "aug", "august", "sep", "sept", "september", "oct", "october", "nov",
    "november", "dec", "december",
];

/// The header keywords a mail reply block prints, as they appear glued to the end of the
/// name printed above them: `Peter Aldhous Subject`, `Eric Cc`, `Larry Sent`.
const REPLY_BLOCK_HEADERS: &[&str] = &["bcc", "cc", "from", "sent", "subject"];

/// `Date` and `To` are reply-block headers too, but unlike the five above they are also
/// ordinary English words that end real names: `Blind Date`, `Save The Date`, `Tokyo To`.
/// They therefore count only with the header's colon still attached
/// (`Sara Shackleton To:`); the whole-value header rule still takes `To: Vince J Kaminski`
/// and `Date: Mon`, and the `X-` rule still takes `X-To`.
const COLON_ONLY_REPLY_BLOCK_HEADERS: &[&str] = &["date", "to"];

/// The separator Outlook puts above a quoted message. Never part of a name.
const ORIGINAL_MESSAGE_MARKER: &str = "-----original message-----";

const BLOB_MIN_CHARS: usize = 24;
const BLOB_MIN_CASE_SWITCHES: usize = 4;
/// Letter-spaced headings arrive as one entity per heading. Lowering the threshold breaks
/// on `J F Kennedy`, which carries two single-character tokens and is a name. What
/// separates them is that letter-spacing leaves nothing but single characters. See
/// `is_entirely_single_characters`.
const MAX_SINGLE_CHAR_TOKENS: usize = 3;
const MAX_TOKENS: usize = 12;
const MAX_CHARS: usize = 200;

/// A header key is one hyphenated word; anything else before a colon is prose.
fn is_header_key_shaped(key: &str) -> bool {
    let mut chars = key.chars();
    match chars.next() {
        Some(c) if c.is_ascii_lowercase() => {}
        _ => return false,
    }
    chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
}

/// Any `X-` extension header, so a corpus's private ones need no enumeration.
fn is_extension_header(key: &str) -> bool {
    key.len() > 2 && key.starts_with("x-") && is_header_key_shaped(key)
}

/// Adjacent letter pairs whose case differs: ~1 per word in a name, many in base64.
fn case_switches(value: &str) -> usize {
    let mut switches = 0;
    let mut previous: Option<char> = None;
    for c in value.chars() {
        if !c.is_alphabetic() {
            previous = None;
            continue;
        }
        if let Some(p) = previous
            && p.is_uppercase() != c.is_uppercase()
        {
            switches += 1;
        }
        previous = Some(c);
    }
    switches
}

/// True for a base64/quoted-printable payload fragment.
///
/// Four conditions together, because each alone has a false positive: no whitespace (a
/// name has some), long (short tokens are identifiers people search for), a digit or
/// `+`/`/` (a run-together CamelCase company name has neither), and shuffled case (a
/// hexadecimal hash or an uppercase acronym does not). `@` and `:` are not in the
/// alphabet, which is what keeps addresses and URLs out of this rule.
fn looks_like_encoded_blob(value: &str) -> bool {
    if value.chars().any(char::is_whitespace) || value.chars().count() < BLOB_MIN_CHARS {
        return false;
    }
    let body = value.trim_end_matches('=');
    if !body
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '+' | '/' | '.' | '_' | '-'))
    {
        return false;
    }
    if !body.chars().any(|c| c.is_ascii_digit() || c == '+' || c == '/') {
        return false;
    }
    case_switches(body) >= BLOB_MIN_CASE_SWITCHES
}

/// True for `U I`, `∆ Y`, `R X X`: letter-spaced text too short to trip the token count.
fn is_entirely_single_characters(tokens: &[&str]) -> bool {
    tokens.len() > 1 && tokens.iter().all(|t| t.chars().count() == 1)
}

/// True for `<name> Subject`, `<name> Cc`, `<name> Sent: Monday`, `<name> To:`.
///
/// A mail body's reply block puts the header keyword on the line under the name, and the
/// model returns the pair as one entity, which the whole-value rules never see, because
/// the value is not the keyword, it merely ends with it.
///
/// Deliberately narrow on two axes. By position: matching a header keyword anywhere in a
/// value would take `Mission To Mars` with it, so the first token is exempt entirely
/// (`Subject Matter Experts` survives) and only the last token or a colon-carrying one
/// counts. By keyword: a bare trailing `Date` or `To` is ordinary English and is left
/// alone, so those two count only with the colon attached.
fn ends_in_a_header_keyword(tokens: &[&str]) -> bool {
    if tokens.len() < 2 {
        return false;
    }
    let last = tokens.len() - 1;
    tokens.iter().enumerate().skip(1).any(|(index, token)| {
        let keyword = token.trim_end_matches(':').to_lowercase();
        let bare_header = REPLY_BLOCK_HEADERS.contains(&keyword.as_str());
        if token.ends_with(':')
            && (bare_header || COLON_ONLY_REPLY_BLOCK_HEADERS.contains(&keyword.as_str()))
        {
            return true;
        }
        index == last && bare_header
    })
}

/// True if `value` is extraction debris rather than a named entity.
pub fn is_stopped_entity(value: &str) -> bool {
    let text = value.trim();
    if text.is_empty() || text.chars().count() > MAX_CHARS {
        return true;
    }
    if !text.chars().any(char::is_alphanumeric) {
        return true;
    }
    // Markup that survived a text extractor: `<td align`, `FONT SIZE=1>Updated`.
    if text.contains('<') || text.contains('>') {
        return true;
    }

    // One latin character. A model handed a base64 payload returns its fragments as
    // entities, and most of them are one letter long. Non-ASCII is exempt: a single CJK
    // character is a word, and can be a surname.
    if text.chars().count() == 1 && text.is_ascii() {
        return true;
    }

    let lowered = text.to_lowercase();
    if DAY_AND_MONTH_TOKENS.contains(&lowered.as_str())
        || PROTOCOL_TOKENS.contains(&lowered.as_str())
    {
        return true;
    }

    let header_key = lowered.split(':').next().unwrap_or_default().trim();
    if is_header_key_shaped(header_key)
        && (MAIL_HEADER_NAMES.contains(&header_key) || is_extension_header(header_key))
    {
        return true;
    }

    if lowered.contains(ORIGINAL_MESSAGE_MARKER) {
        return true;
    }

    let tokens: Vec<&str> = text.split_whitespace().collect();
    if tokens.len() > MAX_TOKENS {
        return true;
    }
    let single_char = tokens
        .iter()
        .filter(|t| t.chars().count() == 1 && t.chars().all(char::is_alphanumeric))
        .count();
    if single_char > MAX_SINGLE_CHAR_TOKENS {
        return true;
    }
    if is_entirely_single_characters(&tokens) || ends_in_a_header_keyword(&tokens) {
        return true;
    }

    // A quoted-printable soft line break: the `=` is the line continuation, and the model
    // takes the fragment before it (`of=`, `th=`) for a name.
    if !text.chars().any(char::is_whitespace) && text.ends_with('=') {
        return true;
    }

    looks_like_encoded_blob(text)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The values that made the Entities facet unusable on a mail corpus, taken from
    /// `entity_hit` as stored. Mirrors `tests/unit/test_entity_stoplist.py`.
    const DEBRIS: &[&str] = &[
        "Content-Transfer-Encoding",
        "Message-ID",
        "Mime-Version",
        "MIME-Version",
        "Content-Type",
        "Subject",
        "Subject:",
        "Cc",
        "Date: Mon",
        "Sent: Tuesday",
        "Thread-Topic: Invitation Fontys Open Day",
        "X-Folder",
        "X-Origin",
        "X-FileName",
        "X-To",
        "X-From",
        "X-YMailISG",
        "Authentication-Results",
        "Mon",
        "Fri",
        "Thursday",
        "thursday",
        "Tuesday",
        "Jan",
        "May",
        "September",
        "ESMTP",
        "SMTP",
        "quoted-printable",
        "base64",
        "7bit",
        "text/plain",
        "of=",
        "th=",
        "RGVhciBzdHVkZW50LA0KDQpMaWtlIGxhc3QgTm92ZW1iZXI",
        "CH0D30CYqUPrSizQBUYtBpBcLyCczRvQU7JHvAv5endkFKBrVHQHS0GIH9Hz",
        "mZ2kI.zNjgnAdLPRgf0O6aIHpNgu6D76dg_e18XcXsbE2TMgD2OSSf6p5JlW",
        "F O N T Y S",
        "L  B U S I N E S S  S C H O O L",
        // Letter-spaced runs too short for the token count.
        "∆ Y",
        "U I",
        "R X X",
        // A reply block's header keyword glued to the name printed above it.
        "Peter Aldhous Subject",
        "ECT@ENRON Subject",
        "Enron@Enron Subject",
        "David Subject",
        "Eric From",
        "Eric Cc",
        "Larry Sent",
        "Kay Sent: Monday",
        "Ted -----Original Message----- From",
        // `To` and `Date` are ordinary words, so they count only with the header's colon.
        "Sara Shackleton To:",
        "Steven Kean Date:",
        // A doubled colon is still one header keyword. Pinned because this is where the
        // two implementations drifted apart once already.
        "Kay Sent:: Monday",
        "FONT SIZE=1>Updated",
        "-- ",
        "G",
        "I",
    ];

    /// `Mr`, `Inc` and `NA` are debatable and are deliberately kept: a stop-list that
    /// guesses at what is uninteresting removes real names.
    const KEEP: &[&str] = &[
        "Enron",
        "Enron Corp",
        "Jeff Dasovich",
        "Vince J Kaminski",
        "PG&E",
        "S&P",
        "Sun Microsystems",
        "May Chen",
        "June Smith",
        "March of Dimes",
        "Mr",
        "Inc",
        "NA",
        "Rights Reserved",
        "Jeff.Dasovich@enron.com",
        "ENRON_DEVELOPMENT@ENRON_DEVELOPMENT",
        "http://www.fontys.nl/fihe/default.asp",
        "Reuters English News Service",
        "New York",
        "J F Kennedy",
        "InternationalBusinessMachinesCorporation",
        // A header keyword in the middle of a name is prose, and the first token is
        // exempt entirely: these are the false positives the positional rules avoid.
        "Mission To Mars",
        "Ode To Joy",
        "Subject Matter Experts",
        "From Dusk Till Dawn",
        "Dow Jones & Company",
        "U.S.",
        "3M",
        "eBay",
        "李",
        // A bare trailing `Date` or `To` is ordinary English, not a reply block.
        "Blind Date",
        "Save The Date",
        "Tokyo To",
        "A To Z",
    ];

    #[test]
    fn debris_is_stopped() {
        for value in DEBRIS {
            assert!(is_stopped_entity(value), "{value:?} should not be an entity");
        }
    }

    #[test]
    fn real_entities_survive() {
        for value in KEEP {
            assert!(!is_stopped_entity(value), "{value:?} must stay searchable");
        }
    }

    #[test]
    fn the_rule_matches_the_whole_value_never_a_substring() {
        assert!(is_stopped_entity("Sun") && !is_stopped_entity("Sun Microsystems"));
        assert!(is_stopped_entity("May") && !is_stopped_entity("May Chen"));
        assert!(is_stopped_entity("Subject") && !is_stopped_entity("Subject Matter Experts"));
    }

    #[test]
    fn letter_spacing_is_stopped_but_initials_next_to_a_name_are_not() {
        // Lowering MAX_SINGLE_CHAR_TOKENS takes `J F Kennedy` with it. What separates the
        // two is that letter-spacing leaves nothing but single characters.
        assert!(is_stopped_entity("U I") && is_stopped_entity("∆ Y"));
        assert!(!is_stopped_entity("J F Kennedy") && !is_stopped_entity("3M"));
    }

    #[test]
    fn a_header_keyword_is_debris_at_the_end_and_prose_in_the_middle() {
        assert!(is_stopped_entity("Eric Cc") && is_stopped_entity("Peter Aldhous Subject"));
        assert!(!is_stopped_entity("Mission To Mars") && !is_stopped_entity("Subject Matter Experts"));
    }

    #[test]
    fn a_header_keyword_that_is_also_an_english_word_needs_its_colon() {
        // `Cc` and `Subject` end nothing but a reply block, so a bare one is enough.
        // `Date` and `To` end real names, so they are debris only with the colon still
        // attached, and a value that really is a header line is caught by the
        // whole-value rule long before this one is reached.
        assert!(!is_stopped_entity("Blind Date") && !is_stopped_entity("Tokyo To"));
        assert!(is_stopped_entity("Sara Shackleton To:") && is_stopped_entity("Steven Kean Date:"));
        assert!(is_stopped_entity("Date: Mon") && is_stopped_entity("To: Vince J Kaminski"));
        assert!(is_stopped_entity("X-To") && is_stopped_entity("X-cc"));
    }

    #[test]
    fn a_paragraph_is_not_an_entity() {
        assert!(is_stopped_entity(&vec!["word"; 13].join(" ")));
        assert!(!is_stopped_entity(&vec!["word"; 12].join(" ")));
        assert!(is_stopped_entity(&"x".repeat(201)));
    }

    // ----------------------------------------------------------------------------------
    // Parity with the Python twin.
    // ----------------------------------------------------------------------------------

    /// FNV-1a 64 of `canonical_stoplist_rendering()`. The identical literal lives in
    /// `main_services/processing/tests/unit/test_entity_stoplist.py`; when this test says
    /// the digest changed, make the same edit there and set the new digest in BOTH files.
    const STOPLIST_PARITY_DIGEST: &str = "f4d99d806844b2eb";

    /// Every value the two implementations must agree on, in one deterministic string.
    ///
    /// Sorted, because the two languages spell their collections differently and only the
    /// content is the contract. Byte order and code-point order coincide in UTF-8, so
    /// Rust's `sort` and Python's `sorted` produce the same sequence.
    fn canonical_stoplist_rendering() -> String {
        let limits = [
            format!("blob_min_case_switches={BLOB_MIN_CASE_SWITCHES}"),
            format!("blob_min_chars={BLOB_MIN_CHARS}"),
            format!("max_chars={MAX_CHARS}"),
            format!("max_single_char_tokens={MAX_SINGLE_CHAR_TOKENS}"),
            format!("max_tokens={MAX_TOKENS}"),
        ];
        let sections: [(&str, Vec<&str>); 9] = [
            ("mail_header_names", MAIL_HEADER_NAMES.to_vec()),
            ("protocol_tokens", PROTOCOL_TOKENS.to_vec()),
            ("day_and_month_tokens", DAY_AND_MONTH_TOKENS.to_vec()),
            ("reply_block_headers", REPLY_BLOCK_HEADERS.to_vec()),
            (
                "colon_only_reply_block_headers",
                COLON_ONLY_REPLY_BLOCK_HEADERS.to_vec(),
            ),
            ("original_message_marker", vec![ORIGINAL_MESSAGE_MARKER]),
            ("limits", limits.iter().map(String::as_str).collect()),
            ("debris", DEBRIS.to_vec()),
            ("keep", KEEP.to_vec()),
        ];
        let mut rendering = String::new();
        for (name, mut items) in sections {
            rendering.push_str(&format!("[{name}]\n"));
            items.sort_unstable();
            for item in items {
                rendering.push_str(item);
                rendering.push('\n');
            }
        }
        rendering
    }

    /// FNV-1a over UTF-8. Chosen because it is ten lines in both languages and needs no
    /// dependency on either side; this is a change detector, not a security boundary.
    fn fnv1a_64(text: &str) -> String {
        let mut digest: u64 = 0xcbf2_9ce4_8422_2325;
        for byte in text.as_bytes() {
            digest = (digest ^ u64::from(*byte)).wrapping_mul(0x100_0000_01b3);
        }
        format!("{digest:016x}")
    }

    /// The two modules cannot share a file: `hoover4-worker` mounts only
    /// `main_services/processing` and `hoover4-website` mounts only `website/`, so no path
    /// is visible to both test runs. Each side hashes its own copy of the rule data and
    /// the cases above into the same literal instead. A change made here and not there
    /// fails this test; updating the digest to match then fails the Python side until the
    /// same change is made there, so the two lists cannot land out of step.
    #[test]
    fn the_two_implementations_have_not_drifted() {
        let digest = fnv1a_64(&canonical_stoplist_rendering());
        assert_eq!(
            digest, STOPLIST_PARITY_DIGEST,
            "the stop-list data changed. Make the same change in \
             main_services/processing/tasks/entity_stoplist.py and its unit test, and set \
             STOPLIST_PARITY_DIGEST to {digest} in both files."
        );
    }
}
