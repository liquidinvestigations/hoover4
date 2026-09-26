# 03. The talking points for the California PUC hearings

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | `enron` only, chosen by the user |
| data needed | `enron`, datasets `dasovich_j` and `maildir` |

## Prompt

```text
Search only the Enron emails. What talking points did Jeff Dasovich draft for the California PUC hearings at the end of December 2000, who did he send them to, and what changed between drafts?
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 38 documents hold the phrase "talking points for California PUC". | `enron` | a text scan of the collection |
| Jeff Dasovich sent "DRAFT talking points for California PUC Hearings on the 27th/28th" on 2000-12-26 at 15:15 and again at 15:20. | `enron` | `/all_documents/7953.` (`0919d5054ad4`), `/sent/2757.` (`0839bcea3918`) |
| He sent a later version on 2000-12-27 at 11:07. | `enron` | `/sent/2763.` (`068913ac6051`) |
| Scott Stoness replied on 2000-12-26 at 17:25. | `enron` | `/notes_inbox/6021.` (`06da229be58b`) |
| The recipients include susan.mara@enron.com, vicki.sharp@enron.com, wanda.curry@enron.com and mday@gmssr.com. | `enron` | `/sent/2756.` (`a7fb9e79bd29`) |

The same email is stored in more than one datasets, because `maildir` holds the other four. A correct answer does not count one message twice.

## Expected tool calls

1. It calls `write_todo`.
2. It calls `search_collections` with `{"collectionname": ["enron"], "query": "\"talking points\" PUC Dasovich", "sort": {"field": "date", "direction": "asc"}}`. The user narrowed the scope, so a collection list is correct here.
3. It calls `search_histogram` or a date filter from 2000-12-20 to 2001-01-05, when the first search returns many hits.
4. It calls `doc_email` or `read_documents` on the 15:15, 15:20 and 11:07 versions.
5. `doc_diff_sources` is not the tool for two emails, so it is not called. The agent reads both and compares them in prose.
6. It calls `cite_documents` for each version and the reply.
7. It calls `mark_todo`, then it answers.

## Expected result

The answer gives the dates and times of each draft, the recipients and the change between drafts, with a card for each email. It names duplicates as one message stored in more than one folders.

## Requirements exercised

The story exercises these requirements: first todo write, a collection scope that the user asks for, and no wider search, todo edits, document cards shown to the user, a passage to jump to, a task completed.
