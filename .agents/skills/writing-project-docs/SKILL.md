---
name: writing-project-docs
description: Writes and repairs the prose that ships with the code — a `Readme.md`, a module header, a docstring, a doc comment, a comment in a compose file, migration or shell script. Use whenever editing any of those, whenever asked to "document this", "update the readme", "add comments", "explain this in the docs", or when a change has made an existing comment or section untrue. Covers the present-tense-truth rule and why a date or a plan reference is a dead link, keeping the lesson while dropping the anecdote, how small a documentation patch should be, and why a missing-documentation lint must never be bulk-filled.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Writing project documentation

Everything here — every `Readme.md`, every `//!` `///` `#` `--` comment, every docstring,
every comment in a compose file, `Dockerfile`, `.sql` migration or shell script — obeys one
rule, and the rest are consequences of it.

## The rule

**The tree documents what is true now.** `git log`, `git blame` and `git show` document when
it became true, and they do it correctly. Nothing in the tree competes with them.

Consequences, each of which is a real defect when violated:

- **No dates, no commit hashes, no history of the change.** Not "on 2026-08-06", not "this
  session", not "previously", "used to be", "was renamed from", "moved here in", "now that X
  landed", "added later", "until X lands".
- **Never name the scratch folder.** Not `plans/`, not a document number, not a phase or part
  label invented there, not a paraphrase of one. That folder is gitignored and gets wiped, so
  every such reference is a dead link the moment it is written. (`P0`–`P6` are different:
  those are the pipeline stages' real names in the code.)
- **Nothing aspirational.** No planned, deferred or parked work. If something is genuinely a
  stub, say it is a stub and what it does today.
- **Keep the lesson, drop the anecdote.** Hard-won knowledge about a past failure is the most
  valuable thing in these files. Write it as a standing property of the system and the
  failure it prevents:

> Not: "the loop that stalled for 26 minutes on 2026-08-06"
> But: "a synchronous call on the event-loop thread stalls this activity indefinitely while
> heartbeats keep flowing, so it is never retried"

## Comments obey the same rule

A comment is documentation that happens to live in a source file.

1. **A comment earns its place by saying something the code cannot** — the unit, the
   invariant, the failure it guards, the reason the value is not the obvious one, the trap
   that cost someone hours. If deleting it loses nothing, it was filler. `/// The foo field.`
   and `//! Admin collection detail page.` are filler.
2. **Never comment out code.** Delete it; git has it. A commented-out line in a diff is
   always a mistake.
3. **No `TODO`, `FIXME` or `XXX`.** Do the thing or drop the line.
4. **Change the comment in the same patch that changes what it describes.** This is the rule
   this tree actually needs: a stale comment has cost more here than every superfluous one
   combined, because these comments are load-bearing enough that a false one is a confident
   lie rather than noise.
5. **No target ratio.** Comment density is not a quality metric and is not measured here.

`.agents/skills/reviewing-changes/scripts/check-diff-comments.sh` reports these shapes over a
diff in a fraction of a second. It informs; it never gates, and it cannot see the biggest
problem — a comment that is well written and no longer true.

## Patch size

**Fix the text your change made untrue. Leave the rest alone.** Do not rewrite untouched
sections wholesale, and do not "improve" prose you are not otherwise touching — a large
documentation diff hides the small true correction inside it.

Removing an outdated section is in scope. Reformatting a section that is still correct is
not.

## Where a piece of prose belongs

| it describes | it goes in |
|---|---|
| this directory's contents and its local invariants | the `Readme.md` beside the code |
| how a subsystem is shaped, and why | `docs/architecture/` |
| a procedure a person will repeat | `docs/operations/` or `docs/development/` |
| a procedure an agent loads mid-task | a skill in `.agents/skills/` |
| what the product does, as agreed | `docs/technical-specification/` |

Every code directory has a `Readme.md`. Read it before changing the code around it, and
correct it as you go.

## Long documents

Anything over about a hundred lines opens with a table of contents, because the alternative
is that readers grep the file for its own headings.

## References

- `reference/lint-honesty.md` — why a missing-documentation lint must never be bulk-filled,
  and what to report instead.
