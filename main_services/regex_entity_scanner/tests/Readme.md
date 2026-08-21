# `tests/`

| File | What it pins |
|---|---|
| `support/mod.rs` | Builds a scanner over the vendored tree next to the manifest, so tests do not depend on the environment the way the binary does. |
| `dates.rs`, `email.rs`, `identifiers_bank.rs`, `identifiers_company.rs`, `identifiers_security.rs`, `maritime.rs`, `devices_network.rs`, `extras.rs`, `national_ids.rs`, `phone.rs`, `money.rs` | One file per rule family: what each validator keeps, what it rejects, and what the value normalises to. |
| `contract.rs` | Structural properties of the wire contract: an entity round-trips through JSON for every value kind, and no candidate pattern depends on its haystack boundaries. |
| `golden.rs` | The labelled corpus, scored as precision and recall. |
| `conformance.rs`, `conformance/` | Agreement with the upstream projects the rules were ported from, scored as recall, precision and coverage. |
| `explain.rs` | Explainer cards, including that every compiled rule has a catalogue entry and that an entity round-trips from `/scan` into `/explain` unchanged. |
| `http.rs` | The service surface over a real socket. |

## The golden corpus

`golden/corpus.jsonl` is the test that decides whether a rule change was an improvement. Unit tests
pin individual behaviours; only a labelled corpus answers "did this pattern start swallowing version
numbers", which is how this kind of system actually fails.

`./test.sh -- --nocapture` shows the precision and recall numbers on a passing run; a failure lists
every spurious and missed span by itself.

Roughly half the corpus is fragments where the right answer is nothing at all. Negative cases are
not padding — precision is the property under test, and a corpus of positives alone cannot measure
it.

Fixtures name the surface form and the canonical value rather than byte offsets, because offsets
counted by hand are wrong often enough to stop people extending the corpus. The harness separately
asserts that every reported span really does cover the text it claims, which is the property the
offsets needed to prove.

Add a case for every rule change: the input that motivated it, and the near-miss that must stay
rejected.

## The upstream conformance run

`conformance/` holds cases taken from the reference projects' own test material and `conformance.rs`
scores them; `./test-long.sh` is the entry point and `tests/conformance/Readme.md` describes the
case-file schema and how an upstream test becomes a fragment we scan.

It is a normal test target with its one test `#[ignore]`d, rather than a `[[bin]]` or a separate
`[[test]]` with `harness = false`. That way the fast battery compiles it, rustfmt and clippy cover
it, and `tests/support` is shared — so it cannot rot unnoticed — while `cargo test` still never runs
it. `./test-long.sh` runs it by name with `--ignored`.

The golden corpus and the conformance run answer different questions and neither replaces the
other: the corpus is cases we wrote, and only a labelled corpus of our own can measure precision on
running prose; the conformance run is cases upstream wrote, and only those can show that a ported
check digit means what its author meant.

## Speed

The whole battery stays inside two to three minutes and an individual test inside ten to fifteen
seconds. Reference corpora are large; a test iterates a representative subset and says what the
subset covers. A suite that takes long enough to skip is not more thorough, it is unused.

The one exhaustive test is the ISO week sweep in `dates.rs`, and it is exhaustive because no corpus
anywhere carries a week date: it generates its own cases over eight chosen years rather than
iterating a vendored corpus, which is exactly what keeps it inside the budget.
