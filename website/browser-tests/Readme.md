# Browser scenarios

Each file in this directory is one capture scenario. The file name is the slug:
`{number}-{section}.ini`. The capture engine reads every numbered file in slug-number
order. `website/tools/capture_screenshots.py` is that engine.

`summary` is one sentence that says what the case exercises.

## Hundred-block numbers

| block | contents | section prefix |
|---:|---|---|
| 000 to 099 | entry points and addresses that name nothing | `home`, `bad-url-*` |
| 100 to 199 | search, filters and sort | `search-*`, `filter-*`, `sort-*`, `qa-sort-*` |
| 200 to 299 | document viewer, excluding tables | `view-doc-*` except table |
| 300 to 399 | storage browser and tree | `storage-*`, `qa-storage-*` |
| 400 to 499 | the table browser | `view-doc-table-*`, `qa-table-*` |
| 500 to 599 | chat | `ai-chat*` |
| 600 to 699 | admin and the operations log | `admin-*` |
| 700 to 799 | manual procedures | `manual-*` |
| 800 to 899 | PDF source switching | `qa-pdf-*` |

A new case takes the next unused number in its block. Other blocks keep their numbers.

## Keys

| key | meaning |
|---|---|
| `url` | path on the site, appended to the base URL |
| `actions` | one per line: verb argument |
| `viewport` | `WIDTHxHEIGHT`. When present, this size replaces the run's `--resolutions` list for this scenario, and the capture goes to a directory named for the declared size (such as `600x900/`) instead of `720p/` or `1080p/`. A layout test that must hold at one declared width belongs here. Leave it unset to capture at every selected resolution. |
| `full_page` | `true` to capture past the fold, as a supplementary image beside the exact-size primary capture |
| `settle_ms` | quiet time before and after the actions. The directory loader uses 800 when the file omits this key |
| `expect` | one or more of `missing_page`, `error_display`, `error_bar`, comma separated. Declares that this scenario is built to reach that negative state, and reclassifies the matching observation from `application_error` to `expected_outcome`. `allow_error_markers` and `allow_http_errors` only suppress an unrelated, already-known exemption. They do not assert that the state was observed, so a scenario built to demonstrate one uses `expect` instead |
| `scroll_captures` | one or more pixel offsets, comma separated. An extra same-size capture at each offset, for a page taller than the viewport, beside the primary capture at offset 0 |
| `manual_asset` | the stable filename `docs/user-manual/User_Manual.md` links for this scenario's capture. The runner records it in the manifest beside the capture it names. It never renames the PNG file itself, so a document that changes keeps the manual's link valid |
| `requires_dataset` | a page whose route or assertions are tied to one dataset names it here (several, comma-separated, if it needs more than one; `any` if it needs one of the four datasets `main_services/verify-stack.sh` always ingests, testdata_testfiles, testdata_zips, testdata_shapes, other_emails, but not a specific one). The capture wrapper skips a page whose dataset is not on the running site, with the missing dataset named, rather than failing it. A page with no `requires_dataset` renders without the corpus |
| `procedure` | name of a Python procedure in `procedures/` |
| `summary` | one sentence that says what the case exercises |

Verbs: `goto`, `wait_text`, `wait_css`, `click_text`, `click_css`, `type_css` (SEL :: TEXT),
`wait_text_in` / `click_text_in` (SELECTOR :: TEXT), `press_enter`, `hover_css`,
`scroll`, `sleep`, `eval`.

The long base64 segments are CBOR-encoded route parameters. They are written out rather
than driven through the UI because typing into the home box and waiting for a
navigation is three failure modes to reach a page that a URL reaches in one. See
`frontend/src/data_definitions/url_param.rs`. `9g==` is `None`.

## Procedures

`procedures/` holds one Python file per manual procedure. The file name is the procedure
name used in the `procedure` key. `website/tools/manual_qa_runtime.py` loads that directory
and keeps the shared helpers.

## Restoring a concatenated ini

`website/tools/split_browser_tests.py` writes this directory from a concatenated ini.
`website/tools/verify_browser_test_split.py` compares the parsed scenario list from that
ini with this directory.
