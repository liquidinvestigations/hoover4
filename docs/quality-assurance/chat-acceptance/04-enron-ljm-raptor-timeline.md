# 04. A dated timeline of LJM and the Raptor vehicles

| field | value |
|---|---|
| mode | deep research, internet tools on |
| collections in scope | all seven |
| data needed | `enron`, datasets `maildir`, `kaminski_v` and `mann_k` |

## Prompt

```text
Research in depth what Enron's own staff wrote about LJM and the Raptor vehicles between late 1999 and the end of 2000: who wrote about them, when, what the research group valued, and what the lawyers worried about. Build a dated timeline and show me the emails it rests on.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| Stinson Gibner sent "LJM put valuation" on 1999-12-27. | `enron` | `/all_documents/11046.` (`b8ee59de2a73`), `/discussion_threads/4351.` (`fe3d7175ab80`) |
| Paulo Issler sent "LJM pricing" on 2000-02-14 and "LJM model" on 2000-02-15. | `enron` | subject rows in `email_identity` |
| Vince Kaminski sent "LJM update" on 2000-02-16. | `enron` | subject rows in `email_identity` |
| Shari Stack sent "Agreement re: Rhythms Net/LJM assets" on 2000-03-10. | `enron` | subject rows in `email_identity` |
| Carol St. Clair sent "Project Raptor" on 2000-05-02. Mary Cook sent "Raptor" on 2000-05-11. | `enron` | subject rows in `email_identity` |
| Sara Shackleton sent "Raptor II" on 2000-06-20, "Project Raptor III" on 2000-08-29 and "Project Raptor - Warrants" on 2000-08-30. | `enron` | subject rows in `email_identity` |
| Mary Cook sent "Project Raptor - Securities Act representation" on 2000-08-25. | `enron` | subject rows in `email_identity` |

A full ingest of `enron` can hold more documents than these facts name, so a reviewer reads the counts again before a verdict.

## Expected tool calls

1. The planner writes a plan with one node for each question: the research group, the legal work, the timeline, and the web context.
2. After the approval, the organizer runs one sub-agent for each node, with the plan node ids the plan tree gives.
3. Each sub-agent writes its own todo list, then searches with no `collectionname` or with `["enron"]`, for example `search_collections` with `{"query": "LJM | Raptor", "sort": {"field": "date", "direction": "asc"}}` and `search_passages` with `{"queries": ["LJM put valuation", "Raptor hedges", "Project Raptor warrants", "Rhythms LJM"]}`.
4. It calls `doc_email` or `read_documents` on each email the timeline cites.
5. A web search for public context, for example `["LJM2 Enron Fastow Raptor", "Raptor vehicles Enron Powers report"]`, and a `read_page` of one source.
6. It calls `cite_documents` with each email of the timeline, then the report.

## Expected result

A timeline where each row has a date, a sender, a subject, one sentence of content from the email, and a card. The report keeps the facts from the emails apart from the web context, and it names each claim that rests only on the web.

## Requirements exercised

The story exercises these requirements: first todo write, in each sub-agent, search over all collections, query variants, more than one in one call, todo edits, web search and page reads, document cards shown to the user, a task completed.
