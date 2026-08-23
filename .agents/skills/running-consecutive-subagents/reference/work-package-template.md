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

## Timebox

State it. Around thirty minutes of work, with the instruction to stop and report rather than
continue. A pass that runs long is a pass whose scope was wrong, and the report is where that
becomes visible.
