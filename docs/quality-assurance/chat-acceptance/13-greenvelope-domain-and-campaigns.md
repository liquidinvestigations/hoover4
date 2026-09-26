# 13. What is this service, and how much of it is in my files

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | all seven |
| data needed | `consulate`, dataset `files`, and `tables`, dataset `greenvelope` |

## Prompt

```text
The consulate files have a folder called greenvelope. What is that service, who is the domain registered to, and how many invitation campaigns do my files hold?
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| The folder `/Consulate General of Israel in Atlanta, United States/greenvelope/` holds 21 campaign folders with numeric names, for example `2360064`, `2868640` and `4913667`. | `consulate` | a count of the folders in `vfs_files` |
| 20 of the folders hold an `event.json` with the event name and date. The first is "Israel's 71 Independence Day Yom Ha'atzmaut" on May 14, 2019, and the last dated one is a Curiosity Labs event on July 11, 2024. | `consulate` | the `event.json` files, for example `.../greenvelope/8962972/event.json` (`bfa8bb04c83f`) |
| The card links in the exports have the form `https://www.greenvelope.com/card/<code>`. | `consulate` | `.../greenvelope/2868640/contacts_export.csv` (`7e414cc8320d`) |
| `tables/greenvelope` holds a copy of one part of the same folder, 329 files. | `tables` | `vfs_files` counts per dataset |

## Expected tool calls

1. It calls `write_todo`.
2. It calls `folder_overview` on `consulate`, then `folder_list` on the `greenvelope` folder, to count the campaigns.
3. It calls `search_collections` with no `collectionname` and the query `greenvelope.com`, to find the collections that hold the files.
4. It calls `whois_lookup` with `["greenvelope.com"]`.
5. It calls `web_search` with `["greenvelope online invitations"]`, then `read_page` of the service's own page.
6. It calls `cite_documents` with one export file, then it answers.

## Expected result

The answer gives the campaign count from the folder listing, and says that `tables` holds a copy of part of it. It describes the service from a web page that it names, and gives the registrant data that the WHOIS answer holds, or says that the answer hides it.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, web search and page reads, and the WHOIS tool, document cards shown to the user, a task completed.
