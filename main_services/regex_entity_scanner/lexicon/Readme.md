# Investigative lexicon

Term lists that point a reader at the passages worth reading first. They cover the language of
concealment, bribery, accounting manipulation, pressure and dissent, conflict and crime, the
atrocity crimes of international law, and the vocabulary that marks a document as a contract, a legal letter, an invoice, a proof of payment or a
scam. The scanner loads every list at startup and reports each match as a **signal**.

A signal is a reason to look, never a finding. Keyword search on its own finds a minority of the
relevant documents. Most keyword alerts in communications surveillance turn out false. Many of these
words are written more often by accusers, lawyers, auditors and compliance staff than by the people
doing what the words describe. Each category's `does_not_prove` text says what a match leaves open,
and `/explain` repeats it on every card.

## Layout

```text
categories.tsv          one row per category: id, title, catches, does_not_prove
<lang>/<category>.tsv   the terms, one file per category and language (en, de, fr, ru, es, he, ar)
licenses/               licence texts of upstream sources that require one to travel with the data
```

Every category exists in every language directory, and every language directory holds the same set
of files. The categories are one flat list, and each term belongs to exactly one category per
language:

`concealment`, `accounting`, `bribery`, `rationalisation`, `hostility`, `litigation`, `crime`,
`financial_crime`, `violence`, `sexual_misconduct`, `genocide`, `crimes_against_humanity`,
`war_crimes`, `coded_language`, `scam`, `marketing`, `legal_document`, `contract`, `legal_letter`,
`memorandum`, `invoice`, `invoice_draft`, `invoice_final`, `payment_proof`, `international_transfer`,
`jurisdiction`.

`genocide`, `crimes_against_humanity` and `war_crimes` follow Articles 6, 7 and 8 of the Rome
Statute, one category per crime. Each holds three kinds of term: the statutory elements as courts and
commissions of inquiry quote them (`intent to destroy`, `widespread or systematic attack`, `human
shields`), the names of the acts and their traces as investigators and reporters write them (`mass
grave`, `filtration camp`, `double tap strike`), and the words of the people ordering or inciting
them (`wipe them out`, `take no prisoners`, dehumanising names for a group). A term that fits more
than one crime sits in the one whose statute names it: torture and enforced disappearance under
crimes against humanity, hostage-taking and pillage under war crimes. Hostage-taking in the sense of
a kidnapping stays in `violence`, and forced prostitution outside armed conflict in
`sexual_misconduct`.

## Term files

Tab-separated, with a header row:

| Column | Meaning |
|---|---|
| `term` | The word or phrase as people write it. A trailing `*` makes it a prefix: `bestech*` matches `Bestechung` and `bestechen`. A `*` anywhere else is refused at load time. |
| `tier` | `H`, `M` or `L`. `H` is rarely innocent and worth a look alone. `M` has a routine reading in some context. `L` is a common word that counts only beside other signals. |
| `speaker` | Who usually writes it: `actor` (a participant), `insider` (an uneasy participant or a future witness), `accuser` (whistleblower, lawyer, auditor, journalist, policy), `neutral` (document furniture). |
| `concept` | The English term this row expresses, spelt exactly as its `en/` row, with the `*` of a stem. In `en/` it is the term itself. It groups one idea across languages. |
| `source` | Where the term comes from; see [Sources](#sources). |
| `review` | `original` for the English lists. `mt-edited` for a row drafted by machine translation and then rewritten by hand into an idiomatic equivalent, but not yet read by a native speaker. |
| `note` | Free text: why the term is there, or what it is often confused with. |

A term is matched exactly, but insensitive to case, punctuation and accents: `don't`, `dont` and
`DON’T` are one term; `cover-up` and `cover up` are one term; `illégal` matches `illegal`. The
normalisation is in `src/lexicon/Readme.md`. Two spellings that the normalisation does not join
(`coverup` and `cover up`, `Geldwäsche` and `Geldwaesche`) need a row each.

A term is only ever a whole word or a run of whole words. With a trailing `*` it is a whole-word
start. So `leak` does not match inside `bleak`, and `откат` does not match `откатить` unless it is
written `откат*`. That is why several Russian and German rows list inflected forms explicitly
instead of using a stem. A stem such as `секрет*` would also match `секретарь` (secretary), and
`Leck*` would match `lecker` (tasty).

### Arabic and Hebrew

Both scripts join the conjunction, the article and the one-letter prepositions to the next word:
`والرشوة` is "and the bribe", `בשוחד` "with a bribe". The lists write the bare word, and the
matcher adds the common proclitic chains in front of a term's first word by itself, so `رشوة`
also matches `بالرشوة` and `שוחד` also matches `והשוחד`. A single word of fewer than four letters
gets no such variants, because a prefix on a short word too often spells another word (`מ` +
`ספר` is `מספר`, number), and the lists spell out the joined forms of those they need (`רצח`,
`הרצח`, `ברצח`). A phrase gets the variants whatever the length of its first word.

Only the first word is prefixed. An Arabic adjective agrees with its noun in definiteness
(`مقبرة جماعية`, `المقابر الجماعية`), and a Hebrew construct takes the article on its second noun
(`קבר אחים`, `קבר האחים`), so the definite forms that matter are rows of their own, noted
`definite form` or `definite construct`.

The normalisation already joins the spellings everyday typing mixes: pointed and unpointed Hebrew,
`أ` `إ` `آ` and a bare `ا`, `ة` and `ه`, `ى` and `ي`, a word stretched with tatweel, and
Arabic-Indic digits. Hebrew terms are written in full spelling (`שוחד`, not `שחד`), which is how
unpointed text writes them.

### Romanised rows

Much Arabic chat is written in Arabizi, Latin letters with digits standing for the sounds Latin
lacks (`3` for `ع`, `7` for `ح`, `2` for `ء`, `5` for `خ`). In one Egyptian SMS and chat corpus
most conversations were entirely Arabizi, so an Arabic-script list alone misses the register that
matters most. The `ar/` lists hold Arabizi rows for the chat-register categories (concealment,
bribery, threats, pressure, scams), noted `Arabizi` with the dialect. The fold keeps digits inside
a word, so `ma7adsh` is one word. Arabizi has no standard spelling, so a phrase has one row per
common spelling (`ma7adsh hay3raf`, `mahadesh hay3raf`).

Hebrew chat keeps Hebrew script, so `he/` romanises only the few Hebrew words that English text
writes in Latin letters (`protektzia`, `kombina`), noted `romanised Hebrew`.

A translation that folds to the same string as its English term is not repeated, because the
English row already matches it in text of any language. The same holds for language-neutral terms:
ISO 20022 element names, MT103, UETR, acronyms and application names exist only in `en/`.

## Sources

`curated` terms were written for this lexicon. `investigator-list` terms come from a working
investigators' list, which itself follows the fraud phrases Ernst & Young and the FBI published in
2013. Every other source is a published document or dataset, quoted or paraphrased as short terms:

| Source | What was taken | Licence |
|---|---|---|
| `ey-fbi-2013` | Fraud-triangle phrases as republished by Polonious, Case IQ and Live Science | quoted short phrases |
| `doj-sec-fcpa-guide` | "Bribes have been mischaracterized as" list and third-party red flags, *A Resource Guide to the U.S. Foreign Corrupt Practices Act*, 2nd ed. | US government work |
| `fatf-egmont-tbml` | Trade-based money-laundering risk indicators, **paraphrased** (the publication reserves all rights) | paraphrase only |
| `fincen-pig-butchering` | FinCEN Alert FIN-2023-Alert005 | US government work |
| `fincen-human-trafficking` | FinCEN Advisory FIN-2020-A008 | US government work |
| `fincen-bis-export-control` | FinCEN and BIS joint alert on Russian export-control evasion | US government work |
| `sec-insider-trading-2026` | SEC complaint 1:26-cv-12068 | US government work |
| `cftc-barclays-libor` | CFTC release 6289-12, the Barclays LIBOR order | US government work |
| `fsa-cftc-libor-chats` | Trader chat quoted from the FSA and CFTC LIBOR releases | quoted short phrases |
| `fca-hsbc-fx` | FCA Final Notice to HSBC Bank plc on FX benchmarks (2014) | quoted short phrases |
| `nice-actimize-lexicon` | Example lexicon entries from NICE Actimize's surveillance white paper | quoted short phrases |
| `global-relay-surveillance` | Regulation names from Global Relay's surveillance guide | names |
| `dea-slang-2018` | DEA *Slang Terms and Code Words* (DEA-HOU-DIR-022-18) | US government work |
| `spamassassin-advance-fee` | Phrases from Apache SpamAssassin `rules/20_advance_fee.cf` | Apache-2.0, `licenses/spamassassin.LICENSE` |
| `cuad` | Clause category names of the Contract Understanding Atticus Dataset, The Atticus Project | CC BY 4.0 |
| `contractnli` | Terms from the ContractNLI dataset, Koreeda and Manning | CC BY 4.0 |
| `mt103-pacs008` | SWIFT MT103 field names and ISO 20022 pacs.008 element names | standard field names |
| `uncl1001` | UNTDID 1001 invoice type names as listed by Peppol BIS Billing 3.0 | standard code names |
| `uk-cpr-pre-action` | Practice Direction – Pre-Action Conduct and Protocols, UK Civil Procedure Rules | Open Government Licence |
| `mou-definition` | Vocabulary of non-binding instruments | terms only |
| `courts-db` | Court names from Free Law Project courts-db | BSD-2-Clause |
| `rome-statute` | The elements of genocide, crimes against humanity and war crimes and the rules on incitement, command responsibility and superior orders, Articles 6–8, 25, 28 and 33 of the Rome Statute of the International Criminal Court, from its authentic Arabic, English, French, Russian and Spanish texts | treaty text |
| `genocide-convention` | The punishable acts of Article III, Convention on the Prevention and Punishment of the Crime of Genocide | treaty text |
| `un-atrocity-framework` | Incitement and dehumanisation indicators, **paraphrased**, UN *Framework of Analysis for Atrocity Crimes* | paraphrase only |
| `il-nazi-law-1950` | The definitions of crimes against humanity and war crimes, Nazis and Nazi Collaborators (Punishment) Law, 5710-1950 | Israeli statute |
| `il-genocide-law-1950` | The Hebrew legal name of genocide and its punishable acts, Crime of Genocide (Prevention and Punishment) Law, 5710-1950 | Israeli statute |
| `vstgb` | German Code of Crimes against International Law (Völkerstrafgesetzbuch), §§ 3–12 | German statute, in the public domain under § 5 UrhG |

Lists that would fit here but cannot be used: HurtLex (non-commercial licence), Hatebase and its
successor (access-controlled), and the IWF keyword list (members only, and the kind of list that
must not be public). Case-specific and access-controlled lists are supplied per request instead of
being stored here.

## Editing

Change a term in the file for its category and language. Moving a term to another category means
deleting it from the first: the loader refuses a term that appears twice in one language. Adding a
language is adding a directory holding one file for every category. `./test.sh lexicon` checks the
files load, and the signal corpus in `tests/golden/signals.jsonl` measures what the change did.
