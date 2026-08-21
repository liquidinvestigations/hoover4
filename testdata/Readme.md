# Test data

Corpora and fixtures the pipeline tests and `main_services/verify-stack.sh` ingest.

| path | is |
|---|---|
| `hoover-testdata/` | a fetched upstream fixture corpus, pulled by `main_services/fetch-testdata.sh` |
| `enron-kaminski-v/` | a mail corpus in maildir-like folders |
| `generated/` | fixtures produced for specific behaviours: large files, gaps, tables, wide rows, filename-only hits, rescan probes |

Two properties of the mail corpus shape the tests that use it: the files carry no extensions,
so type detection must work on content alone, and a fifth of the messages share a message id
with another message, so anything keyed on that id must tolerate duplicates.

Fixture depth matters. Verification takes ingest roots from the environment because a host
whose corpus sits one level deeper finds nothing at the default path.
