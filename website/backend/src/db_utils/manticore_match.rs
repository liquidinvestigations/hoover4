//! Turning user text into a Manticore `MATCH()` argument.
//!
//! Manticore has no parameter binding over the HTTP SQL endpoint, so a `MATCH()`
//! argument crosses two language boundaries at once and each one has its own escape
//! rule:
//!
//! 1. the **SQL string literal** it is wrapped in: `\` and `'` are what could break
//!    out of it, and Manticore wants a **backslash**, not the SQL-standard doubling;
//! 2. the **full-text query expression** living inside that literal, `"`, `(`, `/`,
//!    `~`, `|` and `\` are operators, and an unbalanced or dangling one is a hard error
//!    from the parser rather than an empty result set. Quoting a phrase does not make
//!    its contents inert: `|` and `\` keep their meaning inside one.
//!
//! `format_sql_query::QuotedData` handles neither: it doubles the quote, which
//! Manticore's parser rejects outright (`P01: syntax error`). **Never build a
//! `MATCH()` argument with it.** Everything goes through [`prepare_match_query`] or,
//! for text that is already known to carry no query syntax, [`quoted_manticore_string`].
//!
//! The same rules are implemented in Python for the collection-search MCP server
//! (`collection_search_server/backends.py`). Both runtimes talk to the same Manticore
//! and neither may depend on the other being right.

/// Escape a value for a single-quoted Manticore SQL string literal.
///
/// Backslash first, then the quote, reversing the order would double-escape the
/// backslashes introduced by the quote pass.
pub fn escape_manticore_string(value: &str) -> String {
    value.replace('\\', "\\\\").replace('\'', "\\'")
}

/// [`escape_manticore_string`] wrapped in the single quotes it is escaped for, ready to
/// interpolate into a statement.
pub fn quoted_manticore_string(value: &str) -> String {
    format!("'{}'", escape_manticore_string(value))
}

/// Manticore's boolean/proximity keywords. They are not search terms, so they do not
/// count when deciding whether a query has anything positive to match on, and a `/`
/// directly after one is that operator's distance argument rather than a stray slash.
const MATCH_KEYWORDS: &[&str] =
    &["AND", "OR", "NOT", "MAYBE", "NEAR", "SENTENCE", "PARAGRAPH", "ZONE", "ZONESPAN"];

/// A `MATCH()` expression that cannot be repaired into something searchable.
///
/// The message is shown to whoever typed the query, so it says what to do about it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MatchQueryError(pub String);

impl std::fmt::Display for MatchQueryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for MatchQueryError {}

/// The result of turning free text into a `MATCH()` expression.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PreparedMatch {
    /// Escaped and ready to interpolate into a single-quoted Manticore string literal.
    pub expr: String,
    /// What was silently fixed, so a caller can say so rather than return a surprise.
    pub repairs: Vec<String>,
}

impl PreparedMatch {
    /// The expression wrapped in the single quotes it is escaped for.
    pub fn quoted(&self) -> String {
        format!("'{}'", self.expr)
    }
}

/// One token of [`rewrite_boolean_words`]: its byte range in the query.
struct WordToken {
    start: usize,
    end: usize,
}

/// Split a query into tokens for [`rewrite_boolean_words`]. Whitespace separates tokens,
/// `(` and `)` outside quotes are tokens of their own, and a quoted run, closed or not,
/// stays inside the token that holds it.
fn boolean_word_tokens(query: &str) -> Vec<WordToken> {
    let mut tokens = Vec::new();
    let mut start: Option<usize> = None;
    let mut in_phrase = false;
    for (i, c) in query.char_indices() {
        if c == '"' {
            in_phrase = !in_phrase;
            start.get_or_insert(i);
            continue;
        }
        if in_phrase {
            continue;
        }
        if c.is_whitespace() || c == '(' || c == ')' {
            if let Some(s) = start.take() {
                tokens.push(WordToken { start: s, end: i });
            }
            if c != '(' && c != ')' {
                continue;
            }
            tokens.push(WordToken { start: i, end: i + 1 });
            continue;
        }
        start.get_or_insert(i);
    }
    if let Some(s) = start {
        tokens.push(WordToken { start: s, end: query.len() });
    }
    tokens
}

/// Read the words `OR`, `AND` and `NOT` as the operators they are in a Boolean search.
///
/// Manticore reads these words as ordinary search terms, so `a OR b` finds only a text
/// that holds all three words. The rule: `OR` between two terms becomes `|`, a bare
/// `AND` is dropped because every word must occur anyway, and `NOT x` becomes `-x`. An
/// `OR` or `NOT` with no term on the needed side is dropped. Only the upper-case words
/// are operators, and nothing inside double quotes changes. Each operator token is
/// replaced in place and the rest of the text is kept as it is, so `"a b"~3` and an
/// unbalanced quote reach the later passes unchanged.
///
/// The Python copy is `_rewrite_boolean_words` in
/// `collection_search_server/backends.py`. The two copies are one rule and change in
/// one patch.
fn rewrite_boolean_words(query: &str) -> (String, Vec<String>) {
    let tokens = boolean_word_tokens(query);
    let text = |t: &WordToken| &query[t.start..t.end];
    let is_term = |s: &str| !matches!(s, "OR" | "AND" | "NOT" | "|" | "(" | ")");
    let (mut or_read, mut and_dropped, mut not_read, mut stray) = (0usize, 0usize, 0usize, 0usize);
    let mut out = String::with_capacity(query.len());
    // The last token written to the output, for the left side of an `OR`.
    let mut last_written: Option<String> = None;
    let mut join_next = false;
    let mut cursor = 0usize;
    for (i, token) in tokens.iter().enumerate() {
        let gap = &query[cursor..token.start];
        if !join_next {
            out.push_str(gap);
        }
        join_next = false;
        cursor = token.end;
        let word = text(token);
        let next = tokens.get(i + 1).map(text);
        let written = match word {
            "AND" => {
                and_dropped += 1;
                None
            }
            "OR" => {
                let before = last_written.as_deref().is_some_and(|w| is_term(w) || w == ")");
                let after = next.is_some_and(|w| is_term(w) || w == "(");
                if before && after {
                    or_read += 1;
                    Some("|")
                } else {
                    stray += 1;
                    None
                }
            }
            "NOT" => {
                if next.is_some_and(|w| is_term(w) || w == "(") {
                    not_read += 1;
                    join_next = true;
                    Some("-")
                } else {
                    stray += 1;
                    None
                }
            }
            other => Some(other),
        };
        if let Some(w) = written {
            out.push_str(w);
            if w != "-" {
                last_written = Some(w.to_string());
            }
        }
    }
    out.push_str(&query[cursor..]);
    let mut repairs = Vec::new();
    if or_read > 0 {
        repairs.push(format!("read {or_read} OR as |, because OR is an ordinary word in a search"));
    }
    if and_dropped > 0 {
        repairs.push(format!("dropped {and_dropped} AND, because every word of a query must occur anyway"));
    }
    if not_read > 0 {
        repairs.push(format!("read {not_read} NOT x as -x, because NOT is an ordinary word in a search"));
    }
    if stray > 0 {
        repairs.push(format!("dropped {stray} OR or NOT with no word on one side"));
    }
    (out, repairs)
}

/// Drop a dangling `"`. An unbalanced quote is `syntax error, unexpected $end`.
fn balance_quotes(query: &str) -> (String, Vec<String>) {
    if query.matches('"').count() % 2 == 0 {
        return (query.to_string(), Vec::new());
    }
    let cut = query.rfind('"').expect("odd count implies at least one");
    let mut out = String::with_capacity(query.len() - 1);
    out.push_str(&query[..cut]);
    out.push_str(&query[cut + 1..]);
    (out, vec![r#"dropped an unbalanced ": a phrase search needs both quotes"#.to_string()])
}

/// Close or drop unbalanced `(`. Same `unexpected $end` failure as a stray quote.
///
/// A missing `)` is closed rather than dropped, because `(test | document` is a complete
/// thought with a typo in it and `(test | document)` is what was meant. A surplus `)`
/// has no such reading and is removed.
///
/// Parens **inside a phrase are not counted here**: they are operators there too, and
/// [`neutralise_stray_operators`] removes them. Counting them instead would put the
/// repair outside the quotes it was trying to fix. An entity value like `Rule 20.4(c`
/// is searched for as the phrase `"Rule 20.4(c"`, and closing that `(` appends the `)`
/// after the closing quote, a syntax error built by the code meant to prevent one. This
/// runs after [`balance_quotes`], so the scan can never end mid-phrase.
fn balance_parens(query: &str) -> (String, Vec<String>) {
    let mut out = String::with_capacity(query.len());
    let mut depth = 0usize;
    let mut dropped = 0usize;
    let mut in_phrase = false;
    for c in query.chars() {
        if c == '"' {
            in_phrase = !in_phrase;
        } else if !in_phrase {
            match c {
                '(' => depth += 1,
                ')' => {
                    if depth == 0 {
                        dropped += 1;
                        continue;
                    }
                    depth -= 1;
                }
                _ => {}
            }
        }
        out.push(c);
    }
    let mut repairs = Vec::new();
    if dropped > 0 {
        repairs.push(format!("dropped {dropped} unmatched ')'"));
    }
    if depth > 0 {
        repairs.push(format!("added {depth} missing ')' to close the grouping"));
    }
    out.push_str(&")".repeat(depth));
    (out, repairs)
}

/// Neutralise the operator characters that cannot stand where they are.
///
/// **Outside a phrase**, `/` and `~` are suffix operators on a phrase or a keyword:
/// `"a b"~3` is proximity, `"a b c"/2` is quorum, `NEAR/3` carries its distance the same
/// way. Standing alone between two words they are neither: `3/4` and `a~2` are
/// `P08: syntax error` from the parser, not a zero-result search.
///
/// **Inside a phrase**, quoting does NOT make the contents inert, measured against a
/// live Manticore rather than assumed. `"Rule 20.4(c"`, `"a) b"` and `"File | New"` are each a
/// `P08: syntax error`, while the same phrases with those characters removed match. So
/// `(`, `)` and `|` keep their meaning between quotes and are neutralised there, and `\`
/// still escapes the character after it. A value ending in one escapes the phrase's own
/// closing quote and the query runs off the end (`unexpected $end`).
///
/// This is why parens inside a phrase are removed here rather than balanced: a phrase is
/// how the entities panel searches for a value, corpus entity values are full of
/// unmatched parens and menu pipes, and closing one would append the `)` outside the
/// quote it was meant to fix.
///
/// Every replacement is a word separator rather than a deletion, because Manticore
/// tokenises on non-alphanumerics anyway: the repaired query searches for what was typed.
fn neutralise_stray_operators(query: &str) -> (String, Vec<String>) {
    let chars: Vec<char> = query.chars().collect();
    let mut out = String::with_capacity(query.len());
    let mut in_phrase = false;
    let mut word = String::new();
    let mut stray = 0usize;
    for (i, &c) in chars.iter().enumerate() {
        if c == '"' {
            in_phrase = !in_phrase;
            word.clear();
            out.push(c);
            continue;
        }
        if in_phrase {
            match c {
                '|' | '(' | ')' => {
                    stray += 1;
                    out.push(' ');
                }
                '\\' => stray += 1,
                _ => out.push(c),
            }
            continue;
        }
        if c == '/' || c == '~' {
            // The distance/quorum argument of the phrase or keyword just closed.
            let attached = matches!(chars[..i].iter().rev().find(|c| !c.is_whitespace()), Some('"'))
                || (c == '/' && MATCH_KEYWORDS.contains(&word.to_uppercase().as_str()));
            if attached {
                out.push(c);
            } else {
                stray += 1;
                out.push(' ');
            }
            word.clear();
            continue;
        }
        if c.is_whitespace() {
            word.clear();
        } else {
            word.push(c);
        }
        out.push(c);
    }
    let repairs = if stray > 0 {
        vec![format!("neutralised {stray} operator character that cannot stand where it was")]
    } else {
        Vec::new()
    };
    (out, repairs)
}

/// Whether anything in the query can *match*, as opposed to only exclude.
///
/// Manticore rejects a query built only from negations: `-zzz` alone is
/// `query is non-computable (single NOT operator)`, an error rather than an empty
/// result. A quoted phrase counts as positive, and so does any word not introduced by
/// `-`/`!`.
fn has_positive_term(query: &str) -> bool {
    let mut in_phrase = false;
    for token in query.split_whitespace().flat_map(split_keeping_quotes) {
        if token == "\"" {
            in_phrase = !in_phrase;
            continue;
        }
        if in_phrase {
            if token.chars().any(|c| c.is_alphanumeric()) {
                return true;
            }
            continue;
        }
        if token.starts_with('-') || token.starts_with('!') {
            continue;
        }
        let word = token.trim_matches(|c| "()|/~^=*".contains(c));
        // `NEAR/3` and `ZONE/2` carry their distance in the token, so compare on the
        // part before the slash, otherwise the operator itself reads as a search word
        // and `NEAR/3 -zzz` looks computable when Manticore says it is not.
        let head = word.split('/').next().unwrap_or(word).to_uppercase();
        if MATCH_KEYWORDS.contains(&head.as_str()) || word.starts_with('@') {
            continue;
        }
        if word.chars().any(|c| c.is_alphanumeric()) {
            return true;
        }
    }
    false
}

/// Split one whitespace-delimited token into runs of non-quote text and bare `"`
/// markers, so [`has_positive_term`] can track phrase boundaries mid-token.
fn split_keeping_quotes(token: &str) -> Vec<&str> {
    let mut parts = Vec::new();
    let mut start = 0;
    for (i, c) in token.char_indices() {
        if c == '"' {
            if i > start {
                parts.push(&token[start..i]);
            }
            parts.push(&token[i..i + 1]);
            start = i + 1;
        }
    }
    if start < token.len() {
        parts.push(&token[start..]);
    }
    parts
}

/// Turn caller text into a `MATCH()` expression, repairing what can be repaired.
///
/// Operators are **passed through** rather than stripped: `"exact phrase"`, `-exclude`,
/// `term*`, `a | b`, `^start`, `=exact` and `NEAR/3` are what a caller uses Manticore's
/// extended syntax for. What this heads off instead are the shapes that come back as a
/// parser error the user cannot act on:
///
/// * an unbalanced `"` or `(`: `syntax error, unexpected $end`
/// * a stray `/` or `~`, `P08: syntax error, unexpected '/'`
/// * a query with no positive term, `non-computable (single NOT operator)`
/// * an empty query, `MATCH('')` is not an error at all, which is worse: it matches
///   **every row** in the shard. A caller that means "everything" must say so by not
///   calling this.
///
/// Escaping stays last: the SQL literal is a separate concern from the query language
/// living inside it, and running the repair pass over already-escaped text would count
/// the escape backslashes as content.
///
/// The words `OR`, `AND` and `NOT` are read first, by [`rewrite_boolean_words`], and
/// each rewrite is one line of `repairs`.
pub fn prepare_match_query(query: &str) -> Result<PreparedMatch, MatchQueryError> {
    if query.trim().is_empty() {
        return Err(MatchQueryError("query is empty".to_string()));
    }

    let (cleaned, mut repairs) = rewrite_boolean_words(query);
    let (cleaned, quote_repairs) = balance_quotes(&cleaned);
    repairs.extend(quote_repairs);
    let (cleaned, paren_repairs) = balance_parens(&cleaned);
    let (cleaned, operator_repairs) = neutralise_stray_operators(&cleaned);
    repairs.extend(paren_repairs);
    repairs.extend(operator_repairs);

    let cleaned = cleaned.split_whitespace().collect::<Vec<_>>().join(" ");
    if cleaned.is_empty() {
        return Err(MatchQueryError("query has no searchable terms".to_string()));
    }
    if !has_positive_term(&cleaned) {
        return Err(MatchQueryError(
            "query only excludes terms; Manticore cannot run a search made of \
             negations alone. Add at least one word to search for, e.g. \
             'contract -draft' rather than '-draft'."
                .to_string(),
        ));
    }

    Ok(PreparedMatch { expr: escape_manticore_string(&cleaned), repairs })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The whole reason this module exists: Manticore rejects the SQL-standard doubling
    /// that `format_sql_query::QuotedData` emits.
    #[test]
    fn a_quote_is_escaped_with_a_backslash_never_by_doubling() {
        assert_eq!(escape_manticore_string("it's"), r"it\'s");
        assert_eq!(quoted_manticore_string("it's"), r"'it\'s'");
        assert!(!escape_manticore_string("it's").contains("''"));
    }

    #[test]
    fn the_backslash_pass_runs_before_the_quote_pass() {
        // Reversed, the `\` introduced by the quote pass would be doubled again and the
        // quote would arrive at Manticore unescaped.
        assert_eq!(escape_manticore_string(r"a\b"), r"a\\b");
        assert_eq!(escape_manticore_string(r"a\'b"), r"a\\\'b");
    }

    fn prepared(query: &str) -> String {
        prepare_match_query(query).unwrap().expr
    }

    #[test]
    fn an_apostrophe_survives_as_content() {
        assert_eq!(prepared("it's a test"), r"it\'s a test");
    }

    #[test]
    fn a_dangling_quote_is_dropped() {
        let p = prepare_match_query(r#"say"hi"#).unwrap();
        assert_eq!(p.expr, "sayhi");
        assert_eq!(p.repairs.len(), 1);
    }

    #[test]
    fn a_balanced_phrase_is_left_alone() {
        assert_eq!(prepared(r#""exact phrase" other"#), r#""exact phrase" other"#);
        assert!(prepare_match_query(r#""exact phrase""#).unwrap().repairs.is_empty());
    }

    #[test]
    fn unbalanced_parens_are_closed_or_dropped() {
        assert_eq!(prepared("(test | document"), "(test | document)");
        assert_eq!(prepared("test | document)"), "test | document");
    }

    /// Quoting does not make a phrase's contents inert. Each of these was run against a
    /// live Manticore in both spellings: with the character it is `P08: syntax error`,
    /// without it the phrase matches. Every shape here comes straight out of the corpus.
    /// NER emits legal citations, menu paths and Windows paths, and the entities panel
    /// searches each value as a phrase.
    #[test]
    fn the_operators_that_keep_their_meaning_inside_a_phrase_are_neutralised() {
        assert_eq!(prepared(r#""Rule 20.4(c""#), r#""Rule 20.4 c""#);
        assert_eq!(prepared(r#""a) b""#), r#""a  b""#.replace("  ", " "));
        assert_eq!(prepared(r#""File | New""#), r#""File New""#);
        // A trailing `\` escapes the phrase's own closing quote: `unexpected $end`.
        assert_eq!(prepared(r#""Shared\ PhotoEd\""#), r#""Shared PhotoEd""#);
    }

    /// …while outside a phrase every one of them is a real operator and must survive.
    #[test]
    fn the_same_operators_outside_a_phrase_are_left_alone() {
        assert_eq!(prepared("a | b"), "a | b");
        assert_eq!(prepared("(a | b)"), "(a | b)");
        assert_eq!(prepared(r#"("exact phrase" | other"#), r#"("exact phrase" | other)"#);
    }

    #[test]
    fn a_stray_slash_or_tilde_becomes_a_separator() {
        assert_eq!(prepared("3/4"), "3 4");
        assert_eq!(prepared("a~2"), "a 2");
        assert_eq!(prepared("path/to/file"), "path to file");
    }

    #[test]
    fn the_phrase_operators_keep_their_argument() {
        assert_eq!(prepared(r#""hello world"~3"#), r#""hello world"~3"#);
        assert_eq!(prepared(r#""one two three"/2"#), r#""one two three"/2"#);
        assert_eq!(prepared("NEAR/3 contract"), "NEAR/3 contract");
        // Inside a phrase both are literal text.
        assert_eq!(prepared(r#""3/4 cup""#), r#""3/4 cup""#);
    }

    #[test]
    fn a_negation_only_query_is_an_error_not_a_500() {
        // Manticore answers `non-computable (single NOT operator)` to all of these.
        for bad in ["!a", "-draft", "!a !b", "-a -b"] {
            assert!(prepare_match_query(bad).is_err(), "should reject {bad:?}");
        }
        // …but a negation with something to subtract from is a real query.
        assert_eq!(prepared("contract -draft"), "contract -draft");
        assert_eq!(prepared("a !b"), "a !b");
    }

    #[test]
    fn an_empty_query_is_an_error_because_it_would_match_everything() {
        assert!(prepare_match_query("").is_err());
        assert!(prepare_match_query("   ").is_err());
        assert!(prepare_match_query("\"\"").is_err());
    }

    #[test]
    fn a_phrase_counts_as_a_positive_term() {
        assert_eq!(prepared(r#""annual report" -draft"#), r#""annual report" -draft"#);
    }

    #[test]
    fn whitespace_is_trimmed_and_collapsed() {
        assert_eq!(prepared("  a   b  "), "a b");
    }

    /// The rewrite of `OR`, `AND` and `NOT`. The Python copy in
    /// `collection_search_server/tests/test_backends_rewrite.py` holds the same table,
    /// and the two tables change in one patch. The output is the text before the escape.
    const OR_LINE: &str = "read 1 OR as |, because OR is an ordinary word in a search";
    const AND_LINE: &str = "dropped 1 AND, because every word of a query must occur anyway";
    const NOT_LINE: &str = "read 1 NOT x as -x, because NOT is an ordinary word in a search";
    const STRAY_LINE: &str = "dropped 1 OR or NOT with no word on one side";

    #[test]
    fn the_boolean_words_are_read_as_operators() {
        let table: &[(&str, &str, &[&str])] = &[
            (r#"JoeBWilkinson@cs.com OR "Joe B Wilkinson""#, r#"JoeBWilkinson@cs.com | "Joe B Wilkinson""#, &[OR_LINE]),
            ("LJM AND Raptor", "LJM Raptor", &[AND_LINE]),
            ("water NOT draft", "water -draft", &[NOT_LINE]),
            ("(a OR b) AND c", "(a | b) c", &[OR_LINE, AND_LINE]),
            (r#""cats OR dogs""#, r#""cats OR dogs""#, &[]),
            ("water or sewage", "water or sewage", &[]),
            ("OR water", "water", &[STRAY_LINE]),
            ("a OR OR b", "a | b", &[OR_LINE, STRAY_LINE]),
            (r#""a b"~3 OR c"#, r#""a b"~3 | c"#, &[OR_LINE]),
            (r#"a OR "b"#, r#"a | "b"#, &[OR_LINE]),
        ];
        for (input, want, want_repairs) in table {
            let (got, repairs) = rewrite_boolean_words(input);
            assert_eq!(got.split_whitespace().collect::<Vec<_>>().join(" "), *want, "for {input:?}");
            assert_eq!(repairs, want_repairs.iter().map(|s| s.to_string()).collect::<Vec<_>>(), "for {input:?}");
        }
        assert_eq!(
            prepare_match_query("NOT"),
            Err(MatchQueryError("query has no searchable terms".to_string()))
        );
        // The rewrite runs first, so its lines come before the repairs of the later passes.
        let p = prepare_match_query(r#"a OR "b"#).unwrap();
        assert_eq!(p.expr, "a | b");
        assert_eq!(p.repairs[0], OR_LINE);
        assert_eq!(p.repairs.len(), 2);
    }

    /// The characters measured against a live Manticore as breaking the extended
    /// syntax. Every one of them must now produce something the parser accepts, or a
    /// typed error, never a string that reaches Manticore and errors there.
    #[test]
    fn every_known_breaking_character_is_handled() {
        for (input, expected) in [
            ("it's", Some(r"it\'s")),
            ("3/4", Some("3 4")),
            (r#"say"hi"#, Some("sayhi")),
            ("a~2", Some("a 2")),
            ("computer", Some("computer")),
            ("!a", None),
        ] {
            match (prepare_match_query(input), expected) {
                (Ok(p), Some(want)) => assert_eq!(p.expr, want, "for {input:?}"),
                (Err(_), None) => {}
                (got, want) => panic!("for {input:?}: got {got:?}, wanted {want:?}"),
            }
        }
    }
}
