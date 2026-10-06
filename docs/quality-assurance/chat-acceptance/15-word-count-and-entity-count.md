# 15. Count by a word and by an entity, and explain the difference

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | every collection |
| data needed | `enron` |

## Prompt

```text
Which documents in the enron collection mention the location Chicago? How many are there?
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 7,568 distinct documents in `enron` hold the word "chicago" in their text. | `enron` | `COUNT(DISTINCT file_hash)` over `enron_1_pages` with `MATCH('chicago')` |
| 3,195 distinct documents in `enron` have "Chicago" as a location entity. | `enron` | `entity_hit` with `entity_type = 'LOC'` |
| The website result list shows about 7,554 for the same word. That number is Manticore's grouped total, which is approximate on large result sets. | `enron` | the search page |

## Expected tool calls

1. It calls `search_collections` with `collectionname` `["enron"]` and the query `Chicago`, and it reads the total.
2. It calls `search_collections` again with the location filter `ner_loc` `["Chicago"]` and no query words, and it reads that total.
3. It reads two documents of each set and calls `cite_documents`.

## Expected result

The answer gives both counts and says what each counts. The word count includes every document that contains the word, also as part of an address, a signature or a quoted news report. The entity count includes only the documents where the named-entity step tagged Chicago as a place, and that step misses some mentions. The answer does not give one number without its method. It names the website filter that gives the same set.

## Requirements exercised

The story exercises these requirements and optional behavior: a count, a filter by entity, the difference between two methods explained, document cards shown to the user, a task completed.
