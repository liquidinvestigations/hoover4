# 12. Who wrote the document, checked on the web

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | all seven |
| data needed | `testdata`, dataset `testfiles` |

## Prompt

```text
Who wrote the EasyChair guide that is in my test data, and where did they work? Then check the web: what else is Andrei Voronkov known for?
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| The guide names Andrei Voronkov and Kryštof Hoder, with EasyChair and the University of Manchester as affiliations. | `testdata` | `/documents/easychair.odt` (`531768b6ac7b`), `/documents/easychair.docx` (`36a12c77e4fd`) |
| The addresses in the guide are andrei@voronkov.com and hoderk@cs.man.ac.uk. | `testdata` | the same two documents |
| A plain text version cites "(Voronkov, 2004)". | `testdata` | `/easychair.txt` (`362795986fa1`) |

## Expected tool calls

1. It calls `write_todo` with a document step and a web step.
2. It calls `search_passages` with no `collectionname` and `["EasyChair guide author", "Voronkov Hoder", "\"Andrei Voronkov\""]`.
3. It calls `read_documents` on the ODT file.
4. It calls `cite_documents` with the author line as the quote.
5. It calls `web_search` with `["\"Andrei Voronkov\" Manchester", "\"Andrei Voronkov\" Vampire theorem prover"]`.
6. It calls `read_page` of one result, then it calls `mark_todo` and answers.

## Expected result

The answer takes the authors and affiliations from the document, with a card. It takes the rest of the career from a web page that it names. It keeps the two parts apart.

## Requirements exercised

The story exercises these requirements: first todo write, search over all collections, web search and page reads, document cards shown to the user, a passage to jump to, a task completed.
