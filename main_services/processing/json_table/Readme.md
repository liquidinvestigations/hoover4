# json-table

`json-table <file>` reads a JSON or JSON Lines file and writes its table sheets to stdout.
The table stage runs it through `read_json_cells` in
[table_readers.py](../tasks/P3_parse_files/table_readers.py). A builder stage of the worker
[Dockerfile](../Dockerfile) compiles it to `/usr/local/bin/json-table`.

## Grammar

The program reads the first 64 KiB. A UTF-16 or UTF-32 byte order mark gives no table.
A file whose first byte other than whitespace is not `{` or `[` gives no table.
The file is JSON Lines when its first two nonblank lines are each one complete JSON object or array.
Every other file is one JSON value. The Python check `json_grammar` uses the same rule.

## Sheets

- JSON Lines is one sheet without a name. Each nonblank line is one row.
- A JSON array at the root is the sheet `$`.
- In a JSON object, each array at a path of at most 3 keys is a candidate sheet, named by its path, for example `$.data.rows`.
  The limit covers the samples: GeoJSON `$.features`, STIX `$.objects`, and TopoJSON `$.objects.<name>.geometries`.
  Arrays deeper than 3 keys, and arrays inside rows, stay JSON text.
- A candidate becomes a sheet when it holds at least one object. A file without such an array has no table.
  An array of strings and an object keyed by names are examples.
- At most 100 sheets. Later sheets are left out, and the manifest records the `sheets` limit.

## Columns

- The program reads the file twice. Pass 1 builds the column paths of each sheet. The schema is then frozen.
  Pass 2 writes every row with the same column identities.
- A column path is a list of keys. Its label joins the keys with dots.
  A key escapes a backslash and a dot with a backslash. An empty key is `\e`. A key `$` or `*` alone gets a backslash.
  The label of `{"a.b": 1}` is `a\.b`, and the label of `{"a": {"b": 2}}` is `a.b`.
- Columns follow the first appearance of their path. A key that a later row adds gets a later column.
- An object becomes dot paths up to 16 levels. A deeper object, an empty object and an array are compact JSON text in one cell.
- A path that holds a scalar in one row and an object in another gets two columns: the path and its child paths.
- A row that is not an object fills the column `$`.
- `null` is a cell with the text `null`. A missing key is an empty cell.
- A duplicate key keeps its last value.
- A sheet with more than 1000 columns collapses objects into JSON text columns.
  The object with the most columns collapses first, and the earliest one wins a tie. This repeats until the sheet fits.
  When no object is left, the earliest root keys keep their columns, and the column `*` holds the other root keys of each row as one JSON object.

## Cells

Each cell carries a kind and its text. Numbers keep their source digits.
The parser writes an exponent as `e` with a sign, for example `1E400` becomes `1e+400`.
The Python reader stores an integer inside Int64 as `int`, a larger integer as `text`, and a finite decimal as `float`.
Strings are `text`, booleans are `bool`, and JSON text is `text`.

## Limits

| Limit | Value | Effect |
|---|---|---|
| Bytes of one row (a line or an array element) | 64 MiB | The read fails and names the row. |
| Nesting | 128 levels (the `serde_json` limit) | The read fails. Before a sheet is found, the file has no table. |
| Schema nodes of one sheet during discovery | 50,000 | The widest objects collapse. Then later root keys go to the column `*`. |
| Columns of one sheet | 1000 | See Columns. |
| Cell text that the program writes | 64 KiB and 4 bytes | The collector stores 64 KiB and records the `cell_bytes` limit. |

The Python collector keeps at most 2,000,000 distinct values across all columns of a document.
A column that reaches that budget reports its distinct count as approximate.

## Protocol

Each stdout line is one JSON object.

| Line | Meaning |
|---|---|
| `{"t":"none","reason":...}` | Valid input without a table. Exit status 0. |
| `{"t":"sheets","mode":"json" or "jsonl","sheets":[...]}` | The frozen sheets with their columns: `id`, `label`, `path`, `json`, `rest`. |
| `{"t":"row","s":<sheet>,"r":<row>,"c":[[<column>,<kind>,<text>],...]}` | One row. Kind `s` string, `n` number, `b` bool, `z` null, `j` JSON text. |
| `{"t":"end"}` | The last line of a complete read. |

A read error exits with status 1 and writes the message to stderr. A JSON file that is malformed before any sheet is found gives `none`.
The Python reader keeps the end of stderr in its error, kills the process when the consumer stops early, and raises when the `end` line is missing.

## Tests

The unit tests are in `src/tests.rs`. Run them in a Rust container:

```
docker run --rm -v "$PWD":/src -w /src docker.io/library/rust:1.91.0-trixie cargo test --release
```
