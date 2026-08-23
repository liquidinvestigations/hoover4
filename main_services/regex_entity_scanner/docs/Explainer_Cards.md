# Explainer cards

A reader clicks a highlighted match and wants to know what it is. The client posts the entity back
**exactly as `/scan` returned it** and gets a card: a title, a subtitle, and a longer body, plus the
same material in structured form.

```console
$ curl -sS -X POST http://127.0.0.1:19705/explain -H 'content-type: application/json' \
    -d '{"type":"email","start":28,"end":54,"text":"Anna.Popescu@Example.CO.UK",
         "value":{"address":"Anna.Popescu@example.co.uk","local":"Anna.Popescu",
                  "domain":"example.co.uk"},"confidence":0.95,"rule_id":"email.basic"}'
{
  "rule_id": "email.basic",
  "entity_type": "email",
  "title": "Email address",
  "subtitle": "example.co.uk · United Kingdom",
  "body": "…Markdown, with links inline…",
  "facts": [ {"label": "Country", "value": "United Kingdom"}, … ],
  "references": [ {"title": "IANA register entry for .uk",
                   "url": "https://www.iana.org/domains/root/db/uk.html",
                   "note": "who sponsors this top-level domain and under what policy"}, … ]
}
```

## The entity is the whole input

Nothing is looked up in a session, a cache or the original document. An entity is self-describing,
so a client can explain one it has kept for months, and the endpoint stays as stateless as the
scanner.

Only `rule_id` is required. Every other field is used if present and ignored if absent, and unknown
fields are accepted silently. An entity produced by a different rule-set version must still explain
itself rather than fail. The `value` is read as raw JSON for the same reason: a shape this build has
never seen produces a thinner card, not an error.

An undocumented `rule_id` returns 404, so a client shows no card rather than an empty box.

## The three text fields

| Field | What goes in it |
|---|---|
| `title` | The human-readable name of what was matched, "ISO 8601 timestamp", never `date.iso8601`. Rules whose meaning varies by match specialise it: a date is a "date" or a "timestamp" depending on its precision. |
| `subtitle` | One line of what **this** match is, from what the entity already carries: the country behind its top-level domain, the register that issued it, the precision and time zone of a date, the bank behind an IBAN. |
| `body` | Markdown. What the format is, what this particular value means, what the validator checked, what acceptance does not prove, who defines the format, and where to read more. |

`facts` and `references` carry the same material structured, for a UI that would rather draw chips
and links than parse prose. Both may be empty; the three text fields are always present.

## Where the knowledge lives

`src/explain/catalog.rs` holds one static entry per rule: what it matches, the standards that define
it, what the validator checks, what acceptance does **not** prove, the authorities, and the
references. It is static because it is knowledge about the **rule**, not about any match, and it
lives next to the rule for the same reason a doc comment does.

`src/explain/cards.rs` holds the per-rule shapers, which add what only this particular match can
say (its country, its weekday, the register entry for its own identifier), and may sharpen the
title. A rule with a catalogue entry and no shaper still produces a usable card, so writing the
entry is the requirement and the shaper is the refinement.

The body is assembled in a fixed order across every rule, so a reader who has opened one card knows
where to look in the next: what this is, what this one says, what was verified, what verification
does not cover, who defines it, where to read more.

## `not_checked` is not optional

Every catalogue entry states what acceptance does not prove, and it deserves as much care as the
list of checks. A validated address has never been delivered to. A correct check digit says a number
is well-formed and nothing whatever about whether it was ever issued, or to whom. A country-code
domain says where a domain is registered, not where its holder sits. A reader deciding how much
weight to put on a match needs the boundary of the claim, and a card that only lists what was
verified quietly overstates it.

## The rest of the catalogue over HTTP

| Route | |
|---|---|
| `GET /rules` | Every documented rule: identifier, type, human-readable title, and whether this build has it compiled, plus the rule-set version and the confidence note, once for the whole set. |
| `GET /rules/{rule_id}` | The full static entry, with no match in hand. |
| `POST /explain` | The card for one entity. |

`GET /rules` reports documented rules rather than compiled ones, and marks which are compiled. The
catalogue is the repository's knowledge; a binary is one deployment of it.

## Documenting a new rule

A rule is not finished until it has a catalogue entry. The test suite asserts that every compiled
rule has one, because a reader who clicks a match and gets nothing is a worse outcome than a rule
that does not exist.

1. Add the `RuleDoc`: title, what it matches, standards, checks, `not_checked`, authorities,
   references.
2. Add a shaper if the match carries anything worth saying that the catalogue cannot know. Country,
   issuer, precision, a register link built from the value itself.
3. Add a test that pins the fact a reader would actually be looking for.

## The FollowTheMoney mapping

Every catalogue entry names the FollowTheMoney schema and property its extraction feeds, and it is
surfaced on `GET /rules/{rule_id}`. Where FollowTheMoney defines a property we use its exact name;
where it does not, the property is prefixed `res:` to mark it as a local extension of their schema
rather than something they define. A consumer reading a `res:` property knows it has to decide where
to put the value; one reading `BankAccount.iban` does not.

The full table, rule by rule, and what each `res:` extension exists for, is in
[FollowTheMoney_Mapping.md](FollowTheMoney_Mapping.md).

## The confidence note

`confidence` is a number, and a number without a stated meaning is read as whatever the reader
already believes. One static string in `src/explain/catalog.rs` says what it means, and it is the
same string everywhere: appended to the body of every card that carries a confidence, as its own
block, and served once at the top level of `GET /rules` so a client can show it beside a threshold
control.

One string, one place, no per-rule variation. A single threshold across the whole rule set only
works if the number means one thing across the whole rule set, and a reader can only believe that if
the explanation beside it does not change from card to card either. What it says is that the number
is about whether the text was read correctly, not whether the identifier was ever issued, whether
the address receives mail, or whether the value is true.

## Cards are English

The catalogue is static `&'static str` throughout and the cards it produces are English only. There
is no content negotiation on `Accept-Language`, and a client asking for another language gets the
same card. Translating them means a keyed catalogue, a negotiated request, and translated copy for
every rule. A different kind of change from writing an entry.
