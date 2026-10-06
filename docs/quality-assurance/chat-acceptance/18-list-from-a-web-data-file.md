# 18. A list from a large data file in a public code repository

| field | value |
|---|---|
| mode | chat, internet tools on |
| collections in scope | every collection |
| data needed | none, the facts are on the web |

## Prompt

```text
Go to https://gitlab.com/jack_poulson/widely-reported/-/tree/master/data?ref_type=heads and extract and list all the names of chief of station and sort them by year and mention location
```

## Facts the answer rests on

| fact | where |
|---|---|
| The folder lists the files of the repository's data set. `ciabase.json` holds the CIABASE records, each with `entrydates` and an `entry` text. | the folder page and `https://gitlab.com/jack_poulson/widely-reported/-/raw/master/data/ciabase.json` |
| The raw file is about 24 MB. Its text holds "Chief of Station" 53 times, in any case. Other forms are "station chief" and "COS". | `read_page` with `find` on the raw address, read on 2026-10-06 |
| Examples: Larry Devlin, Zaire, 1960 to 1963 and 1965 to 1967. Jake Engler, Caracas, Venezuela, 1957 to 1960. Lear Reed, Dominican Republic, 1958. Peer DeSilva, Vietnam, 1963 to 1965. Daniel Arnold, Thailand, until 1979. | the `entry` texts of `ciabase.json` |

## Expected tool calls

1. It calls `read_page` of the folder address to see the files.
2. It calls `read_page` of the raw address of `ciabase.json`, not of the viewer page, with `find` set to `Chief of Station`. It follows the next offset until it has every match.
3. It repeats the find for `station chief` and `COS`, or it says that it did not.
4. It answers with a table of name, location and years, sorted by year.

## Expected result

A table that the person can check against the file: each row gives the name, the location, the years and the record id. Rows without a name or without a year are listed apart, and the answer says how many matches it read and which forms it searched for. The answer gives the raw address as its source. It names no person that the file does not name.

## Requirements exercised

The story exercises these requirements and optional behavior: a page read of a raw repository file, a find across a large page with continuation, a complete list with its limits stated, web facts with their address, a task completed.
