---
name: processing-versions
description: How a change to stored pipeline output reaches the datasets that already hold the old output.
paths: main_services/processing/tasks/**
---

# Changing the output of a stage

A change that makes a stage store different output for the same input changes existing
datasets too. The datasets keep the old output until a processing update rewrites it. Raise
the version, and also make an update step select, rewrite and verify the old output.

## Find the version.

[tasks/stage_versions.py](../../main_services/processing/tasks/stage_versions.py) names each canonical stage and its version.
Some versions are older markers that the writer stores with its output, for example
`READER_VERSION` and `OCR_PAGE_RULE_VERSION`. Raise the marker, and `STAGE_VERSIONS` reads it.
A new stored error name needs its entry in `canonical_stage`, or its retries go to no stage.

## Make the old output selectable.

A version is in the fingerprint of every step that lists the stage in `stages`. A changed
fingerprint makes the coordinator count the step again. The count changes only when the
selector can find the old output.

- When the output stores its version, the selector selects rows with an older version.
- When the output stores no version, add a version column with a new migration. Or select
  every item of the stage when the applied version of the step is older, as
  `select_folder_counts` does.
- When no selector reads the stage, the failed files step retries each file that failed at
  the stage once. That is the only effect of the version change. Existing successful output
  stays unchanged.

## Rewrite and verify.

Give the step its four parts in [tasks/P_admin/updates/](../../main_services/processing/tasks/P_admin/updates).

1. The selector in `selectors.py` counts the files with old output. Keep it bounded, and keep
   file identities out of Temporal payloads.
2. The invalidation removes the old output that the new run does not replace. A text
   writer goes through `insert_text_pages`, which removes the page identities absent from
   the new list.
3. The adapter in `workflows.py` runs the existing stage workflows on the selected files,
   then the stages that read the output: entities, embedding and indexing.
4. The settlement in `_settle` reads the stored output again and fails while old output
   remains. A successful activity return alone does not prove the output exists.

Raise the `version` of the step itself when its selector, work or settlement changes.

## Verify on the local stack.

- Run the unit tests of the selector and the settlement rule.
- Before the change, record the step count and a sample of the stored output.
- Deploy, and confirm that the step waits with the expected count.
- Run the update. Confirm that the sample output changed, that the count is 0, and that the
  applied row holds the new fingerprint.
- Restart the worker without a change. Confirm that no new update operation starts.

Update the step explanation, the feature row and the Readme beside the stage in the same patch.
