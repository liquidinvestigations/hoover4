# Signals

What the investigative lexicon returns, and what a consumer may rely on. The lists themselves and
their format are in [`lexicon/Readme.md`](../lexicon/Readme.md); the matcher is in
[`src/lexicon/Readme.md`](../src/lexicon/Readme.md).

A signal marks a place to read first. It is not an entity. Nothing is validated and nothing is
normalised, because a word being present proves nothing about what the document says.

## `POST /scan` with `"signals": true`

`{"text": "…", "offset": 0, "signals": true}` adds two fields to the usual response:

```jsonc
{
  "entities": [ … ],
  "rule_set_version": 18,
  "signal_set_version": "3f9c0a1b2d4e",
  "signals": [
    {
      "category": "concealment",
      "term": "nobody will find out",       // as the lexicon writes it; a stem keeps its `*`
      "concept": "nobody will find out",    // the English term; shared across languages
      "lang": "en",
      "tier": "H",                          // H, M or L
      "speaker": "actor",                   // actor, insider, accuser, neutral
      "start": 1234, "end": 1254,           // bytes, absolute, exactly like entities
      "text": "Nobody will find out",       // text[start..end] of the source
      "flags": ["negated"]                  // negated, quoted, boilerplate; omitted when empty
    }
  ]
}
```

Without `"signals": true` neither field is present, and the lexicon is not run.

Offsets follow the entity contract: bytes, not characters, absolute in the source document once
`offset` is added. For a stem, the span runs to the end of the word the stem starts, so
`Schmiergeld*` reports `Schmiergeldzahlung`.

Signals overlap freely across categories. `off the books` may be `accounting` in one row and part
of a `concealment` phrase in another, and both are reported. Within one category, a hit nested in a
longer hit is dropped.

## `POST /signal_batch`

`{"texts": ["…", …]}` → one result per text, in order, summarised per category. This is the shape a
storage consumer keeps:

```jsonc
{
  "signal_set_version": "3f9c0a1b2d4e",
  "results": [
    {
      "categories": {
        "concealment": {
          "score": 0.64,                    // 1 − ∏(1 − wᵢ) over distinct terms; a sort key
          "counted": {"H": 1},              // distinct terms that counted, by tier
          "terms": [
            {"term": "nobody will find out", "concept": "nobody will find out", "lang": "en",
             "tier": "H", "speaker": "actor", "count": 2, "text": "Nobody will find out"}
          ]
        }
      }
    }
  ]
}
```

- A category with no signal in a text is absent.
- A term's `flags` are the flags shared by every occurrence. A term negated once and asserted once
  carries none.
- A text whose scan panicked carries an `error` string and no categories, and the other texts still
  answer, as in `/scan_batch`.

Weights are `H` 1.0, `M` 0.4 and `L` 0.1. A quoted or boilerplate term weighs nothing and a negated
one half. An `L` term counts only when the same text holds an unflagged `H` or `M` signal, because a
common word alone is noise by construction.

Put thresholds on `counted`, not on `score`. The detectors in this space that work require several
distinct terms before they alert.

## `GET /signals`

The lexicon's version, languages, total term count, and every category with its `title`, what it
`catches`, what a match `does_not_prove`, and its term count per language. A client shows the last
of these beside a signal.

## Versions

`signal_set_version` is a content hash of the lexicon files. It changes whenever a term does, and it
is independent of `rule_set_version`. A lexicon edit therefore invalidates stored signals and
nothing else. Re-scanning a collection for signals runs at lexicon speed, tens of MB/s per thread,
without re-running the entity scan.

## What a signal does not mean

Keyword search alone finds a minority of the relevant documents, while the people running it
usually believe they found most of them. Most keyword alerts in communications surveillance are
false. Direct words (`fraud`, `bribe`, `illegal`) are written more by accusers, lawyers, auditors and
compliance staff than by the people doing it, which is what `speaker` records. A signal orders a
collection for reading. It does not report that anything happened, and it does not show that a
collection without signals is clean.
