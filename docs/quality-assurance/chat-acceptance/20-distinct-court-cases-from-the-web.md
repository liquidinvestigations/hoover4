# 20. A list of distinct court cases from the web

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | every collection |
| data needed | none, the facts are on the web |

## Prompt

```text
list 5 cases prosecuted in court in Germany related to ADB cannabis
```

## Facts the answer rests on

The web changes, so this story gives checks in place of fixed facts.

| check | how to verify it |
|---|---|
| Each listed case names the court, the date of the decision or of the trial, and a file number or the defendant's description, so that two rows are visibly different cases. | the answer text |
| Two articles about the same case are one row with both addresses. | the pages the answer names |
| Each case concerns ADB-type synthetic cannabinoids (for example ADB-BUTINACA or MDMB-4en-PINACA). A case about another substance is not in the list. | the pages the answer names |
| When the run finds fewer than 5 cases, the answer says so and does not fill the list. | the answer text |
| Each row has the address of a page that the run read. | `read_page` rows of the chat |

## Expected tool calls

1. It calls `web_search` with German and English queries, for example `["ADB-BUTINACA Urteil Landgericht", "synthetische Cannabinoide ADB Anklage", "ADB-BUTINACA court Germany"]`.
2. It calls `read_page` of each candidate case page.
3. It merges the reports of one case and answers.

## Expected result

A list of distinct cases, each with its court, date, substance and the addresses of the pages read. The list is shorter than 5 when fewer cases are found, and the answer says how it searched.

## Requirements exercised

The story exercises these requirements and optional behavior: web search in two languages, page reads, reports of one item merged, a list not filled to the asked length, an address beside each web fact, a task completed.
