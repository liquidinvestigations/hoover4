# Architecture

## The shape of the problem

The entity types this service is built for (dates, sums of money, email addresses, phone numbers,
and the much larger tier of structured identifiers) share a property that decides the whole
design: **matching them is the cheap half.**

Unit-bearing physical quantities are not extracted. There is no quantity entity type, no value
shape for one and no rule that reads one, so `5 in`, `3 T` and `12 kg` are ordinary text here.

A pattern that finds every date in a corpus takes a morning. A pattern that finds every date and
nothing that merely looks like one does not exist, because `2021-13-45`, `1.2.3` and the middle of a
SHA-256 hash are all shaped like dates. What separates a usable extraction from index noise is the
work after the match: deciding whether the candidate is real, and reducing it to a canonical typed
value that a range query can use.

So the pipeline is two-stage, and the stages are held to different rules.

```text
fragment (UTF-8, with the byte offset of its first byte in the source document)
        │
        ├─ 1. PREFILTER ── one RegexSet pass over the whole rule set says which rules fire
        │                  anywhere; only those then scan for their own candidate spans.
        │                  Linear-time engine only. Deliberately over-matches.
        │
        ├─ 2. VALIDATE ─── per candidate, allowed to be expensive.
        │                  Re-imposes the guards stripped out of the pattern, checks calendar
        │                  validity, check digits, list membership, plausibility windows.
        │                  A rejection re-runs the rule's pattern over the candidate's interior
        │                  and queues what it finds, so a valid match nested in an over-matched
        │                  candidate is not lost. Bounded: 8 retries per candidate, 256 per
        │                  fragment.
        │
        ├─ 3. NORMALISE ── span to canonical typed value: RFC 3339 instant, ISO-4217 minor units,
        │                  E.164, compact identifier form.
        │
        ├─ 4. RESOLVE ──── overlaps between rules: structural strength, then length, then position.
        │
        └─ entities, with absolute byte offsets
```

Stages 2 and 3 live together inside each rule, because both are per-type knowledge and separating
them would only mean passing a half-checked value between two functions that always run together.

## Why the prefilter must stay linear-time

The text being scanned is written by whoever wrote the document, which in this domain routinely
means somebody hostile. A backtracking engine has no bounded worst case on input like that, and a
single crafted paragraph is enough to hang a worker. The `regex` crate builds finite automata and is
linear in the input by construction, which is why it is the engine here and why the candidate
patterns carry no lookaround and no backreferences.

That constraint costs something real: the best available upstream pattern corpus is .NET flavour and
leans on lookaround heavily. The answer is not a more permissive engine. It is that a lookbehind
like `(?<!\d)` is exactly the statement "the preceding byte is not a digit", which a validator
checks in one byte comparison once it has a candidate span. The guard moves from the pattern to the
validator and the fast path stays linear.

## Why two passes in the prefilter

`RegexSet::matches` answers "which of these N patterns match anywhere in this text" in one pass.
Most fragments in a real corpus contain none of what any given rule is looking for, so that one pass
usually eliminates almost every rule, and only the survivors scan for spans of their own. At a
handful of rules the saving is small; at several hundred it is the difference between one pass over
the text and several hundred.

## Where the performance actually is

In descending order of effect: multi-pattern single-pass matching, literal prefiltering, not running
expensive validation on non-candidates, and parallelism across fragments. Compiling patterns into
code ahead of time is a real technique and a much smaller lever. A long-lived service compiles its
rule set once at startup and then scans for hours, so compilation cost amortises to nothing.

The engine sits behind `scan::prefilter` for the same reason: swapping in a multi-gigabyte-per-second
prefilter later is a change to one module, and retrofitting that boundary afterwards would not be.
Measure before reaching for it.

## The fragment size limit is an explicit parameter

`RES_MAX_BODY_BYTES` bounds both the request body and the `text` field, and defaults to ten
mebibytes. It is stated rather than inherited from whatever the HTTP stack happens to default to,
because the amount of attacker-supplied text this process will hold in memory is an operational
decision that has to be visible to whoever runs it. A value that does not parse fails startup: an
operational parameter that is silently wrong is worse than one that refuses to boot.

The limit is applied at two layers on purpose. The body limit rejects before the body is buffered,
which is the one that protects memory; the check on the `text` field is the one that answers with a
precise error instead of a generic transport failure.

## Statelessness

One process, N threads, no models, no writes. The scanner is built once at startup and shared; every
request carries its own fragment. That is what makes the container disposable, horizontally
scalable, and independently versionable from anything else in a pipeline. Its rules ship on their
own cadence.
