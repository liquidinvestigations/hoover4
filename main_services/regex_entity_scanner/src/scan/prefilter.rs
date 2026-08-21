//! Stage one: find candidates cheaply, and be wrong in the generous direction.
//!
//! Two passes, for a reason. The `RegexSet` pass answers "does any rule fire anywhere in this
//! fragment" for the whole rule set at once, and most fragments in a real corpus contain none of
//! what any given rule looks for. Only the rules that survive that answer then scan for their own
//! spans. As the rule set grows into the hundreds this is the difference between one pass and
//! hundreds of them, and it is why the candidate patterns must stay expressible in a linear-time
//! engine: they run over raw, attacker-influenceable document text, where a backtracking engine
//! has no bounded worst case.
//!
//! Candidates are collected per rule, so two rules may propose spans that overlap or nest. That is
//! intended — deciding between them is [`super::resolve`]'s job, not this one's.

use anyhow::{bail, Context, Result};
use regex::{Regex, RegexSet};

use crate::rules::Rule;

pub struct Prefilter {
    /// All candidate patterns in one automaton: which rules match anywhere, in a single pass.
    set: RegexSet,
    /// The same patterns individually, for the rules the set says are worth scanning.
    per_rule: Vec<Regex>,
}

impl Prefilter {
    pub fn compile(rules: &[Box<dyn Rule>]) -> Result<Self> {
        let patterns: Vec<&str> = rules.iter().map(|rule| rule.candidate_pattern()).collect();

        for rule in rules {
            reject_haystack_dependent(rule.id(), rule.candidate_pattern())?;
        }

        let set =
            RegexSet::new(&patterns).context("compiling the combined candidate pattern set")?;

        let per_rule = rules
            .iter()
            .map(|rule| {
                Regex::new(rule.candidate_pattern())
                    .with_context(|| format!("compiling the candidate pattern for {}", rule.id()))
            })
            .collect::<Result<Vec<_>>>()?;

        Ok(Self { set, per_rule })
    }

    /// Candidate spans as `(rule index, (start, end))`, in no particular order.
    pub fn candidates(&self, fragment: &str) -> Vec<(usize, (usize, usize))> {
        let mut found = Vec::new();
        for rule_index in self.set.matches(fragment).into_iter() {
            for m in self.per_rule[rule_index].find_iter(fragment) {
                found.push((rule_index, (m.start(), m.end())));
            }
        }
        found
    }

    /// One rule's own pattern over an arbitrary haystack, as `(start, end)` offsets **into that
    /// haystack**. The scan loop uses this to look inside a candidate its validator rejected,
    /// without owning the compiled patterns.
    pub fn find_in(&self, rule_index: usize, haystack: &str) -> Vec<(usize, usize)> {
        self.per_rule[rule_index]
            .find_iter(haystack)
            .map(|m| (m.start(), m.end()))
            .collect()
    }

    /// One rule's next match at or after `at`, as offsets into the **whole fragment**.
    ///
    /// The haystack stays the whole fragment and only the search start moves, which is the
    /// difference that matters: a slice would move the boundaries the pattern sees, and the
    /// candidate patterns are compiled on the promise that they never depend on where their
    /// haystack begins or ends. One match, not an iterator — the scan loop queues it, and a
    /// further resume is a further rejection with a budget of its own.
    pub fn find_from(
        &self,
        rule_index: usize,
        fragment: &str,
        at: usize,
    ) -> Option<(usize, usize)> {
        self.per_rule[rule_index]
            .find_at(fragment, at)
            .map(|m| (m.start(), m.end()))
    }
}

/// A candidate pattern is re-run over a slice of a fragment when the scan loop looks inside a
/// rejected candidate, so it must not depend on where its haystack begins or ends. An anchor or a
/// word boundary means something different against a slice than against the whole fragment, and the
/// difference is silent. Boundary conditions are validator work — the neighbouring byte is there in
/// the candidate — so this is enforced at startup rather than remembered.
fn reject_haystack_dependent(rule_id: &str, pattern: &str) -> Result<()> {
    let offending = if pattern.contains('^') {
        "^"
    } else if pattern.contains('$') {
        "$"
    } else if pattern.contains("\\b") {
        "\\b"
    } else {
        return Ok(());
    };
    bail!(
        "the candidate pattern for {rule_id} contains {offending}: a pattern that depends on where \
         its haystack ends cannot be re-run over a slice, so boundary conditions belong in the \
         validator"
    )
}
