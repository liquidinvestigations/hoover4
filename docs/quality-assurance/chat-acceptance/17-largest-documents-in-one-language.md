# 17. The largest documents in one language

| field | value |
|---|---|
| mode | deep research, internet tools off |
| collections in scope | every collection |
| data needed | `textfiles`, dataset `extra` |

## Prompt

```text
Find me across collections the 10 largest Hungarian language documents.
```

Second turn, in the same chat:

```text
Now find the 10 largest Russian language documents.
```

## Facts the answer rests on

| fact | collection | document |
|---|---|---|
| `textfiles` has a folder `/hun/` with 3,941 Hungarian Wikipedia articles. The other folders are `/eng/`, `/deu/` and `/esp/`. | `textfiles` | `vfs_files` paths |
| The largest Hungarian article is `/hun/Weimari_köztársaság.txt` (`8a6495256da9`), 147,053 bytes. The next are `/hun/Adolf_Hitler.txt` (`0b0d6d9fd471`, 104,739 bytes) and `/hun/Skagerraki_csata.txt` (`852b31e85bd2`, 97,655 bytes). The tenth is `/hun/Labdarúgás.txt` (`b0c2f23e1e4a`, 78,831 bytes). | `textfiles` | `vfs_files` sizes |
| The archive `/testdata-extra-demo-data-master/hun.7z` (9,135,520 bytes) holds the same articles. It is an archive, not a document in Hungarian. | `textfiles` | `vfs_files` |
| No collection holds a document whose main language is Russian. Cyrillic text occurs as quotes inside documents in other languages, for example `/esp/Federación_Rusa.txt` (`81e96b82240b`), and in the multilingual file `/enwikiversity-20170820-pages-meta-current.xml` (`fa098b7d7a24`). | every collection | a text scan |

## Expected tool calls

1. It finds the Hungarian documents with a language filter when one exists. Without a language filter it lists the `/hun/` folder with `folder_list` or a folder filter, and it confirms the language by reading two documents.
2. It sorts the candidates by `file_size` and keeps the 10 largest.
3. It calls `cite_documents` with the 10 documents.
4. In the second turn it searches for Russian text, finds only quotes inside documents in other languages, and says that no document is in Russian.

## Expected result

A table of the 10 Hungarian articles, largest first, with sizes and cards, and a note that the archive is left out. The second answer says that no document is in Russian, and names two documents that only quote Russian. Neither answer lists a document in another language as a match. A plan has no section that needs the result of another section.

## Requirements exercised

The story exercises these requirements and optional behavior: a filter by language or by folder, a sort by size, an empty result reported as empty, independent plan sections, document cards shown to the user, a task completed.
