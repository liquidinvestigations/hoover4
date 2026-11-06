# Browser scenarios

Each file in this directory is one capture scenario. The file name is the slug:
`{number}-{section}.ini`. The capture engine reads every numbered file in slug-number
order. [website/tools/capture_screenshots.py](../tools/capture_screenshots.py) is that engine.

`summary` is one sentence that says what the case exercises.
Operation scenarios use `{{operation_id}}` in JavaScript actions. Pass `--operation-id ID`
to the screenshot wrapper for these scenarios.

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
| `manual_asset` | the stable filename [docs/user-manual/User_Manual.md](../../docs/user-manual/User_Manual.md) links for this scenario's capture. The runner records it in the manifest beside the capture it names. It never renames the PNG file itself, so a document that changes keeps the manual's link valid |
| `requires_dataset` | a page whose route or assertions are tied to one dataset names it here (several, comma-separated, if it needs more than one; `any` if it needs one of the four datasets [main_services/verify-stack.sh](../../main_services/verify-stack.sh) always ingests, testdata_testfiles, testdata_zips, testdata_shapes, other_emails, but not a specific one). The capture wrapper skips a page whose dataset is not on the running site, with the missing dataset named, rather than failing it. A page with no `requires_dataset` renders without the corpus |
| `procedure` | name of a Python procedure in [procedures/](procedures) |
| `init_script` | JavaScript that the browser runs before any page script on the first navigation of the scenario |
| `cold_cache` | `true` to clear the browser cache and bypass it for the first navigation, so every stylesheet, script and font comes from the network |
| `interface_language` | A language code that the language settings page selects before the capture. The harness selects the browser language again after the capture. The setting belongs to the test user, so run such a case with `--shards 1` |
| `summary` | one sentence that says what the case exercises |

Verbs: `goto`, `wait_text`, `wait_css`, `click_text`, `click_css`, `type_css` (SEL :: TEXT),
`wait_text_in` / `click_text_in` (SELECTOR :: TEXT), `press_enter`, `hover_css`,
`scroll`, `sleep`, `eval`.

The long base64 segments are CBOR-encoded route parameters. They are written out rather
than driven through the UI because typing into the home box and waiting for a
navigation is three failure modes to reach a page that a URL reaches in one. See
[frontend/src/data_definitions/url_param.rs](../frontend/src/data_definitions/url_param.rs). `9g==` is `None`.

## Scenarios outside the default run

A run reads the numbered files of this directory. Two subdirectories hold scenarios that a
default run does not read.

| directory | wrapper option | what the scenarios need |
|---|---|---|
| [dispatch/](dispatch) | `--dispatch` | They dispatch server work, such as a chat turn or a stop. |
| [fixture-build/](fixture-build) | `--fixture-build` | They open the harness pages of a website build with the cargo feature `browser-fixtures`. [../tools/serve_fixture_build.sh](../tools/serve_fixture_build.sh) starts that build and gives its target. |

`533-ai-chat-stop-after-written-file` in `dispatch/` needs a held turn.
`main_services/processing/tests/integration/test_agent_run_browser_stop.py` holds it.
Run that test with `HOOVER4_BROWSER_STOP_USER` set to the signed-in account.
When it prints `BARRIER REACHED`, run the scenario with `--dispatch`.

## Procedures

[procedures/](procedures) holds one Python file per manual procedure. The file name is the procedure
name used in the `procedure` key. [website/tools/manual_qa_runtime.py](../tools/manual_qa_runtime.py) loads that directory
and keeps the shared helpers.

## Restoring a concatenated ini

[website/tools/split_browser_tests.py](../tools/split_browser_tests.py) writes this directory from a concatenated ini.
[website/tools/verify_browser_test_split.py](../tools/verify_browser_test_split.py) compares the parsed scenario list from that
ini with this directory.

## Release correction fixtures

The `release` scenarios use the synthetic `release_browser` collection and its `primary` and `duplicate` datasets.
[The fixture helper](../tools/fixtures/release_browser.py) prepares their registry, schemas, indexes, documents, and facet values.
Run it inside a processing container with the application's datastore configuration and current repository source.
Use disposable datastores for this fixture collection.
The helper applies global and fixture collection migrations, then writes its named datasets.
Its JSON output records the stable document hashes used by these scenarios.

The table fixtures contain `row-0-` and `row-1-` prefixes.
The email fixture has one subject match, three recipient matches, and two body matches for `quokka`.
The same email hash occurs in both datasets.
The text fixture retains four mapped `quokka` matches across a removed encoded run.
The table race scenario retains the browser runtime while changing the route and moving through browser history.
The metadata scenario changes the fixture collection display name and restores its original value.

The delayed Abort scenario needs a writable upload target for the primary fixture dataset.
Its transfer and Abort responses are controlled browser fixtures.
The production upload page and driver process both selections through their normal controls.
The old Abort response resolves after the replacement page has a new selection.

The metadata rename and disposable-dataset deletion scenarios require `--dispatch`.
The deletion scenario removes only `release_browser_disposable`.
Prepare that empty dataset with the display name `Delete this dataset` before each deletion run.

The translation fixture page renders production chat cards, board statistics, and generic tool disclosures.
Its scenarios use `--fixture-build` and exercise zero, one, two, five, and twenty-one counts.
The fixture controls only the internet-tool availability response for its board settings.

A deletion request can tombstone the fixture dataset before operation admission fails.
The deletion scenario records that error separately and verifies that the shared tree still removes the dataset.

## Automatic OCR and actual-date fixtures

Run [the automatic-status helper](../tools/fixtures/release_browser_automatic.py) after the release document helper in disposable datastores.
It applies the current collection migration and search-schema update before writing controlled stored rows.
The OCR rows represent planned, published, applied, failed, incomplete, and unsupported coverage.
One failed replacement retains previously published text and positive presence.
These fixtures verify readers and interface states. They do not execute OCR models or settle processing operations.
The helper also retains manual installation values to verify their exclusion from editing controls.

The chronology inputs include a document dated in 2000 and 2010, a document dated in 2005, an unknown date, and a pre-epoch date.
The date scenarios verify the recorded-date gap, inclusive boundaries, unknown-only selection, and pre-epoch selection.
The presence scenario selects only verified published text through canonical value 2.
The automatic creation scenario changes its outgoing mount to an invalid fixture mount before sending the request.
This verifies the registered endpoint and absent manual payload fields without creating a dataset or dispatching ingestion.
The status translation scenario substitutes update-step registry metadata while reading OCR status from stored fixtures.

The stale-status case retains delayed replies through A-to-B-to-A dataset navigation.
It verifies fresh selections and progress, then resolves the older submission while the newer submission still owns its busy state.
A newer Check again response owns the displayed message. The submitted-operation responses are controlled browser fixtures.
