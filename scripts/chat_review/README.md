# Review completed chat deliveries

This tool exports completed turns, requests model reviews, and writes local correction proposals.
Independent source-reviewed records determine delivery acceptance.
Model agreement alone cannot establish factual correctness.
The tool does not change production chat policies, transcripts, or workspace files.

## Run the commands

Run from the repository root in the worker environment with the current checkout mounted.
Use the worker's generated configuration for storage and model routes.
Keep output directories outside scanner input directories and public tracked files.
Each attempt requires a new directory.

```sh
python -m scripts.chat_review.run export \
  --owner USER --session SESSION --turn TURN \
  --requirements requirements.json --out local-runs/export

python -m scripts.chat_review.run review \
  --packet local-runs/export/packet.json --config review-config.json \
  --out local-runs/review

python -m scripts.chat_review.run replay \
  --packet local-runs/export/packet.json --review local-runs/review/result.json \
  --config review-config.json --out local-runs/replay

python -m scripts.chat_review.run grade \
  --packet local-runs/export/packet.json --delivery local-runs/replay/delivery.json \
  --reference reference.json --labels labels.json --out local-runs/grade

python -m scripts.chat_review.run compare \
  --schedule schedule.json --out local-runs/comparison
```

`--resume` returns a recorded result only when inputs, implementation, and saved artifacts match.
A retry requires a new directory and makes a new request.
Requests have no internal retry or redirect handling.
An interrupted request can have an unknown server outcome.

| Command | Exit zero means this condition holds. |
|---|---|
| `export` | The packet is structurally valid. Missing evidence is recorded. |
| `review` | The review schema and declared scope are complete. Findings can remain. |
| `replay` | A local proposal exists and fresh verification completes. Findings can remain. |
| `grade` | Independent records support the complete delivery. |
| `compare` | Every scheduled attempt has an interpretable terminal result. Quality failures can remain. |

Exit `1` means a grade found a defect.
Exit `2` means coverage or review remains incomplete.
Exit `3` means transport or execution failed.
Exit `4` means an input or configuration is invalid.
Exit `130` means the command was interrupted.

## Configure model requests

The configuration contains no credentials or service addresses.
The `model` value selects an existing configured route through [endpoint selection](../../main_services/processing/tasks/llm_endpoints.py).
Provider settings remain explicit.
A rejected response format returns an error and requires a new attempt with changed configuration.

```json
{
  "model": "configured-model-alias",
  "thinking": false,
  "max_tokens": 6000,
  "temperature": null,
  "response_format": "text",
  "connect_timeout": 10,
  "read_timeout": 240,
  "procedure": "fresh"
}
```

These timeout and token values are examples.
Select values for the experiment and record them before submission.
`temperature: null` omits that parameter.
The supported response formats are `text` and `json_object`.
Both require one bare JSON object in the response text.
Truncation, malformed JSON, unknown fields, and invalid spans leave the review incomplete.
Raw responses and request identities remain available beside validated results.

`fresh` reviews the complete delivery against captured evidence.
`history` also includes final visible messages and recorded history omissions.
`per_report` requires a `files` array with one delivered filename and excludes closing text.
A per-report review cannot establish complete-turn acceptance.
A changed version invalidates the earlier review receipt.

## Export pinned evidence

[The exporter](export.py) reads completed runs, published answer metadata, stored tool results, and exact delivered file versions.
It compares publication metadata with successful mutation receipts on the answer thread.
It preserves each original `(thread_id, idx)` identity.
It rechecks mutable records and session deletion before completing the export.
A disagreement or deletion race leaves export incomplete.

The packet retains original tool content when a reduced model view also exists.
It excludes stored hidden reasoning.
Partial messages remain identified but contribute no unfinished content to visible history requests.
Compaction summaries cannot replace original source bytes.

Captured responses retain typed source identities and extent metadata.
The exporter marks their document completeness as unestablished.
Citation reasons remain claims within metadata.
They do not become verified source facts.
Missing reads and unavailable image bytes remain explicit missing evidence.
Export does not retrieve additional documents or web pages.

`--requirements` supplies independently annotated requested outputs.
Each record names `id`, `source_turn`, `request_span`, and `description`.
`filename` is optional when the request does not specify one.
Offsets are Unicode code points in the named original request text.
Earlier request identities use the `thread:` prefix and appear in `request.prior_requests` with their full stored text.
Task-state amendments retain their stored text, source turn, and recorded limits.
Without this file, export records incomplete requested-output evidence.

## Validate findings and proposals

[Schema validation](schema.py) binds every review to a delivery digest and explicit target scope.
Each factual finding needs an exact quote, target file, evidence references, and proposed correction.
A unique quote resolves to character offsets automatically.
Repeated quotes require more context or a zero-based occurrence index.
Line endings remain unchanged.
Byte digests use the original UTF-8 representation.

A missing-output finding requires an explicit requirement identity.
Citation findings use the [shared handle parser](../../main_services/processing/tasks/P_workspace/references.py).
A resolved handle establishes citation identity only.

[Replay](replay.py) retains original workspace versions as provenance.
Changed files receive local revision identities.
New files require explicit missing-output requirements and have no workspace version.
Replay rejects omitted existing files, unrelated files, and changed source identities.
Correction explanations stay in a separate audit artifact.
A fresh verification request receives the corrected delivery without the earlier verdict or correction audit.

The computed delivery comparison records added, removed, changed, and unchanged files.
It records closing-answer changes separately.
Independent grading can compare action claims against those results.

## Author independent grading records

[The grader](grade.py) enumerates every nonblank line in every delivered file and closing answer.
Reference regions can merge adjacent lines or split compound assertions into separate claims.
Every region needs a classification and a coverage basis.
Unclassified text prevents acceptance, including ordinary prose without names or numbers.

Reference records bind the packet, delivery, source digests, and reference revision.
Each claim supplies its exact span, source references, support label, and reason.
Context spans retain subject headings and earlier qualifications.
Quoted-source regions require matching source quotations.
Structural regions need an explicit exclusion basis.

Supported labels apply to the named atomic claim only.
An uncertain assertion remains incomplete.
A supported, correctly scoped uncertainty statement can pass.
An established unsupported or contradicted claim fails the delivery.
Adjudication disagreement cannot remove an established reference defect.

Agent-authored references require a separate recorded source review before acceptance.
The approval binds both the complete unsigned reference and its source digests.
Author and reviewer identities are audit declarations.
They are not authenticated signatures.
Reference classifications still require source inspection.
This tool cannot certify arbitrary new prose automatically.

Use [the source-reviewed test fixtures](tests/conftest.py) for executable schema examples.
The reference and label objects never enter model requests.
A replay changes its delivery digest, so its references must be authored for the changed text.
A mismatched original reference cannot grade a correction.

## Compare fixed attempts

A schedule has `schema_version: 1` and an `attempts` array.
Each attempt supplies `id`, `pair`, `command`, and `inputs`.
The command is `review` or `replay`.
Inputs contain the same JSON objects supplied to that command's individual options.
Attempts with the same `pair` must use the same immutable packet.

Optional `grade_inputs` contains independent `reference` and `labels` objects.
The runner selects the original or proposed delivery for grading.
Unmatched reference digests produce an invalid grade.
Without grading inputs, the quality summary reports `ungraded`.
Execution results, quality verdicts, and call costs remain separate.
Each response retains provider token totals without invented reasoning-token counts.

## Verification commands

Run the deterministic suite in the worker image with the checkout mounted.

```sh
scripts/chat_review/test.sh
```

The tests cover source-scoped export, immutable versions, complete text coverage, malformed responses, replay isolation, and grading disagreements.
Live export needs existing completed chats and read access to storage.
Model checks need configured model routes.
Those checks establish separate claims from deterministic tests.
