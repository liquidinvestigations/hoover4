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
| **work that was wanted and not built** | **`plans/TODO.md`**, one standing file, features as sentences |
| **a defect or limitation still true today** | **`plans/DEFECTS.md`**, then `docs/development/Known_Defects.md` once re-verified |

Everything else (what was tried, what order things happened in, who decided what) is
deliberately dropped. `git log` and `git blame` already hold it, and they hold it correctly.

**The two standing files are the reason a folder can be archived at all.** A pass always ends
with unbuilt intent and unfixed defects; without somewhere for them to go, archiving either
loses them or is never done. They are single files at the top of `plans/`, they are appended to
rather than recreated, and neither is numbered. The numbering is what made two folders' defect
lists collide.

**A defect goes to `plans/DEFECTS.md` first, not straight into the tree.** A finding lifted
from a report is a claim, and later work often fixed it incidentally. Re-verify against the
running stack, delete what is fixed, and only then write the survivors into
`docs/development/Known_Defects.md` as present-tense truth. Say plainly, at the top of the
scratch file, that it is unverified.

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

Move the folder to `plans/old/<DDMMYYYY>/`. The date lives in the archive directory's name,
never in a document's filename and never in the tree.

## A folder that is staying needs the one that is going

The tracked tree is not the only thing that points at a plan folder. **A live plan folder
routinely depends on an archived one**, for a specification it did not restate, a decision it
cites, a scope table it continues. Archiving under it leaves it naming work that no longer
exists anywhere.

Copy what it depends on **into** it, in an `inherited/` subfolder, verbatim, and repoint its
links there. Verbatim rather than summarised: a specification is the thing being preserved, and
a paraphrase of a design is a new design nobody reviewed. Those copies are transcribed, not
authored. Leave the old tags in them and let the tag checker skip the folder.

Then write **one prose document** in the live folder describing that inherited work with no
tags at all, so the folder can be read without opening the copies. The copies are the record;
the prose is the thing a person actually reads.

## The check

Before archiving, search for every reference to the folder you are about to retire (its path,
its number, and any phase or part label it invented) in **three** places:

1. the tracked tree, including source comments;
2. **every other plan folder that is staying**;
3. the two standing files, `plans/TODO.md` and `plans/DEFECTS.md`.

Every hit is a link that is about to break. `.agents/check-doc-ids.py` finds the tag-shaped
ones; the rest is a scoped grep.

Then verify the folders that are staying still stand alone: run the checker over each, and
confirm every relative link in them resolves.

## When to do this

At the end of a sprint large enough that its folders are no longer being read, which in
practice means when a new pass starts and nobody has opened the last one in a week. Doing it
per-folder as each finishes is better than a periodic sweep, because the lift is accurate while
the work is fresh and guesswork afterwards.

A sweep across several folders at once is a different job and costs more than it looks: the
folders will have invented colliding tags, their defect lists will overlap, and deciding what
is still true takes longer than writing it did.

**Never delete.** `plans/` is gitignored, so an archived folder exists only on this disk and is
not recoverable from git. Moving is safe; deleting is not.
