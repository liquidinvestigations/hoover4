# Work-package skeleton

Copy the headings, fill every one. A section left empty is a section the pass will invent for
itself, badly.

```markdown
# <id>: <one line naming the deliverable>

You are agent `<id>`. **Your prompt is this file. Your deliverable is `<exact path>`.**

Written against commit `<short sha>`. Tool-call budget: `<n>`.

## Key
<every short tag this prompt uses: the tag, what it is, and a link to where it is defined>
<plus the tags the reader will meet on the other side of any link this prompt makes>
<omit the section only if the prompt uses no tags at all>

## 1. Read before you start
<paths, in reading order, each with one line saying why>
<the settled decisions, marked binding and not to be re-opened>

## 2. What lands
<the enumerated deliverables, and where each one goes>
<per item, the answer that authorises it, linked to the row in the answers file>
<what is a draft rather than gospel, and the instruction to fix it and say so>

## 3. What is true now
<every place the tree has moved since the research was written>
<what exists and must be documented as existing>
<what is deliberately not built and must not be described as existing or as coming>

## 4. What must not happen
<the standing prohibitions, restated because they are easiest to violate under pressure>
<what would be unrecoverable, such as anything published, pushed, or deleted>

### Technical implementation
<for a pass that changes code, follow technical-pass-design.md beside this template>
<name the files and symbols this pass owns, and the shared ones with their owner>
<give interfaces with types, units, valid values and lifecycle>
<give algorithm steps, invariants, tie rules and stopping conditions>
<define state transitions, persistence, retry and recovery>
<give schemas, identifiers, ordering and migration behaviour>
<name every caller, container, registry and documentation row that moves with the change>
<link each primary source to the decision it supports>
<say which commands exist today and which this pass must create>
<give acceptance cases whose expected result does not come from the implementation>

## 5. Before you finish
<each check as a runnable command, with what its output must show>

## 6. The report
<the exact section list the report must carry, and a new report path beside this package>
<order one Write for a new report beside its prompt, then no more than two later edits>
<end it with "Open questions for the user": each one written out in full with a recommended
 answer, never a count and never a pointer elsewhere, and restated in the handover message>
```

## The sections that are always got wrong

**"What is true now" is not optional.** Research and implementation overlap here, and a pass
that acts on a stale description of the tree spends its budget writing something that has to
be undone. Name what landed since, and name what was deliberately cut so it is not described
as forthcoming.

**Prohibitions need their reason.** "Do not push" is followed; "do not push, because the
diff has not been scanned for private detail yet" is followed *and* generalises to the next
situation the prompt did not anticipate.

**The deliverable's format belongs in the prompt.** A report whose sections were chosen by
its author cannot be compared with the report beside it.

**Name the timebox.** A pass self-timeboxes and reports what it did not reach, rather than
running until it is stopped.

**Stamp the commit the package was written against.** The tree moves while a package sits
unsent, and a pass that reads a stale package silently works from a description of a tree that
no longer exists. The stamp costs one `git rev-parse --short HEAD` and it makes the drift
checkable:

```
git diff --stat <sha>..HEAD -- <the paths the package names>
```

Run that before launching. An empty output means the package is still true. Anything else goes
into "What is true now" before the pass starts, and not into a correction afterwards.

**Name the tool-call budget**, being 202 for a pass that writes and 101 for one that only
reads. The context cap cannot be checked by the pass, and a tool-call count can. Say what to
do on reaching it, which is to stop, finish the current step, and hand over the rule it
derived. `.agents/hooks/warn-tool-call-budget.py` sets the same two numbers from the agent
type on the launch call, so the package and the counter agree.

**Name the pass's tasks in order, with the check on each line.** A pass carries about three. A
list with no check on a line is the brief shape that has been measured to deliver one task of
five.
