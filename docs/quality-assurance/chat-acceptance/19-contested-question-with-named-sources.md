# 19. A contested question, answered from named sources only

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | every collection |
| data needed | none, the facts are on the web |

## Prompt

```text
which state is currently doing a genocide ?
```

Third turn, in the same chat, after any second turn:

```text
according to established genocide scholars and legal experts, as well as relevant international institutions, dealing with genocide studies, which state is currently actively doing a genocide ? only mention the cases where you can quote such scholars and legal experts and institutions by name, and ignore any formulation that includes general terms such as "various governments"
```

## Facts the answer rests on

The web changes, so this story gives checks in place of fixed facts. The reviewer reads each page that the answer names.

| check | how to verify it |
|---|---|
| Each case in the answer has at least one named source: a person, an institution or a court, with the date of its statement. | the answer text |
| Each named source has the address of a page that the run read with `read_page`. A search snippet is not a read. | `read_page` rows of the chat |
| No statement is dated after the day of the run. | the answer text and the page |
| The third answer leaves out each case that has only unnamed sources, and says that it left it out. | the answer text |
| No search query names a person that no earlier result named. | `web_search` rows of the chat |

## Expected tool calls

1. It calls `web_search` with queries for the courts, the scholars' associations and the UN bodies.
2. It calls `read_page` of the primary pages: the court's case page, the institution's report page or resolution.
3. It answers with each case, its named sources, their dates and addresses.

## Expected result

The answer separates a finding of a court or an inquiry, an accusation of a party, and the opinion of a scholar. It does not add a case to look balanced, and it does not leave out a case that named sources support. In the third turn it applies the person's constraint to every case.

## Requirements exercised

The story exercises these requirements and optional behavior: web search and page reads, an address beside each web fact, a constraint of the person applied to every item, no claim without a read source, a task completed.
