# 11. One person across more than one collections

| field | value |
|---|---|
| mode | deep research, internet tools off |
| collections in scope | all seven |
| data needed | `epstein` and `tables` |

## Prompt

```text
In which of my collections does Darren Indyke appear, and in what role in each? Give me the numbers per collection and two example documents for each.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 117 documents in `epstein` hold "Indyke". | `epstein` | a text scan of the collection |
| The signature "Darren K. Indyke, PLLC, 301 East 66th Street, 10B New York" is in legal filings about the Edwards articles. | `epstein` | `/TEXT/001/HOUSE_OVERSIGHT_013405.txt` (`83f9bf86371b`), `/TEXT/001/HOUSE_OVERSIGHT_013415.txt` (`914373941fee`) |
| 49 documents in `tables` hold "Indyke". He writes from `dkiesq@aol.com` in the Reporty emails. | `tables` | `/0000014385-Re_ Touch base DI.eml.meta` (`c6a632cea878`), `/1 (174).html` (`d9b3ce286622`) |
| The OCR text of `epstein` also spells the name "lndyke", with a lower-case L. | `epstein` | `/TEXT/002/HOUSE_OVERSIGHT_032873.txt` (`82a001f8df5a`) |
| One document in `enron` holds "Craig Indyke", a different person, in a recipient list. No document in `consulate`, `textfiles`, `other` or `testdata` holds the name. | `enron` and the rest | `/benson-r/inbox/236.` (`20011396834d`), and a text scan |
| 31 documents in `epstein` hold the OCR spelling "lndyke". | `epstein` | a text scan of the collection |

## Expected tool calls

1. The planner writes one node for each collection that holds the name, after one search with no `collectionname`.
2. It calls `search_collections` with no `collectionname` and the query `Indyke | lndyke | dkiesq`. The facet `collection_dataset` in the result gives the count per dataset.
3. Each sub-agent reads two documents with `read_documents` and cites them.
4. The report gives a table of collection, count and role, with cards.

## Expected result

A table with `epstein` and `tables` and their counts, a note that the `enron` hit is a different person, the role in each (a lawyer on legal filings, a participant in the Reporty emails), and two cards per collection. The report names the OCR spelling and says whether it counted it.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections in one call, query variants and spellings, more than one in one call, document cards shown to the user, a task completed.
