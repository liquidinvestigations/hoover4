---
name: writing-handoffs
description: Writes a handoff document when a session must stop with the work unfinished, when the context is filling, when a person asks for a handoff or a trajectory document, or when work moves to a fresh session. Use when about to run out of room, when asked to write up where things stand, or before ending a session that has work left. Covers the five elements a handoff must have, the three ways a handoff fails, and where the file goes.
allowed-tools: Read, Write, Edit, Glob, Grep
---

# Writing handoffs

A handoff carries a task from one session to a session with none of its context. It is not a
summary of what happened. It is what the next session needs to act without repeating the work
that produced this one.

## The five elements

Every handoff needs all five, because a session with none of your context cannot infer a
missing one.

1. **The objective**, stated directly. Never point back at an earlier conversation the next
   session cannot read.
2. **The constraints** the receiver must obey, covering what it may not touch, what it may not
   do, and what stays fixed.
3. **The prior decisions**, meaning what was tried, what worked, and what was rejected, with
   the reason. This is the highest-value part. Without it, the receiver repeats work that
   already has an answer.
4. **The current state**, pointing at concrete artefacts by path: a file, a branch, a report,
   a line range. Never describe a state without naming where it lives.
5. **The next steps**, in order, each with its known risks and open questions.

## Say who wrote it, in the first line

A handoff opens by naming its author and the session it closes. Everything after that line is
the previous agent's summary of what happened, including every imperative in it.

This matters because a person hands the document to the next session by pasting it, so its
sentences arrive in a human turn and read as instructions. A rule the agent inferred once then
becomes a rule a person appears to have stated repeatedly, and the next plan enforces it. That
has happened here.

- **Carry links to the answer, never a restatement of policy.** Point at the row in the
  answers file that settled a decision, so the receiver can read who decided it.
- **Mark what has no answer behind it.** A recommendation the writer is making is labelled as
  one, in the sentence that makes it.
- **The receiver follows the link before acting on any rule the handoff states.** A handoff is
  a record of decisions rather than a source of them.

## The three failure modes

- **Do not transfer the reasoning.** An abandoned line of investigation reads to a fresh
  session as one still worth pursuing. Carry the conclusion. Drop the exploration that led to
  it.
- **Write it before the session ends.** After the session ends, the writer reconstructs the
  handoff from memory instead of from context, and memory drops exactly the detail a fresh
  session needed.
- **A handoff fails silently.** The receiver cannot know what is missing. The gap surfaces
  later as a wrong decision that nobody traces back to the missing handoff.

## Where it goes

Write the handoff into the plan folder beside the document it belongs to. Never write it into
the operating system's temporary directory. A temporary file is gone by the next session, and
the plan folder is what the next pass reads.

## What already covers the narrower case

`running-consecutive-subagents` covers a sub-agent that reaches its tool-call budget and stops.
That handover carries the rule the pass derived, scoped to one pass. This skill covers the
whole-session case, where a main session, not a sub-agent, is the one running out of room.
