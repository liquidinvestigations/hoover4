# 09. Show me the invitation itself

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | all seven |
| data needed | `testdata` (dataset `emails`) or `other` (dataset `emails`), one set of files |

## Prompt

```text
When was the Fontys international open day in Venlo and what was on the programme? Show me the invitation itself.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| The invitation PDF says "International Open Day Invitation 2nd of February, 2014". | `testdata`, `other` | `/International Open Day Invitation.pdf` (`dd27d5ea0260`) |
| The email "FW: Invitation Fontys Open Day 2nd of February 2014 - Campus Venlo" came from campusvenlo@fontys.nl on 2013-12-16. It says "Like last November we organize an Open Day especially for interested international students." | `testdata`, `other` | the `.eml` file (`a141b84dab86`) |
| Both collections hold the same two documents, because `testdata/emails` and `other/emails` read one folder. | `testdata`, `other` | the source folder of each dataset |

## Expected tool calls

1. It calls `write_todo`.
2. It calls `search_passages` with no `collectionname` and `["Fontys open day Venlo", "\"International Open Day\"", "campusvenlo invitation", "Fontys \"2nd of February\""]`.
3. It calls `read_documents` on the PDF and the email.
4. It calls `cite_documents` for the PDF, with the programme lines as the quote, and for the email.
5. It calls `mark_todo`, then it answers.

## Expected result

The answer gives 2 February 2014 from the documents, lists the programme items from the PDF, and shows the PDF as a card so the user can open it. It does not answer with a later open day from the web. A web check is optional, and the answer marks it as web context.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, query variants, more than one in one call, document cards shown to the user, a passage to jump to (the programme in the PDF), a task completed, with the documents preferred over the web.
