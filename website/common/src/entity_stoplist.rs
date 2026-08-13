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
//! Rules reject on **shape** where a shape exists — an `X-` header name, a token ending
//! in the quoted-printable soft break `=`, a long case-shuffled run of base64 characters,
//! four or more single-character tokens (letter-spaced PDF text) — and fall back to a
//! named set only for things with no shape: the standard mail headers, the day and month
//! names, a handful of SMTP/MIME protocol words. Every rule matches the **whole value**,
//! so `May` goes and `May Chen` stays.

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

const BLOB_MIN_CHARS: usize = 24;
const BLOB_MIN_CASE_SWITCHES: usize = 4;
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

    // A quoted-printable soft line break: the `=` is the line continuation, and the model
    // takes the fragment before it (`of=`, `th=`) for a name.
    if !text.chars().any(char::is_whitespace) && text.ends_with('=') {
        return true;
    }

    looks_like_encoded_blob(text)
}

#[cfg(test)]
mod tests {
    use super::is_stopped_entity;

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
        "Dow Jones & Company",
        "U.S.",
        "3M",
        "eBay",
        "李",
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
    fn a_paragraph_is_not_an_entity() {
        assert!(is_stopped_entity(&vec!["word"; 13].join(" ")));
        assert!(!is_stopped_entity(&vec!["word"; 12].join(" ")));
        assert!(is_stopped_entity(&"x".repeat(201)));
    }
}
