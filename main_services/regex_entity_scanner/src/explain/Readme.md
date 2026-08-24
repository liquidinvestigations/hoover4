# `src/explain/`

Explainer cards. A client posts an entity back exactly as `/scan` returned it and gets a title, a
subtitle and a body for the reader who clicked the match.

| File | |
|---|---|
| `mod.rs` | The request and card types, and the dispatcher. |
| `catalog.rs` | One static entry per rule: what it matches, the standards, the checks, what acceptance does not prove, authorities, references. |
| `cards.rs` | Per-rule shapers, and the fixed-order body assembly. |

## Why the catalogue is static Rust

It is knowledge about the rule, not about any match, the standard that defines the format, the
authority that runs the register, the boundary of what validation proves. Keeping it beside the rule
is what stops it going stale, exactly as with a doc comment. Loading it from a data file would move
it away from the code it describes and gain nothing, because it changes when the rule changes.

Reference **data** is a different thing and does come from `vendored/`: territory names resolve a
country-code top-level domain to a country the reader recognises. Static knowledge, vendored data.

## The tolerance rule

Only `rule_id` is required on the way in, and `value` is read as raw JSON rather than typed. An
entity a client kept from an older rule set must still explain itself, so a value shape this build
has never seen thins the card instead of failing it. This is also why the endpoint sidesteps the
`Value` round-trip question entirely. It never deserialises into the typed enum.

## The FollowTheMoney mapping and the confidence note

Two things are the same for the whole rule set rather than per match, and both live in `catalog.rs`.

Every entry carries an `FtmMapping`: the FollowTheMoney schema and property this extraction feeds,
with `res:` marking a property FollowTheMoney does not define and we are adding locally. It rides on
`GET /rules/{rule_id}` with the rest of the entry, and the test suite fails a rule that has none.
`docs/FollowTheMoney_Mapping.md` is the table it adds up to.

`CONFIDENCE_NOTE` is one sentence about what a confidence number means. It is appended to every card
that carries a confidence and served once at the top of `GET /rules`. It does not vary by rule,
because a single threshold across every rule is only accurate if the number means one thing across
every rule.

## Adding a rule

A catalogue entry is required; a shaper is optional. A rule with an entry and no shaper still
produces a usable card, which is what keeps documenting a new rule cheap enough to actually happen.
The test suite fails if a compiled rule has no entry.
