# Administration routes manage stored data and operations.

[Admin pages](../../../website/frontend/src/pages/admin/) and [admin APIs](../../../website/backend/src/api/admin/) own these controls.
[The administration manual](../../user-manual/Admin_Manual.md) explains the procedures.

## Controls

| Route family | Controls | Constraint |
|---|---|---|
| Collections and datasets | Create, rename, inspect access, inspect processing, and dispatch supported actions. | A dataset belongs to its collection permanently. |
| Dataset creation | Pick a dataset mount and a folder directly beneath it. In a writable mount, name a new folder, which the server creates. In a writable mount, select Accept uploads. | The form takes no path. A read-only mount offers no new folder and no Accept uploads, and the server refuses both. With one mount the form shows no mount select. Accept uploads is disabled while another dataset of the collection accepts uploads. |
| Dataset upload setting | Turn Accept uploads on or off on the dataset page. | The checkbox shows for a disk dataset whose folder is beneath a writable mount, and for a dataset that accepts uploads. Turning it on is refused while another live dataset of the collection accepts uploads. Turning it off is always accepted. |
| Processing | Inspect five stage groups, errors, throughput, and task time. | Display groups are P0, P1, P2/P3, P4, and P6. |
| Operations | Filter states and collections, open details, repeat supported operations, and cancel active work. | Destructive actions require the displayed target confirmation. An `ingest_upload` operation shows like `add_dataset` and counts plans. It cannot be repeated, because its upload queue claims its batches. |
| Operation detail | Inspect counts, plans, events, and failure links. | Plans and events use separate 100-row pages. |
| Errors/Failures | Filter document errors and grouped operation failures. | Document errors and operation failure trees are separate records. |
| Users and groups | Inspect account origin, edit supported fields, and grant collection access. Set the Group admin and Uploader flags of a membership on the user page and on the group page. | The backend verifies administrator access. A change of one flag keeps the other flag. Adding an existing member keeps the stored membership. A membership from the login proxy starts with both flags clear and keeps them across logins. |
| Settings | Change runtime settings and inspect deployment configuration. | Deployment configuration is read-only. |
| LLM | Refresh the model catalog, inspect selected models, and run reports. | Reports run only when requested. |
| AI status and metrics | Inspect providers, active turns, queues, and datastore activity. | Configured and serving capabilities can differ. |
| Feedback | Search reports, open details, change read state, and archive reports. | Archiving preserves the independent read state. |

## States

| State | Display |
|---|---|
| Pending or queued operation | The operation waits for admission: a slot of its kind, or the end of a running operation of the same dataset or collection. The progress cell reads "waiting for a free slot or a free target". |
| Running operation | Progress uses the operation's available work unit. |
| Finished operation | The operation ended. Its document errors still require separate inspection. |
| Failed operation | The operation identifies its recorded failure and available detail. |
| Cancelled operation | The cancellation finalizer recorded termination. |
| Empty filtered list | The list states that the selected filter has no rows. |
| Request failure | The affected component displays the request error. |

## Constraints

Collection and dataset locks prevent conflicting dispatch according to the operation kind.
Admission also keeps two operations of overlapping targets from running together, whatever their kinds.
An older operation that waits for its own target does not take a slot from a newer operation of the same kind with a free target.
Deleting or purging a dataset stops its unfinished upload batches. Files already placed stay in the folder.
New uploads into the dataset are refused until that operation ends. Cancelling the deletion does not restore the stopped uploads.
Cancelling queued work requires the same finalizer as cancelling running work.
A progress denominator can remain unknown while new targets appear.
A completed plan can contain failed documents.
Provider changes use deployment configuration, while supported runtime settings take effect without deployment.

## Operation states distinguish waiting from completion.

[Operation workflows](../../../main_services/processing/tasks/P_ops/workflows.py) own the state transitions.
Cancellation uses its finalizer and retains completed work.
A repeated operation receives a new operation identifier.

```mermaid
stateDiagram-v2
    accTitle: Operation admission and terminal states
    accDescr: A pending operation queues or starts running. It finishes, fails, or is cancelled. Cancellation also applies before admission.
    [*] --> pending
    pending --> queued: Capacity unavailable
    pending --> running: Admitted
    queued --> running: Admitted
    running --> finished: Work completes
    pending --> errored: Start fails
    running --> errored: Work fails
    pending --> cancelled: Finalizer completes
    queued --> cancelled: Finalizer completes
    running --> cancelled: Finalizer completes
```
