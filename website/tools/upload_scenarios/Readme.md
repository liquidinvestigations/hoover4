# Upload scenario data sets

[generate.py](generate.py) writes the data sets of the bounded upload scenarios.
Each subcommand writes one data set into a new folder.
The script refuses a folder that exists and a folder inside a Git working tree.
It refuses options that write more than 1,000 files or 512 MiB.
Write the data sets to a scratch disk outside the repository, and remove them after the run.
Run the script with a low priority, so the run leaves the stack its I/O.

```sh
nice -n 19 ionice -c3 python3 website/tools/upload_scenarios/generate.py many_small /var/tmp/upload-scenarios/t1
python3 website/tools/upload_scenarios/generate.py <data set> --help
```

| Data set | Scenario | Default content |
|---|---|---|
| `smoke` | smoke | 30 text files in 3 folder levels. Each file holds the word `quokkasmoke` and the word `quokkasmoke<n>` with its number. |
| `many_small` | T1 and R3, many small files | 1,000 text files of 1,024 bytes in 10 folders |
| `one_large` | T2, cut and resumed transfer | one file of 256 MiB random bytes |
| `many_members` | T3, archive with many members | one zip of 1,000 members of 100 bytes |
| `nested_archives` | T3, nested archives | one zip of 2 zips with 100 members each |
| `path_rules` | M2, path rules | `begin.json` with one path for each path rule, `cases.json` with the rule texts, and `disk/` with the cases that a Linux disk can hold |
| `large_manifest` | M3, manifest limit | `below.json`, a `begin` body of exactly 16 MiB with 1,000 empty files, and `above.json`, 1 byte larger. Spaces before the end of the file list fill each body to its size. |
| `shared_path` | C1, two uploads with one path | the folders `first` and `second`, which share `shared/report.txt` |
| `no_space` | S1, no free space | 2 sparse files of 16 MiB |

Sizes take the suffixes `K`, `M` and `G` for powers of 1,000, and `Ki`, `Mi` and `Gi` for powers of 1,024.
`--seed` sets the content. Two runs with one seed write the same bytes.
Two data sets with one seed have the same hashes, so the second ingests no new document.
Every file has the modification time `1792500000`.

A sparse file holds no disk blocks at the source.
The website writes every received byte, so the upload space and the dataset folder need the full size.
