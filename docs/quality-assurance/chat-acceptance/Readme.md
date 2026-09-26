# Chat acceptance stories

Each story is a request that an investigative journalist could make of the chat, on the test corpora. A story gives the prompt, the mode, and the facts that a correct answer rests on. It names the document that holds each fact, the tool calls a good run makes, and the result. A run of a story is reviewed with [report-template.md](report-template.md).

## The stories

| file | mode | internet tools | collections the facts are in | what it tests most |
|---|---|---|---|---|
| [01-email-address-everywhere.md](01-email-address-everywhere.md) | chat | on | `consulate`, `tables` | one search over every collection, query variants, a follow-up turn |
| [02-epstein-ruemmler-wolff.md](02-epstein-ruemmler-wolff.md) | chat | off | `epstein` | dated quotes with cards, OCR spellings |
| [03-enron-dasovich-puc-talking-points.md](03-enron-dasovich-puc-talking-points.md) | chat | off | `enron` | a scope the user narrows, duplicate emails |
| [04-enron-ljm-raptor-timeline.md](04-enron-ljm-raptor-timeline.md) | deep research | on | `enron` | a plan with one node for each part, a timeline with cards |
| [05-nili-priell-barak-fortress.md](05-nili-priell-barak-fortress.md) | chat | on | `tables` | data in a collection whose name does not suggest it |
| [06-hebrew-and-latin-spellings.md](06-hebrew-and-latin-spellings.md) | chat | off | `tables` | variants in two scripts in one call |
| [07-consulate-legislator-invitations.md](07-consulate-legislator-invitations.md) | chat | off | `consulate` | table tools over many exports, todo edits |
| [08-textfiles-rommel-multilingual.md](08-textfiles-rommel-multilingual.md) | chat | off | `textfiles` | variants in three languages, a word inside another word |
| [09-fontys-open-day-invitation.md](09-fontys-open-day-invitation.md) | chat | on | `testdata`, `other` | documents in preference to the web, a card the user opens |
| [10-reporty-homeland-security.md](10-reporty-homeland-security.md) | deep research | on | `tables` | plan node ids, web context kept apart |
| [11-darren-indyke-across-collections.md](11-darren-indyke-across-collections.md) | deep research | off | `epstein`, `tables` | counts per collection, a person with the same surname |
| [12-easychair-authors-and-web.md](12-easychair-authors-and-web.md) | chat | on | `testdata` | a document fact and a web fact kept apart |
| [13-greenvelope-domain-and-campaigns.md](13-greenvelope-domain-and-campaigns.md) | chat | on | `consulate`, `tables` | folder tools, WHOIS and web reads |

## How to run a story

1. Sign in to the site under test as an account that can read every collection the story names.
2. Open `/ai_chat`. Select the collections the story names, and set the two switches to the story's mode.
3. Paste the prompt from the story word for word, and send it. A deep research run stops for plan approval. Approve it, unless the story says otherwise.
4. Wait until the turn ends. Copy the session id from the page URL.
5. Read the rows of the chat from the tables that the report template names, and fill a copy of [report-template.md](report-template.md).

A driver can send the same requests through the website's server functions, in place of the page. It must send the identity of a real account, so that the person can open the chat afterwards.

## When the data changes

Each fact names its collection, its path and the first 12 characters of its content hash. Before a verdict, the reviewer checks that the fact is still in the data with a text scan of the collection. A story whose facts are gone is marked stale, and it is not run until its facts are read again.
