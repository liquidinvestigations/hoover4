# regex-entity-scanner

A stateless Rust service that reads UTF-8 text and returns typed, normalised entity spans: dates,
sums of money, email addresses, network and cryptocurrency addresses, coordinates, and the large
tier of
checksummed structured identifiers, with IBAN, BIC, LEI, ISIN, IMO, MMSI, container, IMEI, DOI,
ORCID and national identity numbers among them.

It exists because matching is the cheap half of this problem. A pattern that finds every date in a
corpus takes a morning; a pattern that finds every date and nothing that merely looks like one does
not exist. What makes an extraction usable is the work after the match: deciding whether the
candidate is real, and reducing it to a canonical value a range query can use. Everything below
follows from that.

```sh
./build-dev.sh                              # the toolchain image
./shell.sh vendored/fetch-all.sh            # the vendored pattern data
./test.sh                                   # rustfmt, clippy, the battery
./test-long.sh                              # agreement with the upstream projects
./run-server.sh                             # detached on 127.0.0.1:19705
```

```console
$ curl -sS -X POST http://127.0.0.1:19705/scan -H 'content-type: application/json' \
    -d '{"text": "On 2021-03-04T09:12:00+0200 ops@Example.ORG filed it."}' | jq .entities
[
  {
    "type": "date",
    "start": 3, "end": 27,
    "text": "2021-03-04T09:12:00+0200",
    "value": {
      "kind": "date",
      "rfc3339": "2021-03-04T09:12:00+02:00", "precision": "second", "tz_known": true
    },
    "confidence": 0.99,
    "rule_id": "date.iso8601"
  },
  {
    "type": "email",
    "start": 28, "end": 43,
    "text": "ops@Example.ORG",
    "value": {
      "kind": "email",
      "address": "ops@example.org", "local": "ops", "domain": "example.org"
    },
    "confidence": 0.95,
    "rule_id": "email.basic"
  }
]
```

## How it works

```text
fragment ─► prefilter ─► validate ─► normalise ─► resolve ─► entities
```

**Prefilter.** One `RegexSet` pass over the whole rule set says which rules fire anywhere in the
fragment; only those then scan for their own candidate spans. Most fragments contain none of what
any given rule looks for, so that first pass usually eliminates almost every rule. It runs in a
linear-time engine (no lookaround, no backreferences), because the text was written by whoever
wrote the document, and a backtracking engine has no bounded worst case on input like that. It is
expected to over-match.

**Validate.** Per candidate, and allowed to be expensive because it only ever sees candidates. It
re-imposes the guards that had to be stripped out of the pattern (a lookbehind `(?<!\d)` is exactly
"the preceding byte is not a digit", one comparison once a span exists) then applies the checks that
decide truth: calendar validity, check digits, list membership, plausibility windows.

**Normalise.** Span to canonical typed value: an RFC 3339 instant, minor units plus an ISO-4217
code, E.164, a compact identifier form. This is the half that makes the output worth indexing.

**Resolve.** Rules scan independently, so their spans can overlap. Structural strength wins first,
then length, then position, a match that had to satisfy a checksum is the less accidental reading
even when it is shorter.

Details in [docs/Architecture.md](docs/Architecture.md).

## HTTP

| Route | Purpose |
|---|---|
| `GET /health` | Liveness, the number of compiled rules, the size of the loaded TLD list, and the concurrency bound with what is in it (`scan_threads`, `queue_depth`, `in_flight`). It answers 503 with `"status": "degraded"` and names the tables when the vendored data loaded short, because a rule with an empty table matches nothing instead of failing. |
| `GET /rules` | Every documented rule: identifier, type, human-readable title, and whether this build has it compiled. |
| `GET /rules/{rule_id}` | The full static documentation for one rule. |
| `POST /scan` | `{"text": "…", "offset": 0}` → `{"entities": [...], "rule_set_version": N}`. Every span, for a caller that highlights them. |
| `POST /scan_batch` | `{"texts": ["…", …]}` → one entry per text, in order, holding deduplicated values per type with an occurrence count. For a caller that stores values rather than spans. |
| `POST /explain` | An entity, posted back exactly as `/scan` returned it → an explainer card. |

`offset` is the byte offset of the fragment's first byte in the source document; it is added to
every span, so a caller windowing a large document gets offsets usable against the original bytes.
Windows overlap by at least the longest matchable entity, never split a codepoint, and are
deduplicated on `(type, start, end)`.

Offsets are **bytes**, never characters. `text[start..end]` on the source is always exactly the
reported `text`.

Full contract, including what `confidence`, `rule_id` and the flags mean:
[docs/Entity_Contract.md](docs/Entity_Contract.md).

`rule_set_version` also rides on `/health` and `/rules`. Extraction is not idempotent across rule
sets, so it is what makes the scope of a reindex computable rather than guessed.

### Batch scanning and admission control

`/scan_batch` exists because the span list is the wrong shape for storage: 193 real text segments
produced 325 365 entity objects, of which a consumer keyed on normalised values wanted a few
thousand. Values are deduplicated server-side on `(type, normalised value)`, and each carries the
count, the rule behind its highest-confidence occurrence, the canonical value object that `/explain`
takes back, and the surface form of its first occurrence, which is not the normalised value, and is
what a caller offering find-in-page needs.

Scanning is synchronous and CPU-bound, so it runs on a blocking pool and never on an async worker.
`/health`, `/rules` and `/explain` therefore stay answerable at full load; a health check a busy
process cannot answer reports the wrong thing at exactly the moment the answer matters.

`RES_SCAN_THREADS` concurrent scans are admitted and `RES_QUEUE_DEPTH` more may wait. Past that the
answer is **503 with a `Retry-After`**, which is the same contract the NER twin has and which a
client already understands as retryable. The alternative is a request served long after the caller
gave up on it.

### Configuration

| Variable | Default | What it is |
|---|---|---|
| `RES_BIND` | `0.0.0.0:19705` | Listen address. |
| `RES_VENDORED_DIR` | - | Root of the vendored tables. |
| `RES_MAX_BODY_BYTES` | `10485760` | Applied to both the request body and each `text`; an oversized request is a `413`. |
| `RES_WORKER_THREADS` | `4` | Async workers. They parse JSON and move bytes; the work is elsewhere. |
| `RES_SCAN_THREADS` | `10` | Concurrent scans. About 0.85 MB/s each. |
| `RES_QUEUE_DEPTH` | `32` | Waiters allowed in front of them before 503. |
| `RES_LOG` | `info` | Tracing filter. |

None of the thread counts derive from the host's core count: a service that sizes itself to the box
oversubscribes any box that is also running something else. A value that does not parse (or that is
zero) fails startup rather than falling back silently, because an operational parameter that is
quietly wrong is worse than one that refuses to boot.

`--health-check` runs the binary as a one-shot probe against its own port and exits non-zero unless
`/health` answers 200. It is in the binary because the release image carries no shell tooling, and a
health check that needs a package installed to run is a health check that stops being run.

## Explainer cards

A reader clicks a highlighted match and wants to know what it is. The client posts the entity back
**unchanged** and gets a card with three text fields (a title, a subtitle and a Markdown body)
plus the same material as structured facts and links.

```console
$ curl -sS -X POST http://127.0.0.1:19705/explain -H 'content-type: application/json' -d @entity.json
{
  "title": "Email address",
  "subtitle": "example.co.uk · United Kingdom",
  "body": "…what the format is, what this value means, what was checked, what it does not prove…",
  "facts": [ {"label": "Country", "value": "United Kingdom"}, … ],
  "references": [ {"title": "IANA register entry for .uk",
                   "url": "https://www.iana.org/domains/root/db/uk.html", "note": "…"}, … ]
}
```

The entity is the whole input. Nothing is looked up in a session or in the original document, so a
client can explain a match it stored months ago. Only `rule_id` is required; unknown fields and
unfamiliar value shapes thin the card rather than fail it, because an entity from an older rule set
must still explain itself.

The knowledge is static and lives in `src/explain/catalog.rs`: one entry per rule with what it
matches, the standards that define it, what the validator checks, what acceptance does **not**
prove, the authorities and the references. Per-rule shapers add what only a particular match can
say. The country behind its top-level domain, the weekday its date fell on, the register entry for
its own identifier. Every compiled rule must have an entry, and the test suite fails if one does
not: a reader who clicks a match and gets nothing is worse than a rule that does not exist.

Every entry also names the FollowTheMoney schema and property the extraction feeds, so a value has
somewhere to land in the schema an investigative consumer already has:
[docs/FollowTheMoney_Mapping.md](docs/FollowTheMoney_Mapping.md).

Details in [docs/Explainer_Cards.md](docs/Explainer_Cards.md).

## Entity types

A type is a facet a consumer would build, not a value shape: several types share one `value` shape,
which is why the value carries its own `kind` tag. `date`, `email`, `phone`, `money`,
`bank_account`, `company_id`, `security`, `vessel`, `cargo_container`, `device`, `network`,
`publication`, `vulnerability`, `crypto_wallet`, `coordinates`, `national_id` and `message_id` are
the categories; each holds at most six rules, which is the budget a new rule is measured against.
`national_id` holds six and is full: the next national scheme is a conversation about splitting the
type per region rather than a seventh entry.

Compiled today:

| Type | Rule | What the validator checks |
|---|---|---|
| `date` | `date.iso8601` | Real calendar date, real clock time, year inside a plausibility window, no adjacent digits. Normalises to RFC 3339 with an explicit precision, and canonicalises `Z`, `+0200` and `+02:00` to one spelling. |
| `date` | `date.rfc2822` | A mail header date, with the day of the week checked against the calendar date; the obsolete zone abbreviations normalise to offsets. |
| `date` | `date.clf` | The bracketed Common Log Format timestamp web servers emit. The brackets make it self-identifying; the span reported is the timestamp inside them. |
| `date` | `date.iso_week` | An ISO week date, resolved through week-date arithmetic so week 53 is accepted only in the years that have one. |
| `email` | `email.basic` | RFC 5321 length limits, an addressable local part, no adjacent addressable characters on either side, and (the largest single precision win) the top-level domain must be in the IANA list. |
| `bank_account` | `bank.iban` | The country's entry in the vendored IBAN registry: exact length, positional character classes, then ISO 7064 mod-97-10 over the rearranged form. |
| `bank_account` | `bank.bic` | Eight or eleven characters, positions five and six an ISO 3166-1 country, and a label (BIC, SWIFT, IBAN, bank, beneficiary, correspondent) nearby. ISO 9362 defines no check digit. |
| `bank_account` | `bank.payment_card` | Luhn over thirteen to nineteen digits, one separator character throughout or none, an issuer identification range that was allocated together with the length that issuer uses, and a word (card, cardholder, Visa, Mastercard, Amex, Discover, JCB, Diners, Maestro) nearby. |
| `bank_account` | `bank.aba_routing` | The 3-7-1 weighted check over nine digits, a leading Federal Reserve routing symbol in one of the four allocated blocks, and a word (routing, ABA, RTN, transit) nearby. Compact form only. |
| `company_id` | `company.lei` | ISO 7064 mod-97-10 over all twenty characters, letters counting as their base-36 value. |
| `company_id` | `company.vat_eu` | An EU VAT number: the member-state prefix, that state's own body length and alphabet, and the check digit its tax administration publishes. All twenty-seven states, with Greece under `EL`. |
| `company_id` | `company.vat_non_eu` | The same VATIN shape outside the Union, for the countries whose check digit is implemented: GB, CH, NO, RS, ME, MK, RU and TR. The Swiss and Norwegian numbers carry the tax abbreviation their administrations append. |
| `company_id` | `company.se_organisationsnummer` | Luhn over ten digits, a leading digit that is one of the eight allocated legal forms, a third digit of at least two (which is what separates it from a personnummer) and a word: organisationsnummer, orgnr, org.nr, företagsnummer, company identity, company registration. |
| `security` | `security.isin` | Luhn over the letter-expanded form, and a prefix that is an ISO 3166-1 country or one of the allocations ISO 6166 makes to substitute agencies. |
| `security` | `security.cusip` | The alternating-weight check digit, plus a cue word (CUSIP, SEDOL, ISIN, ticker, security, CIK) because nine alphanumerics are also every part number there is. |
| `security` | `security.sedol` | The weighted check digit, the vowel-free alphabet, and the same cue words. |
| `vessel` | `vessel.imo` | The weighted check digit over the hull number, admitted by the literal `IMO` marker or a word (vessel, ship, tanker, hull, flag) nearby. |
| `vessel` | `vessel.mmsi` | The first three digits are a Maritime Identification Digit triple the ITU has allocated, and a word (MMSI, AIS, call sign, vessel, ship) is nearby. An MMSI has no check digit. |
| `cargo_container` | `container.iso6346` | The ISO 6346 check digit and the equipment-category letter, which is one of U, J, Z or R and is what makes the format self-identifying. |
| `device` | `device.imei` | The Luhn check digit over fifteen digits, plus a word (IMEI, handset, device) nearby, because a bare digit run is also every reference number there is. |
| `device` | `device.mac` | Consistent separators and twelve hex digits. The bare twelve-hex spelling is not matched: it is indistinguishable from half a hash. |
| `network` | `network.ip` | The address parses through `std::net`, which is the definition of both formats; a CIDR prefix is range-checked, and words like version or firmware nearby reject a dotted quad that is a release number. |
| `network` | `network.asn` | The literal `AS`/`ASN` prefix is part of the match, and the number fits the allocated 32-bit space. |
| `vulnerability` | `vulnerability.cve` | The literal `CVE-` prefix and a year inside the scheme's own window. |
| `publication` | `publication.doi` | The `10.` directory code, a registrant code and a non-empty suffix; sentence punctuation is trimmed off the span. |
| `publication` | `publication.orcid` | The ISO 7064 mod 11-2 check character, with a final `X` standing for ten. |
| `national_id` | `natid.it_codice_fiscale` | The CIN check character over the sixteen positions, and the fixed letter/digit pattern including the omocodia substitutions. |
| `national_id` | `natid.es_nif_nie` | The modulo-23 check letter, with `X`, `Y` and `Z` standing for a leading 0, 1 and 2 and `K`, `L`, `M` carrying the older algorithm. |
| `national_id` | `natid.mx_curp` | The weighted check digit and a state code the registry uses. |
| `national_id` | `natid.in_pan` | The holder-type letter, a serial that is not all zeroes, and a word (PAN, income tax, Aadhaar, ITR, assessee) nearby. The check character's algorithm is unpublished. |
| `national_id` | `natid.pl_pesel` | The weighted check digit over eleven digits, a birth date that exists once the century has been read out of the month field, and the word PESEL nearby. The date is read only to reject an impossible one. |
| `national_id` | `natid.se_personnummer` | Luhn over the last ten digits, a birth date that could exist, and a word (personnummer, samordningsnummer, personal identity, person number, pnr) nearby. The value keeps the separator, because it is the century. |
| `crypto_wallet` | `crypto.bitcoin` | The base58check or bech32 checksum, and a version byte or witness program the standard defines. |
| `crypto_wallet` | `crypto.ethereum` | Where the address is mixed case, the EIP-55 checksum hidden in the capitalisation; where it is not, the shape only, reported with a lower confidence and the no-checksum flag. |
| `coordinates` | `coord.decimal` | Latitude and longitude ranges, and at least four decimal places on both sides, because a coarser pair is a pair of measurements as often as a place. |
| `coordinates` | `coord.dms` | Both hemispheres present, minutes and seconds below sixty, and the ranges after the sign is applied. Minutes and seconds are marked with the ASCII apostrophe and quote or with the typographic prime and double prime. Normalises to decimal degrees. |
| `coordinates` | `coord.plus_code` | The vowel-free Open Location Code alphabet, the separator's position, and the first pair's range. Decodes to the centre of the cell. |
| `phone` | `phone.international` | A country calling code the ITU has assigned and a national number the country actually issues, both from libphonenumber's metadata. International form only (a leading `+` or the `00` prefix) because a national-format number needs a region the document does not supply. Normalises to E.164 and names the line type. |
| `money` | `money.iso_code` | The three-letter code is in ISO 4217 and in current use; every thousands group is exactly three digits; the fraction is no longer than the currency's own minor units. A code that is also an English word (ALL, TOP, CUP, TRY) additionally needs a word about money nearby. |
| `money` | `money.symbol` | The sign is one CLDR publishes for a currency in current use, in its standard or narrow form. An ISO 4217 code standing beside the sign settles which currency it is; otherwise a sign shared by several currencies names the most widely used one and carries the ambiguous-currency flag. |
| `message_id` | `message.rfc5322` | Angle brackets and a header name (Message-ID, In-Reply-To, References, Resent-Message-ID) immediately to the left, with nothing between it and the value but whitespace, list punctuation and complete angle-bracketed groups. The label is the whole precision story, because a `From` line has the same shape. |

Full RFC 5322 is deliberately not the target for email: it accepts a great deal nobody writes, and
on real corpora the TLD membership test is where the precision actually comes from.

## Containers

Nothing is built or run on the host, no host toolchain, no host Python.

| Script | |
|---|---|
| `build-dev.sh [--force]` | The toolchain image, bind-mounted on the working tree. |
| `build-rel.sh [--force]` | The release image: optimised binary, runtime data, licence notices, nothing else. |
| `shell.sh [command…]` | Throwaway dev container, interactive or running a command. |
| `run-server.sh [--dev]` | Detached server on `127.0.0.1:19705`. |
| `test.sh [filter…]` | rustfmt, clippy, the battery. |
| `test-long.sh [origin]` | The upstream conformance run: our rules scored against the reference projects' own test cases. |

The dev image holds no state: cargo's cache, `target/` and the shell history live under the mount,
so deleting the container costs nothing. The release image carries no toolchain and no sources. It
is around 95 MB and answers on HTTP.

More in [docs/Containers_And_Scripts.md](docs/Containers_And_Scripts.md).

## Vendored data

The patterns and lexicons are not ours and should not be. Month names across two hundred locales,
unit surface forms, currency names, phone metadata, and two hundred check-digit algorithms already
exist upstream under permissive licences; hand-writing any of them would be a mistake rather than
diligence. `vendored/` holds curated subsets of CLDR, Recognizers-Text, dateparser, python-stdnum,
libphonenumber, quantulum3, price-parser, Presidio, Kingfisher, Gitleaks, the grok patterns,
FollowTheMoney, the IANA TLD list, OurAirports and the ITU MID table, each with its upstream,
licence and a fetch script.

```sh
./shell.sh vendored/fetch-all.sh              # everything except the GLEIF bulk download
./shell.sh vendored/clone-reference-repos.sh  # full upstreams into tmp/, for reading
```

Provenance and licences: [vendored/README.md](vendored/README.md).

## Testing

```sh
./test.sh
```

The battery stays inside two to three minutes and each test inside ten to fifteen seconds, because
precision work only happens when the loop is short enough to run on every rule change.

`tests/golden/corpus.jsonl` is the labelled corpus, scored as precision and recall. Roughly half its
cases expect nothing at all. Precision is the property under test, and a corpus of positives cannot
measure it. Every rule change adds a case: the input that motivated it, and the near-miss that must
stay rejected.

More in [docs/Testing.md](docs/Testing.md).

## Writing a rule

A candidate pattern, a validator, a fixture, and a catalogue entry so the match can explain itself.
The pattern goes in the prefilter and must stay linear-time; the validator gets one candidate at a
time and does the deciding. Guards that need lookaround move into the validator as byte comparisons.
See [docs/Rules_And_Patterns.md](docs/Rules_And_Patterns.md),
[docs/Explainer_Cards.md](docs/Explainer_Cards.md) and `src/rules/Readme.md`.

Person names, organisations, locations and relationships are deliberately out of scope. This layer
owns everything with machine-checkable structure; meaning belongs to an NLP layer. The two meet at
entity resolution, a validated identifier is the anchor that disambiguates a fuzzy name match.

## Licence

AGPL-3.0-or-later. See [LICENSE](LICENSE), and `vendored/licenses/` for the upstream notices that
travel with the vendored data.
