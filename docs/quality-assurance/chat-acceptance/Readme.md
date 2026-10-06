# Chat acceptance stories

Each story is a request that an investigative journalist could make of the chat, on the test corpora. Every story runs in chat mode. Stories 14 to 23 each test one distinct operation that a reviewer of the demo chats tried. Stories 18 to 20 and 23 rest on the web, so they give checks of the answer's sources in place of fixed facts. A story gives the prompt, the mode, and the facts that a correct answer rests on. It names the document that holds each fact, the tool calls a good run makes, and the result. A run of a story is reviewed with [report-template.md](report-template.md).

## The stories

| file | mode | internet tools | collections the facts are in | what it tests most |
|---|---|---|---|---|
| [01-email-address-everywhere.md](01-email-address-everywhere.md) | chat | on | `consulate`, `tables` | one search over every collection, query variants, a follow-up turn |
| [02-epstein-ruemmler-wolff.md](02-epstein-ruemmler-wolff.md) | chat | off | `epstein` | dated quotes with cards, OCR spellings |
| [03-enron-dasovich-puc-talking-points.md](03-enron-dasovich-puc-talking-points.md) | chat | off | `enron` | a scope the user narrows, duplicate emails |
| [04-enron-ljm-raptor-timeline.md](04-enron-ljm-raptor-timeline.md) | chat | on | `enron` | several questions in one turn, a timeline with cards |
| [05-nili-priell-barak-fortress.md](05-nili-priell-barak-fortress.md) | chat | on | `tables` | data in a collection whose name does not suggest it |
| [06-hebrew-and-latin-spellings.md](06-hebrew-and-latin-spellings.md) | chat | off | `tables` | variants in two scripts in one call |
| [07-consulate-legislator-invitations.md](07-consulate-legislator-invitations.md) | chat | off | `consulate` | table tools over many exports, optional todo use |
| [08-textfiles-rommel-multilingual.md](08-textfiles-rommel-multilingual.md) | chat | off | `textfiles` | variants in three languages, a word inside another word |
| [09-fontys-open-day-invitation.md](09-fontys-open-day-invitation.md) | chat | on | `testdata`, `other` | documents in preference to the web, a card the user opens |
| [10-reporty-homeland-security.md](10-reporty-homeland-security.md) | chat | on | `tables` | several parts in one turn, web context kept apart |
| [11-darren-indyke-across-collections.md](11-darren-indyke-across-collections.md) | chat | off | `epstein`, `tables` | counts per collection, a person with the same surname |
| [12-easychair-authors-and-web.md](12-easychair-authors-and-web.md) | chat | on | `testdata` | a document fact and a web fact kept apart |
| [13-greenvelope-domain-and-campaigns.md](13-greenvelope-domain-and-campaigns.md) | chat | on | `consulate`, `tables` | folder tools, WHOIS and web reads |
| [14-largest-files-of-one-type.md](14-largest-files-of-one-type.md) | chat | off | `testdata`, `epstein` | a file type filter, a size sort, an empty result |
| [15-word-count-and-entity-count.md](15-word-count-and-entity-count.md) | chat | off | `enron` | a count by word and by entity, the difference explained |
| [16-emails-from-one-sender-to-one-recipient.md](16-emails-from-one-sender-to-one-recipient.md) | chat | off | `enron` | sender and recipient filters, copies of one message grouped |
| [17-largest-documents-in-one-language.md](17-largest-documents-in-one-language.md) | chat | off | `textfiles` | a language or folder filter, a size sort, an absent language |
| [18-list-from-a-web-data-file.md](18-list-from-a-web-data-file.md) | chat | on | none | a raw repository file, a find across a large page |
| [19-contested-question-with-named-sources.md](19-contested-question-with-named-sources.md) | chat | on | none | named sources only, a constraint applied to every item |
| [20-distinct-court-cases-from-the-web.md](20-distinct-court-cases-from-the-web.md) | chat | on | none | distinct items, reports of one item merged, no filler |
| [21-primary-documents-and-press-coverage.md](21-primary-documents-and-press-coverage.md) | chat | off | `enron` | a primary source told apart from press coverage |
| [22-follow-a-lead-without-inventing-names.md](22-follow-a-lead-without-inventing-names.md) | chat | off | `enron` | a missing fact reported as missing |
| [23-question-with-a-disputed-premise.md](23-question-with-a-disputed-premise.md) | chat | on | none | a premise checked before the answer |

## How to run a story

1. Sign in to the site under test as an account that can read every collection the story names.
2. Open `/ai_chat`. Select the collections the story names, and set the internet tools switch to the story's mode.
3. Paste the prompt from the story word for word, and send it.
4. Wait until the turn ends. Copy the session id from the page URL.
5. Read the rows of the chat from the tables that the report template names, and fill a copy of [report-template.md](report-template.md).

A driver can send the same requests through the website's server functions, in place of the page. It must send the identity of a real account, so that the person can open the chat afterwards.

`website/observe-chat.sh --prompts story-14,story-17` runs the named stories and their second turns.
The observer reads prompt text and internet settings from these documents.
It reports a failed second turn as incomplete execution.
The `all` selection retains the fixed workload.

## When the data changes

Each fact names its collection, its path and the first 12 characters of its content hash. Before a verdict, the reviewer checks that the fact is still in the data with a text scan of the collection. A story whose facts are gone is marked stale, and it is not run until its facts are read again.
