---
name: planning-work
description: Sets up and runs a multi-stage piece of work the way this repository does it — a numbered work folder, the request captured verbatim, a research stage, a plan, then paired prompt and report files per pass, a coordinator log, and a final report. Use when asked to "write a plan", "plan this out", "scope it", "spec this", "start an epic", "investigate before building", "write a work package", "archive this", or when a task is large enough that one pass cannot finish it. Covers how a stage is sized, what a prompt file must contain, why artefacts fan out into a folder beside the document, and the rule that nothing in the tracked tree may ever cite the scratch folder.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Planning work

Work larger than one sitting is run as a folder of documents, not as a conversation. The
folder is the memory: a later pass reads it instead of re-deriving what was already decided.

## Where it lives, and the one hard rule about it

Working documents go in `plans/<n>-<slug>/` at the repo root. **`plans/` is gitignored
scratch and is wiped when the work finishes.** Everything follows from that:

- **No tracked file may ever cite it** — not by path, not by document number, not by a phase
  or part label invented inside it, not by paraphrase (`the design doc`, `the epic`,
  `the part-6 spike`). Every such reference is a dead link the moment it is written.
- Knowledge that must survive the wipe is **lifted** into the `Readme.md` beside the code, or
  into `docs/`, as a present-tense statement about how the system works. Do that as the work
  lands, not afterwards — afterwards never comes.
- Archive a finished folder by moving it under `plans/old/<DDMMYYYY>/`. **Never delete one** —
  `plans/` is gitignored, so an archived folder exists only on this disk.
- Two standing files sit at the top of `plans/` and outlive every folder: **`TODO.md`** for
  work that was wanted and not built, and **`DEFECTS.md`** for defects and limitations awaiting
  re-verification before they move into `docs/development/`. A pass ends by appending to them.
  Without somewhere for unbuilt intent and open defects to go, a folder can never be archived.

## The file sequence

Numbered so the reading order is the order they were written.

| file | holds |
|---|---|
| `0-prompt.md` | the request **verbatim**, unedited. It is the only record of what was actually asked |
| `1-research-report.md` | what is true today: the code as it is, measured, with file paths |
| `2-scope-and-cuts.md` | what lands, what does not, and the reason for each cut |
| `N-prompt-NN-<pass>.md` | the work package for one pass |
| `N-report-NN-<pass>.md` | that pass's report, written by whoever ran it |
| `N-coordinator-log.md` | decisions taken mid-flight, in the order they were taken |
| `N-final-report.md` | what landed, what did not, and what the next session needs |

Prompt and report are **paired and adjacent**: a prompt with no report beside it is a pass
that did not finish, and that is visible at a glance from the directory listing.

## Short tags, and the `## Key` table

A scope table and a results table only line up if the items have short names, so
letter-and-number tags — `M3`, `S13`, `X7`, `Q1` — are the right tool **inside one plan
folder** and nowhere else. Measured across this repository's plans, a quarter of tag
citations could not be resolved in the document that made them, and more than half the tags
meant two different things in two different files. That is what the rules below prevent.

- **A tag never leaves the folder that defined it.** Referring to another pass's item means
  **naming it and linking to it**. The same three characters are a scope item in one folder
  and a defect in another, and nothing in a bare citation says which.
- **A document that uses tags opens with a `## Key` table** — every tag it mentions, what it
  is, and a link to where it is defined — and expands each at its **first mention** in the
  body. After that the bare tag is fine, exactly as an acronym works.
- **If the document links into an earlier pass**, the Key table also decodes the tags a
  reader will meet on the other side of that link. A decoder that is not exhaustive for what
  the document links to is worse than none.
- **Worded references are tags.** "Phase 1", "Chapter 3", "Workstream A" index a structure
  the reader cannot see just as much as `X3` does. Same rule.
- **Never in a tracked file**, which includes `docs/`, `.agents/`, a `Readme.md` beside code,
  and **a source comment**. `plans/` is gitignored, so a tag cited from shipped code is
  unresolvable forever for anyone who clones the repository. State the fact instead — in
  practice the sentence beside the tag already says it.

```
.agents/check-doc-ids.py [path ...]     # names every unresolvable tag
```

Run it over the folder before calling a document finished. It is not wired into a hook: the
archived folders under `plans/old/` predate the rule and would fail it forever.

## Fanning out artefacts

Complex work produces more than prose — screenshots, extracted datasets, scratch scripts,
test output. Those go in a folder **beside** the document that discusses them, named for it,
and the document links to them. This is the expected pattern, not an exception: a finding
whose evidence is only in a scrollback is a finding nobody can check.

## Sizing a stage

The unit is **the smallest piece of work that carries its own verification cycle and is
worth a fresh reviewer's attention.** Not a checkbox, and not a whole feature.

Two failure shapes to avoid:

- **A stage with no check of its own.** If nothing can be run at the end of it, it is half a
  stage, and its report will be a claim rather than evidence.
- **A stage that spans two verification cycles.** It will be reported as done when only the
  first is green.

## What a prompt file must contain

A pass is only as good as its work package. Every one of these, or the pass reconstructs it
badly from context it does not have:

1. **Role and scope** — what this pass owns, and what it must not touch.
2. **What to read first**, by path, including the decisions that are already settled and are
   not to be re-opened.
3. **What is true now**, where the tree has moved since the research was written.
4. **The deliverable** — the exact output path and its required sections.
5. **The checks to run before finishing**, named as commands.
6. **The prohibitions**, including the standing ones that are easy to violate under pressure.

## Closing a stage

Before a stage is called finished:

- Every check named in its prompt has been run in that session and its output read —
  `verifying-before-claiming`.
- A capability that was added, removed or re-scoped has had its row in
  `docs/technical-specification/` edited **in the same patch** as the code.
- Documentation beside the changed code is true again — `writing-project-docs`.
- The report says plainly what was not done and why. A check that failed and was shipped
  anyway is stated as such; an honest gap is worth more than a clean-looking summary.

## References

- `reference/prompt-template.md` — the skeleton of a work package, with the sections above.
- `reference/archiving.md` — closing a folder, and what gets lifted into the tree before the
  scratch is wiped.
