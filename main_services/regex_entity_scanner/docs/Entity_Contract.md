# Entity contract

What `POST /scan` returns, and what a consumer may rely on.

```jsonc
{
  "type": "date",                     // the entity category
  "start": 1234,                      // byte offset in the source document
  "end": 1244,                        // one past the last byte
  "text": "2021-03-04",               // surface form exactly as it appears
  "value": {                          // internally tagged on `kind`
    "kind": "date", "rfc3339": "2021-03-04", "precision": "day", "tz_known": false
  },
  "confidence": 0.99,
  "rule_id": "date.iso8601",          // which rule produced this
  "flags": ["no_timezone"]            // machine-readable caveats; omitted when empty
}
```

## Offsets are bytes, and they are absolute

`start` and `end` are byte offsets into the **source document**, not into the fragment that was
scanned and not character indices. A caller scanning a large document:

1. splits it into windows that **overlap** by at least the longest matchable entity, so nothing is
   lost on a boundary;
2. passes each window's own byte offset as `offset` in the request;
3. deduplicates on `(type, start, end)` across the overlap.

Windows must never split a UTF-8 codepoint. `text[start..end]` on the original bytes is always
exactly the reported `text`; the test suite asserts it on every corpus case.

## The value shapes

`value` is internally tagged on `kind`, so an entity deserialises back into a typed value by
construction and a consumer dispatches on the shape without knowing the rule set. The tag is the
**shape of the fields**, not the facet: many identifier rules across several entity types all
produce `identifier`, and one type may produce more than one shape.

| `kind` | Fields |
|---|---|
| `date` | `rfc3339`, `precision`, `tz_known` |
| `email` | `address`, `local`, `domain` |
| `phone` | `e164`, `country`, `national`, `number_type` |
| `money` | `currency`, `amount_minor`, `exponent` |
| `identifier` | `scheme`, `compact`, `country?`, `parts` |
| `network_address` | `family`, `address`, `prefix_length?` |
| `geo_point` | `latitude`, `longitude`, `datum` |

`identifier.parts` is a string map of scheme-specific components (bank code, check digits, issuer)
omitted when empty. A named field per scheme across two dozen schemes would force a model change for
every new identifier. `country` is promoted out of that map because it is cross-scheme and maps to a
property of its own.

`money.amount_minor` is a string-encoded integer because a JSON number is a double in most
consumers, and a sum of money is not a float. `exponent` is the ISO 4217 minor-unit count, so the
major-unit value is `amount_minor / 10^exponent` computed in integers by whoever needs it.

## A type holds at most six rules

An entity type is a facet somebody indexes, and a facet fed by a dozen loosely related rules stops
meaning one thing. Six is the budget a proposed rule is measured against: when a type is full, the
question is which of its rules is the weakest, not how to raise the cap.

`national_id` is full. Its six are `natid.it_codice_fiscale`, `natid.es_nif_nie`, `natid.mx_curp`,
`natid.in_pan`, `natid.pl_pesel` and `natid.se_personnummer`. The next national scheme is therefore
a contract conversation. Splitting the type per region changes what a consumer's facet means,
rather than a seventh entry.

`bank_account` holds four, and its two newest are a payment card and a United States routing number,
which are the instrument and the institution rather than the account. Both produce `identifier`,
under the schemes `payment_card` and `aba_routing`, and both map into FollowTheMoney through a `res:`
extension because the schema has no property for either. `company_id` holds four.

## The value is the point

`text` is what was written. `value` is what it means, and it is what belongs in a typed index field
 (a date field, a scaled integer plus a currency, a double plus a unit), so that range queries
work. Keeping `text` alongside it is not redundancy: highlighting needs it, and so does a user
asking why the system treats this as a date.

Values are canonical, so two spellings of one thing collapse. `2021-03-04T09:12:00+0200` and
`2021-03-04T09:12:00+02:00` produce the same value; an address's domain is lowercased and its local
part is not, which is what RFC 5321 says about case sensitivity.

`precision` travels with a date because indexing a day-precision date as an instant is spurious
accuracy, and a consumer that cannot tell them apart will produce it.

## `rule_id` and `confidence`

`rule_id` is provenance. Asking "which rule produced this garbage?" over a real corpus is how
precision work gets done, and without the field it is guesswork. It is stable, dotted from general
to specific, and renaming one is a data migration.

`confidence` is what a consumer thresholds on at index time. It means: how likely this span is to be
the thing the rule claims, given what the validator was able to check. A rule that verified a check
digit claims more than a rule that matched a shape and a nearby cue word, and the numbers have to
stay comparable across rules for a single threshold to make sense.

Comparable means a fixed ladder, not a per-rule opinion:

| Value | What the validator was able to do |
|---|---|
| 0.99 | Check digit verified **and** the surface form is self-identifying, a country prefix, a fixed alphabet, a literal marker |
| 0.97 | Check digit verified on a bare token, admitted on a cue word |
| 0.95 | No check digit; structure plus membership of an authoritative list or published register (email TLD, BIC country, MMSI MID, ISO 4217 code, a country's numbering plan) |
| 0.90 | No check digit; structure plus a cue word |
| 0.85 | Structure and a plausibility window only |
| 0.80 | Structure only, with an ambiguity reported as a flag |

A rule may not claim a number its checks do not earn, and the catalogue entry's `checks` list is the
audit trail for the one it claims. A date in a machine format sits at the top of the ladder because
its separators are the literal marker and every field is constrained by the calendar, which is the
same kind of arithmetic agreement a check digit gives. A telephone number sits on the membership row
for the mirror-image reason: nothing in it is redundant, so no arithmetic can ever confirm it, and
what earns the number instead is that the country calling code and the national number both match
the numbering plan that country publishes. That is the same kind of evidence a sum of money has when
its ISO 4217 code is in the list (narrow, authoritative, and not arithmetic), so the two rules
report the same number, and the no-checksum flag says which kind of evidence it was.

## Flags, not guesses

Some ambiguity is real and unresolvable from the text alone: `03/04/2021` is genuinely two dates, a
timestamp without an offset is genuinely not an instant. The contract reports it instead of picking
one and presenting it as certainty: `ambiguous_order`, `no_timezone`, `no_checksum` for a format
that carries no check digit at all, `ambiguous_currency` for a symbol shared by several ISO 4217
codes, and `separator_inferred` for a number whose decimal and grouping marks rested on a convention
the document never stated. An investigative index is exactly the place where a silently wrong value
is expensive.

## The entity is a handle

An entity is self-describing, and one endpoint depends on that: `POST /explain` takes an entity back
exactly as it was returned (no field stripped, renamed or reordered), and answers with a card for
the reader who clicked it. A client can therefore explain a match it stored months ago, and needs to
keep nothing but the entity itself. See [Explainer_Cards.md](Explainer_Cards.md).

## Versioning

Extraction is not idempotent across rule versions: changing a rule changes what a document yields.
`rule_set_version` is returned on every scan response and on `/health` and `/rules`. Store it beside
a document's entities, and the scope of a reindex becomes computable rather than guessed.

It is bumped by any change to a candidate pattern, to a validator's accept or reject boundary, to a
normalised value, or to the rule inventory. Card text, doc comments and catalogue entries do not
bump it, because none of them change what a document yields.
