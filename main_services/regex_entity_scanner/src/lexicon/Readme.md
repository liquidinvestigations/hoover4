# `src/lexicon/`

The investigative lexicon's matcher: it loads the term lists in `lexicon/`, compiles them into one
automaton, and turns matches into signals.

```text
fragment ─► fold ─► match ─► check ─► signals ─► summarise
```

It runs beside the entity pipeline and never joins it. An entity is a validated value. A signal is a
word that is present, which proves nothing on its own, so signals do not enter `resolve`, where an
overlap drops the weaker reading. Otherwise a hit on `claim` could delete an insurance-policy number
that it overlaps.

## `fold.rs`

The normalisation that terms and text share. The module header lists the steps. The ones that
decide what matches are these:

- Apostrophes are deleted, and the Hebrew geresh with them.
- Punctuation and whitespace runs become one space.
- Letters are lowercased, with `ß` folded to `ss`.
- Combining marks are dropped after Latin, Greek, Cyrillic, Hebrew and Arabic letters and kept
  after other scripts. In Hebrew and Arabic the marks are vowel points and hamza signs that
  everyday writing leaves out, so `أ`, `إ` and `آ` fold to `ا`.
- Arabic `ة` folds to `ه` and `ى` to `ي`, the Persian `ی` and `ک` to their Arabic forms, and
  Arabic-Indic digits to ASCII. The tatweel that stretches a word is deleted.

Cyrillic `й` loses its breve like `ё` loses its diaeresis, so `й` and `и` fold together. The data
was deduplicated under the same rule.

The folded text begins and ends with a space and has exactly one space at every word boundary. That
single property makes a whole-word match a literal search for ` term ` and a stem a search for
` stem`. The automaton needs no boundary logic at all.

Each folded byte remembers the source offset of the character that produced it. A signal therefore
carries byte offsets into the caller's document, exactly like an entity. `text[start..end]` is
always the reported `text`, and the corpus test asserts it for every signal.

## `clitics.rs`

Arabic and Hebrew join the conjunction, the article and the one-letter prepositions to the next
word, so a term whose first word is in either script also compiles with the common proclitic
chains in front of that word: `رشوة` with `ال`, `و`, `بال`, `لل` and the rest, `שוחד` with `ה`,
`ו`, `ב`, `וה` and the rest. A match on a variant reports its term, with the clitic inside the
span. A single word shorter than four letters gets no variants, because a prefix on a short word
too often spells another word; a phrase gets them at any length. A variant that some row spells
out belongs to that row alone. The Arabic and Hebrew lists add about 55 000 variant patterns to
their 2 600 terms.

## `load.rs`

Reads `categories.tsv` and every `<lang>/<category>.tsv`, and refuses a malformed lexicon at
startup, naming the file and line:

- a missing category file in some language;
- a file that is not a listed category;
- a wrong header or column count;
- an unknown tier, speaker or review value;
- a `*` anywhere but at the end;
- a stem shorter than three characters;
- a term that folds to nothing;
- the same folded term twice in one language.

Each of these would otherwise load as a lexicon that quietly matches less than it claims to, or
counts one word twice.
A double quote anywhere is refused too. CSV-style TSV readers, GitHub's file view among them, take
it for a field quote and refuse to show the whole file.

The version is the first twelve hex digits of a SHA-256 over every file loaded. It is a content
hash rather than a hand-bumped number, because the lists are edited far more often than the code.

## `mod.rs`

One Aho-Corasick automaton over every term of every language. It is a contiguous NFA with standard
semantics, searched for overlapping matches, so two adjacent terms can share the space between them.
The choices were measured:

| Engine | Terms | Scan |
|---|---|---|
| `regex` alternation, case-insensitive, punctuation-tolerant | 10 000 | 0.18 MB/s |
| Aho-Corasick DFA | 88 000 | 106 MB/s, 1.25 GB of tables |
| Aho-Corasick contiguous NFA | 88 000 | 143 MB/s, 16 MB |
| Aho-Corasick contiguous NFA | 240 000 | 107 MB/s, 47 MB |

For scale, the entity scan runs at about 1.5 MB/s on one thread. The fold costs more than the match
on non-Latin text: about 140 MB/s on English and 50 MB/s on mixed scripts.
The lexicon as shipped, about 10 600 terms and 65 000
patterns with the clitic variants, scans a mixed-script sample at about 45 MB/s in a release build.

Two languages may spell a term identically, such as `attentat*` in German and French. The pattern
compiles once and keeps a list of every term behind it.

`summarise` turns one text's signals into per-category summaries: distinct terms, counts, the flags
every occurrence shared, a score, and the number of distinct terms that counted, by tier. The score
is `1 − ∏(1 − wᵢ)` over distinct terms, with `H` 1.0, `M` 0.4 and `L` 0.1. Three rules adjust it:

- A quoted or boilerplate hit weighs nothing.
- A negated hit weighs half.
- An `L` term weighs nothing unless the same text holds an unflagged `H` or `M` signal.

The score is a sort key. The counts are what a threshold belongs on, because the rule-based
detectors that work require several distinct terms rather than one.

## `check.rs`

Everything that needs context runs here, per hit or once per fragment, never as another pass per
hit over the text.

- **Nesting.** Within one category, a hit inside a longer hit is dropped: `cover up` inside
  `cover up the losses`. A second term compiling to the same span is dropped too. Across categories
  both stay. This is one pass after a sort, with a running maximum.
- **`negated`.** A negation word within the five words before the term, and inside the same clause,
  sets it. The words `never`, `nicht`, `jamais`, `не`, `nunca`, `לא` and `لا` are among them,
  with the joined Hebrew and Arabic forms (`ולא`, `ولا`), and the list is in the module. The window is the one the clinical negation literature settled on. It stops at `.`, `,`,
  `;`, `:`, `!`, `?`, their Arabic forms and line ends, so "I'm not comfortable with this, I want no part of this" does
  not negate the second clause. `not only` and `no doubt` are not negations. A term that contains
  its own negation (`do not volunteer information`) is unaffected, because only the words before it
  are read.
- **`quoted`.** The hit is on a line starting `>`, or below a reply separator, an attribution line
  (`… wrote:`, `… schrieb:`, `… a écrit :`, `… написал:`, `… escribió:`, `… כתב:`, `… كتب:`) or an Outlook-style `From:`/`Sent:`
  block. A separator counts only after the message has said something, because a header block at
  the top of a message is its own header.
- **`boilerplate`.** The hit is in a paragraph that opens like an email disclaimer. At most 64
  disclaimer paragraphs are searched per fragment.

Flags annotate, they never drop. A compliance training text that says "never keep funds off the
books" is exactly what `negated` catches, and it can still be what someone wants to read. The
corpus holds the case where the negation does not reach: in "never keep funds off the books or
backdate contracts", `backdate` is seven words from `never` and reads as asserted.
