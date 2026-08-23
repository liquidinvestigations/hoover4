# Rules and patterns

A rule is a candidate pattern plus a validator. Adding an entity type is a pattern, a validator and
a fixture, not a new pipeline.

## What each half may do

**The candidate pattern** is compiled into the prefilter alongside every other rule's and runs over
raw document text. It must be expressible in a linear-time engine: no lookaround, no
backreferences, and no `^`, `$` or `\b`. See below. It is expected to over-match. Being generous
here is free, because everything it proposes is checked.

**The validator** sees one candidate at a time, with the surrounding fragment available, and may be
as expensive as it likes. It returns nothing to reject the candidate, or a verdict carrying the
canonical value, a confidence, any flags, and possibly a narrowed span.

## Stripped guards

Upstream pattern corpora lean on lookaround, and the best of them (Microsoft's Recognizers-Text)
is .NET flavour throughout. Those guards do not survive the port, and they should not: a lookbehind
`(?<!\d)` is exactly "the byte before this span is not a digit", which is one comparison in the
validator once a candidate exists. Strip the guard from the pattern, re-impose it in the validator,
and the scanning pass stays linear.

The same move handles trailing punctuation. A pattern that tries to exclude the full stop at the end
of a sentence becomes unreadable; a validator that trims a trailing `.` is one line.

## No anchors, no `\b`

A candidate pattern must not depend on where its haystack begins or ends, because it is re-run over
a **slice** of the fragment whenever the scan loop looks inside a rejected candidate. `^`, `$` and
`\b` all mean something different against a slice than against the whole fragment, and the
difference is silent. The prefilter refuses to compile a pattern containing any of them at startup,
so the constraint is enforced rather than remembered.

Nothing is lost by it. A boundary condition is validator work and always was: the validator holds
the whole fragment and absolute offsets, so "the preceding byte is not a digit" is one comparison,
and it is the same move that strips a lookbehind out of the pattern.

## Looking inside a rejected candidate

The prefilter takes leftmost-longest per rule, so a long over-matched candidate that fails its
validator routinely contains a shorter one that would pass. An identifier-shaped run whose tail is
a page number, a timestamp with an impossible clock wrapped around a perfectly good date, an address
ending in a top-level domain that does not exist. If rejection were terminal all of those would be
lost.

So a rejection shrinks the candidate by one character from the right, re-runs the rule's own pattern
over the interior, and queues whatever it finds. That yields both cases in one mechanism: the
shorter match at the same start, and the nested match that starts later. The validator is unchanged.
It still receives the whole fragment and absolute offsets, so the adjacent-byte guards read the
real neighbours rather than the edges of a slice.

**The recovery is bounded and therefore best-effort: eight retries per candidate, two hundred and
fifty-six per fragment.** A valid match nested more deeply than that is still lost, and that is the
right trade: unbounded retry is quadratic in the fragment on adversarial input, which is exactly the
property the linear-time prefilter exists to protect.

One consequence for new rules: a shortened re-scan is a search for a shorter match, and short
strings are far more likely to be accidentally valid. A great many two-letter sequences are
registered top-level domains. A rule whose format has a variable length needs its right-hand
boundary guard as much as its left.

## Guards that remove the most noise

Roughly in order of noise removed per line of code:

1. **Structural validity.** A calendar that has the day; a check digit that agrees. This alone
   removes the bulk of numeric false positives, and for the identifier types it is close to
   decisive. A check digit is a one-in-ten to one-in-ninety-seven filter applied for free.
2. **Plausibility windows.** A year range, an amount magnitude, a unit magnitude. Kills version
   strings and identifier fragments.
3. **Adjacent-byte guards.** The stripped lookarounds. A date wedged between digits is part of a
   longer number.
4. **List membership.** The IANA TLD list, airport codes, MMSI flag prefixes. Cheap, and decisive
   for the types that have no checksum, though for short tokens membership is necessary and never
   sufficient, and those rules also demand a cue word nearby.
5. **Ambiguous-lexeme rules.** Surface forms that collide with ordinary words (bare `m`, `in`,
   `t`, `$`) need stronger context before they count at all.
6. **Negative contexts.** Inside a URL, inside a base64 blob, inside a hash, inside a code block.

## Confidence is a ladder, not an opinion

Confidence is thresholded by consumers at index time, so it must mean the same thing across every
rule: how likely this span is to be what the rule claims, given what the validator could actually
check. Thirty rules cannot be thresholded on one number unless the number is picked off a fixed
ladder.

| Value | What the validator was able to do |
|---|---|
| 0.99 | Check digit verified **and** the surface form is self-identifying, a country prefix, a fixed alphabet, a literal marker |
| 0.97 | Check digit verified on a bare token, admitted on a cue word |
| 0.95 | No check digit; structure plus membership of an authoritative list or published register (email TLD, BIC country, MMSI MID, ISO 4217 code, a country's numbering plan) |
| 0.90 | No check digit; structure plus a cue word |
| 0.85 | Structure and a plausibility window only |
| 0.80 | Structure only, with an ambiguity reported as a flag |

A rule may not claim a number its checks do not earn. The catalogue entry's `checks` list is the
audit trail for the number it claims, which is what makes the ladder auditable rather than
aspirational.

## Identifiers are matched in the form the standard defines

Case and separators are the two ways one identifier is written many ways, and the answer is the same
across the rule set: **the surface form a rule matches is the one its issuing standard defines, in
capitals.** A VAT number is matched compact, prefix against body; an ISO 6346 container number is
matched with the single spaces the standard's own grouped form uses and in no other punctuation; a
NIF is matched compact even though a Spanish form prints it with hyphens.

The reason is that case folding and separator stripping are what a *caller* does once it already
knows what the token is. A scanner does not know that yet (the guess is the whole job), and every
character of tolerance multiplies the candidate space against a check digit that is often only a
one-in-eleven or one-in-twenty-three filter. Upstream libraries face the opposite way: `compact()`
is called after the caller has said "this string is a VAT number", so their tolerance costs them
nothing and would cost a scanner precision.

The cost is real and is written on the cards that carry it: a number typed in lower case, or split
by the separators an invoice or a form prints, is not matched. Each of those cards says so, and says
why, rather than leaving the limit to be discovered.

### Separator tolerance is bought with arithmetic

The rule above is a price, not a preference, and a format that can pay it gets tolerance. What pays
is the strength of the filter waiting behind the widened candidate class.

`bank.iban` accepts single spaces and hyphens between groups. Behind them stand ISO 7064 mod-97-10
over up to 34 characters (one candidate in 97 survives it by accident) an exact per-country length
from the registry, and a per-country positional structure over the alphabet. A hyphenated part
number of IBAN shape reaches all three and stops there, so the tolerance costs nothing and wins the
spelling every bank statement prints.

`natid.es_nif_nie` does not. Its arithmetic is one check letter over seven digits: 22 candidates in
23 are turned away, which is a strong filter for a token somebody has already called a NIF and a
weak one against every hyphenated reference in a corpus. `container.iso6346` is in the same
position, with one check digit and a four-letter owner prefix. `bank.aba_routing` is the plainest
case of all (nine digits behind a one-in-ten weighted sum), so the hyphenated fractional spelling
printed on some cheques is not matched. All three stay compact, and their cards say so.

`bank.payment_card` accepts separators and is the case that shows what the price really buys. Luhn
alone is one in ten; what pays for the tolerance is the issuer table on top of it (the number must
begin in a range some issuer was allocated *and* be as long as that issuer's cards) plus the
requirement that one separator character be used throughout, since a run mixing spaces and hyphens
is a reference number rather than a card. Even those two together leave several article and
tracking numbers standing on a page of invoice-like text, which is why the rule is cue-gated as
well: separator tolerance and cue-gating are two different prices for two different weaknesses, and
this rule pays both.

The repetition bound that admits a grouped form is arithmetic of its own and worth stating
separately: a candidate pattern's upper bound has to cover the separators as well as the characters,
because the scan loop's recovery only ever shrinks a candidate. A bound that truncates a grouped
IBAN produces a candidate that fails the exact length check, and nothing downstream can grow it
back.

## Cue words

A check digit on a bare digit run is a one-in-ten filter, and one in ten invoice numbers is far too
many to put into a facet. For the formats that are nothing but a token and a check digit (IMO,
MMSI, IMEI, CUSIP, SEDOL, the payment card, the ABA routing number, the PESEL, the personnummer and
the organisationsnummer) acceptance also requires a cue word within a short window either side,
matched case-insensitively and on ASCII word boundaries. The window is 48 bytes, roughly a clause.

For those rules the cue is one of the terms the rule was admitted on, rather than a
tie-breaker on top of the arithmetic. A payment card is a digit run, an organisationsnummer is a digit run, and
each was weighed as *check digit plus structure plus the word beside it*. **If the cue requirement
is ever dropped from one of them, the rule goes with it**. That sentence is on each of their
cards, so the decision cannot be quietly reversed by a later change that finds the cue
inconvenient.

The same guard covers a second case: a format with no check digit at all whose shape collides with
ordinary words. A BIC is eight or eleven uppercase characters, and `DOCUMENT` and `CUSTOMER` both
carry a valid ISO 3166-1 country code in positions five and six, so the label beside the code is
what makes the rule usable rather than merely correct.

The cue list lives with the rule and appears verbatim in its catalogue entry: "this was accepted
because the word IMO was nearby" is exactly what a reader needs in order to weigh the match.

### The window is field-scoped

Proximity in bytes stops being proximity in meaning as soon as a document has structure. In a header
block, a mail list or a table, the label on one line belongs to that line's value:

```text
CUSIP 037833100
Reference 594918104
```

Forty-eight bytes reach from `CUSIP` to `594918104`, and a cue that reaches is a cue that vouches,
for a number in a different field, which the label says nothing about. The window therefore stops at
the line break either side of the candidate. The one break that does not stop it is a **folded**
one, where the next line begins with a space or a tab: that is RFC 5322 continuation, and it is the
same shape a wrapped cell or a continued log line takes, so `References:`⏎` <a@b.com>` still
matches.

The cost of getting this wrong is not one spurious entity. `resolve` decides an overlap by dropping
the loser, so a spurious reading that outranks a correct one *deletes* it: an address in a `To:` line
read as a message id leaves the fragment with a wrong entity in place of the right one.

### A label is stronger than a cue, where the format has one

A cue is proximity, and proximity is symmetric. It counts a word to the right of the candidate and
a word with a clause in between. Where the format's context is a literal field name, the rule can
ask for more: `message.rfc5322` requires one of its four header names to the **left**, with nothing
between the colon and the value but whitespace, list punctuation and complete angle-bracketed
groups, which is the `References:` list form. That refuses `Please quote the Message-ID when you
reply to <legal@example.com>`, which a proximity test accepts.

The label is strong enough to carry the rule on its own, which is why that rule does not also
require the right side of the address to be a registered domain: RFC 5322 admits a bare
`dot-atom-text` there, and `<…@thyme>` from an internal mail system is a well-formed message id.

## A marker binds to the number that follows it

The two money rules are the only patterns in the set whose marker (an ISO 4217 code or a currency
sign) may stand either in front of the amount or behind it. Both spellings are written and neither
is more correct, so both are matched; the ambiguity that creates is settled by one rule.

**A span that ends in a marker is refused when a digit follows it within one optional space.** In
`qty 2 EUR 30 per unit` the trailing-code reading `2 EUR` is available and it is a *wrong* reading,
not merely a worse one: it reports two euro for a thirty-euro line. The same principle already
decides that a code standing immediately in front of a sign names the currency (`SGD$4.90` is
Singapore dollars), and both are the same statement about which number a marker is attached to.

The candidate search has to cooperate. A leftmost-first engine proposes `2 EUR` before `EUR 30`, and
looking inside a rejected candidate cannot find a match that ends past it, so the rules whose markers
can trail ask the scan loop to resume the search past a rejection. Refusing the span without the
resume converts a wrong value into a miss, which is the better of the two; refusing it with the
resume converts it into the right value.

## A date rule ships only when the match fixes the whole day

Standing policy for the `date` type: **a date rule emits nothing unless the match itself determines
year, month and day.** A format that leaves any of the three to be inferred is not matched at all.

Two consequences, both deliberate:

- **Yearless formats are not matched.** A syslog line's `Mar  4 09:12:00` carries no year, and the
  only ways to supply one are to invent it, to take it from the surrounding document, or to emit a
  partial value. The first is a silently wrong date in an investigative index, the second is state
  a stateless scanner does not have, and the third puts a value in a date field that a range query
  cannot use. So the rule does not exist, and the model needs no partial-date flag.
- **Bare `YYYYMMDD` is not matched.** Eight adjacent digits with a valid calendar reading is the
  noisiest date shape there is, and in an identifier-heavy corpus most of them are not dates. It
  determines the whole day, so it does not fail the rule above. It fails on precision, which is a
  different and equally sufficient reason. An honest version of it needs a cue word or a
  document-level format prior.

The same policy is what keeps `2021-W09` out of `date.iso_week`: it names a week, not a day.

## At most six rules per entity type

An entity type is a facet somebody indexes, and a facet fed by a dozen loosely related rules stops
meaning one thing. Six is the budget, and it is what a proposed rule is measured against: if a type
is full, the question is which of its rules is weakest, not how to raise the cap.

## Rule identifiers

Dotted, general to specific: `date.iso8601`, `email.basic`. The identifier ships in the output and
lands in the index, which makes renaming one a data migration rather than a tidy-up.

## Every rule is documented

A rule is not finished when it matches correctly. It is finished when a reader who clicks one of its
matches can find out what it is: a catalogue entry in `src/explain/catalog.rs` naming what it
matches, the standards behind it, what the validator checks, what acceptance does **not** prove, the
authorities and the references. The test suite asserts that every compiled rule has one. See
[Explainer_Cards.md](Explainer_Cards.md).

## What does not belong here

Person names, organisation names, locations, job titles, relationships, events. The division is
clean and worth holding: **this layer owns everything with machine-checkable structure; an NLP layer
owns everything defined by meaning.** They meet at entity resolution. A validated identifier is the
anchor that disambiguates a fuzzy name match, which is the pairing that makes an index useful.
