# Closing a work folder

The scratch folder is wiped. Anything worth keeping has to be somewhere else **before** that
happens, written so it makes sense to someone who never saw the work.

## The lift

Walk the folder's reports and sort every finding into one of four destinations:

| finding | goes to |
|---|---|
| how a piece of code behaves now | the `Readme.md` beside that code |
| how a subsystem is shaped, and why | a page under `docs/architecture/` |
| a procedure someone will repeat | a page under `docs/operations/` or `docs/development/` |
| a trap that cost hours | the skill or rule that fires in the situation where it bites |

Everything else — what was tried, what order things happened in, who decided what — is
deliberately dropped. `git log` and `git blame` already hold it, and they hold it correctly.

## Rewriting a finding for the tree

A report says *what happened*. The tree says *what is true*. The transform is mechanical:

> Report: "The loop stalled for 26 minutes because a synchronous call ran on the event-loop
> thread; we moved it to a thread pool in the third attempt."
>
> Tree: "A synchronous call on the event-loop thread stalls this activity indefinitely while
> heartbeats keep flowing, so it is never retried."

No date, no attempt count, no plan reference. The standing property, and the failure it
prevents.

## Then archive

Move the folder to `plans/old/<DDMMYYYY>/`. The date lives in the archive directory's name —
never in a document's filename and never in the tree.

## The check

Before archiving, search the tracked tree for references to the folder you are about to
retire: its path, its number, and any phase or part label it invented. Every hit is a link
that is about to break.
