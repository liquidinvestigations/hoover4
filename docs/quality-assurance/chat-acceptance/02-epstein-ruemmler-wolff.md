# 02. Kathy Ruemmler, Jeffrey Epstein and the Michael Wolff book

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | all seven |
| data needed | `epstein` (dataset `docs`) |

## Prompt

```text
What did Kathy Ruemmler and Jeffrey Epstein write to each other about Michael Wolff and his book? Give me dates and quote them.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 178 documents mention Ruemmler and 192 mention Michael Wolff. | `epstein` | a text scan of the collection |
| On 1/4/2018 Kathy Ruemmler wrote to jeevacation@gmail.com that Trump's lawyers had sent a letter to "mw's publisher" to stop the book. | `epstein` | `/TEXT/002/HOUSE_OVERSIGHT_032702.txt` (`eec2f336cb7a`) |
| On 7/8/2018 Ruemmler answered Epstein on a forwarded Steve Bannon interview. | `epstein` | `/TEXT/001/HOUSE_OVERSIGHT_030722.txt` (`3fa3a7018f92`) |
| On 3/23/2018 Michael Wolff wrote to Epstein about "Three hours with SB" and a next book. | `epstein` | `/TEXT/001/HOUSE_OVERSIGHT_027062.txt` (`86863644cb0d`) |
| The sender address is written both `jeevacation@gmail.com` and, after OCR, `jeeyacation@gmail.com`. | `epstein` | `/TEXT/002/HOUSE_OVERSIGHT_032873.txt` (`82a001f8df5a`) |

## Expected tool calls

1. It calls `write_todo` with a goal and three or four items.
2. One `search_passages` call with no `collectionname`, for example `{"queries": ["Ruemmler Wolff book", "\"Kathy Ruemmler\" publisher", "Ruemmler \"Michael Wolff\"", "jeevacation Ruemmler"]}`.
3. It calls `search_collections` with a phrase and a date sort, for example `{"query": "\"Kathy Ruemmler\" Wolff", "sort": {"field": "date", "direction": "asc"}}`, when the answer needs dates in order.
4. It calls `read_documents` on the hits with the best quotes.
5. It calls `cite_documents` with each quoted document.
6. It calls `mark_todo` as the items land, then it answers.

## Expected result

A list of messages in date order. Each item gives the date, the sender, the receiver, a verbatim quote and a card. The answer says that the documents are OCR text of House Oversight releases, so a quote can hold OCR errors. It does not add facts about the book that are not in a cited document.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, query variants, more than one in one call, document cards shown to the user, a passage to jump to, a task completed.
