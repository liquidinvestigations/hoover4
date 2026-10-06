# 14. The largest files of one type in one collection

| field | value |
|---|---|
| mode | chat, internet tools off |
| collections in scope | every collection |
| data needed | `testdata`, and `epstein` for the second turn |

## Prompt

```text
Go in collection testdata and retrieve all the pdf files. Sort them by size, largest first.
```

Second turn, in the same chat:

```text
How many PDF documents does the epstein collection hold? List the 10 largest.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| `testdata` holds 15 distinct documents whose canonical type is PDF. | `testdata` | a count of `file_type_canonical` with `file_type = 'pdf'` |
| The largest is `/documents/stanley.ec02.pdf` (`d21ccff5b16f`), 455,683 bytes, at 12 paths. The next are `/International Open Day Invitation.pdf` (`dd27d5ea0260`, 285,468 bytes) and `/part-1.2-TWEOL.pdf` (`4299eca96e26`, 206,848 bytes). | `testdata` | `vfs_files` sizes |
| The smallest is `/born-digital-no-ocr.pdf` (`696dc59ceff1`), 592 bytes. | `testdata` | `vfs_files` sizes |
| `epstein` holds no PDF. Its documents are 2,309 emails, 471 text files, 106 tables and 2 HTML files. | `epstein` | a count of `file_type_canonical` by `file_type` |

## Expected tool calls

1. It calls `search_collections` with `collectionname` `["testdata"]`, a file type filter for PDF, no query words, and the sort `file_size` descending.
2. It calls `read_more` until it has every row, or it uses the total of the result.
3. It calls `cite_documents` with the three largest files.
4. In the second turn it calls `search_facet_values` or `search_collections` with the file type facet on `epstein`, and it reads the PDF count of 0 from the result.

## Expected result

A table of the 15 PDFs with path, size and card, largest first, and the total. A search for the text ".pdf" is not a type filter: an email that names a PDF is not a PDF. The second answer says that `epstein` holds no PDF and gives the types it does hold. It does not list documents of another type in place of PDFs.

## Requirements exercised

The story exercises these requirements and optional behavior: a filter by file type, a sort by size, a complete list, an empty result reported as empty, document cards shown to the user, a task completed.
