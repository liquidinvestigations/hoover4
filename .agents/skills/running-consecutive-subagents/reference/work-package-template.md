# Work-package template

The same skeleton `planning-work` uses, with the notes that matter when the reader is a
sub-agent rather than a future session.

```markdown
# <id>: <the deliverable in one line>

You are agent `<id>`, running inside a larger pass. **Your prompt is this file. Your
deliverable is `<exact path>`**. The launching agent reads that and nothing else.

## 1. Read before you start
## 2. What lands
## 3. What is true now
## 4. What must not happen
## 5. Before you finish
## 6. The report: <the exact section list>
```

## Notes per section

**Read before you start.** Order the list, and give each entry one line saying why it is
there. An unordered list of eight paths is read in the order they appear, which is rarely the
useful order.

**What lands.** Enumerate. If a draft or an earlier document is an input, say explicitly
whether it is authoritative or merely a starting point. A pass told "here is the draft" will
implement it faithfully including its errors.

**What is true now.** The section that is skipped most often and costs most. Name what has
landed since the inputs were written, and name what was deliberately cut, so the pass does not
document unbuilt work as forthcoming.

**What must not happen.** Give each prohibition its reason. A prohibition with a reason
generalises to the situation you did not anticipate; a bare one does not. Everything
unrecoverable belongs here: pushing, publishing, deleting, deploying over a live
verification.

**Before you finish.** Commands, not intentions. "Run the unit tests" becomes the exact
invocation, and the sentence that says what its output must show.

**The report.** Fix the section list. Include a section that invites the pass to say what it
could not do and where it shipped past a failing check. Without that section it will
present a clean summary instead.

## Writing for a reader who may be a weaker model

Every package is written to this standard, because it is also what makes a package readable
after a compaction. Four properties, and a package that has all four costs nothing extra to
write.

1. **Every fact inlined.** No reference to a decision taken in the organizer's session, and no
   phrase that assumes the reader watched the work being scoped. The reader was not there.
2. **Every step ends in a command with its expected output.** A step whose success is a
   judgement is a step a weaker model will report as done.
3. **An explicit out-of-scope list**, by path or by name, so an edit outside it shows up in one
   `git diff --stat`.
4. **Stop conditions**, meaning what makes the pass stop and report rather than continue.

State what would make the pass a failure **before it runs**, so the result is not argued
afterwards. An edit outside the named scope, a check reported as passing that you cannot
reproduce, and a second revision round still not meeting the done criteria are each enough.

## Timebox and tool-call budget

State the timebox as a budget of effort and attention, and never as a clock. A pass cannot
measure its own elapsed time and always overestimates it.

**State the tool-call budget as a number.** The context cap is a token figure and a pass cannot
see its own context, so the package carries the cap converted at the p90 growth rate: 96 calls
for an implementation pass, 58 for a read-only one. Tell the pass what to do when it reaches
the budget, which is to stop taking new work, finish the step it is on, and write a handover
naming what is done, what is not, and **the rule it derived**. A handover that carries the rule
is what stops the next context deriving it again, and that re-derivation is the whole of the
5.8x forecast error in the archive.

Say what the pass owns, and instruct it to stop and report what it did not reach rather than
narrowing the work to fit a feeling about time. A pass that stops with items unreached has told
you the scope was wrong. A pass that runs long while still making progress has not.

Where the item is one rule applied across many files, say so, and tell the pass to build the
instrument first. Deriving the rule once and applying it with a script is what makes a large
homogeneous item fit inside one pass at all.
