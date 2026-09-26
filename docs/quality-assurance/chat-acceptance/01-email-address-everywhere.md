# 01. Everything on one email address

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | all seven |
| data needed | `consulate` (dataset `files`) and `tables` (dataset `greenvelope`) |

## Prompt

```text
show me all data on this guy  JoeBWilkinson@cs.com
```

The second turn, in the same chat:

```text
where does that email appear in our dataset?
```

Send both prompts word for word, the double space included.

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| The address occurs in 9 documents in `tables` and in the same files in `consulate`. All are exports of the greenvelope invitation service. | `consulate`, `tables` | the `greenvelope/<campaign>/` folders |
| On 5/3/2019 the person with this address declined an invitation. The reason given was "Conflicts with the first meeting of the Task Force for the Promotion of Public Trust." | `consulate` | `.../greenvelope/2360064/inbox.csv` (`307033ff8279`) and `.../2360064/contacts/30.json` (`e2a66e482edf`) |
| On 11/20/2019 the same person declined a second invitation with "Will not be back in Atlanta then." | `consulate` | `.../greenvelope/2868640/contacts_export.csv` (`7e414cc8320d`) |
| The contact record gives the name Joe Wilkinson, the address 1605 Bruce Drive, Saint Simons Island, Georgia, and the contact group "State of Georgia". | `consulate` | `.../greenvelope/2360064/contacts_export.csv` (`9fc5b68be93b`) |
| Campaign 2360064 is "Israel's 71 Independence Day Yom Ha'atzmaut" on Tuesday, May 14, 2019. Campaign 2868640 is "Silent Exodus, Jewish Refugee Commemoration" on Sunday, November 24, 2019. | `consulate` | `.../greenvelope/2360064/event.json` (`9163aad556d0`), `.../greenvelope/2868640/event.json` (`51f493ba32ce`) |
| Campaign 4913667 is "Commemoration of the Expulsion of Jews from Arab lands" on Monday, November 29, 2021. | `consulate` | `.../greenvelope/4913667/event.json` (`fc96909f0ba2`) |
| The address is on a 2021 invitation list as well, status "Unopened". | `consulate` | `.../greenvelope/4913667/contacts_export.csv` (`33d70bc10b17`) |
| No document in `enron`, `epstein`, `textfiles`, `other` or `testdata` holds the address. | all | a text scan of every collection |

The folder `greenvelope` is the invitation service of the Consulate General of Israel in Atlanta. `tables/greenvelope` is a copy of one folder of `consulate/files`, so a correct answer names both collections and says that they hold one set of files.

## Expected tool calls

1. It calls `write_todo`, with plain item ids.
   ```json
   {"goal": "Find every document that mentions JoeBWilkinson@cs.com and say who the person is",
    "items": [{"id": "search", "text": "Search all collections for the address and the name", "status": "in_progress"},
              {"id": "read", "text": "Read the documents that hold the address", "status": "pending"},
              {"id": "web", "text": "Check the web for the person the documents name", "status": "pending"},
              {"id": "answer", "text": "Answer with cards for each document", "status": "pending"}]}
   ```
2. One search over every collection, with no `collectionname`, and more than one variant in one call.
   ```json
   {"queries": ["JoeBWilkinson@cs.com", "\"Joe Wilkinson\"", "\"Wilkinson, Joe\"", "JoeBWilkinson"]}
   ```
   sent to `search_passages`. A `search_collections` call with no `collectionname` and the query `JoeBWilkinson@cs.com | "Joe Wilkinson"` is also correct.
3. It calls `read_documents` on two or three of the hits, for example `inbox.csv` of campaign 2360064.
4. It calls `mark_todo` on `search` and `read`.
5. It calls `web_search` with the name and the place from the documents, for example `["\"Joe Wilkinson\" \"Saint Simons Island\"", "\"Joe Wilkinson\" Georgia \"Task Force for the Promotion of Public Trust\""]`.
6. It calls `read_page` on one result that names the task force or the Georgia role.
7. It calls `cite_documents` with the three or four documents above, each with a verbatim quote.
8. It calls `mark_todo` on the last items, then it answers.

## Expected result

The answer names every document that holds the address, grouped by campaign and date, with a card for each. It quotes the two decline messages and names the event of each campaign from its `event.json`. It says that the documents are guest-list exports, and it does not call them email threads. The web part keeps the person in the documents apart from other people with the same name, and it says which web claim is not confirmed. The second turn answers from the cited documents and gives the full list again, without a new claim that the address occurs "once".

## Requirements exercised

The story exercises these requirements: first todo write, with a valid id on the first attempt, search over all collections in one call, query variants and spellings, more than one in one call, web search and page reads, document cards shown to the user, a passage to jump to (the decline message), a task completed, with no claim that has no result behind it.
