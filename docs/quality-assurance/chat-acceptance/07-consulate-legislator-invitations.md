# 07. Which legislators the consulate invited, and who declined

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | all seven |
| data needed | `consulate`, dataset `files` |

## Prompt

```text
Which members of the Georgia General Assembly did the Israeli consulate in Atlanta invite to its events in 2019, and which of them declined and why? Give me a table.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 168 documents hold "Georgia General Assembly". They are contact files of 21 greenvelope campaigns. | `consulate` | a text scan, and a count of `greenvelope/<campaign>/` folders |
| On 5/3/2019 todd.jones@house.ga.gov declined with "I'll be traveling out of the country." | `consulate` | `.../greenvelope/2360064/inbox.csv` (`307033ff8279`) |
| In the same campaign sheila.nelson@house.ga.gov is a "Georgia General Assembly" contact with status "Responded". | `consulate` | `.../greenvelope/2360064/contacts/21.json` (`6112acc655da`) |
| The contact files use short JSON keys, for example `"c"` for the company and `"em"` for the email address. | `consulate` | `.../greenvelope/8962972/contacts/3.json` (`c9c4d6c73671`) |

## Expected tool calls

1. It calls `write_todo`.
2. It calls `search_collections` with no `collectionname`, the query `"Georgia General Assembly"` and a date filter for 2019.
3. It calls `folder_overview` on `consulate` to find the campaign folders, then `table_overview` and `table_search_cells` on the `contacts_export.csv` and `inbox.csv` of each 2019 campaign.
4. It calls `cite_documents` for each row of the table.
5. It calls `mark_todo`, then it answers.

## Expected result

A table with one row for each invited legislator: name, email address, campaign, response status and the decline message. Each row has a card, and the answer says how many campaigns it read and which it did not read.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, todo edits, as the campaign count becomes known, document cards shown to the user, a passage to jump to, a task completed.
