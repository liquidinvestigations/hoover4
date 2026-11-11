# Replay the plan workflows.

The suite replays recorded histories of the plan workflows on the current workflow code.
The Temporal `Replayer` fails on a command that a history does not hold.
A passing case therefore shows that the current code gives the recorded commands.

Run it in the worker container:

```sh
docker exec hoover4-worker sh -lc 'cd /app && uv run pytest tests/replay -q'
```

It needs no running service.

## Fixtures

| file | holds |
|---|---|
| [fixtures/compose_histories.json.gz](fixtures/compose_histories.json.gz) | Two `ExecuteSinglePlan` and two `ProcessItemsBatched` histories of the local Compose stack, recorded before the host claim existed. |
| [fixtures/host_queue_histories.json.gz](fixtures/host_queue_histories.json.gz) | The histories that [generate_histories.py](generate_histories.py) writes. |

Each file maps a key to `workflow_id`, `workflow_type` and `history`.
The history is the JSON of `WorkflowHistory.to_json()`.

The generator runs the current code on a local Temporal development server, never on the queues of the stack.
Its activities return the results of the recorded Compose plan `compose-ExecuteSinglePlan-88` and its group.
It writes these scenarios:

| key prefix | history |
|---|---|
| `k3s-branch-` | The claim of the earlier `k3s` branch on the host `pod-a`. That branch had no patch marker, so the generator removes the marker from the plan history. |
| `current-shared-` | The current claim without `HOOVER4_HOST_QUEUE`. Every activity uses a shared queue. |
| `current-host-` | The current claim on the host `pod-a`. |
| `current-lost-host-` | The host `pod-a` never polls. The plan claims `pod-b` and runs there. |
| `current-cancelled-` | The plan is cancelled while its group runs on `pod-a`. The server terminates the group. |

Regenerate the file after a change to the plan workflows:

```sh
docker exec hoover4-worker sh -lc 'cd /app && uv run python tests/replay/generate_histories.py'
```

## Checks

- Each Compose history replays with the default history source.
- Each current history replays with either history source.
- Each `k3s` branch history replays with `HOOVER4_HISTORY_SOURCE=k3s-branch`.
- The `k3s` branch plan fails without that setting, and a Compose plan fails with it.
- Every prefix of a history that ends while an activity or a child runs replays. Such a prefix is the history that a restarted worker replays.
- Compose and current histories replay on one replayer.
- The generated histories hold the expected queues, claims, lost-host retry and cancellation.

Set `HOOVER4_REPLAY_HISTORIES` to a folder of captured histories to replay the histories of a deployment with [tests/unit/test_ocr_workflow_replay.py](../unit/test_ocr_workflow_replay.py).
