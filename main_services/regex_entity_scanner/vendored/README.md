# Vendored data

Third-party pattern databases, lexicons and reference data, plus the scripts that fetch them.
Nothing here is ours. Every entry below records where it came from, what it is licensed under, and
what we take from it — a vendored file whose provenance is not written down is trivial to add and
painful to reconstruct later, so adding data without adding its row is not done.

## Layout

| Path | Contents |
|---|---|
| `data/` | What the scanner loads at run time. This is the only part copied into the release image. |
| `reference/` | Upstream material we port from and generate from at development time. Absent from the release image. |
| `licenses/` | Upstream license texts, shipped alongside the data because the licenses require it. |
| `fetch/` | One script per upstream. They run **inside the dev container**. |
| `gleif/data/` | The GLEIF bulk download. Gitignored — it is measured in gigabytes. |

Each vendored directory carries an `.upstream` file naming its source and the commit or version the
snapshot was taken at. That stamp is the one place a date or revision is welcome anywhere in the
tree: it is a fact about the data we ship, and without it the snapshot cannot be diffed against its
upstream.

## Fetching

```sh
./shell.sh vendored/fetch-all.sh              # everything except GLEIF
./shell.sh vendored/fetch-all.sh cldr iana-tlds   # named fetchers only
./shell.sh vendored/fetch/gleif.sh            # gigabytes; only when LEI resolution is wanted
./shell.sh vendored/clone-reference-repos.sh  # full upstreams into tmp/reference, for reading
```

Every fetch stages its download or clone under `tmp/` and copies only the subset we use into place,
so a re-fetch is reviewable as a diff of that subset rather than of an entire upstream tree.

## License compatibility

**This section governs what lives under `vendored/`** — material we clone, transform and rehost, and
therefore redistribute together with the upstream notice. Ordinary crates.io dependencies are a
different question: `cargo` resolves them, they are not copied into this tree, and nothing here is
the place to record them.

This project is AGPL-3.0-or-later, which puts us on the receiving end of copyleft — the easy
direction. MIT, BSD-2/3, ISC, Apache-2.0, MPL-2.0, LGPL-2.1+, GPL-3.0, Unicode-3.0, CC0 and
public-domain data all combine into an AGPLv3 work without further obligation beyond keeping the
notices. Two things do not: **GPL-2.0-only**, which is genuinely incompatible, and **Hyperscan 5.5
and later**, which is under the Intel Proprietary License — Vectorscan is the BSD-3 fork of 5.4 and
is the one to use.

Check the licence of a **dataset** separately from the licence of the library that reads it. In this
field they routinely differ, and the datasets are the restrictive half: OurAirports is public
domain and GLEIF is CC0, but OpenFlights is ODbL, OpenSanctions' data is non-commercial-use-only,
OpenSky's aircraft database is effectively unlicensed, and the UK ISCD branch directory is a
commercial feed. Those four are deliberately not vendored here.

## Runtime data — `data/`

| Directory | Upstream | License | What we take, and why |
|---|---|---|---|
| `iana/` | [IANA TLD list](https://data.iana.org/TLD/tlds-alpha-by-domain.txt) | Public domain | The registered top-level domains. One membership test, and most of what an email pattern otherwise matches — file names, sprite paths, internal hostnames — disappears. |
| `ourairports/` | [OurAirports](https://davidmegginson.github.io/ourairports-data/) | Unlicense (public domain) | IATA and ICAO codes for 72k airports, cut to five columns. Membership is necessary but never sufficient: a bare three-letter token collides with ordinary text, so the rule that uses this also requires a cue word. |
| `cldr/` | [unicode-org/cldr-json](https://github.com/unicode-org/cldr-json) | Unicode-3.0 (GPL-compatible) | English names for the ISO 3166-1 alpha-2 territories, flattened to one map, plus the currency tables. The explainer resolves a country-code top-level domain to the country it belongs to, and a card that says "GB" where it could say "United Kingdom" is a card nobody needed. `iso4217.json` is code → minor units and name, restricted to the codes in current use, because the exponent is what turns an amount into a scaled integer and it is three for the Bahraini dinar and zero for the yen. `currency-symbols.json` is symbol → codes, most widely used first: a one-entry list is an unambiguous symbol and a longer one is what sets the ambiguous-currency flag. |
| `iban/` | [arthurdejong/python-stdnum](https://github.com/arthurdejong/python-stdnum) (`stdnum/iban.dat`) | LGPL-2.1+ | The IBAN registry: per-country length, BBAN structure and bank identifier position, transcribed upstream from the SWIFT registry. ISO 7064 mod-97-10 accepts about one malformed candidate in ninety-seven on its own; the per-country length and positional character classes are what close that gap. |
| `itu/` | [michaeljfazio/MIDs](https://github.com/michaeljfazio/MIDs) | MIT | ITU Maritime Identification Digits: the first three digits of an MMSI are its flag state. An MMSI carries no check digit, so a valid MID plus a cue word is the whole precision story for that rule. |

## Development reference — `reference/`

| Directory | Upstream | License | What we take, and why |
|---|---|---|---|
| `recognizers-text/` | [microsoft/Recognizers-Text](https://github.com/microsoft/Recognizers-Text) | MIT (one licence over code, patterns and specs alike) | The language-neutral YAML under `Patterns/`: curated, false-positive-tuned patterns and lexicons for dates, currency, units, phones, email and more, in fifteen languages, kept separate from the implementations. **The patterns are .NET flavour and lean on lookaround**, which no linear-time engine accepts — they are input to rule authoring, not something we compile as-is. From `Specs/` we take eight English spec files — the date, currency, IP, phone and email recognisers — as free-text test material for the upstream conformance run. The tree carries fifteen languages and a dozen recognisers we ship no rule for; taking it whole would be hoarding. |
| `cldr/` | [unicode-org/cldr-json](https://github.com/unicode-org/cldr-json) | Unicode-3.0 (GPL-compatible) | `ca-gregorian.json`, `numbers.json` and `units.json` for every modern locale, plus supplemental currency, week and subtag data. The only source that scales past a handful of languages without linear human effort. CLDR describes *formatting*; inverting a format pattern into a parser is our work, and an inverted pattern is always laxer than the formatter that produced it. |
| `dateparser/` | [scrapinghub/dateparser](https://github.com/scrapinghub/dateparser) | BSD-3 | CLDR-derived translation tables for 200+ locales — month and weekday names, separators, skip-words — with a hand-curated supplementary layer over what CLDR misses. Data rather than code, so it ports as a transform. `tests/test_date_parser.py` comes with it: one long parametrised list of date strings with the datetime each is expected to parse to, spanning every locale and format the project supports, which is what the upstream conformance run scores the date rules against. |
| `python-stdnum/` | [arthurdejong/python-stdnum](https://github.com/arthurdejong/python-stdnum) | LGPL-2.1+ | 343 format modules with their real check-digit algorithms: IBAN, BIC, EU VAT, company registration numbers across some sixty jurisdictions, LEI, ISIN, national identity numbers, IMO, MMSI, ISO 6346, IMEI. This is the specification we port from. A check digit turns "matched something plausible" into "verified", which is the difference between a join key and index noise. |
| `libphonenumber/` | [google/libphonenumber](https://github.com/google/libphonenumber) | Apache-2.0 (code and metadata alike) | `PhoneNumberMatcher.java` and `PhoneNumberUtil.java` — the reference implementation of finding numbers in free text, which is the two-stage design in its original form. `PhoneNumberMetadata.xml` and `PhoneNumberMatcherTest.java` are taken for their **test material**: an `<exampleNumber>` for every region and line type, and the matcher's labelled free-text corpus, both of which the upstream conformance run scores against. The ranges the phone rule validates against still reach us through the `phonenumber` crate, because regulators reassign number ranges continuously and a frozen copy would rot. |
| `quantulum3/` | [nielstron/quantulum3](https://github.com/nielstron/quantulum3) | MIT | The unit lexicon and entity taxonomy, and the common-words list that keeps bare `m`, `in` and `t` from matching ordinary prose — which is the actual problem with units. |
| `price-parser/` | [scrapinghub/price-parser](https://github.com/scrapinghub/price-parser) | BSD-3 (code and test data alike) | Separator inference: the best available answer to `1.234` meaning either a thousand or one-and-a-bit depending on who wrote it. `tests/test_price_parsing.py` comes with it: several hundred (text, currency, amount) rows collected from a random sample of real pages, which is what the upstream conformance run scores the money rules against. |
| `presidio/` | [microsoft/presidio](https://github.com/microsoft/presidio) | MIT | 123 predefined recognisers. Not our engine — Python, no money or units, spans for redaction rather than canonical values — but the best available checklist of PII entity types and per-country identifier formats, each declaring whether it validates by pattern, by checksum or by context. The 91 pattern-based recogniser test modules under `tests/` come with them: each is a parametrised list of free-text fragments with the spans upstream asserts are in them, including the fragments it asserts hold nothing, which is the shape this service is asked about — an identifier inside a sentence — and the material the upstream conformance run scores the free-text rules against. The model-backed recogniser tests are left behind; they assert against spaCy, Stanza, transformer and cloud back-ends and carry no pattern data. |
| `open-location-code/` | [google/open-location-code](https://github.com/google/open-location-code) | Apache-2.0 (the repository and its test data alike) | The four CSVs under `test_data/`: codes with the validity the specification asserts for each, codes with the cell their decode produces, and the coordinate pairs an encode is fed. The invalid half is the adversarial set nobody could write for themselves — a plus sign in the wrong position, padding after data, a non-alphabet Unicode character mid-code. `encoding.csv` also writes latitude and longitude as two adjacent comma-separated cells, which is the decimal rule's surface form exactly, so the pair is a token upstream wrote rather than one joined out of two columns. |
| `isemail/` | [dominicsayers/isemail](https://github.com/dominicsayers/isemail) | BSD-3 (Copyright 2016 Dominic Sayers) | `test/tests.xml`: 164 addresses, each with the category and the diagnosis upstream's validator returns. The categories are what make it usable — one end is wrong under any reading, the other is right under every reading, and the graded middle is upstream saying "legal under RFC 5322 and a bad idea". Control characters are written as the U+2400-block symbol for each, which upstream's own header explains, because XML cannot carry them. |
| `eth-utils/` | [ethereum/eth-utils](https://github.com/ethereum/eth-utils) | MIT | `tests/core/address-utils/test_address_utils.py`, the parametrised tables that separate the three readings of an Ethereum address a scanner has to keep apart: checksummed and correct, checksummed and wrong, and written in a single case so that EIP-55 carries no information at all. Two of the tables document a canonical spelling, which is the only value evidence for that rule anywhere. |
| `erc-55/` | [ethereum/ERCs](https://github.com/ethereum/ERCs) | CC0-1.0 | `ERCS/erc-55.md`, for the eight vectors in its Test Cases section — the addresses the mixed-case checksum standard is defined by. The licence is the ERC text's own and is not the licence of the code that implements it, which is why it sits in its own directory rather than beside `eth-utils/`. |
| `crossref/` | [Crossref REST API](https://api.crossref.org/works) | **No SPDX identifier applies.** Crossref states the terms on the API's own documentation page, <https://www.crossref.org/documentation/retrieve-metadata/rest-api/>: "No sign-up is required to use the REST API, and almost none of the metadata is subject to copyright, and you may use it for any purpose. Some abstracts contained in the metadata may be subject to copyright by publishers or authors." The one carve-out in that sentence is abstracts, and no abstract is taken here — the slice is identifiers. This is the only row in the tree whose licence is a policy rather than an identifier, and it is written out in full for that reason. | Two queries against the publication day 2020-01-01, reduced to identifiers before anything is written: a thousand works for their DOIs, and the same day filtered to works carrying an ORCID, because an arbitrary day's author records carry one only a few times in a hundred. Registered identifiers only, so the origin measures recall and has no malformed identifier to stay silent about. The `.upstream` stamp carries the fetch date in place of a commit, because a live API has none. |
| `advisory-database/` | [github/advisory-database](https://github.com/github/advisory-database) | CC-BY-4.0, from `LICENSE.md` at the repository root; the attribution the licence asks for is this row | The 213 reviewed advisories of `advisories/github-reviewed/2021/12`, in the OSV schema, flattened out of the one-directory-per-advisory layout. The month directory is the slice, so the name says exactly what is here. Two fields are what it is for: `aliases` carries the CVE identifier bare, and `references[].url` carries it inside an NVD or vendor URL — the same identifier in the surface context a document writes it in. |
| `pyais/` | [M0r13n/pyais](https://github.com/M0r13n/pyais) | MIT | `tests/test_decode.py` and `tests/test_decode_8.py`, for their decoded expectations: the MMSI each AIS message decodes to, which is the only labelled MMSI corpus that is both public and redistributable. The sample sentence files are deliberately left behind — an AIS sentence carries the identity in a six-bit payload and contains no MMSI as text, so scanning one produces nothing and the four megabytes buy nothing. |
| `hoover-mail/` | [liquidinvestigations/hoover-testdata](https://github.com/liquidinvestigations/hoover-testdata) | MIT, "Copyright (c) 2019 The Liquid Investigations Authors" | The mail slice, named explicitly because the licence covers the repository and not the third-party documents inside it: the two mbox archives, the messages of `data/lists.mbox`, and the `.eml`/`.emlx` files of the `eml-*` and `emlx-*` directories, each under a size cap. Real mail is the one thing no other origin here has — message ids, dates, addresses and Received chains inside the header lines that carry them, which is where the field-scoped cue window and the header-label test are exercised by the shape they exist for. What is left behind is left behind on purpose: `data/disk-files` and the other sample collections are hundreds of megabytes of images and office documents pulled off the public internet, and a message whose bulk is a base64 attachment or a PGP payload costs megabytes for one header block. |
| `secret-rules/` | [mongodb/kingfisher](https://github.com/mongodb/kingfisher), [gitleaks/gitleaks](https://github.com/gitleaks/gitleaks) | Apache-2.0, MIT | 623 Kingfisher rule files and the Gitleaks TOML config: the largest maintained bodies of credential and token patterns there are. Kingfisher's schema is also the best model for ours — match, then confirm. |
| `grok/` | [logstash-plugins/logstash-patterns-core](https://github.com/logstash-plugins/logstash-patterns-core) | Apache-2.0 | Battle-tested building blocks for the machine formats that fill logs and mail headers: syslog and common-log timestamps, IPs, URIs, paths, UUIDs, MACs. The 21 spec files under `spec/` come with them: each pairs a pattern with the log lines it is expected to match, which is where the date formats appear in their native habitat — Apache, syslog, firewall and application logs rather than isolated tokens — and that is the material the upstream conformance run scores the date rules against. |
| `followthemoney/` | [alephdata/followthemoney](https://github.com/alephdata/followthemoney) | MIT | The investigative data model, 69 schema files. We take the schema, not the code: naming our output properties the way FtM names them is what makes an extraction usable in the tooling investigative users already run. |

## GLEIF — `gleif/`

[GLEIF open data](https://www.gleif.org/en/about/open-data), CC0. The complete Legal Entity
Identifier population. It is what takes an LEI from a validated string to a resolved company —
legal name, jurisdiction, registered address, status, parent relationships. Fetched on demand by
`fetch/gleif.sh`; the download is gigabytes and is gitignored.
