---
name: running-unattended
description: Runs a whole plan folder end to end with nobody watching, overnight or headless. Use when a prompt says unattended, headless, overnight, autonomous, "do not stop", "keep going until everything is attempted", or when a person hands over a plan and leaves. Covers the three rules an unattended run suspends and how it pays for them, the open-questions file that replaces the asking tool, the timebox and the one extension pass, what to do when context fills instead of ending the session, and the rules that keep their full force with nobody watching.
allowed-tools: Task, Read, Write, Edit, Glob, Grep, Bash
---

# Running unattended

An unattended run is one organizer session that takes a finished plan folder and attempts every
item in it with nobody available to answer. It ends when every item has been attempted, and at
no other point.

**This mode is entered only from a written instruction that names it.** A prompt file, or a
person saying so in the conversation. It is never entered because the work looks long, because a
person went quiet, or because a previous session was unattended. An agent that puts itself in
this mode has removed the person from decisions the person never delegated.

## The three rules it suspends, and what it pays instead

Each of these carries the condition "unless otherwise stated, for example an unattended pass" in
the document that states it. Read that document, not this summary, before relying on the
suspension.

| suspended | where it is stated | what replaces it |
|---|---|---|
| ask the frontier through the asking tool | `AGENTS.md`, "An assumption written into a deliverable"; `planning-work`, the question round | write the question and the choice into `OPEN_QUESTIONS.md`, and carry on |
| a scope change needs a question round first | `AGENTS.md`, "The organizer does not change the scope"; `planning-work`, "A scope change re-opens the round" | record the change, the reason and how to undo it in `OPEN_QUESTIONS.md`, then implement it |
| stop and ask on what the intent does not settle | `running-consecutive-subagents`, "Resolving a conflict" | choose the reading that keeps the plan's checks runnable, record both readings, carry on |

**The payment is `OPEN_QUESTIONS.md`.** It sits beside the plan folder's `TODO.md` and it is the
only reason the suspension is acceptable. A run that suspends the asking rule and writes nothing
down has not deferred the questions. It has deleted them.

## OPEN_QUESTIONS.md

One file per plan folder, appended to as the run goes, never rewritten at the end from memory.
Each entry carries five things.

1. **The question**, written out in full, the way it would have been asked.
2. **What was chosen**, and the pass it landed in.
3. **Why that choice**, in one or two sentences, naming what it kept working.
4. **How to undo it**, as a file path or a command, so reversing it is cheap.
5. **Whether the run is confident.** Two values are enough: `provisional`, meaning a person
   should look, and `settled by evidence`, meaning a check proved it.

A decision recorded here is provisional until a person reads it. Anything built on top of a
provisional decision is provisional too, and the entry says which later work depends on it.

## The timebox, and the one extension

**Each pass gets one timebox, named in the prompt.** A pass that reaches it stops working and
hands over, exactly as it would on a tool-call budget. `writing-handoffs` carries what the
handover has to contain.

**The handover starts one extension pass, and an extension pass is never extended again.** Two
invocations per item is the limit. What the extension does not finish goes into
`OPEN_QUESTIONS.md` as a summary and into the plan folder's `TODO.md` as unchecked items, and
the run moves to the next item.

That limit exists because an agent cannot measure its own elapsed time and always overestimates
it. Passes reporting they had "roughly doubled" a one-hour box had used twenty-four minutes of
it. A timebox is therefore a budget of effort and attention rather than a clock, and the wall
clock comes from outside the agent. Without a hard cap on extensions, one item absorbs the
night.

## Not stopping

**The run ends when every item has been attempted.** These are not endings.

- **A question with no answer.** Choose, record it in `OPEN_QUESTIONS.md`, carry on.
- **A blocked item.** Attempt it, record what blocked it and how far it got, carry on.
- **A pass that fails its checks.** Record the failure with its output, mark the item unchecked,
  carry on. A failing check is a result.
- **The organizer's own context filling.** Write the handoff into the plan folder and continue
  from it. Running out of room is a handover, and a handover is not an ending.
- **A sub-agent that stops, errors or returns nothing.** Read what it left on disk, and either
  run the extension pass or record the gap and carry on.
- **A prohibition that would refuse the work.** The item is attempted up to the prohibition,
  and what the prohibition refused is recorded. The prohibition holds.

**One thing does end a run before the items do**, and it is an action outside the written scope
that cannot be undone. Reaching for a remote, a production host, or a destructive command that
the prompt did not name. Stop, record it, and leave the rest of the run for a person.

## What keeps its full force with nobody watching

Suspending three rules does not suspend the rest, and an unattended run is where the rest matter
most, because nothing else is reading.

- **Evidence before claims.** A check that did not run in this session did not pass.
  `verifying-before-claiming` is unchanged. An unattended run is judged on its records, and a
  record of a check that never ran makes the whole run worthless.
- **No private infrastructure detail in a tracked file.** No hostname, address, port identifying
  a real host, or credential.
- **A commit message is one lowercase line under about 50 characters**, with no body and no
  trailer, exactly as always.
- **Push only what the prompt named.** An unattended run that reaches a remote nobody watched it
  reach is the failure this mode is most likely to produce. If the prompt says local only, every
  repository the run touches is committed and none is pushed.
- **Sub-agents run one at a time, waited on**, each with a written work package.
  `running-consecutive-subagents` is unchanged.
- **Documentation states what is true now**, and the specification row moves in the same patch
  as the code.
- **Run no git write command while a pass is live.** One tree means one index.

## How the run reports

Three files, updated as work lands rather than at the end.

- The plan folder's `TODO.md`, ticked item by item.
- `OPEN_QUESTIONS.md`, appended to as decisions are taken.
- The organizer log, carrying decisions in the order they were taken.

Then a final report that restates the plan's estimate table with an actuals column, records the
forecast pass count against the actual pass count, and lists every item that was attempted and
did not land. `planning-work` carries the shape.

**Say what was attempted and did not work, before saying what worked.** A run nobody watched is
read for its failures first, because those are what the next session has to act on.

## The three ways an unattended run fails

- **It stops.** Half the items are untouched and the record does not say why, so the next
  session cannot tell a blocked item from an unreached one.
- **It decides silently.** Choices were made, the work was built on them, and
  `OPEN_QUESTIONS.md` is empty or written at the end from memory. Nothing can be reviewed
  because nothing was recorded when it happened.
- **It reports success it did not measure.** With nobody watching, an unverified claim survives
  until someone acts on it. This is the one failure the mode makes more likely and the one it
  can least afford.
