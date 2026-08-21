# Documentation standards

How prose is written in this repository, and why. Applies to every `Readme.md`, every doc
comment and inline comment in every language, and to the pages in this tree.

The procedural half — what to do while editing a file — is
`.agents/skills/writing-project-docs/`.

## Contents

- [The rule](#the-rule)
- [Keep the lesson, drop the anecdote](#keep-the-lesson-drop-the-anecdote)
- [Where a piece of prose belongs](#where-a-piece-of-prose-belongs)
- [Patch size](#patch-size)
- [Comments](#comments)
- [What is measured, and what is not](#what-is-measured-and-what-is-not)
- [Doc comments and lints](#doc-comments-and-lints)
- [Long documents](#long-documents)

## The rule

**The tree documents what is true now.** Version control documents when it became true, and
does it correctly. Nothing written here competes with that.

Four consequences, each a real defect when violated:

- **No dates, no commit hashes, no history of the change.** Not "on such a date", not "this
  session", not "previously", "used to be", "was renamed from", "moved here in", "now that X
  landed", "until X lands".
- **Never name the scratch folder**, or a document inside it, or a phase or part label
  invented there, or a paraphrase of one. That folder is gitignored and is wiped when the
  work it belongs to finishes, so every such reference is a dead link the moment it is
  written. (`P0`–`P6` are different: those are the pipeline stages' real names in the code.)
- **Nothing aspirational.** No planned, deferred or parked work. A genuine stub says it is a
  stub and what it does today, not which future work will fill it in.
- **No private infrastructure detail.** This tree is public. Hostnames, addresses, ports that
  identify a real host, credentials and descriptions of an authentication boundary live in
  `INFRASTRUCTURE_INVENTORY.md` at the repository root, which is local and gitignored. Pages
  that need them name that path.

## Keep the lesson, drop the anecdote

Hard-won knowledge about a past failure is the most valuable thing in these files — and it is
also where the history rule is hardest to hold. The transform is mechanical: write the
standing property of the system and the failure it prevents, with no date and no story.

> Not: "the loop that stalled for 26 minutes, until we moved the call to a thread pool"
>
> But: "a synchronous call on the event-loop thread stalls this activity indefinitely while
> heartbeats keep flowing, so it is never retried"

The second is shorter, is still true next year, and tells a reader what to do.

## Where a piece of prose belongs

| it describes | it goes in |
|---|---|
| this directory's contents and its local invariants | the `Readme.md` beside the code |
| how a subsystem is shaped, and why | `docs/architecture/` |
| a procedure a person will repeat | `docs/operations/` or `docs/development/` |
| a procedure an agent loads mid-task | a skill in `.agents/skills/` |
| an invariant that applies while editing a kind of file | a rule in `.agents/rules/` |
| what the product does, as agreed | `docs/technical-specification/` |

**Every code directory has a `Readme.md`.** Read it before changing the code around it, and
correct it as you go.

The split between a `docs/` page and a skill is not duplication: the page is what a person
reads before there is a task, and the skill is what an agent loads in the middle of one. The
same knowledge appears in both shapes on purpose, and each is written for its reader.

## Patch size

**Fix the text your change made untrue. Leave the rest alone.**

Removing an outdated section is in scope. Rewriting a section that is still correct is not —
a large documentation diff hides the small true correction inside it, and the next reviewer
cannot tell which lines were the point.

## Comments

A comment is documentation that happens to live in a source file, so the rule above applies
unchanged. Six more that are specific to source:

1. **A comment earns its place by saying something the code cannot** — the unit, the
   invariant, the failure it guards, the reason the value is not the obvious one, the trap
   that cost someone hours. If deleting it loses nothing, it was filler. A header that
   restates the file's own name is filler.
2. **Never comment out code.** Delete it; version control has it. A commented-out line in a
   diff is always a mistake.
3. **A comment states what is true now.** No dates, no "used to be", no "until this existed".
4. **Nothing aspirational, and no `TODO`.** Work you intend to do belongs somewhere it will
   be seen, which a comment is not.
5. **Never name the scratch folder or a plan label.** Words like "phase" describing the
   code's *own* stages are fine and common — the test is whether a reader with only the
   repository can tell what the word refers to.
6. **When you change what a comment describes, change the comment in the same patch.** This
   is the rule this tree actually needs. A stale comment has cost more here than every
   superfluous one combined, because these comments are load-bearing enough that a false one
   is a confident lie rather than noise.

## What is measured, and what is not

**Comment density is not a quality metric and is not measured here.** The literature that
measures it says so too: comments can raise the ratio with no effect on readability, which is
what makes the metric invalid, and the useful replacement is classifying comments by kind
rather than counting them.

The one number worth watching is **commented-out code**, because it is the only shape a tool
can judge unambiguously, and this tree carries almost none.

`.agents/skills/reviewing-changes/scripts/check-diff-comments.sh` reports five shapes over a
diff in a fraction of a second: commented-out code, plan or phase references, dates used as
history, aspirational markers, and narration of the change. It notes when a patch is more
than forty per cent comment — as a prompt to read it, never as a failure.

**It never gates a commit, and it cannot see the biggest problem in this area**: a comment
that is well written and no longer true. Nothing automatic can.

## Doc comments and lints

A missing-documentation lint measures **presence**, not content, and that is the whole
problem with it. Bulk-filling one produces a file of doc comments that restate their
identifiers: the lint now reports zero while the code is still undocumented, grep is
defeated, and every future reader pays the context to skim past it.

The bar for a doc comment is that it adds something the identifier and its type do not
already say. If there is nothing to add, **leave the item undocumented and report that the
lint cannot be satisfied honestly for those items.** That is a real answer; generated filler
is a way of hiding the question.

The one lint worth enabling is the one that finds commented-out code. No linter can judge
whether a comment says something the code cannot, and none can detect a comment that has gone
stale — say that plainly rather than shopping for a tool that claims otherwise.

## Long documents

Anything over about a hundred lines opens with a table of contents. The alternative is that
readers grep the file for its own headings, which is what happened to the document that
became four of the pages in this tree.
