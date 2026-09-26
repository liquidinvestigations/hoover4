# 08. A topic across the multilingual encyclopedia texts

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | all seven |
| data needed | `textfiles`, dataset `extra` |

## Prompt

```text
What do my files say about Erwin Rommel and the Afrika Korps? I read English, German and Hungarian.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| `textfiles` holds 26,593 encyclopedia texts in more than one languages, under folders such as `/deu/` and `/hun/`. | `textfiles` | the collection counts |
| 623 documents hold the letters "Rommel". Some are matches inside other words, for example "Trommel" in `/deu/Brasilien.txt` (`9058fe551007`). | `textfiles` | a substring scan |
| The Hungarian article on the German Afrika Korps says Rommel led it for only six and a half months. | `textfiles` | `/hun/N%C3%A9met_Afrika-hadtest.txt` (`634b07354e7d`) |
| "Erwin Rommel" is a PER entity in 131 documents. | `textfiles` | `entity_hit` counts |

## Expected tool calls

1. It calls `write_todo`.
2. It calls `search_passages` with no `collectionname` and variants in three languages, for example `["\"Erwin Rommel\" Afrika Korps", "\"Deutsches Afrikakorps\" Rommel", "\"Német Afrika-hadtest\"", "Rommel Nordafrika"]`.
3. It calls `search_facet_values` on the PER facet with the query `Rommel`, to count the documents.
4. It calls `read_documents` on two or three articles, one for each language.
5. It calls `cite_documents`, then it answers.

## Expected result

A short summary with cards for the articles it used, one language at a time. It gives the six and a half months fact from the Hungarian text with a quote. It does not count the "Trommel" matches as Rommel documents.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, query variants and spellings, more than one in one call, in three languages, document cards shown to the user, a passage to jump to, a task completed.
