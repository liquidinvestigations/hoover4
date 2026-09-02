//! Upstream conformance: do our rules agree with the projects we ported them from?
//!
//! The golden corpus measures us against cases we wrote. This measures us against cases the
//! upstream implementers wrote, every `python-stdnum` module's docstring is a labelled
//! valid/invalid corpus for its own scheme, and the same is true of the other reference projects
//! on disk. Agreement with upstream is the only evidence that a ported check digit means what its
//! author meant.
//!
//! The run is deliberately out of the fast battery's way: it is `#[ignore]`d, so `cargo test`
//! compiles and lints it but never runs it, and `./test-long.sh` runs it by name. Keeping it a
//! normal test target rather than a binary means it shares `tests/support`, gets clippy and
//! rustfmt for free, and cannot rot unnoticed.
//!
//! ## Reading an upstream test as a scan
//!
//! Upstream calls an API on a bare token; we scan free text. The translation is fixed and applied
//! uniformly, and it is recorded in the case file rather than reinvented here:
//!
//! - **The carrier.** Every token is placed in one neutral sentence that contains no digits, no
//!   currency symbol and no cue word of its own, so the only thing the scanner can find in a case
//!   is the token.
//! - **The cue.** Several rules refuse a bare token without a nearby cue word, because a check
//!   digit alone is a one-in-ten filter. Calling `stdnum.cusip.validate` *is* the statement "this
//!   is a CUSIP", so that scheme's own documented cue goes in the carrier. A cue is never supplied
//!   to a rule that does not require one.
//! - **The token is verbatim.** Separators, case and punctuation are left exactly as upstream
//!   wrote them, because how a number survives contact with real prose is the property under test.
//!
//! ## The three numbers
//!
//! Recall, precision and coverage are reported separately and never blended. Recall is over
//! upstream-valid cases in a scheme we implement; precision is over upstream-invalid ones, and
//! asks only whether we stayed silent, except where upstream's assertion was about one
//! recogniser rather than about a span, for which see `classify`; coverage is how much of the extracted material was scored
//! at all. Every excluded case carries an individually justifiable reason and is counted beside
//! the scores, because a run that excludes its way to a good number is worthless.

mod support;

use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::path::{Path, PathBuf};
use std::time::Instant;

use regex_entity_scanner::model::{Entity, Value};
use serde::{Deserialize, Serialize};

/// The per-scheme cap that keeps the run inside its budget. The case file is sorted by id and an
/// id starts with its scheme, so taking the first `n` of a scheme is a stable sample: the same
/// cases every run, on any machine, with no random seed to carry. Raise it with
/// `RES_CONFORMANCE_MAX_PER_SCHEME`.
const DEFAULT_MAX_PER_SCHEME: usize = 500;

/// Regression floors, in percent. They are a ratchet, not a target: they sit just under the
/// numbers the current rule set produces, so a rule change that loses upstream agreement fails the
/// run instead of quietly eroding it. Raise them when a fix moves the real number up.
///
/// An origin joining the corpus changes the denominator rather than the rules, so the aggregate
/// floor is re-derived from the run at the commit that adds one. A new rule does the same thing
/// from the other side: the cases for a scheme nothing claimed were excluded as *no rule for this
/// entity type*, and the rule that claims them turns every one of them into a scored case at once.
/// Both are a larger denominator rather than a regression, and both re-derive the floor in the
/// commit that moves it. It is never lowered to let an unchanged corpus pass.
///
/// The aggregate stands under a corpus in which the payment-card scheme is scored: the card rule
/// requires a cue word, and three of Presidio's valid fixtures are one fragment holding three card
/// numbers and no cue, which is the rule's documented limit rather than a defect.
const MIN_RECALL_PERCENT: f64 = 97.4;
const MIN_PRECISION_PERCENT: f64 = 99.5;

/// The same ratchet per origin: minimum recall, then minimum precision. The aggregate floor alone
/// lets one origin regress a long way behind the others. The largest origin is twenty times the
/// smallest, so a rule that loses every case in a small one moves the aggregate by less than the
/// floor's own margin. Every origin in the corpus must appear here, which is what makes adding an
/// origin a decision about the number it is expected to hold rather than a free pass.
///
/// An origin with no upstream-invalid cases has no precision to measure; its precision floor is
/// still written down, and is not asserted until such a case exists.
const ORIGIN_FLOORS: &[(&str, f64, f64)] = &[
    ("advisory-database", 99.5, 99.5),
    ("crossref", 99.5, 99.5),
    ("dateparser", 99.0, 99.0),
    ("eth-utils", 99.5, 99.5),
    ("grok", 99.0, 99.0),
    ("hoover-mail", 95.0, 99.5),
    ("isemail", 78.0, 99.5),
    ("libphonenumber", 98.5, 99.5),
    ("open-location-code", 99.5, 99.5),
    // The five cue-gated schemes are scored here, and eight of their sixty-four cases are out of
    // reach on purpose. Five are cards: three sit in one fragment that writes three card numbers
    // and no cue word, and two are a fifteen-digit airline-range number the issuer table does not
    // admit. Two more are a Swedish number beside a word its rule's cue list does not carry, and
    // one is a number written with no space between it and the word in front of it, which the
    // standalone guard refuses.
    ("presidio", 97.0, 99.5),
    ("price-parser", 98.0, 99.5),
    ("pyais", 99.5, 99.5),
    ("python-stdnum", 86.0, 99.5),
    ("recognizers-text", 78.5, 99.5),
];

#[derive(Debug, Deserialize)]
struct Case {
    id: String,
    origin: String,
    source: String,
    scheme: String,
    token: String,
    text: String,
    token_start: usize,
    token_end: usize,
    valid: bool,
    rule_id: Option<String>,
    entity_type: Option<String>,
    expect_value: Option<String>,
    exclusion: Option<String>,
}

/// What one case turned into. The four failing kinds are separated because they call for different
/// work: a miss is ours to fix or to justify, a value disagreement is a normalisation argument,
/// and a spurious match under another type is a precision bug in a rule the case was not aiming at.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
enum Outcome {
    /// Upstream-valid, and we produced the expected type and normalised value.
    Hit,
    /// Upstream-valid, we produced the expected type, and upstream documents no canonical form to
    /// compare against (an `is_valid` example answers only `True`).
    HitValueUnchecked,
    /// Upstream-valid, we produced the expected type with a different normalised value.
    ValueDisagreement,
    /// Upstream-valid, we produced nothing of the expected type over the token.
    Miss,
    /// Upstream-invalid, and we stayed silent.
    Silent,
    /// Upstream-invalid, and we emitted the type the case was aiming at.
    SpuriousSameType,
    /// Upstream-invalid, and some other rule matched the token.
    SpuriousOtherType,
}

impl Outcome {
    fn counts_for_recall(self) -> bool {
        matches!(
            self,
            Outcome::Hit | Outcome::HitValueUnchecked | Outcome::ValueDisagreement | Outcome::Miss
        )
    }

    fn is_success(self) -> bool {
        matches!(
            self,
            Outcome::Hit | Outcome::HitValueUnchecked | Outcome::Silent
        )
    }
}

#[derive(Debug, Default, Serialize)]
struct Tally {
    cases: usize,
    scored: usize,
    excluded: usize,
    valid_scored: usize,
    valid_agreed: usize,
    invalid_scored: usize,
    invalid_silent: usize,
    /// Agreements where upstream documented no canonical form, so only the type was checked. They
    /// count towards recall exactly like a full agreement, and without the column a recall figure
    /// reads as stronger evidence than it is.
    value_unchecked: usize,
}

impl Tally {
    fn record(&mut self, outcome: Outcome) {
        self.scored += 1;
        if outcome == Outcome::HitValueUnchecked {
            self.value_unchecked += 1;
        }
        if outcome.counts_for_recall() {
            self.valid_scored += 1;
            if outcome.is_success() {
                self.valid_agreed += 1;
            }
        } else {
            self.invalid_scored += 1;
            if outcome.is_success() {
                self.invalid_silent += 1;
            }
        }
    }

    fn recall(&self) -> Option<f64> {
        percent(self.valid_agreed, self.valid_scored)
    }

    fn precision(&self) -> Option<f64> {
        percent(self.invalid_silent, self.invalid_scored)
    }

    fn coverage(&self) -> Option<f64> {
        percent(self.scored, self.cases)
    }
}

fn percent(part: usize, whole: usize) -> Option<f64> {
    (whole > 0).then(|| 100.0 * part as f64 / whole as f64)
}

fn show(value: Option<f64>) -> String {
    value.map_or_else(|| "     -".to_string(), |v| format!("{v:5.1}%"))
}

#[derive(Debug, Serialize)]
struct Failure {
    id: String,
    scheme: String,
    rule_id: Option<String>,
    source: String,
    outcome: Outcome,
    token: String,
    expected: Option<String>,
    observed: Vec<String>,
}

#[derive(Debug, Serialize)]
struct SchemeReport {
    scheme: String,
    rule_id: Option<String>,
    #[serde(flatten)]
    tally: Tally,
    recall_percent: Option<f64>,
    precision_percent: Option<f64>,
}

#[derive(Debug, Serialize)]
struct OriginReport {
    origin: String,
    #[serde(flatten)]
    tally: Tally,
    recall_percent: Option<f64>,
    precision_percent: Option<f64>,
    coverage_percent: Option<f64>,
    schemes: Vec<SchemeReport>,
}

#[derive(Debug, Serialize)]
struct Report {
    rule_set_version: u32,
    max_per_scheme: usize,
    sampled_away: usize,
    elapsed_seconds: f64,
    #[serde(flatten)]
    total: Tally,
    recall_percent: Option<f64>,
    precision_percent: Option<f64>,
    coverage_percent: Option<f64>,
    origins: Vec<OriginReport>,
    exclusions: Vec<Exclusion>,
    failures: Vec<Failure>,
}

#[derive(Debug, Serialize)]
struct Exclusion {
    reason: String,
    cases: usize,
    schemes: usize,
}

fn conformance_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/conformance")
}

/// Every case file in the conformance directory, or just one when `RES_CONFORMANCE_ORIGIN` names
/// it. The environment variable holds the file stem, which is what `./test-long.sh stdnum` passes.
fn case_files() -> Vec<PathBuf> {
    let dir = conformance_dir();
    if let Ok(only) = std::env::var("RES_CONFORMANCE_ORIGIN") {
        let path = dir.join(format!("{only}.jsonl"));
        assert!(
            path.is_file(),
            "no case file for origin {only:?} at {path:?}"
        );
        return vec![path];
    }
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .expect("reading the conformance directory")
        .filter_map(|entry| {
            let path = entry.expect("a directory entry").path();
            (path.extension().is_some_and(|ext| ext == "jsonl")).then_some(path)
        })
        .collect();
    files.sort();
    assert!(!files.is_empty(), "no case files in {dir:?}");
    files
}

/// The comparable form of a match: the same canonical string the golden corpus compares on.
fn canonical(entity: &Entity) -> String {
    match &entity.value {
        Value::Date { rfc3339, .. } => rfc3339.clone(),
        Value::Email { address, .. } => address.clone(),
        Value::Phone { e164, .. } => e164.clone(),
        Value::Money {
            currency,
            amount_minor,
            ..
        } => format!("{currency} {amount_minor}"),
        Value::Identifier { compact, .. } => compact.clone(),
        Value::NetworkAddress { address, .. } => address.clone(),
        Value::GeoPoint {
            latitude,
            longitude,
            ..
        } => format!("{latitude},{longitude}"),
    }
}

/// How far two coordinate readings may differ and still name the same point. A reference
/// implementation's own encode and decode material disagrees in the last bits of the double
/// (`2.7821874999999996` on one side, `2.7821875` on the other), and scoring that pair as a
/// disagreement measures floating-point formatting rather than the rule. A billionth of a degree is
/// a tenth of a millimetre, so nothing a reader would call a different place hides under it. It is
/// one constant applied componentwise rather than a per-case field, because a per-case field makes
/// every extractor fill in a column that one origin needs.
const COORDINATE_TOLERANCE: f64 = 1e-9;

/// Whether an observed canonical value answers the expected one: exact string equality, or
/// (for the comma-separated pair a geographic point formats as) componentwise agreement within
/// [`COORDINATE_TOLERANCE`].
fn values_agree(observed: &str, expected: &str) -> bool {
    if observed == expected {
        return true;
    }
    match (coordinate_pair(observed), coordinate_pair(expected)) {
        (Some(left), Some(right)) => {
            (left.0 - right.0).abs() <= COORDINATE_TOLERANCE
                && (left.1 - right.1).abs() <= COORDINATE_TOLERANCE
        }
        _ => false,
    }
}

fn coordinate_pair(text: &str) -> Option<(f64, f64)> {
    let (latitude, longitude) = text.split_once(',')?;
    Some((
        latitude.trim().parse().ok()?,
        longitude.trim().parse().ok()?,
    ))
}

fn type_name(entity: &Entity) -> String {
    serde_json::to_value(entity.entity_type)
        .expect("an entity type serialises")
        .as_str()
        .expect("as a string")
        .to_string()
}

fn classify(case: &Case, entities: &[Entity]) -> (Outcome, Vec<String>) {
    // Only matches that touch the token say anything about the case; nothing else in the carrier
    // can match, but overlap is the property that makes that a check rather than an assumption.
    let touching: Vec<&Entity> = entities
        .iter()
        .filter(|entity| entity.start < case.token_end && entity.end > case.token_start)
        .collect();
    let observed: Vec<String> = touching
        .iter()
        .map(|entity| {
            format!(
                "{}={} [{}]",
                type_name(entity),
                canonical(entity),
                entity.rule_id
            )
        })
        .collect();

    let wanted_type = case
        .entity_type
        .as_deref()
        .expect("a scored case names an entity type");
    let same_type: Vec<&&Entity> = touching
        .iter()
        .filter(|entity| type_name(entity) == wanted_type)
        .collect();

    // A case whose token is the whole fragment is an upstream sentence that one recogniser found
    // nothing in. That says nothing about the other facets: an email corpus asserting "no address
    // here" in a sentence that also holds an IP address is not a claim about the IP address, and
    // scoring the IP match as a false positive would measure the wrong thing. Where upstream named
    // a span, any type over that span is still a failure. That is the case the distinction turns
    // on.
    let whole_fragment = case.token_start == 0 && case.token_end == case.text.len();

    let outcome = if case.valid {
        match (&case.expect_value, same_type.first()) {
            (_, None) => Outcome::Miss,
            (None, Some(_)) => Outcome::HitValueUnchecked,
            (Some(want), Some(_)) => {
                if same_type
                    .iter()
                    .any(|entity| values_agree(&canonical(entity), want))
                {
                    Outcome::Hit
                } else {
                    Outcome::ValueDisagreement
                }
            }
        }
    } else if touching.is_empty() || (whole_fragment && same_type.is_empty()) {
        Outcome::Silent
    } else if same_type.is_empty() {
        Outcome::SpuriousOtherType
    } else {
        Outcome::SpuriousSameType
    };
    (outcome, observed)
}

fn max_per_scheme() -> usize {
    std::env::var("RES_CONFORMANCE_MAX_PER_SCHEME")
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(DEFAULT_MAX_PER_SCHEME)
}

#[test]
#[ignore = "the upstream conformance run; ./test-long.sh runs it, the fast battery does not"]
fn upstream_conformance() {
    let started = Instant::now();
    let scanner = support::scanner();
    let cap = max_per_scheme();

    let mut origins: Vec<OriginReport> = Vec::new();
    let mut exclusions: BTreeMap<String, (usize, std::collections::BTreeSet<String>)> =
        BTreeMap::new();
    let mut failures: Vec<Failure> = Vec::new();
    let mut total = Tally::default();
    let mut sampled_away = 0usize;

    for file in case_files() {
        let body = std::fs::read_to_string(&file).expect("reading a case file");
        let cases: Vec<Case> = body
            .lines()
            .filter(|line| !line.trim().is_empty())
            .map(|line| serde_json::from_str(line).expect("a well-formed case line"))
            .collect();

        let mut per_origin: BTreeMap<String, BTreeMap<String, (Option<String>, Tally)>> =
            BTreeMap::new();
        let mut seen_in_scheme: BTreeMap<String, usize> = BTreeMap::new();

        for case in &cases {
            let seen = seen_in_scheme.entry(case.scheme.clone()).or_default();
            *seen += 1;
            if *seen > cap {
                sampled_away += 1;
                continue;
            }

            let scheme_tally = per_origin
                .entry(case.origin.clone())
                .or_default()
                .entry(case.scheme.clone())
                .or_insert_with(|| (case.rule_id.clone(), Tally::default()));
            scheme_tally.1.cases += 1;

            if let Some(reason) = &case.exclusion {
                scheme_tally.1.excluded += 1;
                let entry = exclusions.entry(reason.clone()).or_default();
                entry.0 += 1;
                entry.1.insert(case.scheme.clone());
                continue;
            }

            let entities = scanner.scan(&case.text, 0);
            for entity in &entities {
                assert_eq!(
                    &case.text[entity.start..entity.end],
                    entity.text,
                    "in {} the span {}..{} does not cover the reported text",
                    case.id,
                    entity.start,
                    entity.end
                );
            }
            let (outcome, observed) = classify(case, &entities);
            scheme_tally.1.record(outcome);
            if !outcome.is_success() {
                failures.push(Failure {
                    id: case.id.clone(),
                    scheme: case.scheme.clone(),
                    rule_id: case.rule_id.clone(),
                    source: case.source.clone(),
                    outcome,
                    token: case.token.clone(),
                    expected: case.expect_value.clone(),
                    observed,
                });
            }
        }

        for (origin, schemes) in per_origin {
            let mut tally = Tally::default();
            let mut rows: Vec<SchemeReport> = Vec::new();
            for (scheme, (rule_id, scheme_tally)) in schemes {
                tally.cases += scheme_tally.cases;
                tally.scored += scheme_tally.scored;
                tally.excluded += scheme_tally.excluded;
                tally.valid_scored += scheme_tally.valid_scored;
                tally.valid_agreed += scheme_tally.valid_agreed;
                tally.invalid_scored += scheme_tally.invalid_scored;
                tally.invalid_silent += scheme_tally.invalid_silent;
                tally.value_unchecked += scheme_tally.value_unchecked;
                rows.push(SchemeReport {
                    scheme,
                    rule_id,
                    recall_percent: scheme_tally.recall(),
                    precision_percent: scheme_tally.precision(),
                    tally: scheme_tally,
                });
            }
            rows.retain(|row| row.tally.scored > 0);
            rows.sort_by(|a, b| a.scheme.cmp(&b.scheme));
            total.cases += tally.cases;
            total.scored += tally.scored;
            total.excluded += tally.excluded;
            total.valid_scored += tally.valid_scored;
            total.valid_agreed += tally.valid_agreed;
            total.invalid_scored += tally.invalid_scored;
            total.invalid_silent += tally.invalid_silent;
            total.value_unchecked += tally.value_unchecked;
            origins.push(OriginReport {
                origin,
                recall_percent: tally.recall(),
                precision_percent: tally.precision(),
                coverage_percent: tally.coverage(),
                schemes: rows,
                tally,
            });
        }
    }

    failures.sort_by(|a, b| a.id.cmp(&b.id));
    let report = Report {
        rule_set_version: regex_entity_scanner::rules::RULE_SET_VERSION,
        max_per_scheme: cap,
        sampled_away,
        elapsed_seconds: started.elapsed().as_secs_f64(),
        recall_percent: total.recall(),
        precision_percent: total.precision(),
        coverage_percent: total.coverage(),
        origins,
        exclusions: exclusions
            .into_iter()
            .map(|(reason, (cases, schemes))| Exclusion {
                reason,
                cases,
                schemes: schemes.len(),
            })
            .collect(),
        failures,
        total,
    };

    print!("{}", render(&report));
    if let Ok(path) = std::env::var("RES_CONFORMANCE_REPORT") {
        let path = PathBuf::from(path);
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).expect("creating the report directory");
        }
        std::fs::write(
            &path,
            serde_json::to_string_pretty(&report).expect("the report serialises"),
        )
        .expect("writing the report");
        println!("machine-readable report: {}", path.display());
    }

    assert!(
        report.total.scored > 0,
        "no case was scored; the harness measured nothing"
    );
    // A floor over an empty measurement is nothing rather than zero: an origin whose upstream
    // publishes only registered identifiers has no invalid case to stay silent about, and a run
    // narrowed to it has no precision to compare against a floor.
    if let Some(recall) = report.recall_percent {
        assert!(
            recall >= MIN_RECALL_PERCENT,
            "aggregate recall {recall:.1}% is below the {MIN_RECALL_PERCENT:.1}% floor"
        );
    }
    if let Some(precision) = report.precision_percent {
        assert!(
            precision >= MIN_PRECISION_PERCENT,
            "aggregate precision {precision:.1}% is below the {MIN_PRECISION_PERCENT:.1}% floor"
        );
    }

    // Skipped when the run was narrowed to one origin: the others are absent by request, not by
    // regression, and asserting a missing floor there would fail every single-origin run.
    if std::env::var("RES_CONFORMANCE_ORIGIN").is_err() {
        for (name, min_recall, min_precision) in ORIGIN_FLOORS {
            let origin = report
                .origins
                .iter()
                .find(|origin| &origin.origin == name)
                .unwrap_or_else(|| panic!("origin {name} has a floor but no cases in the corpus"));
            if let Some(value) = origin.recall_percent {
                assert!(
                    value >= *min_recall,
                    "{name} recall {value:.1}% is below its {min_recall:.1}% floor"
                );
            }
            if let Some(value) = origin.precision_percent {
                assert!(
                    value >= *min_precision,
                    "{name} precision {value:.1}% is below its {min_precision:.1}% floor"
                );
            }
        }
        for origin in &report.origins {
            assert!(
                ORIGIN_FLOORS
                    .iter()
                    .any(|(name, _, _)| name == &origin.origin),
                "origin {} has cases but no floor; add one to ORIGIN_FLOORS",
                origin.origin
            );
        }
    }
}

/// The human-readable half of the run: one row per scheme, the exclusions beside the scores, and
/// every disagreement named so it can be worked on without re-running.
fn render(report: &Report) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "\nupstream conformance — rule set version {}\n",
        report.rule_set_version
    );
    let _ = writeln!(
        out,
        "{:<26} {:>6} {:>6} {:>7} {:>7} {:>8} {:>9}",
        "scheme", "cases", "scored", "excl", "unchk", "recall", "precision"
    );
    for origin in &report.origins {
        let _ = writeln!(out, "{}", "-".repeat(73));
        let _ = writeln!(out, "{}", origin.origin);
        for row in &origin.schemes {
            let _ = writeln!(
                out,
                "  {:<24} {:>6} {:>6} {:>7} {:>7} {:>8} {:>9}",
                row.scheme,
                row.tally.cases,
                row.tally.scored,
                row.tally.excluded,
                row.tally.value_unchecked,
                show(row.recall_percent),
                show(row.precision_percent),
            );
        }
        let _ = writeln!(
            out,
            "  {:<24} {:>6} {:>6} {:>7} {:>7} {:>8} {:>9}   coverage {}",
            "= origin total",
            origin.tally.cases,
            origin.tally.scored,
            origin.tally.excluded,
            origin.tally.value_unchecked,
            show(origin.recall_percent),
            show(origin.precision_percent),
            show(origin.coverage_percent),
        );
    }
    let _ = writeln!(out, "{}", "=".repeat(73));
    let _ = writeln!(
        out,
        "{:<26} {:>6} {:>6} {:>7} {:>7} {:>8} {:>9}   coverage {}",
        "AGGREGATE",
        report.total.cases,
        report.total.scored,
        report.total.excluded,
        report.total.value_unchecked,
        show(report.recall_percent),
        show(report.precision_percent),
        show(report.coverage_percent),
    );
    let _ = writeln!(
        out,
        "\nrecall is over {} upstream-valid cases, precision over {} upstream-invalid ones.",
        report.total.valid_scored, report.total.invalid_scored
    );

    let _ = writeln!(out, "\nexclusions ({} cases):", report.total.excluded);
    for exclusion in &report.exclusions {
        let _ = writeln!(
            out,
            "  {:>5} cases across {:>3} schemes — {}",
            exclusion.cases, exclusion.schemes, exclusion.reason
        );
    }

    let _ = writeln!(out, "\ndisagreements ({}):", report.failures.len());
    for failure in &report.failures {
        let _ = writeln!(
            out,
            "  [{:?}] {} ({}) token {:?}",
            failure.outcome, failure.id, failure.source, failure.token
        );
        if let Some(expected) = &failure.expected {
            let _ = writeln!(out, "        expected {expected:?}");
        }
        if !failure.observed.is_empty() {
            let _ = writeln!(out, "        observed {}", failure.observed.join(", "));
        }
    }
    let _ = writeln!(
        out,
        "\n{} cases sampled away by the per-scheme cap of {}; run took {:.1}s",
        report.sampled_away, report.max_per_scheme, report.elapsed_seconds
    );
    out
}
