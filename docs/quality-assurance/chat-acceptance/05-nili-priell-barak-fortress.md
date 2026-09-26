# 05. Nili Priell Barak and the Fortress consulting agreement

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | all seven |
| data needed | `tables`, dataset `ehudx` |

## Prompt

```text
Who is Nili Priell Barak, and what did she send Ehud Barak about a consulting agreement with Fortress? I want to see the emails.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 103 documents hold "Nili Priell" and 108 hold `nilipriell`. | `tables` | a text scan of the collection |
| On 12/24/2014 at 12:03 AM Nili Priell Barak (`nilipriell@gmail.com`) sent Ehud Barak the file "Fortress consulting agreement.rtf". | `tables` | `/1 (494).html` (`00fae8d56651`) |
| On 12/24/2014 at 1:52 AM Ehud Barak sent Jeff Feig (`jeff@fortress.com`) "a standard draft agreement". | `tables` | `/1 (73).html` (`f0d70b131e48`) |
| Jeff Feig answered that he sent it "to our guys", and Barak replied at 2:47 AM. | `tables` | `/1 (66).html` (`bc8eab0cb8e1`), `/0000014232-Re_ Fortress consulting agreement.rtf.eml.meta` (`f028b1973272`) |
| She also handled Ehud Barak's speaking calendar with the Harry Walker agency. | `tables` | `/1 (187).html` (`4067bc961a1c`) |

The data is in `tables`, which the name does not suggest. An agent that searches only the collections whose names sound right misses it.

## Expected tool calls

1. It calls `write_todo`.
2. It calls `search_passages` with no `collectionname` and the variants `["\"Nili Priell Barak\" Fortress", "nilipriell Fortress", "\"Fortress consulting agreement\"", "Priell Barak agreement"]`.
3. It calls `read_documents` or `doc_email` on the three emails of 12/24/2014.
4. It calls `cite_documents` with the three emails, each with a quote.
5. It calls `web_search` only for who she is, for example `["\"Nili Priell\" Barak"]`, and the answer marks that part as from the web.
6. It calls `mark_todo`, then it answers.

## Expected result

The answer gives the chain of three emails in order with a card for each. It says that she sent the draft to Ehud Barak, and that he then sent it to Jeff Feig at Fortress. It does not use a web story about a different agreement in place of the documents.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, with no collection named, query variants and spellings, more than one in one call, web search, kept apart from the document facts, document cards shown to the user, a passage to jump to, a task completed.
