# 22. Follow a lead without inventing the missing names

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | every collection |
| data needed | `enron` |

## Prompt

```text
any text in the Enron collection discussing former CIA working for Enron ? if yes, what are their names ?
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| A press report says that Andre Le Gallo was "the first person recruited from the CIA by Enron". | `enron` | "Enron Mentions (major papers only) -- 01/23/02-01/22/02", `/martin-t/inbox/83.` (`365fdcc913e3`) |
| A press report says that John W. Presley, a former FBI agent, led a security team that "also includes four former CIA officers". It does not name the four. | `enron` | "Enron Mentions -- 01/23/02", `/martin-t/inbox/82.` (`bb1822e89e7b`) |
| "Internet Report on Andre LeGallo Departure" of 2000-03-14 reports that Le Gallo left Enron. | `enron` | `/calendar/untitled/393.` (`8e1e499c980c`) |
| 121 documents hold the domain `the-cia.net`. A domain name says nothing about a person's employer. | `enron` | a text scan |

## Expected tool calls

1. It calls `search_collections` with `["\"former CIA\"", "\"Central Intelligence Agency\" Enron", "\"Le Gallo\" | LeGallo"]`.
2. It reads the two press digests and the departure report, and cites them.
3. If it searches for the four officers, it reports that no document names them.

## Expected result

The answer names Andre Le Gallo with his sources, and says that a report mentions four former CIA officers in John W. Presley's team without naming them. It names nobody else as a former CIA officer, and it does not take the domain `the-cia.net` as evidence of an employer. When it searches for the four unnamed officers, it keeps the findings it already has.

## Requirements exercised

The story exercises these requirements and optional behavior: a lead followed to its limit, a missing fact reported as missing, no inference from a domain name, document cards shown to the user, a task completed.
