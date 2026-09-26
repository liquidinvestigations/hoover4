# 10. Ehud Barak and Reporty Homeland Security

| field | value |
|---|---|
| mode | deep research, internet tools on |
| collections in scope | all seven |
| data needed | `tables`, dataset `ehudx` |

## Prompt

```text
Research in depth Ehud Barak's involvement with Reporty Homeland Security in late 2014: who was on the emails, what was proposed, what role Jeffrey Epstein, Darren Indyke and Nicole Junkermann played, and what became of the company afterwards. Use my documents and the web, and show me the key emails.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| 214 documents hold "Reporty". No document in `epstein` holds it. | `tables`, `epstein` | a text scan of both collections |
| On 12/14/2014 Ehud Barak forwarded "Reporty - Answers + Executive materials" to Darren Indyke, Nicole Junkermann and Udi Knaani. | `tables` | `/1 (317).html` (`5120988b87b4`) |
| On 12/17/2014 Barak wrote "Touch Base re Reporty DI,NJ" to Indyke and Junkermann, with Jeffrey Epstein (`Jeevacation@gmail.com`) in CC, to arrange a call with the CEO Amir Elichai. | `tables` | `/1 (283).html` (`a7b1a5196d23`) |
| On 12/20/2014 Amir Elichai (`amir@ireporty.com`) wrote to Barak, with Junkermann, Indyke and others in CC. | `tables` | `/1 (174).html` (`d9b3ce286622`) |
| On 12/22/2014 Barak answered Nicole Junkermann about a call on "Telco,Reporty, Monday 22nd". | `tables` | `/1 (135).html` (`63498595e4fc`) |
| Jeffrey Epstein forwarded "Reporty Homeland Security" on 2014-12-10. | `tables` | `/0000014702-Fwd_ Reporty Homeland Security.eml.meta` (`d49573f6ca68`) |

No document in the test corpora names the later name of the company. That part of the answer comes from the web, and the answer says so.

## Expected tool calls

1. The planner writes one plan node for each part: the people on the emails, the proposal, the roles, and the later history of the company.
2. After the approval, the organizer calls `run_subagent` with the plan node ids that `read_plan` returns. A todo item id is not a plan node id.
3. Each sub-agent searches with no `collectionname`, for example `search_passages` with `["Reporty", "\"Reporty Homeland Security\"", "ireporty Elichai", "Reporty Junkermann Indyke"]`.
4. It calls `doc_email` on the four emails above.
5. It calls `web_search` with `["Reporty Homeland Security Amir Elichai", "Reporty Ehud Barak investment 2015"]`, then `read_page` of one article.
6. It calls `cite_documents` with each key email, then the report.

## Expected result

A report with a dated list of the emails, the people on each and their role, with a card for each email. The later history of the company comes from a web page that the report names. Each web claim is marked as web context.

## Requirements exercised

The story exercises these requirements: first todo write, in each sub-agent, search over all collections, query variants, more than one in one call, todo edits, web search and page reads, document cards shown to the user, a task completed.
