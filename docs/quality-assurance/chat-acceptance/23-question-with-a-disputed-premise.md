# 23. A question whose premise can be false

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | every collection |
| data needed | none, the facts are on the web |

## Prompt

```text
what company is the biggest producer of Synthetic Cannabinoids in Europe ?
```

## Facts the answer rests on

The web changes, so this story gives checks in place of fixed facts.

| check | how to verify it |
|---|---|
| The answer says whether a legal market for synthetic cannabinoids exists, and keeps licensed pharmaceutical producers apart from the illicit market. | the answer text |
| Each company that the answer names has the address of a page that the run read, and that page supports the claim made about it. | `read_page` rows of the chat |
| When no source ranks producers by size, the answer says so and does not name a "biggest" producer. | the answer text |

## Expected tool calls

1. It calls `web_search` with queries for the licensed market (for example dronabinol and nabilone producers) and for the illicit market (for example EMCDDA or EUDA reports).
2. It calls `read_page` of the pages it uses.
3. It answers with the premise checked first.

## Expected result

The answer first checks the premise of the question, then names producers only where a read page supports it, each with its address. It states what is not known.

## Requirements exercised

The story exercises these requirements and optional behavior: a premise checked before the answer, web search and page reads, an address beside each web fact, an unknown stated as unknown, a task completed.
