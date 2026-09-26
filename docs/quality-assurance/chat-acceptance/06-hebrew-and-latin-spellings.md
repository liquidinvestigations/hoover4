# 06. One name in two scripts

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | all seven |
| data needed | `tables`, dataset `ehudx` |

## Prompt

```text
Find the 2012 declaration of assets of Ehud Barak. The documents may write his name in Hebrew. Who sent it, and when?
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 28 documents hold the Hebrew spelling "אהוד ברק". | `tables` | a text scan of the collection |
| An email with the subject "הצהרת הון - 2012 - אהוד ברק" (declaration of assets, 2012), followed by a nine-digit identity number, came from Nili Priell Barak on 2014-12-30. | `tables` | `/0000014167-Fwd_ ... .eml.meta` (`64031e0d435a`) |
| The NER tables hold the Latin forms "Ehud Barak", "ehbarak" and "Barak" as separate values. | `tables` | `entity_hit` counts |

## Expected tool calls

1. It calls `write_todo`.
2. It calls `search_passages` with no `collectionname` and both scripts in one call, for example `["\"אהוד ברק\" 2012", "הצהרת הון", "\"Ehud Barak\" declaration of assets 2012", "ehbarak 2012"]`.
3. It calls `read_documents` on the email and its `.eml.meta` record.
4. It calls `cite_documents` with the Hebrew subject line as the quote.
5. It calls `mark_todo`, then it answers.

## Expected result

The answer names the email, the sender and the date, with a card. It gives the Hebrew subject and an English translation, and it marks the translation as its own.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, query variants and spellings, more than one in one call, in two scripts, document cards shown to the user, a passage to jump to, a task completed.
