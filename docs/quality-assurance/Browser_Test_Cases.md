# Browser test cases

This catalogue has one row per scenario file in `website/browser-tests/`. There are 140 files.
The slug is the file stem. `--names` selects the ini section name, shown in
the reproduce column.

A missing `requires_dataset` value is recorded as `none named`. The literal
`any` is a named value in the file.

## Contents

- [How to reproduce a case](#how-to-reproduce-a-case)
- [How to read a result](#how-to-read-a-result)
- [Entry pages](#entry-pages) (3)
- [Search, filters, and sort](#search-filters-and-sort) (33)
- [Document view](#document-view) (15)
- [Storage and folder tree](#storage-and-folder-tree) (26)
- [Table viewer](#table-viewer) (15)
- [Chat](#chat) (3)
- [Admin](#admin) (23)
- [Manual QA procedures](#manual-qa-procedures) (19)
- [PDF source switch](#pdf-source-switch) (3)

## How to reproduce a case

Set `HOOVER4_SITE_URL` in the environment or in `website/TEST_LOGIN.env`,
or pass `--target URL`. Credentials come from the same login file.
Then run:

```
website/take-screenshots.sh --names SECTION
```

`SECTION` is the ini section name in the reproduce column. More than one name may be comma-separated.
`--only SUBSTRING` selects every section whose name contains the substring.
With no `--names` and no `--only`, the wrapper captures every file.

Output lands in `website/test_reports/screenshots/run-<stamp>-<pid>/`.
See [Capture report format](Capture_Report_Format.md) for the table that run writes.
See [Testing the website](Testing_The_Website.md) for flags and exit status.

## How to read a result

Open `report.md` or `report.html` in the run directory. Each row is one case.
PASS means the capture finished without an application error.
FAIL means an unexpected missing page, a non-200 main document, or an undeclared error marker.
WARNING means a console, network, or behavioral observation that does not change the exit status.
INCOMPLETE means the case did not run. A missing fixture, a failed login, or a stopped browser produces that word.
INCOMPLETE rows sort last.

Look at the linked image and the snapshot. The image shows the pixels.
The snapshot is the rendered DOM outline. `image_inventory.json` stores review state,
starting as `unreviewed`, apart from the machine verdict.

A FAIL or WARNING row that you accept still needs a person to look at the image.
A PASS row can still show the wrong content. The four words classify the harness observation.
They do not replace a person looking at the page.

## Entry pages

Home, an unknown route, and a malformed document parameter.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `001-home` | Exercises the home case. | none named | `--names home` |
| `002-bad-url-unknown-route` | Exercises the bad url unknown route case. | none named | `--names bad-url-unknown-route` |
| `003-bad-url-malformed-param` | Exercises the bad url malformed param case. | none named | `--names bad-url-malformed-param` |

## Search, filters, and sort

Search results, filter panes, sort menus, and query chips.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `101-search-empty-query` | Exercises the search empty query case. | none named | `--names search-empty-query` |
| `102-search-easychair` | Exercises the search easychair case. | none named | `--names search-easychair` |
| `103-filter-modal-collections` | Exercises the filter modal collections case. | none named | `--names filter-modal-collections` |
| `104-filter-pane-filetypes` | Exercises the filter pane filetypes case. | none named | `--names filter-pane-filetypes` |
| `105-filter-pane-filesize` | Exercises the filter pane filesize case. | none named | `--names filter-pane-filesize` |
| `106-filter-pane-filelocation` | Exercises the filter pane filelocation case. | none named | `--names filter-pane-filelocation` |
| `107-filter-pane-filelocation-tree` | Exercises the filter pane filelocation tree case. | `testdata_shapes` | `--names filter-pane-filelocation-tree` |
| `108-filter-pane-date` | Exercises the filter pane date case. | none named | `--names filter-pane-date` |
| `109-filter-pane-date-before` | Exercises the filter pane date before case. | none named | `--names filter-pane-date-before` |
| `110-filter-pane-date-after` | Exercises the filter pane date after case. | none named | `--names filter-pane-date-after` |
| `111-filter-pane-date-bar-clicked` | Exercises the filter pane date bar clicked case. | `any` | `--names filter-pane-date-bar-clicked` |
| `112-filter-pane-date-unknown` | Exercises the filter pane date unknown case. | none named | `--names filter-pane-date-unknown` |
| `113-filter-pane-email` | Exercises the filter pane email case. | none named | `--names filter-pane-email` |
| `114-filter-pane-entities` | Exercises the filter pane entities case. | none named | `--names filter-pane-entities` |
| `115-search-with-chips` | Exercises the search with chips case. | `any` | `--names search-with-chips` |
| `116-sort-menu` | Exercises the sort menu case. | none named | `--names sort-menu` |
| `117-sort-pending` | Exercises the sort pending case. | none named | `--names sort-pending` |
| `118-qa-sort-empty-default` | Exercises the qa sort empty default case. | `testdata_testfiles` | `--names qa-sort-empty-default` |
| `119-qa-sort-explicit-relevance` | Exercises the qa sort explicit relevance case. | `testdata_testfiles` | `--names qa-sort-explicit-relevance` |
| `120-qa-sort-legacy-ascending-relevance` | Exercises the qa sort legacy ascending relevance case. | `testdata_testfiles` | `--names qa-sort-legacy-ascending-relevance` |
| `121-qa-sort-date-to-relevance` | Exercises the qa sort date to relevance case. | `testdata_testfiles` | `--names qa-sort-date-to-relevance` |
| `122-qa-sort-date-directions` | Exercises the qa sort date directions case. | `testdata_testfiles` | `--names qa-sort-date-directions` |
| `123-qa-sort-file-size-directions` | Exercises the qa sort file size directions case. | `testdata_testfiles` | `--names qa-sort-file-size-directions` |
| `124-qa-sort-name-directions` | Exercises the qa sort name directions case. | `testdata_testfiles` | `--names qa-sort-name-directions` |
| `125-filter-filelocation-reopen` | Exercises the filter filelocation reopen case. | `testdata_shapes` | `--names filter-filelocation-reopen` |
| `126-search-filename-only-match` | Exercises the search filename only match case. | `testdata_testfiles` | `--names search-filename-only-match` |
| `127-filter-pane-filelocation-dataset-ticked` | Exercises the filter pane filelocation dataset ticked case. | `testdata_shapes` | `--names filter-pane-filelocation-dataset-ticked` |
| `128-search-filelocation-dataset-applied` | Exercises the search filelocation dataset applied case. | `testdata_shapes` | `--names search-filelocation-dataset-applied` |
| `129-search-filetype-chip` | Exercises the search filetype chip case. | `any` | `--names search-filetype-chip` |
| `130-search-filename-only-hit` | Exercises the search filename only hit case. | `testdata_filenames` | `--names search-filename-only-hit` |
| `131-search-filename-only-hit-900px` | Exercises the search filename only hit 900px case. | `testdata_filenames` | `--names search-filename-only-hit-900px` |
| `132-search-collections-filter-tree` | Exercises the search collections filter tree case. | none named | `--names search-collections-filter-tree` |
| `133-search-collections-filter-expanded` | Exercises the search collections filter expanded case. | none named | `--names search-collections-filter-expanded` |

## Document view

PDF, image, email, text, metadata, file locations, and entity cards.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `201-view-doc-pdf-entities` | Exercises the view doc pdf entities case. | `testdata_testfiles` | `--names view-doc-pdf-entities` |
| `202-view-doc-pdf-metadata` | Exercises the view doc pdf metadata case. | `testdata_testfiles` | `--names view-doc-pdf-metadata` |
| `203-view-doc-image` | Exercises the view doc image case. | `testdata_emails` | `--names view-doc-image` |
| `204-view-doc-email-metadata` | Exercises the view doc email metadata case. | `testdata_emails` | `--names view-doc-email-metadata` |
| `205-view-doc-email-without-body` | Exercises the view doc email without body case. | `testdata_emails` | `--names view-doc-email-without-body` |
| `206-view-doc-text` | Exercises the view doc text case. | `testdata_testfiles` | `--names view-doc-text` |
| `207-view-doc-docx-metadata` | Exercises the view doc docx metadata case. | `testdata_testfiles` | `--names view-doc-docx-metadata` |
| `208-view-doc-file-locations-source` | Exercises the view doc file locations source case. | `testdata_testfiles` | `--names view-doc-file-locations-source` |
| `209-view-doc-metadata-source` | Exercises the view doc metadata source case. | `testdata_testfiles` | `--names view-doc-metadata-source` |
| `210-view-doc-file-locations-multi` | Exercises the view doc file locations multi case. | `testdata_zips` | `--names view-doc-file-locations-multi` |
| `211-view-doc-stale-bookmark` | Exercises the view doc stale bookmark case. | none named | `--names view-doc-stale-bookmark` |
| `212-view-doc-three-tabs` | Exercises the view doc three tabs case. | `testdata_emails` | `--names view-doc-three-tabs` |
| `213-view-doc-file-locations-tab` | Exercises the view doc file locations tab case. | `testdata_emails` | `--names view-doc-file-locations-tab` |
| `214-view-doc-entity-card` | Exercises the view doc entity card case. | `testdata_testfiles` | `--names view-doc-entity-card` |
| `215-view-doc-entity-card-stale` | Exercises the view doc entity card stale case. | `testdata_testfiles` | `--names view-doc-entity-card-stale` |

## Storage and folder tree

Collection storage, archives, breadcrumbs, and landing pages.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `301-storage-collections` | Exercises the storage collections case. | none named | `--names storage-collections` |
| `302-storage-testfiles-root` | Exercises the storage testfiles root case. | `testdata_testfiles` | `--names storage-testfiles-root` |
| `303-storage-shapes-wide` | Exercises the storage shapes wide case. | `testdata_shapes` | `--names storage-shapes-wide` |
| `304-storage-shapes-deep` | Exercises the storage shapes deep case. | `testdata_shapes` | `--names storage-shapes-deep` |
| `305-storage-breadcrumb-popup` | Exercises the storage breadcrumb popup case. | `testdata_shapes` | `--names storage-breadcrumb-popup` |
| `306-storage-shapes-deep-600px` | Exercises the storage shapes deep 600px case. | `testdata_shapes` | `--names storage-shapes-deep-600px` |
| `307-storage-shapes-deepest` | Exercises the storage shapes deepest case. | `testdata_shapes` | `--names storage-shapes-deepest` |
| `308-storage-sidebar-remembered-width` | Exercises the storage sidebar remembered width case. | `testdata_shapes` | `--names storage-sidebar-remembered-width` |
| `309-storage-in-folder-search` | Exercises the storage in folder search case. | `testdata_shapes` | `--names storage-in-folder-search` |
| `310-storage-zip-location` | Exercises the storage zip location case. | `testdata_zips` | `--names storage-zip-location` |
| `311-storage-inside-container` | Exercises the storage inside container case. | `testdata_zips` | `--names storage-inside-container` |
| `312-qa-storage-archive-highlight` | Exercises the qa storage archive highlight case. | `testdata_zips` | `--names qa-storage-archive-highlight` |
| `313-qa-storage-leaf-dataset` | Exercises the qa storage leaf dataset case. | `testdata_leaf, testdata_shapes` | `--names qa-storage-leaf-dataset` |
| `314-qa-storage-cold-expansion` | Exercises the qa storage cold expansion case. | `testdata_zips, testdata_shapes` | `--names qa-storage-cold-expansion` |
| `315-qa-storage-warm-navigation` | Exercises the qa storage warm navigation case. | `testdata_zips` | `--names qa-storage-warm-navigation` |
| `316-qa-storage-back` | Exercises the qa storage back case. | `testdata_zips` | `--names qa-storage-back` |
| `317-storage-emails` | Exercises the storage emails case. | `testdata_emails` | `--names storage-emails` |
| `318-storage-email-preview` | Exercises the storage email preview case. | `testdata_emails` | `--names storage-email-preview` |
| `319-storage-container-by-url` | Exercises the storage container by url case. | `testdata_zips` | `--names storage-container-by-url` |
| `320-storage-tree-unified` | Exercises the storage tree unified case. | `testdata_shapes` | `--names storage-tree-unified` |
| `321-storage-tree-two-datasets` | Exercises the storage tree two datasets case. | `testdata_zips,testdata_emails` | `--names storage-tree-two-datasets` |
| `322-storage-tree-unified-600px` | Exercises the storage tree unified 600px case. | `testdata_shapes` | `--names storage-tree-unified-600px` |
| `323-storage-collection-landing` | Exercises the storage collection landing case. | none named | `--names storage-collection-landing` |
| `324-storage-collection-landing-other` | Exercises the storage collection landing other case. | none named | `--names storage-collection-landing-other` |
| `325-storage-dataset-landing` | Exercises the storage dataset landing case. | `testdata_zips` | `--names storage-dataset-landing` |
| `326-storage-collection-by-click` | Exercises the storage collection by click case. | `testdata_shapes` | `--names storage-collection-by-click` |

## Table viewer

Spreadsheet grids, column filters, and the table column dialog.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `401-view-doc-table-grid` | Exercises the view doc table grid case. | `testdata_excelsc` | `--names view-doc-table-grid` |
| `402-view-doc-table-sorted-blanks` | Exercises the view doc table sorted blanks case. | `testdata_excelsc` | `--names view-doc-table-sorted-blanks` |
| `403-view-doc-table-sheets` | Exercises the view doc table sheets case. | `testdata_excelsc` | `--names view-doc-table-sheets` |
| `404-view-doc-table-sorted` | Exercises the view doc table sorted case. | `testdata_excelsc` | `--names view-doc-table-sorted` |
| `405-view-doc-table-filter-popover` | Exercises the view doc table filter popover case. | `testdata_excelsc` | `--names view-doc-table-filter-popover` |
| `406-view-doc-table-truncated` | Exercises the view doc table truncated case. | `testdata_wide` | `--names view-doc-table-truncated` |
| `407-view-doc-table-metadata` | Exercises the view doc table metadata case. | `testdata_excelsc` | `--names view-doc-table-metadata` |
| `408-qa-table-modal-geometry` | Exercises the qa table modal geometry case. | `testdata_excelsc` | `--names qa-table-modal-geometry` |
| `409-qa-table-modal-backdrop` | Exercises the qa table modal backdrop case. | `testdata_excelsc` | `--names qa-table-modal-backdrop` |
| `410-qa-table-modal-exclusivity` | Exercises the qa table modal exclusivity case. | `testdata_excelsc` | `--names qa-table-modal-exclusivity` |
| `411-qa-table-modal-keyboard` | Exercises the qa table modal keyboard case. | `testdata_excelsc` | `--names qa-table-modal-keyboard` |
| `412-qa-table-modal-light-colors` | Exercises the qa table modal light colors case. | `testdata_excelsc` | `--names qa-table-modal-light-colors` |
| `413-qa-table-modal-dark-colors` | Exercises the qa table modal dark colors case. | `testdata_excelsc` | `--names qa-table-modal-dark-colors` |
| `414-qa-table-picker-visibility` | Exercises the qa table picker visibility case. | `testdata_excelsc` | `--names qa-table-picker-visibility` |
| `415-qa-table-data-sort-filter` | Exercises the qa table data sort filter case. | `testdata_manualqa` | `--names qa-table-data-sort-filter` |

## Chat

The chat page, conversation history, and a missing session.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `501-ai-chat` | Exercises the ai chat case. | none named | `--names ai-chat` |
| `502-ai-chat-history` | Exercises the ai chat history case. | none named | `--names ai-chat-history` |
| `503-ai-chat-session-missing` | Exercises the ai chat session missing case. | none named | `--names ai-chat-session-missing` |

## Admin

Admin dashboard, collections, users, groups, settings, metrics, and operations.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `601-admin-dashboard` | Exercises the admin dashboard case. | none named | `--names admin-dashboard` |
| `602-admin-collections` | Exercises the admin collections case. | none named | `--names admin-collections` |
| `603-admin-collection-processing` | Exercises the admin collection processing case. | none named | `--names admin-collection-processing` |
| `604-admin-users` | Exercises the admin users case. | none named | `--names admin-users` |
| `605-admin-user-detail` | Exercises the admin user detail case. | none named | `--names admin-user-detail` |
| `606-admin-groups` | Exercises the admin groups case. | none named | `--names admin-groups` |
| `607-admin-group-detail` | Exercises the admin group detail case. | none named | `--names admin-group-detail` |
| `608-admin-settings` | Exercises the admin settings case. | none named | `--names admin-settings` |
| `609-admin-metrics` | Exercises the admin metrics case. | none named | `--names admin-metrics` |
| `610-admin-ai-status` | Exercises the admin ai status case. | none named | `--names admin-ai-status` |
| `611-admin-llm` | Exercises the admin llm case. | none named | `--names admin-llm` |
| `612-admin-collection-detail` | Exercises the admin collection detail case. | none named | `--names admin-collection-detail` |
| `613-admin-dataset-detail` | Exercises the admin dataset detail case. | `testdata_testfiles` | `--names admin-dataset-detail` |
| `614-admin-operations` | Exercises the admin operations case. | none named | `--names admin-operations` |
| `615-admin-operations-state-errored` | Exercises the admin operations state errored case. | none named | `--names admin-operations-state-errored` |
| `616-admin-operations-errored-empty` | Exercises the admin operations errored empty case. | none named | `--names admin-operations-errored-empty` |
| `617-admin-operations-collection-testdata` | Exercises the admin operations collection testdata case. | none named | `--names admin-operations-collection-testdata` |
| `618-admin-dataset-rescan-dispatch` | Exercises the admin dataset rescan dispatch case. | `testdata_diskfiles` | `--names admin-dataset-rescan-dispatch` |
| `619-admin-operations-running` | Exercises the admin operations running case. | none named | `--names admin-operations-running` |
| `620-admin-operations-partial-failure` | Exercises the admin operations partial failure case. | none named | `--names admin-operations-partial-failure` |
| `621-admin-operations-destructive-confirm` | Exercises the admin operations destructive confirm case. | none named | `--names admin-operations-destructive-confirm` |
| `622-admin-operations-rerun` | Exercises the admin operations rerun case. | none named | `--names admin-operations-rerun` |
| `623-admin-collection-operations` | Exercises the admin collection operations case. | none named | `--names admin-collection-operations` |

## Manual QA procedures

Longer browser sequences that call a named procedure file.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `701-manual-shipping` | Exercises the manual shipping case. | none named | `--names manual-shipping` |
| `702-manual-mail-search` | Exercises the manual mail search case. | none named | `--names manual-mail-search` |
| `703-manual-folder-search` | Exercises the manual folder search case. | none named | `--names manual-folder-search` |
| `704-manual-sort-dates` | Exercises the manual sort dates case. | none named | `--names manual-sort-dates` |
| `705-manual-sort-size` | Exercises the manual sort size case. | none named | `--names manual-sort-size` |
| `706-manual-sort-name` | Exercises the manual sort name case. | none named | `--names manual-sort-name` |
| `707-manual-relevance` | Exercises the manual relevance case. | none named | `--names manual-relevance` |
| `708-manual-pdf` | Exercises the manual pdf case. | none named | `--names manual-pdf` |
| `709-manual-archive-viewer` | Exercises the manual archive viewer case. | none named | `--names manual-archive-viewer` |
| `710-manual-archive-storage` | Exercises the manual archive storage case. | none named | `--names manual-archive-storage` |
| `711-manual-table` | Exercises the manual table case. | none named | `--names manual-table` |
| `712-manual-entities` | Exercises the manual entities case. | none named | `--names manual-entities` |
| `713-manual-tree` | Exercises the manual tree case. | none named | `--names manual-tree` |
| `714-manual-size-filters` | Exercises the manual size filters case. | none named | `--names manual-size-filters` |
| `715-manual-type-filters` | Exercises the manual type filters case. | none named | `--names manual-type-filters` |
| `716-manual-dates` | Exercises the manual dates case. | none named | `--names manual-dates` |
| `717-manual-email-filters` | Exercises the manual email filters case. | none named | `--names manual-email-filters` |
| `718-manual-entity-filter` | Exercises the manual entity filter case. | none named | `--names manual-entity-filter` |
| `719-manual-email-viewer` | Exercises the manual email viewer case. | none named | `--names manual-email-viewer` |

## PDF source switch

Switching PDF sources in the full viewer and in the preview.

| slug | what it exercises | dataset | reproduce |
|---|---|---|---|
| `801-qa-pdf-full-source-switch` | Exercises the qa pdf full source switch case. | none named | `--names qa-pdf-full-source-switch` |
| `802-qa-pdf-full-delayed-source-switch` | Exercises the qa pdf full delayed source switch case. | none named | `--names qa-pdf-full-delayed-source-switch` |
| `803-qa-pdf-preview-source-switch` | Exercises the qa pdf preview source switch case. | none named | `--names qa-pdf-preview-source-switch` |

