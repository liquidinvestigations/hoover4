---
name: writing-project-docs
description: Writes and repairs the prose that ships with the code, meaning a `Readme.md`, a module header, a docstring, a doc comment, a comment in a compose file, migration or shell script. Use whenever editing any of those, whenever asked to "document this", "update the readme", "add comments", "explain this in the docs", or when a change has made an existing comment or section untrue. Covers the register the repository writes in, the present-tense-truth rule and why a date or a plan reference is a dead link, keeping the lesson while dropping the anecdote, how small a documentation patch should be, and why a missing-documentation lint must never be bulk-filled.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

# Writing project documentation

Everything here obeys two rules. Every `Readme.md`, every `//!` `///` `#` `--` comment, every
docstring, and every comment in a compose file, `Dockerfile`, `.sql` migration or shell script
is covered. The first rule is the register the sentence is written in. The second is that the
sentence states what is true now. The rest of this page is a consequence of those two.

## The register

Write in **Simplified Technical English**, the controlled language defined by
**ASD-STE100**. One approved word per meaning, 20 words in an instruction, 25 in a
description, one instruction to a sentence, active voice, simple tenses, and no figures of
speech. Meet the plain-language standard **ISO 24495-1**, so a reader can find what they
need, understand it, and act on it.

Apply these while you write, and check the result before you save it:

- State the claim. If a sentence is arranged so its last few words land, rewrite it.
- No metaphor where a plain word exists. Say what depends on what, and what breaks
  without it. The banned list is in `AGENTS.md` and starts with load-bearing, seam,
  blast radius, guardrail, footgun and happy path.
- No antithesis used for emphasis, and no verbless sentence.
- No emphasis particles and no preambles. Delete "worth noting", "to be clear", "the whole
  point", "crucially" and the rest of that list.
- No em dash. Use a comma, a full stop, or brackets. At most one colon in a paragraph, and
  only to introduce a list or a literal. No semicolon in prose.
- One word for one act. Pick verify, or confirm, or check, and keep using it.
- Write less. Do not restate the section above, and do not add a closing line.

Code identifiers, error strings and quoted output keep their exact wording, even when they
contain a banned word. The domain nouns stay legal: harness, invariant, contract, idempotent,
barrier, heartbeat, lease, shard, fanout, denormalisation, sidecar. So does `fail loudly`,
`fail silently`, and a plain correction of fact such as "matches by column name, not
position".

`.agents/check-prose-style.py` reports what it can see, and a `PreToolUse` hook refuses an
edit that adds a banned phrase or an em dash. Neither tool sees a sentence that is merely
built to land, so read your own paragraph before you save it.

## The truth rule

**The tree documents what is true now.** `git log`, `git blame` and `git show` document when
it became true, and they do it correctly. Nothing in the tree competes with them.

Consequences, each of which is a real defect when violated:

- **No dates, no commit hashes, no history of the change.** Not "on <a date>", not "this
  session", not "previously", "used to be", "was renamed from", "moved here in", "now that X
  landed", "added later", "until X lands".
- **Never name the scratch folder.** Not `plans/`, not a document number, not a phase or part
  label invented there, not a paraphrase of one. That folder is gitignored and gets wiped, so
  every such reference is a dead link the moment it is written. (`P0`–`P6` are different,
  because those are the pipeline stages' real names in the code.)
- **Nothing aspirational.** No planned, deferred or parked work. If something is genuinely a
  stub, say it is a stub and what it does today.
- **Keep the lesson, drop the anecdote.** Hard-won knowledge about a past failure is the most
  valuable thing in these files. Write it as a standing property of the system and the
  failure it prevents:

> Not: "the loop that stalled for 26 minutes, until we moved the call to a thread pool"
> But: "a synchronous call on the event-loop thread stalls this activity indefinitely while
> heartbeats keep flowing, so it is never retried"

## Comments obey the same rules

A comment is documentation that happens to live in a source file.

1. **A comment earns its place by saying something the code cannot.** Say the unit, the
   invariant, the failure it guards, the reason the value is not the obvious one, or the trap
   that cost someone hours. If deleting it loses nothing, it was filler. `/// The foo field.`
   and `//! Admin collection detail page.` are filler.
2. **Never comment out code.** Delete it, because git has it. A commented-out line in a diff
   is always a mistake.
3. **No `TODO`, `FIXME` or `XXX`.** Do the thing or drop the line.
4. **Change the comment in the same patch that changes what it describes.** This is the rule
   this tree actually needs. A stale comment has cost more here than every superfluous one
   combined, because a reader treats a comment in this tree as fact.
5. **No target ratio.** Comment density is not a quality metric and is not measured here.
6. **No tag from a plan folder**, such as `D22`, `S13` or `R2`. `plans/` is gitignored, so the
   reference is unresolvable forever for anyone who clones this repository, and it was
   carrying nothing. In every case found here the sentence beside it already stated the fact.
   Write "the turn that killed chat with `agent stream broke`" instead of "the `D22` turn".
   `.agents/check-doc-ids.py` finds them.

`.agents/skills/reviewing-changes/scripts/check-diff-comments.sh` reports these shapes over a
diff in a fraction of a second. It informs and never gates, and it cannot see the largest
problem, which is a comment that is well written and no longer true.

## Patch size

**Fix the text your change made untrue. Leave the rest alone.** Do not rewrite untouched
sections wholesale, and do not "improve" prose you are not otherwise touching. A large
documentation diff hides the small true correction inside it.

Removing an outdated section is in scope. Reformatting a section that is still correct is
out of scope.

## Where a piece of prose belongs

| it describes | it goes in |
|---|---|
| this directory's contents and its local invariants | the `Readme.md` beside the code |
| how a subsystem is shaped, and why | `docs/architecture/` |
| a procedure a person will repeat | `docs/operations/` or `docs/development/` |
| a procedure an agent loads mid-task | a skill in `.agents/skills/` |
| what the product does, as agreed | `docs/technical-specification/` |
| a decision that keeps being re-opened | `docs/architecture/Settled_Decisions.md` |

## When a decision is settled, and where it goes

A decision earns a line in `Settled_Decisions.md` when **all three** are true. Two out of three
is not enough, and the page fills up with opinions.

1. **A person decided it**, rather than an agent inferring it from the code.
2. **It has been re-opened at least once**, or it reads like a defect to someone who does not
   know the reason. A decision nobody questions needs no defence.
3. **It is stable**, meaning nothing scheduled will change it. A decision waiting on work is a
   plan, and plans do not go in the tracked tree.

Write it as what is true now plus the reason, and never as the history of the argument. One
entry is two or three sentences. If it needs more, the thing being described is an architecture
and it belongs in its own page.

Every code directory has a `Readme.md`. Read it before changing the code around it, and
correct it as you go.

## Long documents

Anything over about a hundred lines opens with a table of contents, because the alternative
is that readers grep the file for its own headings.

## References

- `reference/lint-honesty.md`, on why a missing-documentation lint must never be bulk-filled,
  and what to report instead.
